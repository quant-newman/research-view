"""研究库采集:Tushare report_rc(卖方研报,已结构化,零 LLM)。

按日期区间拉全市场研报,过滤到 180 池,映射到节点。基金信函信源未接入,另见 fund_letter 表。
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta

import tushare as ts

from .. import config, db


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def collect_reports(days: int = 30) -> dict[str, int]:
    pro = ts.pro_api(config.tushare_token())
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT ts_code, code, name FROM stock WHERE ts_code IS NOT NULL")
        rows = cur.fetchall()
        cur.execute("SELECT code, array_agg(node_id) FROM stock_node GROUP BY code")
        code_nodes = dict(cur.fetchall())
    ts2code = {t: c for t, c, _ in rows}
    pool = set(ts2code)

    end = date.today()
    start = end - timedelta(days=days)
    # report_rc 支持日期区间(全市场),拉回后过滤到池子
    df = pro.report_rc(start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"))

    out = []
    for _, r in df.iterrows():
        ts_code = r.get("ts_code")
        if ts_code not in pool:
            continue
        code = ts2code[ts_code]
        rid = "r:" + hashlib.sha1(
            f"{ts_code}|{r.get('report_date')}|{r.get('org_name')}|{r.get('report_title')}".encode()
        ).hexdigest()[:20]
        rd = str(r.get("report_date") or "")
        out.append((
            rid, code, ts_code, r.get("name"),
            f"{rd[:4]}-{rd[4:6]}-{rd[6:8]}" if len(rd) == 8 else None,
            r.get("report_title"), r.get("org_name"), r.get("author_name"),
            r.get("rating"), r.get("classify"),
            _num(r.get("tp")), _num(r.get("eps")), _num(r.get("pe")), _num(r.get("roe")),
            r.get("quarter"), code_nodes.get(code, []),
        ))

    if out:
        with db.rv_conn() as conn, conn.cursor() as cur:
            cur.executemany("""INSERT INTO research_report(report_id,code,ts_code,name,report_date,
                title,org_name,author_name,rating,classify,tp,eps,pe,roe,quarter,node_ids)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(report_id) DO NOTHING""", out)
    return {"reports": len(out), "market_total": len(df)}
