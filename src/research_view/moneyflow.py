"""A股资金流聚合:节点级 + 个股级,统一输出"亿元"。

学自 agu 产业盘口(dc_client/moneyflow_rt),但形态不同:不做单票实时盯盘表,
而是按 48 产业链节点聚合,织进 B3 报告(客观事实块)/热点信号/个股详情。

两档数据源,消费方统一走 latest():
- EOD:md.moneyflow(Tushare 日频,单位万元,T日 ~22:15 落地)——权威口径,全市场;
- 盘中:md.moneyflow_rt(DC 数据中心每分钟采东财 push2delay,单位元)
  ∪ 自采补充表 moneyflow_rt_extra(DC 监控池=agu 产业表 168 只,核心池缺的十余只
  由 collect_rt_extra() 在 run_light 里自采,同 DC 口径,sql/017)。
主力 = 大单 + 超大单净额(东财口径,DC 已核对)。latest() 优先当日 EOD(盘后),
其次当日盘中 rt,最后回退最近一日 EOD——消费方按 kind/stamp 标注口径。
"""
from __future__ import annotations

import json
import socket
import urllib.request

from . import db

# —— push2delay 强制 IPv4(DC 实测:IPv6/trafficmanager 空回复,只有 A 记录可用)——
_orig_getaddrinfo = socket.getaddrinfo


def _ipv4_only(host, *args, **kwargs):
    return [r for r in _orig_getaddrinfo(host, *args, **kwargs) if r[0] == socket.AF_INET]


_UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com"}


# ---------- 参照层映射 ----------

def _mapping():
    """core 池映射 + 全科技域 ts 集。返回 (name_of{ts:(code,name)}, nodes_of{ts:[(nid,chain,node)]}, all_ts)。"""
    name_of: dict[str, tuple[str, str]] = {}
    nodes_of: dict[str, list[tuple[str, str, str]]] = {}
    all_ts: set[str] = set()
    with db.rv_conn() as conn:
        cur = conn.cursor()
        cur.execute("""SELECT s.ts_code, s.code, s.name, sn.node_id, n.chain, n.node
            FROM stock s JOIN stock_node sn USING(code) JOIN node n USING(node_id)
            WHERE s.ts_code IS NOT NULL""")
        for ts, code, name, nid, chain, node in cur.fetchall():
            name_of[ts] = (code, name)
            nodes_of.setdefault(ts, []).append((nid, chain, node))
            all_ts.add(ts)
        cur.execute("SELECT ts_code, code, name FROM tech_stock WHERE ts_code IS NOT NULL")
        for ts, code, name in cur.fetchall():
            name_of.setdefault(ts, (code, name))
            all_ts.add(ts)
    return name_of, nodes_of, all_ts


def _aggregate(flows: dict[str, float], name_of, nodes_of) -> dict:
    """flows: {ts_code: 主力净额(亿)} → 节点聚合 + 个股字典。"""
    by_node: dict[str, dict] = {}
    for ts, main in flows.items():
        for nid, chain, node in nodes_of.get(ts, ()):
            g = by_node.setdefault(nid, {"node_id": nid, "chain": chain, "node": node,
                                         "main": 0.0, "n": 0, "_stocks": []})
            g["main"] += main
            g["n"] += 1
            code, name = name_of[ts]
            g["_stocks"].append({"code": code, "name": name, "main": round(main, 2)})
    nodes = []
    for g in by_node.values():
        ss = sorted(g.pop("_stocks"), key=lambda s: -s["main"])
        g["main"] = round(g["main"], 2)
        g["top_in"] = [s for s in ss[:2] if s["main"] > 0]
        g["top_out"] = [s for s in ss[-2:] if s["main"] < 0][::-1]
        g["members"] = ss  # 全部成分(资金页下钻用,已按主力净额降序)
        nodes.append(g)
    nodes.sort(key=lambda x: -x["main"])
    pool_ts = set(nodes_of)
    return {"nodes": nodes,
            "pool_main": round(sum(v for t, v in flows.items() if t in pool_ts), 1),
            "stocks": {name_of[t][0]: round(v, 2) for t, v in flows.items()}}


