#!/usr/bin/env python3
"""[开工现场验] 实测 Tushare 1万积分在本 token 下开放了哪些新闻/公告类接口。

行情/财务/资金/龙虎榜已在 marketdata,不重复采;此处只探"marketdata 没有的":
公告原文、新闻快讯、互动易问答。决定新闻层数据源设计。
在阿里云 venv 跑: ./.venv/bin/python scripts/probe_tushare.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from research_view import config  # noqa: E402

import tushare as ts  # noqa: E402

pro = ts.pro_api(config.tushare_token())


def probe(name: str, fn):
    try:
        df = fn()
        n = 0 if df is None else len(df)
        cols = [] if df is None else list(df.columns)
        sample = ""
        if n:
            sample = " | 样例: " + str(df.iloc[0].to_dict())[:180]
        print(f"✅ {name}: {n} 行, 字段={cols}{sample}")
    except Exception as e:
        print(f"❌ {name}: {str(e)[:160]}")


# 先确认 token 有效(便宜接口)
probe("stock_basic(token有效性)", lambda: pro.stock_basic(exchange="", list_status="L", fields="ts_code,name").head(2))

# 新闻/公告类(marketdata 没有的,重点探)
probe("anns_d 信息披露公告", lambda: pro.anns_d(ts_code="300308.SZ", start_date="20260625", end_date="20260701").head(3))
probe("news 新闻快讯", lambda: pro.news(src="sina", start_date="20260701 00:00:00", end_date="20260701 23:59:59").head(3))
probe("major_news 长篇新闻", lambda: pro.major_news(start_date="20260701 00:00:00", end_date="20260701 23:59:59").head(3))
probe("cctv_news 新闻联播", lambda: pro.cctv_news(date="20260630").head(3))
probe("irm_qa_sz 互动易(深)", lambda: pro.irm_qa_sz(ts_code="300308.SZ", start_date="20260625", end_date="20260701").head(3))
