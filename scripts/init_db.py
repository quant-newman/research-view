#!/usr/bin/env python3
"""按顺序应用 sql/*.sql 到 research_view,并从 data/ 载入参照数据。幂等,可重复跑。

在阿里云侧运行(能连 127.0.0.1:5432)。依赖 psycopg。
用法: python3 scripts/init_db.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from research_view import config  # noqa: E402


def main() -> None:
    dsn = config.research_view_dsn()
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            for f in sorted((ROOT / "sql").glob("*.sql")):
                print(f"applying {f.name} ...")
                cur.execute(f.read_text(encoding="utf-8"))
        conn.commit()

    # 参照数据(gen 脚本产出 SQL,再灌)
    ref_sql = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gen_reference_sql.py")],
        capture_output=True, text=True, check=True,
    ).stdout
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(ref_sql)
        conn.commit()
    print("done. 参照数据已载入。ts_code 回填请单独跑(需读 marketdata)。")


if __name__ == "__main__":
    main()
