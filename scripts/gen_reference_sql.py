#!/usr/bin/env python3
"""从 data/ 的三份 JSON 资产生成 research_view 参照数据 INSERT SQL(幂等 upsert)。

用法: python3 scripts/gen_reference_sql.py > /tmp/reference_data.sql
输出可直接喂给 psql 到 research_view。行情/财务不在此,走 marketdata 只读。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def q(s) -> str:
    """SQL 字面量转义(单引号翻倍);None -> NULL。"""
    if s is None or s == "":
        return "NULL"
    return "'" + str(s).replace("'", "''") + "'"


def main() -> None:
    nodes = json.loads((DATA / "nodes.json").read_text(encoding="utf-8"))
    smap = json.loads((DATA / "stock_node_map.json").read_text(encoding="utf-8"))
    tmap = json.loads((DATA / "theme_node_map.json").read_text(encoding="utf-8"))

    out = sys.stdout.write
    out("BEGIN;\n")

    # node
    for n in nodes:
        out(
            f"INSERT INTO node(node_id,chain,chain_en,node) VALUES "
            f"({q(n['node_id'])},{q(n['chain'])},{q(n['chain_en'])},{q(n['node'])}) "
            f"ON CONFLICT (node_id) DO UPDATE SET chain=EXCLUDED.chain,chain_en=EXCLUDED.chain_en,node=EXCLUDED.node;\n"
        )

    # stock(去重:同一 code 可能多行,取首次出现的 name)
    seen: dict[str, str] = {}
    for r in smap:
        seen.setdefault(r["code"], r["name"])
    for code, name in seen.items():
        out(
            f"INSERT INTO stock(code,name) VALUES ({q(code)},{q(name)}) "
            f"ON CONFLICT (code) DO UPDATE SET name=EXCLUDED.name;\n"
        )

    # stock_node(全量映射,含跨链多行)
    for r in smap:
        out(
            f"INSERT INTO stock_node(code,node_id,tier,purity,judgment) VALUES "
            f"({q(r['code'])},{q(r['node_id'])},{q(r.get('tier'))},{q(r.get('purity'))},{q(r.get('judgment'))}) "
            f"ON CONFLICT (code,node_id) DO UPDATE SET tier=EXCLUDED.tier,purity=EXCLUDED.purity,judgment=EXCLUDED.judgment;\n"
        )

    # theme_node(dict: theme -> [node_id,...])
    for theme, node_ids in tmap.items():
        for nid in node_ids:
            out(
                f"INSERT INTO theme_node(theme,node_id) VALUES ({q(theme)},{q(nid)}) "
                f"ON CONFLICT (theme,node_id) DO NOTHING;\n"
            )

    out("COMMIT;\n")
    sys.stderr.write(
        f"generated: {len(nodes)} nodes, {len(seen)} stocks, {len(smap)} stock_node rows, "
        f"{sum(len(v) for v in tmap.values())} theme_node rows\n"
    )


if __name__ == "__main__":
    main()
