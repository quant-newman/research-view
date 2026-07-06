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

from . import config, db, llm, market, moneyflow

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


# ---------- 跨日对照(报告的"记忆"——只用于叙事连贯与增量标注,不作事实源) ----------

def _prev_afterhours(cur, date_utc8: str) -> dict | None:
    """取今日之前最近一份盘后报告的主线+top3,供对照标注「延续/新出现/反转」。"""
    cur.execute("""SELECT report_date, headline, top3 FROM daily_report
        WHERE session='afterhours' AND report_date < to_date(%s,'YYYYMMDD')
        ORDER BY report_date DESC LIMIT 1""", (date_utc8,))
    row = cur.fetchone()
    if not row:
        return None
    rd, headline, top3 = row
    return {"date": str(rd), "fact": (headline or {}).get("fact", ""),
            "top3": [t.get("change", "") for t in (top3 or []) if isinstance(t, dict)]}


def _prev_block(prev: dict | None) -> str:
    """对照块。明示铁律:只用于对照,不得从中引用数字当事实。"""
    if not prev:
        return ""
    lines = "\n".join(f"- {t}" for t in prev["top3"]) or "(无)"
    return (f"【昨日盘后报告(仅供对照标注延续/变化,非事实源——不得从这里引用数字)】\n"
            f"({prev['date']}) 主线:{prev['fact']}\ntop3:\n{lines}")


def _ground_node_ids(cur, rpt: dict) -> dict:
    """top3.node_ids 客观兜底:从 related_stocks 关联的近3天新闻 matched_node_ids 反推,
    按命中频次取前2,映射成「链/节点」标签(与前端chips及历史streak词汇同格式)。
    LLM 填写不稳(时空时自由发挥)——这个字段本可代码算,算得出就覆盖,算不出保留原值。"""
    node_meta = _node_meta(cur)
    for item in rpt.get("top3") or []:
        codes = [c for c in (item.get("related_stocks") or [])
                 if isinstance(c, str) and len(c) == 6 and c.isdigit()]
        if not codes:
            continue
        try:
            cur.execute("""SELECT nid, count(*) FROM raw_news rn,
                    unnest(rn.matched_node_ids) nid
                WHERE rn.relevant AND rn.matched_codes && %s::text[]
                  AND rn.pub_time >= now() - interval '3 days'
                GROUP BY nid ORDER BY count(*) DESC""", (codes,))
            derived = [node_meta[nid] for nid, _ in cur.fetchall() if nid in node_meta][:2]
            if derived:
                item["node_ids"] = derived
        except Exception:  # noqa: BLE001 兜底失败不阻塞报告本体
            pass
    return rpt