# ---------- EOD(md.moneyflow,万元) ----------

def eod() -> dict | None:
    name_of, nodes_of, all_ts = _mapping()
    with db.marketdata_conn() as mc:
        cur = mc.cursor()
        cur.execute("SELECT max(trade_date) FROM md.moneyflow")
        d = cur.fetchone()[0]
        if d is None:
            return None
        cur.execute("""SELECT ts_code, buy_lg_amount, sell_lg_amount, buy_elg_amount, sell_elg_amount
            FROM md.moneyflow WHERE trade_date=%s AND ts_code = ANY(%s)""", (d, list(all_ts)))
        flows = {ts: (float(bl or 0) - float(sl or 0) + float(be or 0) - float(se or 0)) / 1e4
                 for ts, bl, sl, be, se in cur.fetchall()}
    if not flows:
        return None
    return {"kind": "eod", "date": str(d), "stamp": None, **_aggregate(flows, name_of, nodes_of)}


# ---------- 盘中(md.moneyflow_rt ∪ 自采补充表,元) ----------

def rt() -> dict | None:
    """当日盘中口径;今天无 rt 数据(非交易日/未开盘)返回 None。"""
    name_of, nodes_of, all_ts = _mapping()
    flows: dict[str, float] = {}
    stamp = ""
    with db.marketdata_conn() as mc:
        cur = mc.cursor()
        cur.execute("""SELECT ts_code, main_net, last_min FROM md.moneyflow_rt
            WHERE trade_date=current_date AND ts_code = ANY(%s)""", (list(all_ts),))
        for ts, main, lm in cur.fetchall():
            flows[ts] = float(main or 0) / 1e8
            stamp = max(stamp, lm or "")
    with db.rv_conn() as conn:
        cur = conn.cursor()
        cur.execute("""SELECT ts_code, main_net, last_min FROM moneyflow_rt_extra
            WHERE trade_date=current_date""")
        for ts, main, lm in cur.fetchall():
            # 池子盘中调出的票在补采表滞留当日行,不在映射里→曾致 _aggregate KeyError
            # (2026-07-03 和远气体002971被剔除后当晚 mf_snapshot 连败6次,跨天自愈)
            if ts not in name_of:
                continue
            flows.setdefault(ts, float(main or 0) / 1e8)
            stamp = max(stamp, lm or "")
        cur.execute("SELECT to_char(current_date,'YYYY-MM-DD')")
        today = cur.fetchone()[0]
    if not flows:
        return None
    return {"kind": "rt", "date": today, "stamp": stamp, **_aggregate(flows, name_of, nodes_of)}


def latest() -> dict | None:
    """消费方统一入口:当日 EOD(已落地,权威)> 当日盘中 rt > 最近一日 EOD。"""
    e = eod()
    with db.rv_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT to_char(current_date,'YYYY-MM-DD')")
        today = cur.fetchone()[0]
    if e and e["date"] == today:
        return e
    return rt() or e


# ---------- 自采补充(核心池 - DC 监控池的缺口) ----------

def _fetch_klines(ts_code: str) -> list[str]:
    code, ex = ts_code.split(".")
    secid = ("1." if ex == "SH" else "0.") + code
    url = ("https://push2delay.eastmoney.com/api/qt/stock/fflow/kline/get"
           f"?secid={secid}&fields1=f1,f2,f3,f7"
           "&fields2=f51,f52,f53,f54,f55,f56&klt=1&lmt=0")
    socket.getaddrinfo = _ipv4_only
    try:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=12).read()
    finally:
        socket.getaddrinfo = _orig_getaddrinfo
    return (json.loads(raw).get("data") or {}).get("klines") or []


