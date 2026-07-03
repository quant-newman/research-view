"""系统健康监控 + 数据质量校验。挂了要第一时间知道;脏数据标记存疑而非丢弃。"""
from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import time as dtime

from . import db


def record_task(task: str, status: str, records_count: int | None = None,
                duration_ms: int | None = None, error_msg: str | None = None) -> None:
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("""INSERT INTO task_log(task,status,records_count,duration_ms,error_msg)
            VALUES(%s,%s,%s,%s,%s)""", (task, status, records_count, duration_ms, error_msg))


def _count(result) -> int | None:
    if isinstance(result, dict):
        nums = [v for v in result.values() if isinstance(v, (int, float))]
        return int(sum(nums)) if nums else None
    return result if isinstance(result, int) else None


@contextmanager
def task_run(name: str):
    """包裹一个管线步骤:自动计时 + 成功/失败落 task_log。用法:
       with task_run('fetch_news') as t: t['result']=fetch(...)"""
    start = time.monotonic()
    box: dict = {}
    try:
        yield box
        dur = int((time.monotonic() - start) * 1000)
        record_task(name, "成功", _count(box.get("result")), dur)
    except Exception as e:  # noqa: BLE001
        dur = int((time.monotonic() - start) * 1000)
        record_task(name, "失败", 0, dur, str(e)[:500])
        raise


# ---------- 数据质量校验(J) ----------

def sanity_checks(pool_ts: list[str]) -> dict[str, int]:
    """对池子最新行情/估值做合理性校验,异常标记存疑(不丢弃)。"""
    flags = []
    with db.marketdata_conn() as mc, mc.cursor() as cur:
        cur.execute("SELECT max(trade_date) FROM md.bar_daily_raw")
        latest = cur.fetchone()[0]
        # 涨跌幅异常(>21%,主板涨跌停外;双创20%可能正常,这里只作提示)
        cur.execute("""SELECT ts_code, round((close-pre_close)/pre_close*100,2) AS pct
            FROM md.bar_daily_raw WHERE ts_code=ANY(%s) AND trade_date=%s
            AND pre_close>0 AND abs((close-pre_close)/pre_close*100) > 21""", (pool_ts, latest))
        for ts, pct in cur.fetchall():
            flags.append(("涨跌幅异常", ts[:6], f"{ts} 单日{pct}%"))
        # 停牌(当日无成交)
        cur.execute("""SELECT ts_code FROM md.bar_daily_raw
            WHERE ts_code=ANY(%s) AND trade_date=%s AND (volume=0 OR volume IS NULL)""", (pool_ts, latest))
        for (ts,) in cur.fetchall():
            flags.append(("停牌", ts[:6], f"{ts} 当日无成交"))
        # PE 极端(负 或 >1000)
        cur.execute("""SELECT DISTINCT ON (ts_code) ts_code, pe_ttm FROM md.daily_basic
            WHERE ts_code=ANY(%s) ORDER BY ts_code, trade_date DESC""", (pool_ts,))
        for ts, pe in cur.fetchall():
            if pe is not None and (pe < 0 or pe > 1000):
                flags.append(("PE极端", ts[:6], f"{ts} PE_TTM={pe}"))

    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM data_flag WHERE ts_utc8::date = current_date")  # 当日重算覆盖
        if flags:
            cur.executemany("INSERT INTO data_flag(kind,code,detail) VALUES(%s,%s,%s)", flags)
    from collections import Counter
    return dict(Counter(k for k, _, _ in flags))


# ---------- 健康汇总(供导出/前端) ----------

