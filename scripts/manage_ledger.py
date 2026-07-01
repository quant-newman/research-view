#!/usr/bin/env python3
"""判断复盘账本审定 CLI(证伪审定 workflow 的写入侧)。

魂:统计/起草是模型的,**审定钉死是人的**。DeepSeek 只起草证伪条件(草稿态),
人审定后钉进 append-only ledger——一旦钉死不可改(DB 触发器焊死 UPDATE/DELETE)。
验证锚点 = 证伪条件是否触发;触发后记证伪归因(信息错/逻辑错/纯运气)。

前端是静态只读页、阿里云 PG 仅本地监听,故审定走本 CLI(在阿里云侧/ssh 跑),
与 manage_holdings.py 同一模式。

用法:
  # 1) 看某日报告里 DeepSeek 起草的证伪条件(带序号)
  python3 scripts/manage_ledger.py drafts 20260701
  # 2) 审定钉死第 N 条(可覆盖 claim/condition 措辞,补自己的判断与证据)
  python3 scripts/manage_ledger.py pin 20260701:afterhours 0 \
      --judgment "我认为存储涨价可持续,加仓江波龙" --condition "两周内美光现货报价不再上调则证伪"
  # 3) 看账本(存活的判断)
  python3 scripts/manage_ledger.py list
  # 4) 某条判断的证伪条件触发了 → 记归因(kind=attribution 指回原判断)
  python3 scripts/manage_ledger.py falsify 12 --error-type 信息错 --note "涨价是一次性补库"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from research_view import config  # noqa: E402

ERROR_TYPES = ["信息错", "逻辑错", "纯运气"]


def _drafts(cur, date_utc8: str) -> None:
    cur.execute(
        """SELECT report_id, session, headline->>'fact', falsification
           FROM daily_report WHERE report_date=to_date(%s,'YYYYMMDD')
           ORDER BY generated_at DESC""",
        (date_utc8,),
    )
    rows = cur.fetchall()
    if not rows:
        print(f"{date_utc8} 无报告。")
        return
    for report_id, session, fact, fals in rows:
        print(f"\n== {report_id} ({session}) ==")
        print(f"   主线: {fact}")
        fals = fals or []
        if isinstance(fals, str):
            fals = json.loads(fals)
        # 已钉死的(用于标注哪些审过)
        cur.execute("SELECT condition FROM ledger WHERE report_id=%s AND kind='judgment'", (report_id,))
        pinned = {r[0] for r in cur.fetchall()}
        for i, f in enumerate(fals):
            claim = f.get("claim", "")
            cond = f.get("condition", "")
            mark = " ✓已钉死" if cond in pinned else ""
            print(f"   [{i}]{mark} 观察: {claim}")
            print(f"        证伪: {cond}")
    print("\n审定: python3 scripts/manage_ledger.py pin <report_id> <序号> [--claim ..] [--condition ..] [--judgment ..] [--evidence ..]")


def _pin(cur, report_id: str, idx: int, a) -> None:
    cur.execute("SELECT falsification FROM daily_report WHERE report_id=%s", (report_id,))
    row = cur.fetchone()
    if not row:
        print(f"找不到报告 {report_id}")
        return
    fals = row[0] or []
    if isinstance(fals, str):
        fals = json.loads(fals)
    if idx < 0 or idx >= len(fals):
        print(f"序号越界:{report_id} 只有 {len(fals)} 条证伪草稿(0..{len(fals)-1})")
        return
    draft = fals[idx]
    # 人审定:可覆盖措辞;claim=判断内容(默认取草稿观察,--judgment 为人自己的判断优先)
    claim = a.judgment or a.claim or draft.get("claim", "")
    condition = a.condition or draft.get("condition", "")
    if not condition:
        print("证伪条件为空,拒绝钉死(没有可验证锚点的判断不进账本)。")
        return
    cur.execute(
        """INSERT INTO ledger(report_id, claim, evidence, condition, kind)
           VALUES(%s,%s,%s,%s,'judgment') RETURNING ledger_id""",
        (report_id, claim, a.evidence, condition),
    )
    lid = cur.fetchone()[0]
    print(f"✓ 已钉死 ledger#{lid}(不可改)")
    print(f"   判断: {claim}")
    print(f"   证伪: {condition}")


def _list(cur) -> None:
    cur.execute(
        """SELECT l.ledger_id, l.report_id, l.claim, l.condition, l.kind, l.error_type,
                  l.ref_ledger, l.created_at_utc8::date,
                  EXISTS(SELECT 1 FROM ledger a WHERE a.ref_ledger=l.ledger_id) AS falsified
           FROM ledger l WHERE l.kind='judgment' ORDER BY l.ledger_id DESC""")
    rows = cur.fetchall()
    if not rows:
        print("账本空。用 pin 钉死第一条判断。")
        return
    alive = sum(1 for r in rows if not r[8])
    print(f"== 判断账本(存活 {alive} / 共 {len(rows)}) ==")
    for lid, rid, claim, cond, kind, etype, ref, day, falsified in rows:
        status = f"✗已证伪({etype or '?'})" if falsified else "存活"
        print(f"  #{lid} [{status}] {day} {rid}")
        print(f"       判断: {claim}")
        print(f"       证伪: {cond}")


def _falsify(cur, ledger_id: int, a) -> None:
    if a.error_type not in ERROR_TYPES:
        print(f"--error-type 必须是 {ERROR_TYPES} 之一")
        return
    cur.execute("SELECT claim, condition FROM ledger WHERE ledger_id=%s AND kind='judgment'", (ledger_id,))
    row = cur.fetchone()
    if not row:
        print(f"找不到判断 ledger#{ledger_id}")
        return
    claim, cond = row
    # 归因也是一条 append-only 记录,指回被证伪的判断
    cur.execute(
        """INSERT INTO ledger(report_id, claim, evidence, condition, kind, error_type, ref_ledger)
           VALUES((SELECT report_id FROM ledger WHERE ledger_id=%s),
                  %s,%s,%s,'attribution',%s,%s) RETURNING ledger_id""",
        (ledger_id, f"[证伪]{claim}", a.note, cond, a.error_type, ledger_id),
    )
    aid = cur.fetchone()[0]
    print(f"✓ 已记证伪归因 ledger#{aid} → 判断#{ledger_id} 证伪,错误类型:{a.error_type}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("drafts", help="看某日报告的证伪草稿")
    d.add_argument("date", help="YYYYMMDD")
    p = sub.add_parser("pin", help="审定钉死一条判断")
    p.add_argument("report_id"); p.add_argument("idx", type=int)
    p.add_argument("--claim"); p.add_argument("--condition")
    p.add_argument("--judgment", help="人自己的判断(优先作为 claim)")
    p.add_argument("--evidence")
    sub.add_parser("list", help="看账本(存活的判断)")
    f = sub.add_parser("falsify", help="记证伪归因")
    f.add_argument("ledger_id", type=int)
    f.add_argument("--error-type", required=True, dest="error_type")
    f.add_argument("--note")
    a = ap.parse_args()

    with psycopg.connect(config.research_view_dsn()) as conn, conn.cursor() as cur:
        if a.cmd == "drafts":
            _drafts(cur, a.date)
        elif a.cmd == "pin":
            _pin(cur, a.report_id, a.idx, a)
        elif a.cmd == "list":
            _list(cur)
        elif a.cmd == "falsify":
            _falsify(cur, a.ledger_id, a)
        conn.commit()


if __name__ == "__main__":
    main()
