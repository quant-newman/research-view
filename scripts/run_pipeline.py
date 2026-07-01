#!/usr/bin/env python3
"""第1步 新闻/事件层 全流程编排(采集→漏斗→B1结构化→个股事件→导出)。

用法: ./.venv/bin/python scripts/run_pipeline.py [YYYYMMDD]
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from research_view import config, export  # noqa: E402
from research_view.collect import announcements, news  # noqa: E402
from research_view.funnel import run_funnel  # noqa: E402
from research_view.structure import run_structure  # noqa: E402


def main() -> None:
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.now(ZoneInfo(config.TZ)).strftime("%Y%m%d")
    print(f"[Pipeline] {date} UTC+8")
    print(f"  1) 采集 major_news: {news.fetch_major_news(date)} 条")
    print(f"  2) 规则漏斗: {run_funnel()}")
    print(f"  3) B1 结构化: {run_structure()}")
    print(f"  4) 个股事件(marketdata公告/龙虎榜): {announcements.collect_events()}")
    path = export.build_export(date)
    print(f"  5) 导出事件流 JSON: {path}")


if __name__ == "__main__":
    main()
