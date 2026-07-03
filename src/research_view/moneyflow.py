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
        for ts in missing:
            try:
                kl = _fetch_klines(ts)
                if not kl:
                    continue
                p = kl[-1].split(",")  # 最后一分钟 = 全天累计:时间,主力,小单,中单,大单,超大单
                if len(p) < 6:
                    continue
                cur.execute("""INSERT INTO moneyflow_rt_extra
                        (trade_date, ts_code, last_min, main_net, elg_net, lg_net, mid_net, sm_net)
                    VALUES (current_date,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (trade_date, ts_code) DO UPDATE SET last_min=EXCLUDED.last_min,
                        main_net=EXCLUDED.main_net, elg_net=EXCLUDED.elg_net, lg_net=EXCLUDED.lg_net,
                        mid_net=EXCLUDED.mid_net, sm_net=EXCLUDED.sm_net, updated_at=now()""",
                    (ts, p[0][-5:], p[1], p[5], p[4], p[3], p[2]))
                ok += 1
            except Exception:  # noqa: BLE001 单票失败不阻塞
                continue
        conn.commit()
    return {"missing": len(missing), "fetched": ok}


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
