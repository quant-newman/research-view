"""基金信函入库(阿里云侧,纯 DB,不依赖 bs4)。

抓取+B5 在台北侧(scripts/fetch_fund_letters.py,国内连不了海外站),产出 JSON;
本模块读 JSON upsert 进 fund_letter。letter_id 稳定(hash url),可重跑覆盖摘要。
"""
from __future__ import annotations

import json
from pathlib import Path

from . import config, db


def ingest(path: str | None = None, date_utc8: str | None = None) -> dict:
    """读 exports/fund_letters_DATE.json,upsert 进 fund_letter。"""
    if path is None:
        p = config.ROOT / "exports" / f"fund_letters_{date_utc8}.json"
    else:
        p = Path(path)
    if not p.exists():
        return {"ingested": 0, "note": f"无文件 {p.name}"}
    rows = json.loads(p.read_text(encoding="utf-8")).get("letters", [])
    if not rows:
        return {"ingested": 0}
    with db.rv_conn() as conn, conn.cursor() as cur:
        for r in rows:
            cur.execute(
                """INSERT INTO fund_letter(letter_id,fund_name,title,period,url,
                    core_views,stance,strategy,relevance,relevant_points,status)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT(letter_id) DO UPDATE SET title=EXCLUDED.title,
                     period=EXCLUDED.period, core_views=EXCLUDED.core_views,
                     stance=EXCLUDED.stance, strategy=EXCLUDED.strategy,
                     relevance=EXCLUDED.relevance, relevant_points=EXCLUDED.relevant_points,
                     status=EXCLUDED.status""",
                (r["letter_id"], r["fund_name"], r.get("title"), r.get("period"), r.get("url"),
                 json.dumps(r.get("core_views"), ensure_ascii=False), r.get("stance"),
                 r.get("strategy"), r.get("relevance"),
                 json.dumps(r.get("relevant_points"), ensure_ascii=False), r.get("status")),
            )
    return {"ingested": len(rows)}
