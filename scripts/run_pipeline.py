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
from research_view import config, db, export, hotspots, monitor, report, research_digest, universe  # noqa: E402
from research_view.collect import announcements, heatmap, news, research  # noqa: E402
from research_view.funnel import run_funnel  # noqa: E402
from research_view.structure import run_structure  # noqa: E402


def step(name, fn) -> bool:
    """跑一步:计时+落 task_log。失败只记录+打印,不抛出——保证后续步骤(尤其
    export_dashboard 兜底导出)照常跑,前端拿到"现有数据+失败告警"而非冻结。返回是否成功。"""
    try:
        with monitor.task_run(name) as t:
            t["result"] = fn()
        print(f"  {name}: {t['result']}")
        return True
    except Exception as e:  # noqa: BLE001 单步失败不阻断整条管道
        print(f"  {name}: ✗失败 {str(e)[:140]}(已记 task_log,继续)")
        return False


def main() -> None:
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.now(ZoneInfo(config.TZ)).strftime("%Y%m%d")
    print(f"[Pipeline] {date} UTC+8")
    step("tech_universe", universe.build)
    step("fetch_news", lambda: {"n": news.fetch_major_news(date)})
    step("funnel", run_funnel)
    step("structure_b1", run_structure)
    step("stock_events", announcements.collect_events)
    step("heatmap", heatmap.compute)
    step("research", lambda: research.collect_reports(30))
    step("research_digest", lambda: research_digest.persist(date))  # 评级变动榜+观点提炼
    # 每日报告(心脏 B3):需在上面各源采集后、导出前生成,dashboard 才拿得到当日报告
    step("report_afterhours", lambda: {"report_id": report.persist_afterhours(date)})
    step("hotspots", lambda: {"n": hotspots.persist(date)})  # 今日热点/主题热度榜

    # 数据质量校验
    try:
        with db.rv_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT ts_code FROM stock WHERE ts_code IS NOT NULL")
            pool_ts = [r[0] for r in cur.fetchall()]
    except Exception as e:  # noqa: BLE001 取池失败不阻断导出
        print(f"  pool_ts 取失败,跳过校验: {str(e)[:80]}")
        pool_ts = []
    if pool_ts:
        step("sanity_checks", lambda: monitor.sanity_checks(pool_ts))

    # 兜底导出:无论上面哪步失败,都刷新 dashboard(前端至少拿到现有数据+失败角标)
    step("export_dashboard", lambda: str(export.build_dashboard(date)))
    try:
        print(f"  health level: {monitor.health()['level']}")
    except Exception as e:  # noqa: BLE001
        print(f"  health 汇总失败: {str(e)[:80]}")


if __name__ == "__main__":
    main()
