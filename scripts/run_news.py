#!/usr/bin/env python3
"""第1步 新闻管线(采集 + 规则漏斗),跑一天并出摘要。

用法: ./.venv/bin/python scripts/run_news.py [YYYYMMDD]  (默认今天 UTC+8)
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from research_view import config, db  # noqa: E402
from research_view.collect import news  # noqa: E402
from research_view.funnel import run_funnel  # noqa: E402


def main() -> None:
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.now(ZoneInfo(config.TZ)).strftime("%Y%m%d")
    print(f"[新闻管线] 日期={date} UTC+8")

    n = news.fetch_major_news(date)
    print(f"  采集 major_news: {n} 条落库")

    res = run_funnel()
    print(f"  规则漏斗: 处理 {res['processed']} 条,命中相关 {res['relevant']} 条")

    # 按节点分组的相关事件流(取样展示)
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT n.node_id, node.chain, node.node, count(*) AS cnt
            FROM raw_news rn
            CROSS JOIN LATERAL unnest(rn.matched_node_ids) AS n(node_id)
            JOIN node ON node.node_id = n.node_id
            WHERE rn.relevant
            GROUP BY n.node_id, node.chain, node.node
            ORDER BY cnt DESC LIMIT 12
        """)
        print("\n  相关新闻·按节点 Top12:")
        for node_id, chain, nodename, cnt in cur.fetchall():
            print(f"    {cnt:>3}  {chain}/{nodename}")

        cur.execute("""
            SELECT src, title, matched_codes, matched_themes
            FROM raw_news WHERE relevant ORDER BY pub_time DESC LIMIT 8
        """)
        print("\n  最近命中样例:")
        for src, title, codes, themes in cur.fetchall():
            tag = (codes or []) + (themes or [])
            print(f"    [{src}] {title[:42]}  ← {','.join(tag[:4])}")


if __name__ == "__main__":
    main()
