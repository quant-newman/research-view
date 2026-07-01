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

from . import config, db

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
                   rn.matched_tech_codes, rn.tech_industries, rn.pub_time
            FROM raw_news rn
            WHERE rn.relevant AND (rn.is_chain_relevant IS NOT false
                  OR array_length(rn.matched_codes,1) > 0 OR array_length(rn.matched_tech_codes,1) > 0)
            ORDER BY rn.pub_time DESC""")
        news = cur.fetchall()

        # 个股事件(近30天 + 未来解禁)
        cur.execute("""SELECT code,ts_code,node_ids,event_type,direction,event_date,summary
            FROM stock_event WHERE event_date >= current_date - 30 ORDER BY event_date DESC, event_type""")
        events = cur.fetchall()

        cur.execute("SELECT node_id, chain, node FROM node")
        node_meta = {nid: {"chain": ch, "node": nd} for nid, ch, nd in cur.fetchall()}

    with db.marketdata_conn() as mc, mc.cursor() as mcur:
        temperature = _temperature(mcur, pool_ts)

    def flags(codes):
        codes = codes or []
        return {"holding": any(c in holds for c in codes), "watching": any(c in watches for c in codes)}

    # 按节点分组新闻;核心链节点在前,泛科技行业组在后
    by_node: dict[str, dict] = {}
    for nid, src, title, one_line, sent, etype, url, codes, node_ids, tech_codes, tech_inds, pub_time in news:
        item = {"title": title, "one_line": one_line, "sentiment": sent, "event_type": etype,
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
            falsification,holdings_moves,generated_at FROM daily_report
            WHERE report_date=to_date(%s,'YYYYMMDD') ORDER BY generated_at DESC LIMIT 1""",
            (date_utc8,))
        row = cur.fetchone()
        report = None
        if row:
            report = {"report_id": row[0], "session": row[1], "data_cutoff": row[2],
                      "headline": row[3], "top3": row[4], "sectors": row[5],
                      "falsification": row[6], "holdings_moves": row[7],
                      "generated_at": str(row[8])}
            # 盘前报告附隔夜美股科技链(台北 yfinance 产出,scp 到本机 exports/),供前端小面板
            if row[1] == "premarket":
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
            or_yoy,gross_margin,pe,ps,quadrant FROM heatmap_node ORDER BY total_mv DESC NULLS LAST""")
        hn = [{"node_id": r[0], "chain": r[1], "node": r[2], "n_stocks": r[3],
               "total_mv": fnum(r[4]), "ret_1m": fnum(r[5]), "ret_6m": fnum(r[6]),
               "or_yoy": fnum(r[7]), "gross_margin": fnum(r[8]), "pe": fnum(r[9]),
               "ps": fnum(r[10]), "quadrant": r[11]} for r in cur.fetchall()]
        cur.execute("""SELECT code,name,total_mv,pe,ps,ret_1m,ret_6m,or_yoy,gross_margin,pe_pct
            FROM heatmap_stock ORDER BY total_mv DESC NULLS LAST""")
        hs = [{"code": r[0], "name": r[1], "total_mv": fnum(r[2]), "pe": fnum(r[3]),
               "ps": fnum(r[4]), "ret_1m": fnum(r[5]), "ret_6m": fnum(r[6]),
               "or_yoy": fnum(r[7]), "gross_margin": fnum(r[8]), "pe_pct": fnum(r[9])}
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
    research = {"reports": reports, "coverage": coverage, "letters": letters}

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

    from . import monitor
    try:
        health = monitor.health()
    except Exception as e:  # noqa: BLE001 健康汇总失败不应阻塞导出
        health = {"level": "yellow", "error": str(e)[:200], "sources": [], "tasks": [], "flags": []}

    dash = {"meta": ev["meta"], "report": report, "temperature": ev["temperature"],
            "news_by_node": ev["news_by_node"], "stock_events": ev["stock_events"],
            "heatmap": heatmap, "health": health, "research": research, "ledger": ledger}
    path = EXPORT_DIR / "dashboard.json"
    path.write_text(_dump(dash), encoding="utf-8")
    return path
