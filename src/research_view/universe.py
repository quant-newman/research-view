"""科技行业域构建:申万一级 电子/计算机/通信/传媒 ∪ 180核心池。

读 marketdata.index_member(申万成分,当前 out_date 为空),写 research_view.tech_stock。
核心池票标 in_pool=true(高亮子集),泛科技票带申万行业。
"""
from __future__ import annotations

from . import db

TECH_L1 = ("电子", "计算机", "通信", "传媒")


def build() -> dict[str, int]:
    # 核心池
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT code, ts_code, name FROM stock")
        pool = {c: (t, n) for c, t, n in cur.fetchall()}

    rows: dict[str, tuple] = {}
    # 科技 L1 成分(申万当前)
    with db.marketdata_conn() as mc, mc.cursor() as cur:
        cur.execute("""SELECT DISTINCT ON (ts_code) ts_code, l1_name, l2_name
            FROM md.index_member WHERE out_date IS NULL AND l1_name = ANY(%s)
            ORDER BY ts_code, in_date DESC""", (list(TECH_L1),))
        sw = cur.fetchall()
        ts_list = [r[0] for r in sw]
        cur.execute("""SELECT ts_code, name FROM md.security WHERE ts_code = ANY(%s)""", (ts_list,))
        names = dict(cur.fetchall())
    for ts, l1, l2 in sw:
        code = ts[:6]
        rows[code] = (code, ts, names.get(ts, code), l1, l2, code in pool)

    # 并入核心池(池内票即使不在科技L1也纳入,行业留空)
    for code, (ts, name) in pool.items():
        if code not in rows:
            rows[code] = (code, ts, name, None, None, True)
        else:
            r = rows[code]
            rows[code] = (r[0], r[1], r[2], r[3], r[4], True)

    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE tech_stock")
        cur.executemany("""INSERT INTO tech_stock(code,ts_code,name,sw_l1,sw_l2,in_pool)
            VALUES(%s,%s,%s,%s,%s,%s)""", list(rows.values()))
    n_pool = sum(1 for r in rows.values() if r[5])
    return {"tech_total": len(rows), "in_pool": n_pool, "broad": len(rows) - n_pool}