def collect_rt_extra() -> dict:
    """补采 DC 监控池未覆盖的核心池票(动态求差:核心池 - 今日 md.moneyflow_rt 已有)。
    盘中每 15min 由 run_light 调;非交易日/无缺口零开销。字段:全天累计净额(元),同 DC 口径。"""
    with db.marketdata_conn() as mc:
        cur = mc.cursor()
        cur.execute("SELECT 1 FROM md.trade_calendar WHERE cal_date=current_date AND is_open")
        if not cur.fetchone():
            return {"skip": "非交易日"}
        cur.execute("SELECT DISTINCT ts_code FROM md.moneyflow_rt WHERE trade_date=current_date")
        covered = {r[0] for r in cur.fetchall()}
    if not covered:  # DC 侧今天还没开始写(未开盘),自采也没意义
        return {"skip": "rt 未开盘"}
    with db.rv_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT ts_code FROM stock WHERE ts_code IS NOT NULL")
        missing = sorted({r[0] for r in cur.fetchall()} - covered)
        ok = 0
        errs: list[str] = []
        for ts in missing:
            # 抓取与写库分开兜:一条 INSERT 报错会让事务进入 aborted 状态,若不回滚,
            # 后续所有票全部失败且 commit 变隐式 ROLLBACK——整批无声丢失。写库错误
            # 用 SAVEPOINT 只丢这一票,并记录错误不再静默。
            try:
                kl = _fetch_klines(ts)
            except Exception as e:  # noqa: BLE001 单票抓取失败不阻塞
                errs.append(f"{ts}:抓 {str(e)[:40]}")
                continue
            if not kl:
                continue
            p = kl[-1].split(",")  # 最后一分钟 = 全天累计:时间,主力,小单,中单,大单,超大单
            if len(p) < 6:
                continue
            try:
                cur.execute("SAVEPOINT rt_row")
                cur.execute("""INSERT INTO moneyflow_rt_extra
                        (trade_date, ts_code, last_min, main_net, elg_net, lg_net, mid_net, sm_net)
                    VALUES (current_date,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (trade_date, ts_code) DO UPDATE SET last_min=EXCLUDED.last_min,
                        main_net=EXCLUDED.main_net, elg_net=EXCLUDED.elg_net, lg_net=EXCLUDED.lg_net,
                        mid_net=EXCLUDED.mid_net, sm_net=EXCLUDED.sm_net, updated_at=now()""",
                    (ts, p[0][-5:], p[1], p[5], p[4], p[3], p[2]))
                cur.execute("RELEASE SAVEPOINT rt_row")
                ok += 1
            except Exception as e:  # noqa: BLE001
                cur.execute("ROLLBACK TO SAVEPOINT rt_row")
                errs.append(f"{ts}:库 {str(e)[:40]}")
        conn.commit()
    out: dict = {"missing": len(missing), "fetched": ok}
    if errs:
        out["errors"] = len(errs)
        print(f"  ! rt_extra 异常{len(errs)}票(首3): " + "; ".join(errs[:3]))
    return out


# ---------- 盘中累计曲线(资金页,sql/018) ----------

def snapshot_intraday() -> dict:
    """把当日 rt 聚合追加为曲线上的一个时点(run_light 每15min调,分辨率=采集节奏)。
    同一 last_min 时点幂等跳过——午休/收盘后 stamp 不再前进,自然不重复落点。
    节点行(mf_intraday_node,资金页曲线)与个股行(mf_intraday_stock,限核心池,
    个股详情当日曲线+异动检测基线)同事务落点;个股表滚动保留60天。"""
    r = rt()
    if not r or not r.get("stamp"):
        return {"skip": "无盘中数据"}
    with db.rv_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM mf_intraday_node WHERE trade_date=%s AND hhmm=%s AND node_id='POOL'",
                    (r["date"], r["stamp"]))
        if cur.fetchone():
            return {"skip": f"时点 {r['stamp']} 已记录"}
        rows = [(r["date"], r["stamp"], g["node_id"], g["main"]) for g in r["nodes"]]
        rows.append((r["date"], r["stamp"], "POOL", r["pool_main"]))
        cur.executemany("""INSERT INTO mf_intraday_node(trade_date,hhmm,node_id,main)
            VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING""", rows)
        cur.execute("SELECT code FROM stock")
        core = {c for (c,) in cur.fetchall()}
        srows = [(r["date"], r["stamp"], c, v) for c, v in r["stocks"].items() if c in core]
        cur.executemany("""INSERT INTO mf_intraday_stock(trade_date,hhmm,code,main)
            VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING""", srows)
        cur.execute("DELETE FROM mf_intraday_stock WHERE trade_date < current_date - 60")
        conn.commit()
    return {"date": r["date"], "hhmm": r["stamp"], "nodes": len(rows) - 1, "stocks": len(srows)}


