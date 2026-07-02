"""每日报告生成(B3)。盘前/盘后两套。DeepSeek 只呈现变化+提取事实,主线判断留白。

铁律:每个事实带来源;主线 fact 中性陈述,user_judgment 留 <待填>;只用提供数据不外部补充;
标数据截止时点(UTC+8);证伪条件须具体可1-2周验证。

盘前(premarket)独有:隔夜美股科技链(台北侧 yfinance 产出 exports/us_overnight_*.json)
+ 隔夜至今国内增量新闻/研报。盘前 yfinance 只能台北跑,阿里云连不了 Yahoo。
"""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config, db, llm

SYSTEM = """你是投研信息整理器,为一位每日做决策的A股AI科技投资者服务。
你的职责:呈现"发生了什么变化",不做投资判断。
铁律:
- 每个事实必须带来源(evidence 里标 [来源:xxx])。没有来源的信息一律不写。
- 主线那栏(headline.fact)只做"基于数据的中性事实陈述"(如"资金从X净流出、流入Y"),
  绝不写"所以该关注Z""看好W"这类倾向性结论——headline.user_judgment 一栏永远填 "<待填>"。
- 只用我提供的数据,不调用外部知识补充,不编造公告/数字/股票。
- 研报评级/基金观点属于"机构说了什么"的客观事实,可作为变化信号呈现(注明来源),
  但绝不能把机构的看多看空当成你自己的判断或结论——你只转述"谁给了什么评级/说了什么"。
- 证伪条件须具体、可在1-2周内验证(不许写"除非大盘崩盘"这类几乎不可能触发的)。
输出严格JSON。"""


# ---------- 共享格式化助手(盘前/盘后共用) ----------

def _node_meta(cur) -> dict:
    cur.execute("SELECT node_id, chain, node FROM node")
    return {nid: f"{ch}/{nd}" for nid, ch, nd in cur.fetchall()}


def _label(node_meta: dict, node_ids, tech_inds) -> str:
    if node_ids:
        return "、".join(node_meta.get(n, n) for n in node_ids[:2])
    if tech_inds:
        return "泛科技·" + "、".join(tech_inds[:2])
    return "泛科技"


def _views(cv) -> str:
    if not cv:
        return ""
    if isinstance(cv, list):
        return " / ".join(str(x) for x in cv[:2])
    return str(cv)[:120]


# 与 export 一致的相关口径:核心链 + 池内票 + 泛科技,LEFT 不丢无节点新闻
_NEWS_WHERE = """rn.relevant AND rn.one_line IS NOT NULL
    AND (rn.is_chain_relevant IS NOT false
         OR array_length(rn.matched_codes,1) > 0
         OR array_length(rn.matched_tech_codes,1) > 0)"""


def _fetch_news(cur, limit: int):
    cur.execute(f"""SELECT COALESCE(rn.summary, rn.one_line), rn.sentiment, rn.src, rn.matched_codes,
               rn.matched_node_ids, rn.tech_industries
        FROM raw_news rn WHERE {_NEWS_WHERE}
        ORDER BY rn.pub_time DESC LIMIT {int(limit)}""")
    return cur.fetchall()


def _news_lines(rows, node_meta) -> list[str]:
    return [f"- [{_label(node_meta, nids, tinds)}] {ol}(情绪:{se},来源:{src},票:{','.join(codes or [])})"
            for ol, se, src, codes, nids, tinds in rows]


def _fetch_reports(cur, date_utc8: str, days: int, limit: int):
    cur.execute(f"""SELECT report_date, name, org_name, rating, title, scope
        FROM research_report WHERE report_date >= to_date(%s,'YYYYMMDD') - {int(days)}
        ORDER BY report_date DESC NULLS LAST LIMIT {int(limit)}""", (date_utc8,))
    return cur.fetchall()


def _report_lines(rows) -> list[str]:
    return [f"- [{scope or ''}] {org} 予 {name} 「{rating}」评级:{title}(报告日{rd})"
            for rd, name, org, rating, title, scope in rows]


def _fetch_letters(cur, limit: int = 5):
    cur.execute("""SELECT fund_name, stance, strategy, relevance, core_views
        FROM fund_letter WHERE status <> '待分类' AND relevance IS NOT NULL
        ORDER BY relevance DESC NULLS LAST, created_at DESC LIMIT %s""", (limit,))
    return cur.fetchall()


def _letter_lines(rows) -> list[str]:
    return [f"- {fn}(立场:{st or '—'},策略:{sg or '—'},相关度{rl}):{_views(cv)}"
            for fn, st, sg, rl, cv in rows]


def _now_ts() -> str:
    return datetime.now(ZoneInfo(config.TZ)).strftime("%Y-%m-%d %H:%M")


