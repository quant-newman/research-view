#!/usr/bin/env python3
"""确认新闻层可用数据源的量级与结构:major_news 日量 + marketdata 结构化公告表。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from research_view import config, db  # noqa: E402

import tushare as ts  # noqa: E402

pro = ts.pro_api(config.tushare_token())

# major_news 今日全量量级
df = pro.major_news(start_date="20260701 00:00:00", end_date="20260701 23:59:59")
print(f"major_news 今日: {len(df)} 条; 来源分布: {df['src'].value_counts().to_dict() if len(df) else {}}")

# marketdata 结构化公告表:字段 + 最新日期 + 我们池子近30天条数
with db.marketdata_conn() as conn, conn.cursor() as cur:
    for tbl, datecol in [("forecast", "ann_date"), ("express", "ann_date"),
                         ("holder_trade", "ann_date"), ("share_float", "ann_date"),
                         ("hot_rank", "trade_date"), ("moneyflow_rt", "trade_date")]:
        try:
            cur.execute(f"SELECT string_agg(column_name,',') FROM information_schema.columns "
                        f"WHERE table_schema='md' AND table_name='{tbl}'")
            cols = cur.fetchone()[0]
            cur.execute(f"SELECT max({datecol}) FROM md.{tbl}")
            mx = cur.fetchone()[0]
            print(f"\nmd.{tbl}: 最新{datecol}={mx}\n  字段: {cols}")
        except Exception as e:
            print(f"\nmd.{tbl}: ERR {str(e)[:100]}")
