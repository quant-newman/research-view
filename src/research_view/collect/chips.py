"""筹码成本采集(Tushare cyq_perf,东财式估算口径,交易日盘后 17-18 点更新)。

全市场按 trade_date 单次调用(~5500 行)→ 只保留核心池(heatmap_stock)票 upsert。
个股详情弹层「筹码/持仓成本」展示专用:不进 B6/B8 证据矩阵(#22 冻结,
要作信号须先过回测台架)。公共可重拉(宪法梯队4),滚动保留近 30 日。
非交易日跑=重拉最近交易日同数据,幂等。
"""
from __future__ import annotations

import math

import tushare as ts

from .. import config, db


def _f(v) -> float | None:
    try:
        v = float(v)
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None


def collect() -> dict:
    with db.marketdata_conn() as mc:
        cur = mc.cursor()
        cur.execute("SELECT max(trade_date) FROM md.moneyflow")  # 最近已落地交易日
        d = cur.fetchone()[0]
    if not d:
        return {"records_count": 0}
    pro = ts.pro_api(config.tushare_token())
    df = pro.cyq_perf(trade_date=d.strftime("%Y%m%d"))
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT ts_code, code FROM heatmap_stock WHERE ts_code IS NOT NULL")
        code_of = dict(cur.fetchall())
        rows = [(code_of[r.ts_code], d, _f(r.weight_avg), _f(r.winner_rate),
                 _f(r.cost_5pct), _f(r.cost_95pct))
                for r in df.itertuples() if r.ts_code in code_of]
        cur.executemany(
            """INSERT INTO chip_cost(code,trade_date,weight_avg,winner_rate,cost_5pct,cost_95pct)
               VALUES(%s,%s,%s,%s,%s,%s)
               ON CONFLICT (code,trade_date) DO UPDATE SET
                 weight_avg=EXCLUDED.weight_avg, winner_rate=EXCLUDED.winner_rate,
                 cost_5pct=EXCLUDED.cost_5pct, cost_95pct=EXCLUDED.cost_95pct,
                 fetched_at=now()""", rows)
        cur.execute("DELETE FROM chip_cost WHERE trade_date < current_date - 30")
    return {"records_count": len(rows), "trade_date": str(d)}