def _attach_streaks(cur, date_utc8: str, rpt: dict) -> dict:
    """top3 各条按 node_ids 计算「已连续第N天进入top3」——代码算的客观数,不让LLM编。
    对照近10份盘后报告,从昨日往前数连续出现天数;今天算第 streak+1 天。"""
    try:
        cur.execute("""SELECT top3 FROM daily_report
            WHERE session='afterhours' AND report_date < to_date(%s,'YYYYMMDD')
            ORDER BY report_date DESC LIMIT 10""", (date_utc8,))
        history = [{n for t in (row[0] or []) if isinstance(t, dict) for n in (t.get("node_ids") or [])}
                   for row in cur.fetchall()]
        for item in rpt.get("top3") or []:
            nids = set(item.get("node_ids") or [])
            if not nids:
                continue
            streak = 0
            for day_nodes in history:  # 从昨日起往前连续计数
                if nids & day_nodes:
                    streak += 1
                else:
                    break
            if streak:
                item["streak_days"] = streak + 1
    except Exception:  # noqa: BLE001 对照失败不阻塞报告本体
        pass
    return rpt


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
            FROM stock_event
            WHERE event_date BETWEEN to_date(%s,'YYYYMMDD') - 7 AND to_date(%s,'YYYYMMDD')
            ORDER BY event_type, event_date DESC""", (date_utc8, date_utc8))
        events = cur.fetchall()
        reports = _fetch_reports(cur, date_utc8, days=3, limit=30)
        letters = _fetch_letters(cur)
        prev = _prev_afterhours(cur, date_utc8)
        cur.execute("""SELECT hhmm, entry FROM report_increment
            WHERE trade_date = to_date(%s,'YYYYMMDD') ORDER BY hhmm""", (date_utc8,))
        incs = cur.fetchall()

    ev_lines = [f"- [{et}·{d}] {code} {summ}(公告日{ed})" for et, d, code, summ, ed in events]
    inc_seg = ("【当日盘中增量时间线(供叙述「日内节奏」,数字仍以上方数据块为准)】\n"
               + "\n".join(f"- {h} {e}" for h, e in incs)) if incs else ""
    block = "\n\n".join(x for x in [
        _market_block(),
        "【相关产业链新闻(按链/行业)】\n" + ("\n".join(_news_lines(news, node_meta)) or "(无)"),
        "【个股事件(近7日,来自公告/龙虎榜)】\n" + ("\n".join(ev_lines) or "(无)"),
        _moneyflow_block(),
        "【今日新增卖方研报(机构评级=客观事实,非你的判断)】\n" + ("\n".join(_report_lines(reports)) or "(无)"),
        "【相关基金/大行观点(供背景,非你的判断)】\n" + ("\n".join(_letter_lines(letters)) or "(无)"),
        inc_seg,
        _prev_block(prev),
    ] if x)
    return _now_ts(), block


def _market_block() -> str:
    """大盘仪表块(结构化,narrative 第①段以此为准,不再从新闻文本转述指数)。"""
    try:
        g = market.gauge()
    except Exception:  # noqa: BLE001 行情库不可用不阻塞报告
        g = None
    if not g:
        return ""
    return ("【大盘仪表(全市场结构化数据——narrative 第①段的指数/宽度/成交额以此为准,"
            "不要再从新闻文本转述这些数字)】\n" + "\n".join(market.lines(g)))


def _moneyflow_block() -> str:
    """资金面客观事实块(主力=大单+超大单净额,亿元)。取不到不阻塞报告。
    口径标注必须带日期:盘中报告用的可能是当日盘中rt或上一交易日EOD,LLM 须照实引用。"""
    try:
        mf = moneyflow.latest()
    except Exception:  # noqa: BLE001
        mf = None
    if not mf:
        return "【资金面·主力净额】\n(无)"
    label = f"{mf['date']} 收盘EOD" if mf["kind"] == "eod" else f"{mf['date']} 盘中截至{mf['stamp']}"
    block = (f"【资金面·主力净额(大单+超大单,亿元;口径:{label})】\n"
             + "\n".join(moneyflow.lines(mf)))
    # 多日维度:资金持续性(连续N日)+ 资金×涨幅背离(客观标注,LLM 只转述不判断)
    try:
        md_ = moneyflow.multi_day()
    except Exception:  # noqa: BLE001
        md_ = None
    if md_:
        picked = sorted(md_["nodes"], key=lambda x: -abs(x["d5"]))[:6]
        ml = [f"- {g['chain']}/{g['node']} 5日{g['d5']:+.1f}亿/20日{g['d20']:+.1f}亿"
              + (f",连续{abs(g['streak'])}日净{'流入' if g['streak'] > 0 else '流出'}"
                 if abs(g["streak"]) >= 3 else "")
              for g in picked]
        ml += [f"- 资金价格背离:{g['chain']}/{g['node']} 近一周涨跌{g['ret_1w']:+.1f}%"
               f"而主力5日{g['d5']:+.1f}亿(方向相反,仅客观标注)"
               for g in md_["nodes"] if g["divergence"]][:4]
        mk = md_.get("market") or {}
        block += (f"\n\n【多日资金(截至{md_['asof']},EOD口径)】\n"
                  f"(基准:全市场5日主力净额{mk.get('d5', 0):+.0f}亿——主力口径结构性偏净流出,"
                  f"节点数字应读相对强弱与方向变化,不是绝对买卖量)\n" + "\n".join(ml))
    return block


def generate_afterhours(date_utc8: str) -> dict:
    ts, block = _gather(date_utc8)
    user = f"""【数据截止 UTC+8】{ts}
{block}