def seed_today_from_hourly() -> dict:
    """部署当日回填种子:用 DC hourly 4 小时桶(10:30/11:30/14:00/15:00 锚点)拼当日曲线,
    次一交易日起由 15min 快照自然积累,此函数即失去意义(幂等,可重跑)。"""
    name_of, nodes_of, _all_ts = _mapping()
    with db.marketdata_conn() as mc:
        cur = mc.cursor()
        cur.execute("SELECT ts_code, hourly FROM md.moneyflow_rt WHERE trade_date=current_date")
        rows = [(t, h) for t, h in cur.fetchall() if h]
    if not rows:
        return {"skip": "无 hourly"}
    anchors = ["10:30", "11:30", "14:00", "15:00"]
    per_anchor: dict[str, dict[str, float]] = {a: {} for a in anchors}
    for ts, hourly in rows:
        if ts not in name_of:  # DC 监控池含我们域外票(agu 产业表口径更宽),跳过
            continue
        run = 0.0
        for b in hourly:
            run += float(b.get("main") or 0)
            end = (b.get("label") or "").split("-")[-1]
            if end in per_anchor:
                per_anchor[end][ts] = run / 1e8
    n = 0
    with db.rv_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT to_char(current_date,'YYYY-MM-DD')")
        today = cur.fetchone()[0]
        cur.execute("SELECT code FROM stock")
        core = {c for (c,) in cur.fetchall()}
        for a in anchors:
            if not per_anchor[a]:
                continue
            agg = _aggregate(per_anchor[a], name_of, nodes_of)
            rows2 = [(today, a, g["node_id"], g["main"]) for g in agg["nodes"]]
            rows2.append((today, a, "POOL", agg["pool_main"]))
            cur.executemany("""INSERT INTO mf_intraday_node(trade_date,hhmm,node_id,main)
                VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING""", rows2)
            srows = [(today, a, c, round(v, 2)) for c, v in agg["stocks"].items() if c in core]
            cur.executemany("""INSERT INTO mf_intraday_stock(trade_date,hhmm,code,main)
                VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING""", srows)
            n += len(rows2) + len(srows)
        conn.commit()
    return {"seeded": n}


def intraday_series() -> dict | None:
    """最近一个有快照的交易日的节点累计曲线。{date, times, series(按终值降序), pool}。"""
    with db.rv_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT max(trade_date) FROM mf_intraday_node")
        d = cur.fetchone()[0]
        if d is None:
            return None
        cur.execute("SELECT hhmm, node_id, main FROM mf_intraday_node WHERE trade_date=%s", (d,))
        rows = cur.fetchall()
        cur.execute("SELECT node_id, chain, node, chain_en FROM node")
        meta = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
        cur.execute("SELECT DISTINCT chain_en, chain FROM node")
        en2cn = dict(cur.fetchall())
    times = sorted({h for h, _, _ in rows})
    val = {(h, n): float(m) for h, n, m in rows}
    series, pool = [], None
    for nid in {n for _, n, _ in rows}:
        values = [(round(val[(h, nid)], 2) if (h, nid) in val else None) for h in times]
        last = next((v for v in reversed(values) if v is not None), 0.0)
        if nid == "POOL":
            pool = {"values": values, "last": last}
            continue
        if nid in meta:
            chain, node = meta[nid]
        else:
            # 参照层改版后的旧节点id(过渡窗历史曲线):保留曲线,诚实标注,前端不下钻
            prefix = nid.split("::", 1)[0]
            chain = en2cn.get(prefix, prefix)
            node = nid.split("::", 1)[-1] + "(已重组)"
        series.append({"node_id": nid, "chain": chain, "node": node, "values": values, "last": last})
    series.sort(key=lambda s: -s["last"])
    return {"date": str(d), "times": times, "series": series, "pool": pool}


