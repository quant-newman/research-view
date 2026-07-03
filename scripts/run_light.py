#!/usr/bin/env python3
"""盘中轻量刷新:刷新闻/研报 + 重生成 B3 报告/热点(行情类上游 EOD/22:00 才更新,盘中重算无意义)。

采集→漏斗→B1(含核心观点提炼)→近3日研报→观点提炼→盘中报告(session=intraday)→热点→导出 dashboard。每步失败不阻断。
增量友好:funnel 只处理 relevant IS NULL、B1 只处理未结构化,所以每次很轻。
新闻节流:Tushare major_news 配额 40次/天,cron 每15min 全抓必超限(64+盘后>40,实测 2026-07-03 午后连续
频率超限)——只在 :00/:30 火点抓(32次/天+盘后1次=33,留7次余量给手动),:15/:45 档跳过只跑下游增量。
用法: ./.venv/bin/python scripts/run_light.py [YYYYMMDD] [--news 强制抓新闻(手动补抓用)]
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from research_view import config, export, hotspots, monitor, report, research_digest  # noqa: E402
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
    now = datetime.now(ZoneInfo(config.TZ))
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    date = args[0] if args else now.strftime("%Y%m%d")
    print(f"[Light] {date} UTC+8 盘中刷新")
    # cron 火点 :00/:15/:30/:45,minute%30<15 挑出 :00/:30 两档
    if "--news" in sys.argv or now.minute % 30 < 15:
        step("fetch_news", lambda: {"n": news.fetch_major_news(date)})
    else:
        print("  fetch_news: 跳过(major_news 配额节流,每30min一抓;强制用 --news)")
    step("funnel", run_funnel)
    step("structure_b1", run_structure)
    step("research", lambda: research.collect_reports(3))
    step("research_digest", lambda: research_digest.persist(date))
    # 盘中重生成 B3 报告(基于截至此刻的新闻/研报/事件),让报告页盘中也"活"
    step("report_intraday", lambda: {"report_id": report.persist_intraday(date)})
    step("hotspots", lambda: {"n": hotspots.persist(date)})
    step("export_dashboard", lambda: str(export.build_dashboard(date)))


if __name__ == "__main__":
    main()