输出JSON(盘后,呈现"今天发生了什么、资金往哪切、情绪冷热"):
{{
  "data_cutoff": "{ts} UTC+8",
  "session": "afterhours",
  "headline": {{"fact":"基于上述数据的中性事实陈述,不带倾向","user_judgment":"<待填>","confidence":"高|中|低"}},
  "narrative": "约500字今日综述,分3-4个自然段(段间用\\n\\n分隔):①今日大盘温度(涨跌家数/涨停/情绪冷热)与主线;②资金与板块轮动+当日节奏(若有盘中增量时间线,概括资金/消息面在日内怎么推进,如'上午聚焦X、午后转向Y');③重要个股事件与新闻(公告/业绩/增减持/解禁,点名带来源);④研报与基金观点佐证。只陈述事实不下投资判断,不编造数字。",
  "top3": [
    {{"change":"变化描述","evidence":"[来源:xxx]","node_ids":[],"related_stocks":[],"delta":"延续|新出现|反转"}}
  ],
  "sectors": [{{"chain":"光通信","status":"一句状态[来源]"}}],
  "falsification": [
    {{"claim":"某个可证伪的观察","condition":"具体的1-2周内可验证的证伪条件","draft_by":"deepseek"}}
  ]
}}
只用上面提供的数据。narrative 约500字(控制在480-620字,充实但别啰嗦);top3 选今天最值得注意的3个变化。
top3.node_ids 只能从上方新闻行首方括号里的节点标签(如「半导体/存储」)原样摘取,最多2个;对不上就留空数组,不要自造名称。
top3.delta 对照【昨日盘后报告】标注:昨日已提及同一主题="延续";昨日未提="新出现";与昨日方向相反(如昨日资金流入今日转流出)="反转"。无昨日报告时全部标"新出现"。昨日报告只用于对照,事实与数字必须来自上方数据块。主线若与昨日相同,措辞保持连贯,不要为了显得新而改口。
研报评级与基金观点仅作背景与佐证(可在 evidence 里注明"[来源:XX机构评级]"),不得升格为主线判断——headline.user_judgment 仍留 "<待填>"。"""
    return llm.chat_json(SYSTEM, user, timeout=300)


# ---------- 盘中增量条目(演进式:替代原"每15min重烧完整盘中报告") ----------
# 设计:事实层每次从客观数据重算 delta(防链式误差累积);叙事层只写"较上一时点
# 变了什么",基线报告仅作对照避免重复。无实质增量不产生条目也不烧 LLM。

def _delta_news(cur, since, node_meta) -> list[str]:
    cur.execute(f"""SELECT COALESCE(rn.summary, rn.one_line), rn.sentiment, rn.src, rn.matched_codes,
               rn.matched_node_ids, rn.tech_industries
        FROM raw_news rn WHERE {_NEWS_WHERE} AND rn.pub_time > %s
        ORDER BY rn.pub_time DESC LIMIT 40""", (since,))
    return _news_lines(cur.fetchall(), node_meta)


def _delta_mf(cur) -> list[str]:
    """资金位移:mf_intraday_node 最新时点 vs 上一时点,|Δ|≥2亿的节点(亿元)。"""
    cur.execute("""WITH ts AS (
            SELECT DISTINCT hhmm FROM mf_intraday_node
            WHERE trade_date=current_date AND node_id<>'POOL' ORDER BY hhmm DESC LIMIT 2)
        SELECT n.chain, n.node, m.hhmm, m.main FROM mf_intraday_node m
        JOIN node n ON n.node_id=m.node_id
        WHERE m.trade_date=current_date AND m.hhmm IN (SELECT hhmm FROM ts)""")
    rows = cur.fetchall()
    stamps = sorted({r[2] for r in rows})
    if len(stamps) < 2:
        return []
    prev_t, last_t = stamps[0], stamps[1]
    prev = {(c, nd): float(m) for c, nd, h, m in rows if h == prev_t}
    last = {(c, nd): float(m) for c, nd, h, m in rows if h == last_t}
    shifts = sorted(((k, last[k] - prev[k]) for k in last if k in prev),
                    key=lambda kv: -abs(kv[1]))
    return [f"- {c}/{nd} {prev_t}→{last_t} 主力{d / 1e8:+.1f}亿"
            for (c, nd), d in shifts if abs(d) >= 2e8][:6]


def generate_increment(date_utc8: str) -> dict | None:
    """生成一条盘中增量。无实质增量返回 None(不烧 LLM)。"""
    now_hhmm = datetime.now(ZoneInfo(config.TZ)).strftime("%H:%M")
    with db.rv_conn() as conn, conn.cursor() as cur:
        node_meta = _node_meta(cur)
        # 上一检查点:今日最近一条增量;没有则今日 08:30(盘前报告时点)
        cur.execute("""SELECT max(created_at) FROM report_increment
            WHERE trade_date = to_date(%s,'YYYYMMDD')""", (date_utc8,))
        since = cur.fetchone()[0]
        if since is None:
            since = f"{date_utc8[:4]}-{date_utc8[4:6]}-{date_utc8[6:]} 08:30:00+08"
        news_lines = _delta_news(cur, since, node_meta)
        mf_lines = _delta_mf(cur)
        # 基线报告:今日最新一份(盘前/盘后),对照避免重复
        cur.execute("""SELECT session, headline, top3 FROM daily_report
            WHERE report_date = to_date(%s,'YYYYMMDD')
            ORDER BY generated_at DESC LIMIT 1""", (date_utc8,))
        base = cur.fetchone()
    # 实质性门槛:新增相关新闻≥3条 或 有≥2亿的资金位移,否则不值得出条目
    if len(news_lines) < 3 and not mf_lines:
        return None
    base_seg = ""
    if base:
        sess, headline, top3 = base
        t3 = "\n".join(f"- {t.get('change', '')}" for t in (top3 or []) if isinstance(t, dict))
        base_seg = (f"【今日基线报告({sess},仅供对照避免重复——非事实源,不得引用其中数字)】\n"
                    f"主线:{(headline or {}).get('fact', '')}\n{t3}\n\n")
    user = f"""【时点】{_now_ts()} UTC+8(盘中增量检查)
{base_seg}【上一检查点】{since}(以下均为此后的新增事实)

