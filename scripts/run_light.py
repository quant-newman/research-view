#!/usr/bin/env python3
"""盘中轻量刷新:只刷新闻/研报(行情类上游 EOD/22:00 才更新,盘中重算无意义)。

采集→漏斗→B1(含核心观点提炼)→近3日研报→导出 dashboard。每步失败不阻断。
增量友好:funnel 只处理 relevant IS NULL、B1 只处理未结构化,所以每次很轻。
用法: ./.venv/bin/python scripts/run_light.py [YYYYMMDD]
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from research_view import config, export, hotspots, monitor  # noqa: E402
from research_view.collect import news, research  # noqa: E402
from research_view.funnel import run_funnel  # noqa: E402
from research_view.structure import run_structure  # noqa: E402


def step(name, fn):
    try:
        with monitor.task_run(name) as t:
            t["result"] = fn()
        print(f"  {name}: {t['result']}")
    except Exception as e:  # noqa: BLE001 单步失败不阻断
        print(f"  {name}: ✗失败 {str(e)[:120]}(继续)")


def main() -> None:
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.now(ZoneInfo(config.TZ)).strftime("%Y%m%d")
    print(f"[Light] {date} UTC+8 盘中刷新")
    step("fetch_news", lambda: {"n": news.fetch_major_news(date)})
    step("funnel", run_funnel)
    step("structure_b1", run_structure)
    step("research", lambda: research.collect_reports(3))
    step("hotspots", lambda: {"n": hotspots.persist(date)})
    step("export_dashboard", lambda: str(export.build_dashboard(date)))


if __name__ == "__main__":
    main()
