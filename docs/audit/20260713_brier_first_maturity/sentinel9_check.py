# 07-13 22:30 收口·哨兵第9项两层核对 + 07-06到期批对账(全部 SELECT,零写入)
# 口径:docs/SENTINEL_SPEC.md 2026-07-13 追加节(选卡规则 14:48:02 锁定版)
import sys
sys.path.insert(0, "/opt/research_view/src")
from research_view import db
from research_view.scorecard import calibration_block

with db.rv_conn() as c:
    cur = c.cursor()

    print("=== (a) 选卡候选:node×direction 主核字段,direction≠中性,verdict∈{对,错},按 card_id 升序")
    cur.execute("""SELECT cs.card_id, jc.node_id, jc.direction, jc.subjective_prob, cs.verdict
        FROM card_score cs JOIN judgment_card jc USING(card_id)
        WHERE jc.subjective_prob IS NOT NULL AND jc.direction <> '中性'
          AND cs.verdict IN ('对','错')
        ORDER BY cs.card_id""")
    for r in cur.fetchall():
        print(r)

    print("=== (b) 样本域SQL之一:scorecard.py:456-458 原文照抄(node侧,不限trade_date,只滤prob非空)")
    cur.execute("""SELECT jc.prompt_hash, jc.direction, jc.subjective_prob, cs.verdict
            FROM card_score cs JOIN judgment_card jc USING(card_id)
            WHERE jc.subjective_prob IS NOT NULL""")
    node_rows = cur.fetchall()
    print("node侧取回行数:", len(node_rows))
    for r in node_rows:
        print(r)

    print("=== (b) 样本域SQL之二:scorecard.py:460-462 原文照抄(stock侧)")
    cur.execute("""SELECT dc.prompt_hash, dc.direction, dc.subjective_prob, ds.verdict
            FROM decision_score ds JOIN decision_card dc USING(card_id)
            WHERE dc.subjective_prob IS NOT NULL""")
    stock_rows = cur.fetchall()
    print("stock侧取回行数:", len(stock_rows))
    for r in stock_rows:
        print(r)

    print("=== (b) 系统值:取回行手工传入 calibration_block() 纯函数(scorecard.py:340,不触碰weekly)")
    print("node侧 calibration_block:", calibration_block(node_rows))
    print("stock侧 calibration_block:", calibration_block(stock_rows))

    print("=== 二、07-06到期批对账:B6 该日最新卡(DISTINCT ON 同 scorecard.py:115-118)LEFT JOIN card_score")
    cur.execute("""WITH latest AS (
            SELECT DISTINCT ON (trade_date, node_id) card_id, node_id
            FROM judgment_card WHERE trade_date='2026-07-06'
            ORDER BY trade_date, node_id, card_id DESC)
        SELECT l.card_id, l.node_id, (cs.card_id IS NOT NULL) AS scored, cs.verdict
        FROM latest l LEFT JOIN card_score cs ON cs.card_id=l.card_id
        ORDER BY l.card_id""")
    rows = cur.fetchall()
    for r in rows:
        print(r)
    print("B6 合计/scored/unresolved:", len(rows),
          sum(1 for r in rows if r[2]), sum(1 for r in rows if not r[2]))

    print("=== 二、B8 该日最新卡(DISTINCT ON 同 scorecard.py:124-127)LEFT JOIN decision_score")
    cur.execute("""WITH latest AS (
            SELECT DISTINCT ON (trade_date, code) card_id, code
            FROM decision_card WHERE trade_date='2026-07-06'
            ORDER BY trade_date, code, card_id DESC)
        SELECT l.card_id, l.code, (ds.card_id IS NOT NULL) AS scored, ds.verdict
        FROM latest l LEFT JOIN decision_score ds ON ds.card_id=l.card_id
        ORDER BY l.card_id""")
    rows = cur.fetchall()
    for r in rows:
        print(r)
    print("B8 合计/scored/unresolved:", len(rows),
          sum(1 for r in rows if r[2]), sum(1 for r in rows if not r[2]))

    print("=== 三、health黄佐证:data_flag 当日明细(monitor.py:179 flags 触发臂)")
    cur.execute("""SELECT kind, code, detail FROM data_flag
        WHERE ts_utc8::date=current_date ORDER BY kind, code""")
    for r in cur.fetchall():
        print(r)