【新增相关新闻({len(news_lines)}条)】
{chr(10).join(news_lines) or "(无)"}

【资金位移(较上一时点,主力净额变化,亿元)】
{chr(10).join(mf_lines) or "(无)"}

你在为"当日报告的盘中增量时间线"写一条新条目。输出JSON:
{{"material": true, "entry": "50-150字:只写较上一时点的变化(谁在加速/谁在转向/出了什么新消息),带来源,不重复基线报告已说过的内容", "tags": ["涉及的链条或个股名"]}}
若上述新增事实零散、不构成有意义的变化,输出 {{"material": false}}。
铁律:entry 里的每个事实/数字只能来自上方两个"新增"块;不预测走势;不给建议;不重复旧闻。"""
    j = llm.chat_json(SYSTEM, user, timeout=120)
    if not isinstance(j, dict) or not j.get("material") or not (j.get("entry") or "").strip():
        return None
    return {"hhmm": now_hhmm, "entry": j["entry"].strip(), "tags": j.get("tags") or [],
            "n_news": len(news_lines), "mf_shift": "; ".join(mf_lines)[:300] or None}


def persist_increment(date_utc8: str) -> dict:
    """盘中增量检查:有实质变化则追加一条时间线条目(run_light 每15min调)。"""
    inc = generate_increment(date_utc8)
    if not inc:
        return {"skip": "无实质增量"}
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("""INSERT INTO report_increment(trade_date,hhmm,entry,tags,n_news,mf_shift)
            VALUES(to_date(%s,'YYYYMMDD'),%s,%s,%s,%s,%s)
            ON CONFLICT(trade_date,hhmm) DO UPDATE SET entry=EXCLUDED.entry,
                tags=EXCLUDED.tags, n_news=EXCLUDED.n_news, mf_shift=EXCLUDED.mf_shift""",
            (date_utc8, inc["hhmm"], inc["entry"],
             json.dumps(inc["tags"], ensure_ascii=False), inc["n_news"], inc["mf_shift"]))
    return {"hhmm": inc["hhmm"], "n_news": inc["n_news"]}


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
        prev = _prev_afterhours(cur, date_utc8)

    if us and us.get("items"):
        us_lines = [f"- {it['name']}({it['ticker']}) 收{it.get('close')} {it['pct']:+.2f}%  →A股映射:{it['mapping']}"
                    for it in us["items"] if it.get("pct") is not None]
        us_seg = f"【隔夜美股科技链(美东 {us.get('us_session_date')} 收盘)】\n" + ("\n".join(us_lines) or "(无)")
    else:
        us_seg = "【隔夜美股科技链】\n(未取到隔夜美股数据,盘前降级)"

    up_lines = [f"- [{et}·{d}] {code} {summ}(事件日{ed})" for et, d, code, summ, ed in upcoming]
    block = "\n\n".join(x for x in [
        us_seg,
        _market_block(),  # 上一交易日大盘收盘状态(带 trade_date 口径,LLM 须标"昨日收盘")
        "【隔夜至今国内增量新闻(按链/行业)】\n" + ("\n".join(_news_lines(news, node_meta)) or "(无)"),
        "【今日新增卖方研报(机构评级=客观事实,非你的判断)】\n" + ("\n".join(_report_lines(reports)) or "(无)"),
        "【未来7日临近事件(解禁/预约披露等)】\n" + ("\n".join(up_lines) or "(无)"),
        _prev_block(prev),
    ] if x)
    return _now_ts(), block, us


def generate_premarket(date_utc8: str) -> dict:
    ts, block, _us = _gather_premarket(date_utc8)
    user = f"""【数据截止 UTC+8】{ts}(盘前)
{block}

