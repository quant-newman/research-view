"""事件流导出:温度计 + 按节点分组的相关新闻 + 个股事件 → 静态 JSON(前端只读)。

隐私铁律:只输出"是否持仓/自选"布尔标记,绝不输出金额。
有效相关 = is_chain_relevant OR 标题明确点到池内票(不让 B1 砍自己池子的票)。
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config, db, market

EXPORT_DIR = config.ROOT / "exports"


def _scrub(o):
    """递归把 NaN/Inf(float 或 Decimal('NaN'))转成 None,否则 json.dumps 会吐非法 NaN token
    致前端 JSON.parse 崩溃。其余原样返回(Decimal/date 交给 json 的 default=str)。"""
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, Decimal):
        return None if not o.is_finite() else float(o)
    if isinstance(o, dict):
        return {k: _scrub(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_scrub(v) for v in o]
    return o


def _dump(obj) -> str:
    return json.dumps(_scrub(obj), ensure_ascii=False, indent=2, default=str)


def _limit_threshold(ts_code: str) -> float:
    p = ts_code[:3]
    if p in ("300", "301", "688", "689") or ts_code[:2] in ("30", "68"):
        return 19.5  # 创业板/科创 20%
    if ts_code[0] in ("4", "8"):
        return 29.5  # 北交所 30%
    return 9.8


def _temperature(mc_cur, pool_ts: list[str]) -> dict:
    mc_cur.execute("SELECT max(trade_date) FROM md.bar_daily_raw")
    latest = mc_cur.fetchone()[0]
    mc_cur.execute("""SELECT ts_code, (close-pre_close)/pre_close*100 AS pct
        FROM md.bar_daily_raw WHERE ts_code = ANY(%s) AND trade_date=%s AND pre_close>0""",
        (pool_ts, latest))
    up = down = flat = lu = ld = 0
    pcts = []
    for ts, pct in mc_cur.fetchall():
        pct = float(pct); pcts.append(pct); thr = _limit_threshold(ts)
        if pct >= thr: lu += 1
        elif pct <= -thr: ld += 1
        if pct > 0.05: up += 1
        elif pct < -0.05: down += 1
        else: flat += 1
    avg = round(sum(pcts) / len(pcts), 2) if pcts else 0.0
    return {"trade_date": latest, "pool_counted": len(pcts), "up": up, "down": down,
            "flat": flat, "limit_up": lu, "limit_down": ld, "avg_pct": avg}


def _ashare_trends(codes: set[str]) -> dict:
    """6个月日线收盘走势(供个股详情走势小图),keyed by 6位 code。
    只取传入的可点股票(当日 dashboard 里出现的),自限规模。code→ts_code 用 stock ∪ tech_stock。"""
    codes = sorted(c for c in codes if isinstance(c, str) and len(c) == 6 and c.isdigit())
    if not codes:
        return {}
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("""SELECT code, ts_code FROM stock WHERE code = ANY(%s) AND ts_code IS NOT NULL
            UNION SELECT code, ts_code FROM tech_stock WHERE code = ANY(%s) AND ts_code IS NOT NULL""",
            (codes, codes))
        code2ts: dict[str, str] = {}
        for c, t in cur.fetchall():
            code2ts.setdefault(c, t)
    ts2code = {t: c for c, t in code2ts.items()}
    if not ts2code:
        return {}
    trends: dict[str, list] = {}
    with db.marketdata_conn() as mc, mc.cursor() as cur:
        cur.execute("""SELECT ts_code, trade_date, close FROM md.bar_daily_raw
            WHERE ts_code = ANY(%s) AND trade_date >= current_date - 190
            ORDER BY ts_code, trade_date""", (list(ts2code),))
        for ts, dt, cl in cur.fetchall():
            if cl is None:
                continue
            trends.setdefault(ts2code[ts], []).append([dt.strftime("%Y%m%d"), round(float(cl), 2)])
    return trends


def build_export(date_utc8: str) -> Path:
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT ts_code FROM stock WHERE ts_code IS NOT NULL")
        pool_ts = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT code FROM holdings")
        holds = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT code FROM watchlist")
        watches = {r[0] for r in cur.fetchall()}

        # 相关新闻(有效相关),按节点分组;泛科技(无节点)按申万行业分组
        cur.execute("""
            SELECT rn.news_id, rn.src, rn.title, rn.one_line, rn.sentiment,
                   rn.event_type, rn.url, rn.matched_codes, rn.matched_node_ids,
                   rn.matched_tech_codes, rn.tech_industries, rn.pub_time, rn.summary
            FROM raw_news rn
            WHERE rn.relevant AND (rn.is_chain_relevant IS NOT false
                  OR array_length(rn.matched_codes,1) > 0 OR array_length(rn.matched_tech_codes,1) > 0)
              AND rn.pub_time >= current_date - 14
            ORDER BY rn.pub_time DESC""")
        news = cur.fetchall()

        # 个股事件(近30天 + 未来解禁)
        cur.execute("""SELECT code,ts_code,node_ids,event_type,direction,event_date,summary
            FROM stock_event WHERE event_date >= current_date - 30 ORDER BY event_date DESC, event_type""")
        events = cur.fetchall()

        cur.execute("SELECT node_id, chain, node FROM node")
        node_meta = {nid: {"chain": ch, "node": nd} for nid, ch, nd in cur.fetchall()}

    try:
        with db.marketdata_conn() as mc, mc.cursor() as mcur:
            temperature = _temperature(mcur, pool_ts)
    except Exception as e:  # noqa: BLE001 行情库不可用时降级为空,兜底导出不能在这里断掉
        print(f"  ! temperature 降级(marketdata 不可用): {e}")
        temperature = None

    def flags(codes):
        codes = codes or []
        return {"holding": any(c in holds for c in codes), "watching": any(c in watches for c in codes)}

    # 按节点分组新闻;核心链节点在前,泛科技行业组在后
    by_node: dict[str, dict] = {}
    for nid, src, title, one_line, sent, etype, url, codes, node_ids, tech_codes, tech_inds, pub_time, summary in news:
        item = {"title": title, "one_line": one_line, "summary": summary, "sentiment": sent, "event_type": etype,
                "src": src, "url": url, "time": str(pub_time), "codes": codes or [], **flags(codes)}
        if node_ids:  # 命中核心链节点
            for node_id in node_ids:
                g = by_node.setdefault(node_id, {"node_id": node_id, "scope": "核心链",
                                                 **node_meta.get(node_id, {}), "items": []})
                g["items"].append(item)
        elif tech_codes:  # 纯泛科技(无核心节点)→ 按申万行业归组
            for ind in (tech_inds or ["泛科技"]):
                gid = f"泛科技::{ind}"
                g = by_node.setdefault(gid, {"node_id": gid, "scope": "泛科技",
                                             "chain": "泛科技", "node": ind, "items": []})
                g["items"].append({**item, "codes": tech_codes})
    # 核心链在前,泛科技在后,组内按条数
    news_by_node = sorted(by_node.values(),
                          key=lambda g: (g.get("scope") == "泛科技", -len(g["items"])))

    events_out = [{"code": c, "event_type": et, "direction": d, "date": str(ed),
                   "summary": s, "node_ids": nids or [], **flags([c])}
                  for c, ts, nids, et, d, ed, s in events]

    out = {
        "meta": {"date": date_utc8, "generated_at": datetime.now(ZoneInfo(config.TZ)).isoformat(),
                 "tz": "UTC+8", "news_relevant": len(news), "events": len(events_out)},
        "temperature": temperature,
        "news_by_node": news_by_node,
        "stock_events": events_out,
    }
    EXPORT_DIR.mkdir(exist_ok=True)
    path = EXPORT_DIR / f"events_{date_utc8}.json"
    path.write_text(_dump(out), encoding="utf-8")
    return path


def build_dashboard(date_utc8: str) -> Path:
    """前端数据源:盘后报告 + 事件流 + 温度计 合并成一份 dashboard.json。"""
    events = build_export(date_utc8)
    ev = json.loads(events.read_text(encoding="utf-8"))
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("""SELECT report_id,session,data_cutoff,headline,top3,sectors,
            falsification,holdings_moves,generated_at,narrative,report_date FROM daily_report
            WHERE report_date=to_date(%s,'YYYYMMDD') ORDER BY generated_at DESC LIMIT 1""",
            (date_utc8,))
        row = cur.fetchone()
        if row is None:  # 跨天早盘前当日报告还没生成 → 回退显示最近一份(不让报告页空白)
            cur.execute("""SELECT report_id,session,data_cutoff,headline,top3,sectors,
                falsification,holdings_moves,generated_at,narrative,report_date FROM daily_report
                ORDER BY report_date DESC, generated_at DESC LIMIT 1""")
            row = cur.fetchone()
        report = None
        if row:
            report = {"report_id": row[0], "session": row[1], "data_cutoff": row[2],
                      "headline": row[3], "top3": row[4], "sectors": row[5],
                      "falsification": row[6], "holdings_moves": row[7],
                      "generated_at": str(row[8]), "narrative": row[9],
                      "report_date": str(row[10]),
                      "fallback": row[10].strftime("%Y%m%d") != date_utc8}
            # 证伪草稿标注已钉死:锚点=report_id+condition 文本(与 manage_ledger drafts 同口径;
            # pin 时人改写 condition 措辞的,草稿侧不标——账本面板仍会显示该判断)。
            fals = report["falsification"] or []
            if isinstance(fals, str):
                fals = json.loads(fals)
            if fals:
                cur.execute(
                    """SELECT l.condition, l.ledger_id,
                              EXISTS(SELECT 1 FROM ledger a WHERE a.ref_ledger=l.ledger_id)
                       FROM ledger l WHERE l.report_id=%s AND l.kind='judgment'""",
                    (report["report_id"],))
                pinned = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
                for f in fals:
                    hit = pinned.get(f.get("condition", ""))
                    if hit:
                        f["pinned_id"], f["pinned_falsified"] = hit
            report["falsification"] = fals
            # 盘中增量时间线(演进式报告):挂报告自身日期的条目,回退旧报告时也带旧日时间线
            cur.execute("""SELECT hhmm, entry, tags FROM report_increment
                WHERE trade_date=%s ORDER BY hhmm""", (row[10],))
            report["increments"] = [{"hhmm": h, "entry": e, "tags": t or []}
                                    for h, e, t in cur.fetchall()]
            # 盘前/盘中报告附隔夜美股科技链(台北 yfinance 产出,scp 到本机 exports/),供前端小面板。
            # 盘中也附:否则盘中报告一接管,早上的隔夜外盘参照会整天消失。
            if row[1] in ("premarket", "intraday"):
                us_path = EXPORT_DIR / f"us_overnight_{date_utc8}.json"
                if us_path.exists():
                    try:
                        report["us_overnight"] = json.loads(us_path.read_text(encoding="utf-8"))
                    except Exception:  # noqa: BLE001 美股文件损坏不阻塞导出
                        pass
    # 热力图(节点四象限 + 个股散点)。数值列 Decimal → float,否则前端拿到字符串画不出点。
    def fnum(v):
        return float(v) if v is not None else None

    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("""SELECT node_id,chain,node,n_stocks,total_mv,ret_1m,ret_6m,
            or_yoy,gross_margin,pe,ps,quadrant,ret_1d,ret_1w,ret_3m
            FROM heatmap_node ORDER BY total_mv DESC NULLS LAST""")
        hn = [{"node_id": r[0], "chain": r[1], "node": r[2], "n_stocks": r[3],
               "total_mv": fnum(r[4]), "ret_1m": fnum(r[5]), "ret_6m": fnum(r[6]),
               "or_yoy": fnum(r[7]), "gross_margin": fnum(r[8]), "pe": fnum(r[9]),
               "ps": fnum(r[10]), "quadrant": r[11],
               "ret_1d": fnum(r[12]), "ret_1w": fnum(r[13]), "ret_3m": fnum(r[14])} for r in cur.fetchall()]
        # 个股→节点映射(供前端点气泡看成分股)
        cur.execute("SELECT code, array_agg(node_id) FROM stock_node GROUP BY code")
        code_nodes = dict(cur.fetchall())
        cur.execute("""SELECT code,name,total_mv,pe,ps,ret_1m,ret_6m,or_yoy,gross_margin,pe_pct,
            ret_1d,ret_1w,ret_3m FROM heatmap_stock ORDER BY total_mv DESC NULLS LAST""")
        hs = [{"code": r[0], "name": r[1], "total_mv": fnum(r[2]), "pe": fnum(r[3]),
               "ps": fnum(r[4]), "ret_1m": fnum(r[5]), "ret_6m": fnum(r[6]),
               "or_yoy": fnum(r[7]), "gross_margin": fnum(r[8]), "pe_pct": fnum(r[9]),
               "ret_1d": fnum(r[10]), "ret_1w": fnum(r[11]), "ret_3m": fnum(r[12]),
               "node_ids": code_nodes.get(r[0], [])}
              for r in cur.fetchall()]
    heatmap = {"nodes": hn, "stocks": hs}

    # 研究库(卖方研报)+ 基金信函
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("""SELECT report_date,code,name,org_name,rating,title,tp,pe,node_ids,scope,industry
            FROM research_report ORDER BY report_date DESC NULLS LAST LIMIT 120""")
        reports = [{"date": str(r[0]), "code": r[1], "name": r[2], "org": r[3], "rating": r[4],
                    "title": r[5], "tp": (float(r[6]) if r[6] and 0 < float(r[6]) < 2000 else None),
                    "pe": fnum(r[7]), "node_ids": r[8] or [], "scope": r[9], "industry": r[10]}
                   for r in cur.fetchall()]
        cur.execute("""SELECT name, count(*) c, max(report_date), max(scope) FROM research_report
            GROUP BY name ORDER BY c DESC LIMIT 24""")
        coverage = [{"name": r[0], "n": r[1], "latest": str(r[2]), "scope": r[3]} for r in cur.fetchall()]
        cur.execute("""SELECT fund_name,period,stance,strategy,relevance,core_views,status,
                   title,url,relevant_points
            FROM fund_letter ORDER BY relevance DESC NULLS LAST, created_at DESC LIMIT 40""")
        letters = [{"fund_name": r[0], "period": r[1], "stance": r[2], "strategy": r[3],
                    "relevance": r[4], "core_views": r[5], "status": r[6],
                    "title": r[7], "url": r[8], "relevant_points": r[9]} for r in cur.fetchall()]
        # 研报深化(评级变动榜 + 观点提炼;当日无回退最近,回退带 date/fallback 供前端标陈旧)
        cur.execute("SELECT changes, views, report_date FROM research_digest WHERE report_date=to_date(%s,'YYYYMMDD')", (date_utc8,))
        drow = cur.fetchone()
        if drow is None:
            cur.execute("SELECT changes, views, report_date FROM research_digest ORDER BY report_date DESC LIMIT 1")
            drow = cur.fetchone()
    digest = ({"changes": drow[0], "views": drow[1], "date": str(drow[2]),
               "fallback": drow[2].strftime("%Y%m%d") != date_utc8} if drow else None)
    research = {"reports": reports, "coverage": coverage, "letters": letters, "digest": digest}

    # 判断复盘账本(近30日已钉死判断 + 存活/证伪 + 错误类型分布)
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT l.ledger_id, l.report_id, l.claim, l.condition, l.created_at_utc8::date,
                   EXISTS(SELECT 1 FROM ledger a WHERE a.ref_ledger=l.ledger_id) AS falsified,
                   (SELECT a.error_type FROM ledger a WHERE a.ref_ledger=l.ledger_id
                    ORDER BY a.ledger_id LIMIT 1) AS error_type
            FROM ledger l
            WHERE l.kind='judgment' AND l.created_at_utc8 >= now() - interval '30 days'
            ORDER BY l.ledger_id DESC""")
        judgments = [{"id": r[0], "report_id": r[1], "claim": r[2], "condition": r[3],
                      "date": str(r[4]), "falsified": r[5], "error_type": r[6]}
                     for r in cur.fetchall()]
    alive = sum(1 for j in judgments if not j["falsified"])
    error_dist: dict[str, int] = {}
    for j in judgments:
        if j["falsified"] and j["error_type"]:
            error_dist[j["error_type"]] = error_dist.get(j["error_type"], 0) + 1
    ledger = {"judgments": judgments, "alive": alive,
              "falsified": len(judgments) - alive, "error_dist": error_dist}

    # B6 节点研判卡(append-only 表:取最新一日、每节点最新一张;当日无回退最近标 fallback)
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT max(trade_date) FROM judgment_card")
        jd = cur.fetchone()[0]
        judgment = None
        if jd:
            cur.execute("""SELECT DISTINCT ON (jc.node_id) jc.card_id, jc.node_id, n.chain, n.node,
                    jc.direction, jc.confidence, jc.horizon_days, jc.thesis, jc.evidence,
                    jc.scenarios, jc.matrix, jc.resonance, jc.n_agree, jc.n_active, jc.divergence
                FROM judgment_card jc JOIN node n USING(node_id)
                WHERE jc.trade_date=%s ORDER BY jc.node_id, jc.card_id DESC""", (jd,))
            cards = [{"card_id": r[0], "node_id": r[1], "chain": r[2], "node": r[3],
                      "direction": r[4], "confidence": r[5], "horizon_days": r[6],
                      "thesis": r[7], "evidence": r[8] or [], "scenarios": r[9] or [],
                      "matrix": r[10] or {}, "resonance": fnum(r[11]),
                      "n_agree": r[12], "n_active": r[13], "divergence": r[14] or []}
                     for r in cur.fetchall()]
            cards.sort(key=lambda c: -abs(c["resonance"] or 0))
            # 节点成分股(涉及哪些票:龙头tier在前;港股映射票无A股行情也如实列出)
            if cards:
                cur.execute("""SELECT sn.node_id, sn.code, s.name, sn.tier
                    FROM stock_node sn JOIN stock s USING(code)
                    WHERE sn.node_id = ANY(%s)
                    ORDER BY sn.node_id, sn.tier NULLS LAST, sn.code""",
                    ([c["node_id"] for c in cards],))
                members: dict = {}
                for nid, code, name, tier in cur.fetchall():
                    members.setdefault(nid, []).append({"code": code, "name": name, "tier": tier})
                for c in cards:
                    c["stocks"] = members.get(c["node_id"], [])
            judgment = {"date": str(jd), "cards": cards,
                        "fallback": jd.strftime("%Y%m%d") != date_utc8}

    # B8 个股决策卡(影子运行:取最新一日、每股最新一张;当日无回退最近标 fallback)
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT max(trade_date) FROM decision_card")
        dd = cur.fetchone()[0]
        decision = None
        if dd:
            cur.execute("""SELECT DISTINCT ON (dc.code) dc.card_id, dc.code, dc.name,
                    dc.node_id, n.chain, n.node, dc.direction, dc.confidence, dc.horizon_days,
                    dc.thesis, dc.entry_cond, dc.exit_cond, dc.evidence, dc.falsify,
                    dc.matrix, dc.alignment, dc.close
                FROM decision_card dc LEFT JOIN node n USING(node_id)
                WHERE dc.trade_date=%s ORDER BY dc.code, dc.card_id DESC""", (dd,))
            dcards = [{"card_id": r[0], "code": r[1], "name": r[2], "node_id": r[3],
                       "chain": r[4], "node": r[5], "direction": r[6], "confidence": r[7],
                       "horizon_days": r[8], "thesis": r[9], "entry": r[10], "exit": r[11],
                       "evidence": r[12] or [], "falsify": r[13], "matrix": r[14] or {},
                       "alignment": fnum(r[15]), "close": fnum(r[16])}
                      for r in cur.fetchall()]
            dcards.sort(key=lambda c: -abs(c["alignment"] or 0))
            decision = {"date": str(dd), "cards": dcards,
                        "fallback": dd.strftime("%Y%m%d") != date_utc8}

    # B7 成绩单(命中率/分源归因/曲线,对错都晒;未发过卡=None 前端不显)
    try:
        from . import scorecard as _sc
        sc_block = _sc.dashboard_block()
    except Exception as e:  # noqa: BLE001 成绩单失败不阻塞导出
        print(f"  ! scorecard 降级: {e}")
        sc_block = None

    # 今日热点/主题热度榜(当日无则回退最近一份,回退带 date/fallback 供前端标陈旧)
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT headline, items, report_date, brief FROM hotspot_daily WHERE report_date=to_date(%s,'YYYYMMDD')",
                    (date_utc8,))
        hrow = cur.fetchone()
        if hrow is None:
            cur.execute("SELECT headline, items, report_date, brief FROM hotspot_daily ORDER BY report_date DESC LIMIT 1")
            hrow = cur.fetchone()
    hotspot = ({"headline": hrow[0], "items": hrow[1], "date": str(hrow[2]), "brief": hrow[3],
                "fallback": hrow[2].strftime("%Y%m%d") != date_utc8} if hrow else None)

    from . import monitor
    try:
        health = monitor.health()
    except Exception as e:  # noqa: BLE001 健康汇总失败不应阻塞导出
        health = {"level": "yellow", "error": str(e)[:200], "sources": [], "tasks": [], "flags": []}
    try:
        # 台北侧外网信源逐源状态(注册表×上报),系统页信源面板用
        taipei_src = monitor.taipei_sources()
    except Exception:  # noqa: BLE001
        taipei_src = []
    try:
        # A股资金面(节点主力净额聚合+个股字典):报告页面板/热点信号/个股详情/资金页用
        from . import moneyflow as _mf
        mflow = _mf.latest()
        if mflow:
            mflow["intraday"] = _mf.intraday_series()  # 当日节点累计曲线(资金页多线图)
            mflow["multi"] = _mf.multi_day()  # 5/20日累计+连续天数+背离(资金页多日表)
    except Exception:  # noqa: BLE001 资金面失败不阻塞导出
        mflow = None

    # 美股一等公民(台北 build_us 产出完整 blob→scp 到 exports/):
    # board/温度计/热力/新闻(B1)/研究(分析师)/报告(B3)。与 A股 同权,前端顶部一键切。
    # 当日 blob 缺失(build_us 失败/还没跑到)→ 回退最近一份并标 fallback/data_date,
    # 否则美股页整页消失还没任何提示(us_overnight_*.json 前缀不同不会被 glob 误中)。
    us = None
    up = EXPORT_DIR / f"us_{date_utc8}.json"
    us_fallback = False
    if not up.exists():
        cands = sorted(EXPORT_DIR.glob("us_[0-9]*.json"))
        if cands:
            up, us_fallback = cands[-1], True
    if up.exists():
        try:
            us = json.loads(up.read_text(encoding="utf-8"))
            if us_fallback:
                fd = up.stem.split("_")[1]
                us["fallback"] = True
                us["data_date"] = f"{fd[:4]}-{fd[4:6]}-{fd[6:]}"
        except Exception:  # noqa: BLE001 美股文件损坏不阻塞导出
            us = None

    # 大盘仪表(三层漏斗第一层·环境读数):指数/全A宽度/成交额/两融/全A主力
    try:
        market_gauge = market.gauge()
    except Exception as e:  # noqa: BLE001 行情库不可用降级,不阻塞导出
        print(f"  ! market 仪表降级: {e}")
        market_gauge = None

    dash = {"meta": ev["meta"], "report": report, "temperature": ev["temperature"],
            "news_by_node": ev["news_by_node"], "stock_events": ev["stock_events"],
            "heatmap": heatmap, "health": health, "research": research, "ledger": ledger,
            "us": us, "hotspot": hotspot, "sources": {"taipei": taipei_src}, "moneyflow": mflow,
            "market": market_gauge, "judgment": judgment, "scorecard": sc_block,
            "decision": decision}
    path = EXPORT_DIR / "dashboard.json"
    path.write_text(_dump(dash), encoding="utf-8")

    # 走势小图数据(6M日线):单列 trends.json 懒加载,不撑大 dashboard.json。
    # 只取当日 dashboard 里"可点"的 A股(新闻/事件/热力/研报出现过的),自限规模。
    clickable: set[str] = set()
    for g in ev["news_by_node"]:
        for it in g["items"]:
            clickable.update(it.get("codes") or [])
    clickable.update(e["code"] for e in ev["stock_events"] if e.get("code"))
    clickable.update(s["code"] for s in hs)
    clickable.update(r["code"] for r in reports if r.get("code"))
    try:
        a_trends = _ashare_trends(clickable)
    except Exception as e:  # noqa: BLE001 行情库不可用时走势小图降级为空
        print(f"  ! trends 降级(marketdata 不可用): {e}")
        a_trends = {}
    us_trends = (us or {}).get("trends") or {}  # 台北 build_us 产出,随 us blob 带过来
    trends = {"meta": {"date": date_utc8, "a": len(a_trends), "us": len(us_trends)},
              "a": a_trends, "us": us_trends}
    (EXPORT_DIR / "trends.json").write_text(_dump(trends), encoding="utf-8")
    print(f"  trends: A股 {len(a_trends)} 只 / 美股 {len(us_trends)} 只")
    return path
