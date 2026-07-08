# 一次性修复:daily_report 里"6万倍"错误换算(62204% 应为约622倍)
import sys, json
sys.path.insert(0, "src")
from research_view import db

FIXES = [
    ("江波龙净利增超6万倍", "江波龙净利预增62204%-74394%(约622-744倍)"),
    ("江波龙预告H1净利增超6万倍", "江波龙预告H1净利同比预增约622-744倍"),
    ("增超6万倍", "预增约622-744倍"),  # 兜底
]

def fix(s):
    for a, b in FIXES:
        s = s.replace(a, b)
    return s

with db.rv_conn() as conn:
    cur = conn.cursor()
    cur.execute("""SELECT report_id, headline::text, top3::text, narrative FROM daily_report
        WHERE headline::text LIKE '%%6万倍%%' OR top3::text LIKE '%%6万倍%%'
           OR narrative LIKE '%%6万倍%%'""")
    rows = cur.fetchall()
    print("hit rows:", len(rows))
    for report_id, h, t, n in rows:
        cur.execute("""UPDATE daily_report SET headline=%s::jsonb, top3=%s::jsonb, narrative=%s
                       WHERE report_id=%s""",
                    (fix(h), fix(t), fix(n) if n else n, report_id))
        print("fixed:", report_id)
    conn.commit()
    cur.execute("""SELECT count(*) FROM daily_report WHERE headline::text LIKE '%%6万倍%%'
        OR top3::text LIKE '%%6万倍%%' OR narrative LIKE '%%6万倍%%'""")
    print("remaining:", cur.fetchone()[0])
