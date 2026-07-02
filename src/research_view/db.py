"""数据库连接层。

两条连接:
- research_view(读写):本项目自有库,所有采集/生成结果落这里。
- marketdata(只读):数据中心行情库。rv_rw 在 DB 层无写权限(物理只读,非仅靠约定),
  代码层再加 read_only=True 双保险。
"""
from __future__ import annotations

from contextlib import contextmanager

import psycopg

from . import config

# 全系统"今天/近N天"分桶依赖 PG 会话时区(current_date、::date)。
# 在连接层焊死 UTC+8,不再依赖服务器默认值——服务器迁移/重装成 UTC 也不会拉错日期。
_TZ_OPTIONS = "-c TimeZone=Asia/Shanghai"


@contextmanager
def rv_conn():
    """research_view 读写连接。"""
    conn = psycopg.connect(config.research_view_dsn(), options=_TZ_OPTIONS)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def marketdata_conn():
    """marketdata 只读连接(read_only 事务 + DB 层无写权限双保险)。"""
    conn = psycopg.connect(config.marketdata_ro_dsn(), options=_TZ_OPTIONS)
    conn.read_only = True
    try:
        yield conn
    finally:
        conn.close()
