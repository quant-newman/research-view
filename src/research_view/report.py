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
- 研报评级/基金观点属于"机构说了什么"的客观事实,可作为变化信号呈现(注明来源),
  但绝不能把机构的看多看空当成你自己的判断或结论——你只转述"谁给了什么评级/说了什么"。
- 证伪条件须具体、可在1-2周内验证(不许写"除非大盘崩盘"这类几乎不可能触发的)。
输出严格JSON。"""


def _gather(date_utc8: str) -> tuple[str, str]:
    """从 DB 组装盘后输入数据块 + 数据截止时点。

    客观事实全量入口(修管道缺口):相关新闻(含泛科技,与 export 口径一致,LEFT JOIN
    不丢无节点新闻)+ 个股事件 + 今日新增卖方研报(评级/机构,零解读)+ 相关基金信函观点。
    """
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT node_id, chain, node FROM node")
        node_meta = {nid: f"{ch}/{nd}" for nid, ch, nd in cur.fetchall()}

        # 新闻:与 export 相关口径一致(核心链 + 泛科技),不再被 node JOIN 丢弃无节点新闻
        cur.execute("""SELECT rn.one_line, rn.sentiment, rn.src, rn.matched_codes,
                   rn.matched_node_ids, rn.tech_industries
            FROM raw_news rn
            WHERE rn.relevant AND rn.one_line IS NOT NULL
              AND (rn.is_chain_relevant IS NOT false
                   OR array_length(rn.matched_codes,1) > 0
                   OR array_length(rn.matched_tech_codes,1) > 0)
            ORDER BY rn.pub_time DESC LIMIT 80""")
        news = cur.fetchall()

        # 个股事件:时间窗以报告日为锚(补跑历史不错位)
        cur.execute("""SELECT event_type, direction, code, summary, event_date
            FROM stock_event WHERE event_date >= to_date(%s,'YYYYMMDD') - 7
            ORDER BY event_type, event_date DESC""", (date_utc8,))
        events = cur.fetchall()

        # 今日新增卖方研报(近3日,机构评级=客观事实,零解读)
        cur.execute("""SELECT report_date, name, org_name, rating, title, scope
            FROM research_report WHERE report_date >= to_date(%s,'YYYYMMDD') - 3
            ORDER BY report_date DESC NULLS LAST LIMIT 30""", (date_utc8,))
        reports = cur.fetchall()

        # 相关基金/大行信函(已分类、相关度高的近期观点;表空时自然为空)
        cur.execute("""SELECT fund_name, stance, strategy, relevance, core_views
            FROM fund_letter WHERE status <> '待分类' AND relevance IS NOT NULL
            ORDER BY relevance DESC NULLS LAST, created_at DESC LIMIT 5""")
        letters = cur.fetchall()

    def _label(node_ids, tech_inds):
        if node_ids:
            return "、".join(node_meta.get(n, n) for n in node_ids[:2])
        if tech_inds:
            return "泛科技·" + "、".join(tech_inds[:2])
        return "泛科技"

    def _views(cv):
        if not cv:
            return ""
        if isinstance(cv, list):
            return " / ".join(str(x) for x in cv[:2])
        return str(cv)[:120]

    news_lines = [f"- [{_label(nids, tinds)}] {ol}(情绪:{se},来源:{src},票:{','.join(codes or [])})"
                  for ol, se, src, codes, nids, tinds in news]
    ev_lines = [f"- [{et}·{d}] {code} {summ}(公告日{ed})" for et, d, code, summ, ed in events]
    rpt_lines = [f"- [{scope or ''}] {org} 予 {name} 「{rating}」评级:{title}(报告日{rd})"
                 for rd, name, org, rating, title, scope in reports]
    letter_lines = [f"- {fn}(立场:{st or '—'},策略:{sg or '—'},相关度{rl}):{_views(cv)}"
                    for fn, st, sg, rl, cv in letters]

    ts = datetime.now(ZoneInfo(config.TZ)).strftime("%Y-%m-%d %H:%M")
    block = "\n\n".join([
        "【相关产业链新闻(按链/行业)】\n" + ("\n".join(news_lines) or "(无)"),
        "【个股事件(近7日,来自公告/龙虎榜)】\n" + ("\n".join(ev_lines) or "(无)"),
        "【今日新增卖方研报(机构评级=客观事实,非你的判断)】\n" + ("\n".join(rpt_lines) or "(无)"),
        "【相关基金/大行观点(供背景,非你的判断)】\n" + ("\n".join(letter_lines) or "(无)"),
    ])
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
只用上面提供的数据,top3 选今天最值得注意的3个变化。
研报评级与基金观点仅作背景与佐证(可在 evidence 里注明"[来源:XX机构评级]"),不得升格为主线判断——headline.user_judgment 仍留 "<待填>"。"""
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