# ---------- 盘后(afterhours) ----------

def _gather(date_utc8: str) -> tuple[str, str]:
    """从 DB 组装盘后输入数据块 + 数据截止时点。

    客观事实全量入口:相关新闻(含泛科技,与 export 口径一致)+ 个股事件
    + 今日新增卖方研报(评级/机构,零解读)+ 相关基金信函观点。
    """
    with db.rv_conn() as conn, conn.cursor() as cur:
        node_meta = _node_meta(cur)
        news = _fetch_news(cur, 80)
        cur.execute("""SELECT event_type, direction, code, summary, event_date
            FROM stock_event WHERE event_date >= to_date(%s,'YYYYMMDD') - 7
            ORDER BY event_type, event_date DESC""", (date_utc8,))
        events = cur.fetchall()
        reports = _fetch_reports(cur, date_utc8, days=3, limit=30)
        letters = _fetch_letters(cur)

    ev_lines = [f"- [{et}·{d}] {code} {summ}(公告日{ed})" for et, d, code, summ, ed in events]
    block = "\n\n".join([
        "【相关产业链新闻(按链/行业)】\n" + ("\n".join(_news_lines(news, node_meta)) or "(无)"),
        "【个股事件(近7日,来自公告/龙虎榜)】\n" + ("\n".join(ev_lines) or "(无)"),
        "【今日新增卖方研报(机构评级=客观事实,非你的判断)】\n" + ("\n".join(_report_lines(reports)) or "(无)"),
        "【相关基金/大行观点(供背景,非你的判断)】\n" + ("\n".join(_letter_lines(letters)) or "(无)"),
    ])
    return _now_ts(), block


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


# ---------- 盘中(intraday) ----------

def generate_intraday(date_utc8: str) -> dict:
    """盘中报告:复用盘后的全量客观事实层(_gather),但视角是"今日截至此刻在发生什么"。
    A股行情盘中不更新(EOD),所以变化主要来自陆续发布的新闻/研报——这正是盘中值得盯的。"""
    ts, block = _gather(date_utc8)
    user = f"""【数据截止 UTC+8】{ts}(盘中)
{block}

输出JSON(盘中,呈现"今天截至此刻发生了什么、消息面/研报在往哪走、盘中在炒什么"):
{{
  "data_cutoff": "{ts} UTC+8",
  "session": "intraday",
  "headline": {{"fact":"基于截至此刻数据的中性事实陈述,不预测收盘涨跌","user_judgment":"<待填>","confidence":"高|中|低"}},
  "top3": [
    {{"change":"截至此刻最值得注意的一个变化","evidence":"[来源:xxx]","node_ids":[],"related_stocks":[]}}
  ],
  "sectors": [{{"chain":"光通信","status":"一句状态[来源]"}}],
  "falsification": [
    {{"claim":"某个可证伪的观察","condition":"具体的1-2周内可验证的证伪条件","draft_by":"deepseek"}}
  ]
}}
只用上面提供的数据(龙虎榜/资金流盘中尚未落地,若相关块为空属正常,不要脑补)。
top3 选截至此刻最值得注意的3个变化。研报/基金观点仅作佐证并注明来源,不升格为主线判断——headline.user_judgment 仍留 "<待填>"。"""
    return llm.chat_json(SYSTEM, user, timeout=120)


# ---------- 盘前(premarket) ----------

def _load_us_overnight(date_utc8: str) -> dict | None:
    """读台北侧产出的隔夜美股文件(scp 到阿里云 exports/)。缺失返回 None(不阻塞)。"""
    p = config.ROOT / "exports" / f"us_overnight_{date_utc8}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 文件损坏不阻塞盘前(降级为无美股)
        return None