# ---------- 多日资金(EOD 历史,md.moneyflow 2010 起全量) ----------

def multi_day(windows: tuple[int, int] = (5, 20)) -> dict | None:
    """节点多日资金:近5/20交易日累计主力净额 + 连续净流入/流出天数(streak,±号=方向)
    + 资金×涨幅背离(5日资金与 heatmap 周涨幅方向相反且都显著→客观标注,不下结论)。"""
    _name_of, nodes_of, _ = _mapping()
    pool_ts = list(nodes_of)
    with db.marketdata_conn() as mc:
        cur = mc.cursor()
        cur.execute("SELECT DISTINCT trade_date FROM md.moneyflow ORDER BY trade_date DESC LIMIT %s",
                    (max(windows) + 5,))
        dates = sorted(r[0] for r in cur.fetchall())
        if len(dates) < min(windows):
            return None
        cur.execute("""SELECT trade_date, ts_code,
                (coalesce(buy_lg_amount,0)-coalesce(sell_lg_amount,0)
                 +coalesce(buy_elg_amount,0)-coalesce(sell_elg_amount,0))/1e4
            FROM md.moneyflow WHERE trade_date>=%s AND ts_code=ANY(%s)""", (dates[0], pool_ts))
        rows = cur.fetchall()
        # 全市场基准:主力口径结构性偏净流出(大单卖/拆单买),节点数字须对照全市场读相对强弱
        cur.execute("""SELECT trade_date,
                sum(coalesce(buy_lg_amount,0)-coalesce(sell_lg_amount,0)
                    +coalesce(buy_elg_amount,0)-coalesce(sell_elg_amount,0))/1e4
            FROM md.moneyflow WHERE trade_date>=%s GROUP BY trade_date""", (dates[0],))
        mkt = {d: float(v) for d, v in cur.fetchall()}
    mkt_daily = [mkt.get(d, 0.0) for d in dates]
    market = {"d5": round(sum(mkt_daily[-windows[0]:]), 0),
              "d20": round(sum(mkt_daily[-windows[1]:]), 0)}
    nd: dict[str, dict] = {}
    for d, ts, main in rows:
        for nid, _c, _n in nodes_of.get(ts, ()):
            g = nd.setdefault(nid, {})
            g[d] = g.get(d, 0.0) + float(main)
    with db.rv_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT node_id, chain, node, ret_1w FROM heatmap_node")
        meta = {r[0]: (r[1], r[2], float(r[3]) if r[3] is not None else None) for r in cur.fetchall()}
    out = []
    for nid, series in nd.items():
        daily = [series.get(d, 0.0) for d in dates]
        d5, d20 = sum(daily[-windows[0]:]), sum(daily[-windows[1]:])
        streak = 0
        if daily and abs(daily[-1]) > 0.05:  # 当日≈0 不起算,免噪音连续
            sign = 1 if daily[-1] > 0 else -1
            for v in reversed(daily):
                if abs(v) > 0.05 and ((v > 0) == (sign > 0)):
                    streak += 1
                else:
                    break
            streak *= sign
        chain, node, ret1w = meta.get(nid) or ("", nid, None)
        div = (ret1w is not None and abs(d5) >= 2 and abs(ret1w) >= 2
               and (d5 > 0) != (ret1w > 0))
        out.append({"node_id": nid, "chain": chain, "node": node,
                    "d5": round(d5, 1), "d20": round(d20, 1), "streak": streak,
                    "ret_1w": ret1w, "divergence": div})
    out.sort(key=lambda x: -x["d5"])
    return {"asof": str(dates[-1]), "market": market, "nodes": out}


