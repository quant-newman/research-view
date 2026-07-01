#!/usr/bin/env python3
"""第1步 新闻/事件层 全流程编排(采集→漏斗→B1结构化→个股事件→热力图→校验→导出)。
每步计时并落 task_log,任何一步失败可在 health 里看到。

用法: ./.venv/bin/python scripts/run_pipeline.py [YYYYMMDD]
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from research_view import config, db, export, monitor  # noqa: E402
from research_view.collect import announcements, heatmap, news  # noqa: E402
from research_view.funnel import run_funnel  # noqa: E402
from research_view.structure import run_structure  # noqa: E402


def step(name, fn):
    with monitor.task_run(name) as t:
        t["result"] = fn()
    print(f"  {name}: {t['result']}")


def main() -> None:
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.now(ZoneInfo(config.TZ)).strftime("%Y%m%d")
    print(f"[Pipeline] {date} UTC+8")
    step("fetch_news", lambda: {"n": news.fetch_major_news(date)})
    step("funnel", run_funnel)
    step("structure_b1", run_structure)
    step("stock_events", announcements.collect_events)
    step("heatmap", heatmap.compute)

    # 数据质量校验
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT ts_code FROM stock WHERE ts_code IS NOT NULL")
        pool_ts = [r[0] for r in cur.fetchall()]
    step("sanity_checks", lambda: monitor.sanity_checks(pool_ts))

    step("export_dashboard", lambda: str(export.build_dashboard(date)))
    print(f"  health level: {monitor.health()['level']}")


if __name__ == "__main__":
    main()