输出JSON(盘前,呈现"隔夜外盘科技链怎么走、国内有什么新增量、开盘前哪些链条信息增量最大"):
{{
  "data_cutoff": "{ts} UTC+8",
  "session": "premarket",
  "headline": {{"fact":"基于隔夜美股+国内增量的中性事实陈述(如'费半跌X%、存储MU跌Y%;国内MLCC酝酿涨价'),不预测A股今天涨跌","user_judgment":"<待填>","confidence":"高|中|低"}},
  "narrative": "约500字盘前综述,分3-4个自然段(段间用\\n\\n分隔):①隔夜外盘科技链怎么走(费半/关键个股涨跌%);②对应A股链条的外盘参照(中性映射,不预测A股涨跌);③国内隔夜新增量(新闻/公告/研报/基金观点);④隔夜信息增量最集中的链条/方向(按事实归纳哪里变化最大,不构成盯盘建议)。只陈述客观事实与外盘参照,绝不预测A股今日走势,不编造数字。",
  "top3": [
    {{"change":"隔夜信息增量最大的一个客观变化","evidence":"[来源:xxx]","node_ids":[],"related_stocks":[],"delta":"延续|新出现|反转"}}
  ],
  "sectors": [{{"chain":"半导体","status":"该链隔夜外盘映射一句[来源]"}}],
  "falsification": [
    {{"claim":"某个可证伪的观察","condition":"具体的1-2周内可验证的证伪条件","draft_by":"deepseek"}}
  ]
}}
隔夜美股是客观涨跌%,可据此中性陈述对应A股链条的外盘参照,但绝不预测A股今天怎么走(那是判断,user_judgment 留白)。narrative 约500字(480-620字)。
top3 选隔夜信息增量最大的3点(以变化幅度/信息密度为准,不是操作建议)。top3.delta 对照【昨日盘后报告】标注(延续=昨日已提/新出现=昨日未提/反转=方向相反);昨日报告只作对照,事实必须来自上方数据块。研报/基金观点仅作佐证,注明来源,不升格为主线判断。
top3.node_ids 只能从上方新闻行首方括号里的节点标签(如「半导体/存储」)原样摘取,最多2个;对不上就留空数组,不要自造名称。"""
    return llm.chat_json(SYSTEM, user, timeout=300)


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
        if session in ("afterhours", "premarket"):
            rpt = _ground_node_ids(cur, rpt)  # node_ids=代码从关联新闻反推,不靠LLM自觉
            rpt = _attach_streaks(cur, date_utc8, rpt)  # 连续第N天=代码算,不让LLM编
        holdings_moves = _holdings_moves(cur)
        report_id = f"{date_utc8}:{session}"
        cur.execute("""
            INSERT INTO daily_report(report_id,report_date,session,data_cutoff,
                headline,narrative,top3,sectors,falsification,holdings_moves)
            VALUES(%s, to_date(%s,'YYYYMMDD'),%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(report_id) DO UPDATE SET data_cutoff=EXCLUDED.data_cutoff,
                headline=EXCLUDED.headline, narrative=EXCLUDED.narrative, top3=EXCLUDED.top3,
                sectors=EXCLUDED.sectors, falsification=EXCLUDED.falsification,
                holdings_moves=EXCLUDED.holdings_moves, generated_at=now()""",
            (report_id, date_utc8, session, rpt.get("data_cutoff", ""),
             json.dumps(rpt.get("headline"), ensure_ascii=False),
             rpt.get("narrative"),
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