def _gather_premarket(date_utc8: str) -> tuple[str, str, dict | None]:
    """盘前输入:隔夜美股科技链 + 隔夜至今国内增量新闻/研报 + 未来7日临近事件(解禁等)。"""
    us = _load_us_overnight(date_utc8)
    with db.rv_conn() as conn, conn.cursor() as cur:
        node_meta = _node_meta(cur)
        news = _fetch_news(cur, 40)  # 盘前只要最新增量
        reports = _fetch_reports(cur, date_utc8, days=2, limit=20)
        # 未来临近事件(今天起 7 日内,解禁/披露预约等)
        cur.execute("""SELECT event_type, direction, code, summary, event_date
            FROM stock_event
            WHERE event_date BETWEEN to_date(%s,'YYYYMMDD') AND to_date(%s,'YYYYMMDD') + 7
            ORDER BY event_date""", (date_utc8, date_utc8))
        upcoming = cur.fetchall()

    if us and us.get("items"):
        us_lines = [f"- {it['name']}({it['ticker']}) 收{it.get('close')} {it['pct']:+.2f}%  →A股映射:{it['mapping']}"
                    for it in us["items"] if it.get("pct") is not None]
        us_seg = f"【隔夜美股科技链(美东 {us.get('us_session_date')} 收盘)】\n" + ("\n".join(us_lines) or "(无)")
    else:
        us_seg = "【隔夜美股科技链】\n(未取到隔夜美股数据,盘前降级)"

    up_lines = [f"- [{et}·{d}] {code} {summ}(事件日{ed})" for et, d, code, summ, ed in upcoming]
    block = "\n\n".join([
        us_seg,
        "【隔夜至今国内增量新闻(按链/行业)】\n" + ("\n".join(_news_lines(news, node_meta)) or "(无)"),
        "【今日新增卖方研报(机构评级=客观事实,非你的判断)】\n" + ("\n".join(_report_lines(reports)) or "(无)"),
        "【未来7日临近事件(解禁/预约披露等)】\n" + ("\n".join(up_lines) or "(无)"),
    ])
    return _now_ts(), block, us


def generate_premarket(date_utc8: str) -> dict:
    ts, block, _us = _gather_premarket(date_utc8)
    user = f"""【数据截止 UTC+8】{ts}(盘前)
{block}

输出JSON(盘前,呈现"隔夜外盘科技链怎么走、国内有什么新增量、今天开盘该盯什么"):
{{
  "data_cutoff": "{ts} UTC+8",
  "session": "premarket",
  "headline": {{"fact":"基于隔夜美股+国内增量的中性事实陈述(如'费半跌X%、存储MU跌Y%;国内MLCC酝酿涨价'),不预测A股今天涨跌","user_judgment":"<待填>","confidence":"高|中|低"}},
  "top3": [
    {{"change":"今天开盘最值得盯的一个点(源自隔夜变化)","evidence":"[来源:xxx]","node_ids":[],"related_stocks":[]}}
  ],
  "sectors": [{{"chain":"半导体","status":"该链隔夜外盘映射一句[来源]"}}],
  "falsification": [
    {{"claim":"某个可证伪的观察","condition":"具体的1-2周内可验证的证伪条件","draft_by":"deepseek"}}
  ]
}}
隔夜美股是客观涨跌%,可据此中性陈述对应A股链条的外盘参照,但绝不预测A股今天怎么走(那是判断,user_judgment 留白)。
top3 选隔夜最值得开盘关注的3点。研报/基金观点仅作佐证,注明来源,不升格为主线判断。"""
    return llm.chat_json(SYSTEM, user, timeout=120)


# ---------- 我的持仓动态 + 落库 ----------

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


def _persist(date_utc8: str, session: str, rpt: dict) -> str:
    """把报告 + 我的持仓动态存 daily_report(同日同段覆盖)。返回 report_id。"""
    with db.rv_conn() as conn, conn.cursor() as cur:
        holdings_moves = _holdings_moves(cur)
        report_id = f"{date_utc8}:{session}"
        cur.execute("""
            INSERT INTO daily_report(report_id,report_date,session,data_cutoff,
                headline,top3,sectors,falsification,holdings_moves)
            VALUES(%s, to_date(%s,'YYYYMMDD'),%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(report_id) DO UPDATE SET data_cutoff=EXCLUDED.data_cutoff,
                headline=EXCLUDED.headline, top3=EXCLUDED.top3, sectors=EXCLUDED.sectors,
                falsification=EXCLUDED.falsification, holdings_moves=EXCLUDED.holdings_moves,
                generated_at=now()""",
            (report_id, date_utc8, session, rpt.get("data_cutoff", ""),
             json.dumps(rpt.get("headline"), ensure_ascii=False),
             json.dumps(rpt.get("top3"), ensure_ascii=False),
             json.dumps(rpt.get("sectors"), ensure_ascii=False),
             json.dumps(rpt.get("falsification"), ensure_ascii=False),
             json.dumps(holdings_moves, ensure_ascii=False)))
    return report_id


def persist_afterhours(date_utc8: str) -> str:
    """生成盘后报告 + 我的持仓动态,存 daily_report。返回 report_id。"""
    return _persist(date_utc8, "afterhours", generate_afterhours(date_utc8))


def persist_premarket(date_utc8: str) -> str:
    """生成盘前报告(隔夜外盘映射)+ 我的持仓动态,存 daily_report。返回 report_id。"""
    return _persist(date_utc8, "premarket", generate_premarket(date_utc8))


def persist_intraday(date_utc8: str) -> str:
    """生成盘中报告(截至此刻的消息面/研报变化)+ 我的持仓动态,存 daily_report。返回 report_id。"""
    return _persist(date_utc8, "intraday", generate_intraday(date_utc8))
