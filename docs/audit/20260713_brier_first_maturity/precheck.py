# 07-13 白天准备令·三 只读预检(全部 SELECT,零写入)
import sys
sys.path.insert(0, "/opt/research_view/src")
from research_view import db

with db.rv_conn() as c:
    cur = c.cursor()
    print("=== 1/2/3. judgment_card trade_date=2026-07-06 (card_id,node_id,direction,prob,hash)")
    cur.execute("""SELECT card_id, node_id, direction, subjective_prob, prompt_hash
        FROM judgment_card WHERE trade_date='2026-07-06' ORDER BY card_id""")
    rows = cur.fetchall()
    for r in rows: print(r)
    probs = [float(r[3]) for r in rows if r[3] is not None]
    print("B6 count/nonnull/in(0,1)/hash_set:", len(rows), len(probs),
          sum(1 for p in probs if 0 < p < 1), sorted({r[4] for r in rows}))
    print("=== decision_card trade_date=2026-07-06")
    cur.execute("""SELECT card_id, code, direction, subjective_prob, prompt_hash
        FROM decision_card WHERE trade_date='2026-07-06' ORDER BY card_id""")
    rows = cur.fetchall()
    for r in rows: print(r)
    probs = [float(r[3]) for r in rows if r[3] is not None]
    print("B8 count/nonnull/in(0,1)/hash_set:", len(rows), len(probs),
          sum(1 for p in probs if 0 < p < 1), sorted({r[4] for r in rows}))
    print("=== 4. 07-06批既有score(应为空)")
    cur.execute("SELECT card_id FROM card_score WHERE card_id BETWEEN 19 AND 26 ORDER BY card_id")
    print("card_score(19-26):", cur.fetchall())
    cur.execute("SELECT card_id FROM decision_score WHERE card_id BETWEEN 15 AND 26 ORDER BY card_id")
    print("decision_score(15-26):", cur.fetchall())
    print("=== 6. 参照层现状(对890ecb4纪元:77登记节点/267映射)")
    cur.execute("SELECT count(*) FROM node")
    print("node登记数:", cur.fetchone()[0])
    cur.execute("SELECT count(*) FROM stock_node")
    print("stock_node映射数:", cur.fetchone()[0])
    cur.execute("""SELECT snap_date, count(*), count(DISTINCT node_id)
        FROM ref_membership_snap GROUP BY snap_date ORDER BY snap_date DESC LIMIT 3""")
    print("ref_membership_snap近3日(snap_date,rows,distinct_node):", cur.fetchall())
