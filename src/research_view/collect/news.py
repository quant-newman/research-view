"""major_news 采集器(Tushare 唯一开放的新闻源,~800条/日,标题级)。

只落原始新闻,不做判断。去重键 = url(缺失时用 title|pub_time 的 hash)。
"""
from __future__ import annotations

import hashlib
import html
import re

import tushare as ts

from .. import config, db

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _clean_html(s: str, limit: int = 2500) -> str | None:
    """去 HTML 标签/实体/多余空白,截断。major_news 正文是新浪等的 HTML,B1 只需纯文本。"""
    if not s:
        return None
    t = _TAG.sub(" ", s)
    t = html.unescape(t)
    t = _WS.sub(" ", t).strip()
    return t[:limit] or None


def _news_id(url: str | None, title: str, pub_time: str) -> tuple[str, str]:
    """返回 (news_id, content_hash)。"""
    chash = hashlib.sha1(f"{title}|{pub_time}".encode("utf-8")).hexdigest()
    nid = url.strip() if url and url.strip() else f"h:{chash}"
    return nid, chash


QUOTA_24H = 40      # major_news 配额实测按滚动24h窗口计,且超限的失败调用本身也计数
RESERVE = 6         # 盘中留给盘后主采/手动补抓的保底额度
COOLDOWN_MIN = 120  # 收到超限错误后的退避窗口(分钟),不再每30min重撞白烧配额


def throttle(force: bool = False) -> str | None:
    """调用前查滚动24h台账,可调返回 None,否则返回跳过原因。

    台账=task_log 里 fetch_news 的历史记录(成败都是一次真实API调用;
    被本函数拦下的跳过带'台账拦截'标记,不计入)。force=盘后主采/手动,
    只受硬顶约束不受保底/退避约束。"""
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("""SELECT count(*),
              bool_or(status='失败' AND error_msg ~ '最多访问|频率|超限'
                      AND ts_utc8 >= now() - make_interval(mins => %s))
            FROM task_log WHERE task='fetch_news'
              AND ts_utc8 >= now() - interval '24 hours'
              AND (error_msg IS NULL OR error_msg NOT LIKE '%%台账拦截%%')""",
            (COOLDOWN_MIN,))
        calls, cooling = cur.fetchone()
    cap = QUOTA_24H if force else QUOTA_24H - RESERVE
    if calls >= cap:
        return f"台账拦截:滚动24h已调{calls}次(本档上限{cap}/配额{QUOTA_24H})"
    if not force and cooling:
        return f"台账拦截:{COOLDOWN_MIN}分钟内曾撞配额,退避中(24h已调{calls}次)"
    return None


def fetch_major_news(date_utc8: str) -> int:
    """抓某日 major_news 落库(含正文,供 B1 提炼核心观点)。返回新增/更新条数。"""
    pro = ts.pro_api(config.tushare_token())
    start = f"{date_utc8} 00:00:00"
    end = f"{date_utc8} 23:59:59"
    # 显式要 content 字段(默认不返回正文)
    df = pro.major_news(src="", start_date=start, end_date=end, fields="title,content,pub_time,src,url")
    rows = []
    for _, r in df.iterrows():
        title = str(r.get("title") or "").strip()
        if not title:
            continue
        pub = str(r.get("pub_time") or "").strip()
        url = r.get("url")
        nid, chash = _news_id(url, title, pub)
        content = _clean_html(str(r.get("content") or ""))
        rows.append((nid, str(r.get("src") or ""), title, pub, url, content, chash))

    if not rows:
        return 0
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO raw_news(news_id,src,title,pub_time,url,content,content_hash)
               VALUES(%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT(news_id) DO UPDATE SET title=EXCLUDED.title,src=EXCLUDED.src,
                 content=COALESCE(EXCLUDED.content, raw_news.content)""",
            rows,
        )
    return len(rows)