def stocks_hist(days: int = 20) -> dict | None:
    """核心池个股近N交易日逐日主力净额(亿),键=6位代码。个股详情「多日资金趋势」
    (累计画法在前端)用;5日累计(stocks5)由 export 从此结果求和派生,单一取数路径。"""
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT ts_code, code FROM heatmap_stock WHERE ts_code IS NOT NULL")
        code_of = dict(cur.fetchall())
    if not code_of:
        return None
    with db.marketdata_conn() as mc:
        cur = mc.cursor()
        cur.execute("SELECT DISTINCT trade_date FROM md.moneyflow ORDER BY trade_date DESC LIMIT %s",
                    (days,))
        dates = sorted(r[0] for r in cur.fetchall())
        if not dates:
            return None
        cur.execute("""SELECT trade_date, ts_code,
                (coalesce(buy_lg_amount,0)-coalesce(sell_lg_amount,0)
                 +coalesce(buy_elg_amount,0)-coalesce(sell_elg_amount,0))/1e4
            FROM md.moneyflow WHERE trade_date >= %s AND ts_code = ANY(%s)""",
            (dates[0], list(code_of)))
        grid: dict[str, dict] = {}
        for d, ts, v in cur.fetchall():
            grid.setdefault(code_of[ts], {})[d] = float(v)
    return {"dates": [str(d) for d in dates],
            "stocks": {c: [round(m.get(d, 0.0), 2) for d in dates] for c, m in grid.items()}}


def stock_intraday_series() -> dict | None:
    """最近快照日的个股当日累计曲线(走 trends.json 懒加载通道,个股详情用)。"""
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT max(trade_date) FROM mf_intraday_stock")
        d = cur.fetchone()[0]
        if d is None:
            return None
        cur.execute("SELECT hhmm, code, main FROM mf_intraday_stock WHERE trade_date=%s", (d,))
        rows = cur.fetchall()
    times = sorted({h for h, _, _ in rows})
    idx = {h: i for i, h in enumerate(times)}
    stocks: dict[str, list] = {}
    for h, c, m in rows:
        stocks.setdefault(c, [None] * len(times))[idx[h]] = float(m)
    return {"date": str(d), "times": times, "stocks": stocks}


# ---------- 个股资金异动(15分钟窗口;展示+推送层,不进 B6/B8 判断链) ----------

ALERT_WINDOW_MIN = 15     # 目标窗口(实际取快照分辨率下最近的≥13分钟点)
ALERT_FLOOR = 0.3         # 绝对下限(亿):小票按比例阈值可能只有几百万,全是噪音
ALERT_PCT = 0.02          # 相对阈值=20日日均成交额×2%(大票水大,按自身体量定异动)
ALERT_COOLDOWN_MIN = 60   # 同票同方向冷却,防持续大流入每15分钟刷屏


