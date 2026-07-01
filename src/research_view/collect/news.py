"""major_news 采集器(Tushare 唯一开放的新闻源,~800条/日,标题级)。

只落原始新闻,不做判断。去重键 = url(缺失时用 title|pub_time 的 hash)。
"""
from __future__ import annotations

import hashlib

import tushare as ts

from .. import config, db


def _news_id(url: str | None, title: str, pub_time: str) -> tuple[str, str]:
    """返回 (news_id, content_hash)。"""
    chash = hashlib.sha1(f"{title}|{pub_time}".encode("utf-8")).hexdigest()
    nid = url.strip() if url and url.strip() else f"h:{chash}"
    return nid, chash


def fetch_major_news(date_utc8: str) -> int:
    """抓某日 major_news 落库。date_utc8 = 'YYYYMMDD'。返回新增/更新条数。"""
    pro = ts.pro_api(config.tushare_token())
    start = f"{date_utc8} 00:00:00"
    end = f"{date_utc8} 23:59:59"
    df = pro.major_news(start_date=start, end_date=end)
    rows = []
    for _, r in df.iterrows():
        title = str(r.get("title") or "").strip()
        if not title:
            continue
        pub = str(r.get("pub_time") or "").strip()
        url = r.get("url")
        nid, chash = _news_id(url, title, pub)
        content = r.get("content")
        content = str(content).strip() if content is not None and str(content).strip() else None
        rows.append((nid, str(r.get("src") or ""), title, pub, url, content, chash))

    if not rows:
        return 0
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO raw_news(news_id,src,title,pub_time,url,content,content_hash)
               VALUES(%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT(news_id) DO UPDATE SET title=EXCLUDED.title,src=EXCLUDED.src""",
            rows,
        )
    return len(rows)
