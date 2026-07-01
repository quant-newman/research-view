"""事件流导出:温度计 + 按节点分组的相关新闻 + 个股事件 → 静态 JSON(前端只读)。

隐私铁律:只输出"是否持仓/自选"布尔标记,绝不输出金额。
有效相关 = is_chain_relevant OR 标题明确点到池内票(不让 B1 砍自己池子的票)。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config, db

EXPORT_DIR = config.ROOT / "exports"


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

        # 相关新闻(有效相关),按节点分组
        cur.execute("""
            SELECT rn.news_id, rn.src, rn.title, rn.one_line, rn.sentiment,
                   rn.event_type, rn.url, rn.matched_codes, rn.matched_node_ids
            FROM raw_news rn
            WHERE rn.relevant AND (rn.is_chain_relevant IS NOT false OR array_length(rn.matched_codes,1) > 0)
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

    # 按节点分组新闻
    by_node: dict[str, dict] = {}
    for nid, src, title, one_line, sent, etype, url, codes, node_ids in news:
        for node_id in (node_ids or []):
            g = by_node.setdefault(node_id, {"node_id": node_id, **node_meta.get(node_id, {}), "items": []})
            g["items"].append({"title": title, "one_line": one_line, "sentiment": sent,
                               "src": src, "url": url, "codes": codes or [], **flags(codes)})
    news_by_node = sorted(by_node.values(), key=lambda g: -len(g["items"]))

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
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
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
    dash = {"meta": ev["meta"], "report": report, "temperature": ev["temperature"],
            "news_by_node": ev["news_by_node"], "stock_events": ev["stock_events"]}
    path = EXPORT_DIR / "dashboard.json"
    path.write_text(json.dumps(dash, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path
