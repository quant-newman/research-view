"""每日报告生成(B3)。盘前/盘后两套。DeepSeek 只呈现变化+提取事实,主线判断留白。

铁律:每个事实带来源;主线 fact 中性陈述,user_judgment 留 <待填>;只用提供数据不外部补充;
标数据截止时点(UTC+8);证伪条件须具体可1-2周验证。
"""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config, db, llm

SYSTEM = """你是投研信息整理器,为一位每日做决策的A股AI科技投资者服务。
你的职责:呈现"今天发生了什么变化",不做投资判断。
铁律:
- 每个事实必须带来源(evidence 里标 [来源:xxx])。没有来源的信息一律不写。
- 主线那栏(headline.fact)只做"基于数据的中性事实陈述"(如"资金从X净流出、流入Y"),
  绝不写"所以该关注Z""看好W"这类倾向性结论——headline.user_judgment 一栏永远填 "<待填>"。
- 只用我提供的数据,不调用外部知识补充,不编造公告/数字/股票。
- 证伪条件须具体、可在1-2周内验证(不许写"除非大盘崩盘"这类几乎不可能触发的)。
输出严格JSON。"""


def _gather(date_utc8: str) -> tuple[str, str]:
    """从 DB 组装盘后输入数据块 + 数据截止时点。"""
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("""SELECT node.chain, node.node, rn.one_line, rn.sentiment, rn.src, rn.matched_codes
            FROM raw_news rn
            CROSS JOIN LATERAL unnest(rn.matched_node_ids) AS m(node_id)
            JOIN node ON node.node_id = m.node_id
            WHERE rn.relevant AND rn.is_chain_relevant AND rn.one_line IS NOT NULL
            ORDER BY node.chain LIMIT 60""")
        news = cur.fetchall()
        cur.execute("""SELECT event_type, direction, code, summary, event_date
            FROM stock_event WHERE event_date >= current_date - 7
            ORDER BY event_type, event_date DESC""")
        events = cur.fetchall()

    news_lines = [f"- [{ch}/{nd}] {ol}(情绪:{se},来源:{src},票:{','.join(codes or [])})"
                  for ch, nd, ol, se, src, codes in news]
    ev_lines = [f"- [{et}·{d}] {code} {summ}(公告日{ed})" for et, d, code, summ, ed in events]

    ts = datetime.now(ZoneInfo(config.TZ)).strftime("%Y-%m-%d %H:%M")
    block = (f"【相关产业链新闻(按链)】\n" + "\n".join(news_lines) +
             f"\n\n【个股事件(近7日,来自公告/龙虎榜)】\n" + "\n".join(ev_lines))
    return ts, block


def generate_afterhours(date_utc8: str) -> dict:
    ts, block = _gather(date_utc8)
    user = f"""【数据截止 UTC+8】{ts}
{block}

输出JSON(盘后,呈现"今天发生了什么、资金往哪切、情绪冷热"):
{{
  "data_cutoff": "{ts} UTC+8",
  "session": "afterhours",
  "headline": {{"fact":"基于上述数据的中性事实陈述,不带倾向","user_judgment":"<待填>","confidence":"高|中|低"}},
  "top3": [
    {{"change":"变化描述","evidence":"[来源:xxx]","node_ids":[],"related_stocks":[]}}
  ],
  "sectors": [{{"chain":"光通信","status":"一句状态[来源]"}}],
  "falsification": [
    {{"claim":"某个可证伪的观察","condition":"具体的1-2周内可验证的证伪条件","draft_by":"deepseek"}}
  ]
}}
只用上面提供的数据,top3 选今天最值得注意的3个变化。"""
    return llm.chat_json(SYSTEM, user, timeout=120)


def _holdings_moves(cur) -> list[dict]:
    """我的持仓/自选票今日异动(事件 + 相关新闻)。只输出标记,不涉金额。"""
    cur.execute("""
        SELECT h.code, s.name, 'holding' AS kind FROM holdings h LEFT JOIN stock s USING(code)
        UNION ALL
        SELECT w.code, s.name, 'watching' FROM watchlist w LEFT JOIN stock s USING(code)""")
    mine = cur.fetchall()
    moves = []
    for code, name, kind in mine:
        cur.execute("""SELECT event_type, direction, summary FROM stock_event
            WHERE code=%s AND event_date >= current_date - 3 ORDER BY event_date DESC""", (code,))
        evs = [{"type": et, "direction": d, "summary": s} for et, d, s in cur.fetchall()]
        cur.execute("""SELECT one_line, sentiment, src FROM raw_news
            WHERE %s = ANY(matched_codes) AND relevant AND one_line IS NOT NULL LIMIT 3""", (code,))
        news = [{"one_line": ol, "sentiment": se, "src": sr} for ol, se, sr in cur.fetchall()]
        if evs or news:
            moves.append({"code": code, "name": name, "kind": kind, "events": evs, "news": news})
    return moves


def persist_afterhours(date_utc8: str) -> str:
    """生成盘后报告 + 我的持仓动态,存 daily_report。返回 report_id。"""
    rpt = generate_afterhours(date_utc8)
    with db.rv_conn() as conn, conn.cursor() as cur:
        holdings_moves = _holdings_moves(cur)
        report_id = f"{date_utc8}:afterhours"
        cur.execute("""
            INSERT INTO daily_report(report_id,report_date,session,data_cutoff,
                headline,top3,sectors,falsification,holdings_moves)
            VALUES(%s, to_date(%s,'YYYYMMDD'),'afterhours',%s,%s,%s,%s,%s,%s)
            ON CONFLICT(report_id) DO UPDATE SET data_cutoff=EXCLUDED.data_cutoff,
                headline=EXCLUDED.headline, top3=EXCLUDED.top3, sectors=EXCLUDED.sectors,
                falsification=EXCLUDED.falsification, holdings_moves=EXCLUDED.holdings_moves,
                generated_at=now()""",
            (report_id, date_utc8, rpt.get("data_cutoff", ""),
             json.dumps(rpt.get("headline"), ensure_ascii=False),
             json.dumps(rpt.get("top3"), ensure_ascii=False),
             json.dumps(rpt.get("sectors"), ensure_ascii=False),
             json.dumps(rpt.get("falsification"), ensure_ascii=False),
             json.dumps(holdings_moves, ensure_ascii=False)))
    return report_id