def _min_of(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def detect_alerts() -> dict:
    """盘中个股资金异动检测(纯代码,run_light 各档 mf_snapshot 后调):
    15分钟窗口主力净额变动 ≥ max(0.3亿, 20日日均成交额×2%) → 落 mf_alert。
    同票同方向60分钟冷却;PK(日,时点,票)幂等;午休/收盘 stamp 不前进自然零新增,
    跨午休窗口失真(>25分钟)不判。"""
    with db.rv_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT hhmm, code, main FROM mf_intraday_stock WHERE trade_date=current_date")
        rows = cur.fetchall()
        if not rows:
            return {"skip": "无当日个股快照"}
        cur.execute("SELECT code, name, ts_code FROM stock")
        meta = {c: (n, ts) for c, n, ts in cur.fetchall()}
        cur.execute("SELECT code, hhmm, delta FROM mf_alert WHERE trade_date=current_date")
        prior = [(c, h, float(dl)) for c, h, dl in cur.fetchall()]
    series: dict[str, list[tuple[str, float]]] = {}
    latest = ""
    for h, c, m in rows:
        series.setdefault(c, []).append((h, float(m)))
        latest = max(latest, h)
    cands: dict[str, tuple[float, int, float]] = {}  # code -> (Δ, 实际窗口分钟, 当日累计)
    for code, pts in series.items():
        pts.sort()
        h_cur, v_cur = pts[-1]
        if h_cur != latest:
            continue  # 缺采/停牌,数据没跟到最新时点不判
        base = next(((h, v) for h, v in reversed(pts[:-1])
                     if _min_of(h_cur) - _min_of(h) >= ALERT_WINDOW_MIN - 2), None)
        if base is None:
            continue
        win = _min_of(h_cur) - _min_of(base[0])
        if win > ALERT_WINDOW_MIN + 10:
            continue
        cands[code] = (v_cur - base[1], win, v_cur)
    if not cands:
        return {"hhmm": latest, "alerts": 0}
    # 阈值基准:20日日均成交额(bar_daily_raw.amount 千元 → 亿 = /1e5)
    ts_of = {c: meta[c][2] for c in cands if c in meta and meta[c][2]}
    avg_amt: dict[str, float] = {}
    with db.marketdata_conn() as mc:
        mcur = mc.cursor()
        mcur.execute("""SELECT DISTINCT cal_date FROM md.trade_calendar
            WHERE is_open AND cal_date <= current_date ORDER BY cal_date DESC LIMIT 20""")
        days = [r[0] for r in mcur.fetchall()]
        if days:
            mcur.execute("""SELECT ts_code, avg(amount)/1e5 FROM md.bar_daily_raw
                WHERE trade_date >= %s AND ts_code = ANY(%s) GROUP BY ts_code""",
                (min(days), list(ts_of.values())))
            avg_amt = {ts: float(v) for ts, v in mcur.fetchall()}
    fired = []
    for code, (delta, win, cum) in cands.items():
        avg = avg_amt.get(ts_of.get(code, ""), 0.0)
        if abs(delta) < max(ALERT_FLOOR, avg * ALERT_PCT):
            continue
        if any(c == code and (dl > 0) == (delta > 0)
               and _min_of(latest) - _min_of(h) < ALERT_COOLDOWN_MIN for c, h, dl in prior):
            continue
        fired.append((latest, code, meta[code][0], round(delta, 2), win,
                      round(avg, 1) if avg else None,
                      round(delta / avg, 4) if avg else None, round(cum, 2)))
    n = 0
    if fired:
        with db.rv_conn() as conn:
            cur = conn.cursor()
            for f in fired:
                cur.execute("""INSERT INTO mf_alert
                        (trade_date, hhmm, code, name, delta, window_min, avg_amount, ratio, cum)
                    VALUES (current_date,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""", f)
                n += cur.rowcount
            conn.commit()
    return {"hhmm": latest, "alerts": n}


def today_alerts() -> dict | None:
    """最近一个有记录日的异动清单(dashboard.moneyflow.alerts;推送脚本按 date 只推当日)。"""
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT max(trade_date) FROM mf_alert")
        d = cur.fetchone()[0]
        if d is None:
            return None
        cur.execute("""SELECT hhmm, code, name, delta, window_min, ratio, cum FROM mf_alert
            WHERE trade_date=%s ORDER BY hhmm DESC, abs(delta) DESC""", (d,))
        items = [{"hhmm": r[0], "code": r[1], "name": r[2], "delta": float(r[3]),
                  "window_min": r[4], "ratio": float(r[5]) if r[5] is not None else None,
                  "cum": float(r[6]) if r[6] is not None else None} for r in cur.fetchall()]
    return {"date": str(d), "items": items}


# ---------- 报告用文本行 ----------

def lines(mf: dict, top: int = 8) -> list[str]:
    """给 B3 报告的客观事实行:按主力净额绝对值取前 top 节点。"""
    picked = sorted(mf["nodes"], key=lambda x: -abs(x["main"]))[:top]
    out = []
    for g in picked:
        ins = "/".join(f"{s['name']}{s['main']:+.1f}" for s in g["top_in"])
        outs = "/".join(f"{s['name']}{s['main']:+.1f}" for s in g["top_out"])
        seg = f"- {g['chain']}/{g['node']} 主力{g['main']:+.1f}亿({g['n']}只"
        if ins:
            seg += f";净买:{ins}"
        if outs:
            seg += f";净卖:{outs}"
        out.append(seg + ")")
    out.append(f"- 核心池合计 主力净额 {mf['pool_main']:+.1f}亿")
    return out
