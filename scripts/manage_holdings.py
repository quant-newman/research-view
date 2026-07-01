#!/usr/bin/env python3
"""持仓/自选最小维护 CLI(第一版;正式维护页后续做)。

隐私:金额类 cost_price/position_pct 只存本库,绝不进静态导出。
in_pool 自动判定(是否在 180 池 stock 表内);池外票也可加,前端标"⚠池外"。

用法:
  python3 scripts/manage_holdings.py hold  300308 --cost 120.5 --pct 8
  python3 scripts/manage_holdings.py watch 688498 --note "等回调"
  python3 scripts/manage_holdings.py drop  hold 300308
  python3 scripts/manage_holdings.py list
在阿里云侧运行(依赖 psycopg)。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from research_view import config  # noqa: E402


def _name_and_pool(cur, code: str) -> tuple[str | None, bool]:
    cur.execute("SELECT name FROM stock WHERE code=%s", (code,))
    row = cur.fetchone()
    return (row[0], True) if row else (None, False)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("hold"); h.add_argument("code"); h.add_argument("--name"); h.add_argument("--cost", type=float); h.add_argument("--pct", type=float); h.add_argument("--note")
    w = sub.add_parser("watch"); w.add_argument("code"); w.add_argument("--name"); w.add_argument("--note")
    d = sub.add_parser("drop"); d.add_argument("kind", choices=["hold", "watch"]); d.add_argument("code")
    sub.add_parser("list")
    a = ap.parse_args()

    with psycopg.connect(config.research_view_dsn()) as conn, conn.cursor() as cur:
        if a.cmd == "hold":
            name, in_pool = _name_and_pool(cur, a.code)
            name = a.name or name or a.code
            cur.execute(
                """INSERT INTO holdings(code,name,in_pool,cost_price,position_pct,note)
                   VALUES(%s,%s,%s,%s,%s,%s)
                   ON CONFLICT(code) DO UPDATE SET name=EXCLUDED.name,in_pool=EXCLUDED.in_pool,
                     cost_price=EXCLUDED.cost_price,position_pct=EXCLUDED.position_pct,
                     note=EXCLUDED.note,updated_at=now()""",
                (a.code, name, in_pool, a.cost, a.pct, a.note),
            )
            print(f"持有 {a.code} {name}{'' if in_pool else ' ⚠池外'}")
        elif a.cmd == "watch":
            name, in_pool = _name_and_pool(cur, a.code)
            name = a.name or name or a.code
            cur.execute(
                """INSERT INTO watchlist(code,name,in_pool,note) VALUES(%s,%s,%s,%s)
                   ON CONFLICT(code) DO UPDATE SET name=EXCLUDED.name,in_pool=EXCLUDED.in_pool,
                     note=EXCLUDED.note,updated_at=now()""",
                (a.code, name, in_pool, a.note),
            )
            print(f"自选 {a.code} {name}{'' if in_pool else ' ⚠池外'}")
        elif a.cmd == "drop":
            tbl = "holdings" if a.kind == "hold" else "watchlist"
            cur.execute(f"DELETE FROM {tbl} WHERE code=%s", (a.code,))
            print(f"移除 {a.kind} {a.code}")
        elif a.cmd == "list":
            for tbl in ("holdings", "watchlist"):
                cur.execute(f"SELECT code,name,in_pool,note FROM {tbl} ORDER BY code")
                print(f"\n== {tbl} ==")
                for code, name, in_pool, note in cur.fetchall():
                    print(f"  {code} {name}{'' if in_pool else ' ⚠池外'}  {note or ''}")
        conn.commit()


if __name__ == "__main__":
    main()
