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
from research_view import config, db, decision, evidence, export, hotspots, monitor, report, research_digest, scorecard, universe  # noqa: E402
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
    def _fetch_news():
        skip = news.throttle(force=True)  # 盘后主采只受40硬顶约束;拦截时失败入health但带标记不计台账
        if skip:
            raise RuntimeError(skip)
        return {"n": news.fetch_major_news(date)}
    step("fetch_news", _fetch_news)
    step("funnel", run_funnel)
    step("structure_b1", run_structure)
    step("stock_events", announcements.collect_events)
    step("heatmap", heatmap.compute)
    step("research", lambda: research.collect_reports(30))
    step("research_digest", lambda: research_digest.persist(date))  # 评级变动榜+观点提炼
    # 每日报告(心脏 B3):需在上面各源采集后、导出前生成,dashboard 才拿得到当日报告
    step("report_afterhours", lambda: {"report_id": report.persist_afterhours(date)})
    step("hotspots", lambda: {"n": hotspots.persist(date)})  # 今日热点/主题热度榜
    # 校准期冻结状态留痕(DECISIONS #28):records_count 1=冻结(lessons只落库不注入)/0=解冻
    step("calibration_freeze", lambda: {"frozen": int(config.calibration_freeze())})
    # 参照层每日成分快照(留痕):B7 记分按发卡日快照锚定,参照层改版不追溯污染在途卡
    step("ref_snapshot", lambda: {"n": scorecard.snapshot_membership(date)})
    # B6 节点研判卡(二期):六源z矩阵+共振/背离代码算,DeepSeek 出方向/置信/证据链/情景,
    # append-only 落卡供 B7 记分。须在 EOD 资金/龙虎榜/研报都落地后跑(盘后 22:30 满足)。
    step("judgment_cards", lambda: {"n": evidence.persist(date)})
    # B8 个股决策卡(四期,影子运行):候选=当日方向节点卡成分股,须在 judgment_cards 之后
    step("decision_cards", lambda: {"n": decision.persist(date)})
    # B7 日常记分(三期):到期卡(节点+个股)按 horizon 相对全池超额对账,零LLM幂等;周度收口在周日 cron
    step("card_scores", scorecard.score_mature)

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
