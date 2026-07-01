"""系统健康监控 + 数据质量校验。挂了要第一时间知道;脏数据标记存疑而非丢弃。"""
from __future__ import annotations

import time
from contextlib import contextmanager

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
        for tbl, col in [("bar_daily_raw", "trade_date"), ("daily_basic", "trade_date"),
                         ("moneyflow", "trade_date"), ("top_list", "trade_date")]:
            cur.execute(f"SELECT max({col}) FROM md.{tbl}")
            mx = cur.fetchone()[0]
            stale = mx is None
            out["sources"].append({"name": f"marketdata.{tbl}", "latest": str(mx), "stale": stale})

    with db.rv_conn() as conn, conn.cursor() as cur:
        # research_view 侧新鲜度
        for label, q in [("raw_news", "SELECT max(pub_time)::date FROM raw_news"),
                         ("stock_event", "SELECT max(created_at)::date FROM stock_event"),
                         ("daily_report", "SELECT max(generated_at)::date FROM daily_report"),
                         ("heatmap", "SELECT max(updated_at)::date FROM heatmap_node")]:
            cur.execute(q)
            mx = cur.fetchone()[0]
            out["sources"].append({"name": label, "latest": str(mx),
                                   "stale": mx is None or str(mx) != _today(cur)})
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
    any_stale = any(s["stale"] for s in out["sources"])
    out["level"] = "red" if any_fail else "yellow" if (any_stale or out["flags"]) else "green"
    return out


def _today(cur) -> str:
    cur.execute("SELECT current_date")
    return str(cur.fetchone()[0])