def health() -> dict:
    """各源新鲜度 + 今日任务成功率 + 数据存疑数,给前端角标/状态页。"""
    out: dict = {"sources": [], "tasks": [], "flags": [], "level": "green"}
    with db.marketdata_conn() as mc, mc.cursor() as cur:
        # 基准 = 交易日历上"最近的开市日"。行情类表本应更新到此日,落后即滞后(能抓到"上游停更")。
        # 但 EOD 表当日数据有落地时点(行情/估值~16:40,资金流/龙虎榜~22:00),
        # 交易日未到时点前只能停在上一开市日——此时基准退回上一开市日,否则盘中整天误报。
        cur.execute("SELECT max(cal_date) FROM md.trade_calendar WHERE is_open AND cal_date<=current_date")
        ltd = cur.fetchone()[0]
        cur.execute("SELECT max(cal_date) FROM md.trade_calendar WHERE is_open AND cal_date<current_date")
        prev_open = cur.fetchone()[0]
        cur.execute("SELECT current_date, localtime")
        today, now_t = cur.fetchone()
        for tbl, col, landed in [("bar_daily_raw", "trade_date", dtime(17, 30)),
                                 ("daily_basic", "trade_date", dtime(17, 30)),
                                 ("moneyflow", "trade_date", dtime(22, 15)),
                                 ("top_list", "trade_date", dtime(22, 15))]:
            expect = prev_open if (ltd == today and now_t < landed) else ltd
            cur.execute(f"SELECT max({col}) FROM md.{tbl}")
            mx = cur.fetchone()[0]
            stale = mx is None or (expect is not None and mx < expect)
            out["sources"].append({"name": f"marketdata.{tbl}", "latest": str(mx), "stale": stale})

    with db.rv_conn() as conn, conn.cursor() as cur:
        # research_view 侧新鲜度(我方落库/生成时点)。基准=最近开市日+各自落地时点(同上 md 逻辑):
        # 周末/节假日停在上一开市日是正常态;盘中要求"必须等于今天"会对只在盘后 22:30
        # 全管道更新的源(事件/研报/热力)整天误报。raw_news/daily_report 盘前 08:30 起就该有今日数据。
        for label, q, landed in [
                ("raw_news", "SELECT max(pub_time)::date FROM raw_news", dtime(9, 0)),
                ("stock_event", "SELECT max(created_at)::date FROM stock_event", dtime(23, 30)),
                ("research_report", "SELECT max(created_at)::date FROM research_report", dtime(23, 30)),
                ("daily_report", "SELECT max(generated_at)::date FROM daily_report", dtime(9, 0)),
                ("heatmap", "SELECT max(updated_at)::date FROM heatmap_node", dtime(23, 30))]:
            expect = prev_open if (ltd == today and now_t < landed) else ltd
            cur.execute(q)
            mx = cur.fetchone()[0]
            out["sources"].append({"name": label, "latest": str(mx),
                                   "stale": mx is None or (expect is not None and mx < expect)})
        # 基金信函:采集器未接入,标 pending(计入展示但不拉红黄,避免已知待办长期告警)
        cur.execute("SELECT count(*) FROM fund_letter")
        fl = cur.fetchone()[0]
        out["sources"].append({"name": "fund_letter", "latest": f"{fl}条" if fl else "未接入",
                               "stale": fl == 0, "pending": True})
        # 今日任务成功率
        cur.execute("""SELECT task, status, records_count, duration_ms, ts_utc8
            FROM task_log WHERE ts_utc8::date=current_date ORDER BY ts_utc8 DESC""")
        for task, status, cnt, dur, ts in cur.fetchall():
            out["tasks"].append({"task": task, "status": status, "count": cnt,
                                 "duration_ms": dur, "ts": str(ts)})
        # 今日存疑
        cur.execute("SELECT kind, count(*) FROM data_flag WHERE ts_utc8::date=current_date GROUP BY kind")
        out["flags"] = [{"kind": k, "count": c} for k, c in cur.fetchall()]

    any_fail = any(t["status"] == "失败" for t in out["tasks"])
    any_stale = any(s["stale"] for s in out["sources"] if not s.get("pending"))
    out["level"] = "red" if any_fail else "yellow" if (any_stale or out["flags"]) else "green"
    return out
