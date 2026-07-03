"""今日热点/主题热度榜。

统计信号(新闻量/龙虎榜/节点涨跌/情绪)算热度 → 选 Top 候选 → DeepSeek 综合
"今天在炒什么主题、升温还是降温"。铁律:热度是统计的,归因叙述是提炼的,
只呈现事实、不下投资判断、不出买卖建议。
"""
from __future__ import annotations

import json

from . import db, llm

SYSTEM = (
    "你是投研信息整理器,不是分析师。基于给定的统计信号和新闻,综合'今天市场在炒什么主题',"
    "只陈述事实、不下判断、不出买卖建议。输出严格 JSON。"
)


def _signals(date_utc8: str, top: int = 10) -> list[dict]:
    """每节点热度信号,按热度排序取 Top。"""
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT node_id, chain, node FROM node")
        meta = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
        # 今日/昨日每节点相关新闻数 + 情绪
        cur.execute("""
            SELECT m.node_id,
              count(*) FILTER (WHERE rn.pub_time::date = to_date(%s,'YYYYMMDD')) AS today,
              count(*) FILTER (WHERE rn.pub_time::date = to_date(%s,'YYYYMMDD')-1) AS prior,
              count(*) FILTER (WHERE rn.sentiment='利好') AS pos,
              count(*) FILTER (WHERE rn.sentiment='利空') AS neg,
              max(rn.pub_time) FILTER (WHERE rn.pub_time::date = to_date(%s,'YYYYMMDD')) AS latest
            FROM raw_news rn CROSS JOIN LATERAL unnest(rn.matched_node_ids) m(node_id)
            WHERE rn.relevant AND rn.pub_time::date >= to_date(%s,'YYYYMMDD')-1
            GROUP BY m.node_id""", (date_utc8, date_utc8, date_utc8, date_utc8))
        news = {r[0]: {"today": r[1], "prior": r[2], "pos": r[3], "neg": r[4],
                       "latest": str(r[5]) if r[5] else ""} for r in cur.fetchall()}
        cur.execute("SELECT node_id, ret_1d, n_stocks FROM heatmap_node")
        hm = {r[0]: (float(r[1]) if r[1] is not None else None, r[2]) for r in cur.fetchall()}
        # 节点代表新闻(今日,summary 优先)
        cur.execute("""SELECT m.node_id, COALESCE(rn.summary, rn.one_line), rn.sentiment
            FROM raw_news rn CROSS JOIN LATERAL unnest(rn.matched_node_ids) m(node_id)
            WHERE rn.relevant AND rn.pub_time::date=to_date(%s,'YYYYMMDD')
              AND COALESCE(rn.summary, rn.one_line) IS NOT NULL
            ORDER BY rn.pub_time DESC""", (date_utc8,))
        node_news: dict[str, list[str]] = {}
        for nid, txt, se in cur.fetchall():
            node_news.setdefault(nid, []).append(f"[{se or '中性'}]{txt}")
        # 个股→节点 + 代表票名
        cur.execute("SELECT code, array_agg(node_id) FROM stock_node GROUP BY code")
        code_nodes = dict(cur.fetchall())
        cur.execute("SELECT ts_code, code, name FROM stock WHERE ts_code IS NOT NULL")
        pool = cur.fetchall()
    ts2code = {t: c for t, c, _ in pool}
    code2name = {c: n for _, c, n in pool}
    node_stocks: dict[str, list[str]] = {}
    for _t, c, n in pool:
        for nid in code_nodes.get(c, []):
            node_stocks.setdefault(nid, []).append(n)

    # 龙虎榜(marketdata 最新交易日)→ 每节点上榜票数
    with db.marketdata_conn() as mc, mc.cursor() as c:
        c.execute("SELECT max(trade_date) FROM md.top_list")
        ltd = c.fetchone()[0]
        c.execute("SELECT DISTINCT ts_code FROM md.top_list WHERE trade_date=%s", (ltd,))
        lhb_ts = {r[0] for r in c.fetchall()}
    lhb_node: dict[str, int] = {}
    for ts in lhb_ts:
        for nid in code_nodes.get(ts2code.get(ts), []):
            lhb_node[nid] = lhb_node.get(nid, 0) + 1

    # 资金面:每节点主力净额(亿;EOD/盘中由 moneyflow.latest 自动选口径,失败不阻塞热点)
    mf_node: dict[str, float] = {}
    try:
        from . import moneyflow
        mf = moneyflow.latest()
        if mf:
            mf_node = {g["node_id"]: g["main"] for g in mf["nodes"]}
    except Exception:  # noqa: BLE001
        pass

    rows = []
    for nid, (chain, node) in meta.items():
        nw = news.get(nid, {"today": 0, "prior": 0, "pos": 0, "neg": 0, "latest": ""})
        r1d, _n = hm.get(nid, (None, 0))
        lhb = lhb_node.get(nid, 0)
        heat = nw["today"] * 1.0 + lhb * 1.5 + max(0.0, (r1d or 0.0)) * 0.2
        if heat <= 0:
            continue
        trend = "升温" if nw["today"] > nw["prior"] else "降温" if nw["today"] < nw["prior"] else "持平"
        rows.append({
            "node_id": nid, "chain": chain, "node": node, "heat": round(heat, 1), "trend": trend,
            "news_today": nw["today"], "news_prior": nw["prior"], "pos": nw["pos"], "neg": nw["neg"],
            "ret_1d": r1d, "lhb": lhb, "mf": mf_node.get(nid), "latest_time": nw.get("latest", ""),
            "stocks": node_stocks.get(nid, [])[:5],
            "news": node_news.get(nid, [])[:3],
        })
    rows.sort(key=lambda x: -x["heat"])
    return rows[:top]


def generate(date_utc8: str) -> dict:
    rows = _signals(date_utc8)
    if not rows:
        return {"headline": "今日无显著主题热度信号。", "items": []}
    blocks = []
    for i, r in enumerate(rows):
        nl = "；".join(r["news"]) if r["news"] else "(无当日新闻)"
        blocks.append(
            f"{i}. 【{r['chain']}/{r['node']}】热度{r['heat']} | 今日新闻{r['news_today']}条(昨日{r['news_prior']})"
            f" 利好{r['pos']}/利空{r['neg']} | 节点今日涨跌{r['ret_1d']}% | 龙虎榜上榜{r['lhb']}只"
            + (f" | 主力净额{r['mf']:+.1f}亿" if r.get("mf") is not None else "")
            + f" | 代表票:{'、'.join(r['stocks'][:4])} | 新闻:{nl}")
    user = f"""下面是今日各主题的统计热度信号(已按热度排序,新闻已标[利好]/[利空]/[中性])。请综合成"今日热点榜",JSON:
{{
  "headline": "一句话总览今天市场在炒哪些主题(中性事实,如'资金聚焦存储涨价与MLCC,机器人新品密集'),≤50字",
  "pos": ["今日利好面要点,只汇总输入中标[利好]的新闻事实,每条带主题/个股/具体数字,≤40字", "共2-5条,信息不足可少给"],
  "neg": ["今日利空面要点,只汇总输入中标[利空]的新闻事实,格式同上", "共2-5条"],
  "items": [
    {{"node_id":"照抄输入的链/节点对应项","reason":"该主题为什么热的中性归因,必须基于给的信号/新闻(如'今日X条新闻+Y只上榜龙虎榜,存储现货涨价'),≤50字","trend":"升温|降温|持平"}}
  ]
}}
规则:items 顺序与条数尽量对应输入(可略去信号极弱的);reason/pos/neg 只陈述事实,禁止"看好/建议买入/值得关注"等判断词;pos/neg 不得引用输入之外的信息,无对应新闻则给空数组;trend 用输入里"今日vs昨日新闻数"参考。
【信号】
{chr(10).join(blocks)}"""
    try:
        j = llm.chat_json(SYSTEM, user, timeout=240)
    except Exception as e:  # noqa: BLE001 综述失败降级:用统计信号直接出榜
        print(f"  ! 热点综述失败,降级统计榜: {str(e)[:80]}")
        j = {"headline": "今日主题热度(统计榜)", "items": []}

    # 把 DeepSeek 的 reason/trend 合并回统计行(以统计为准,叙述为辅)
    reason_by_node = {it.get("node_id"): it for it in j.get("items", []) if it.get("node_id")}
    # DeepSeek 可能用 "链/节点" 字符串作 node_id,做个宽松匹配
    def _match(r):
        key1, key2 = r["node_id"], f"{r['chain']}/{r['node']}"
        return reason_by_node.get(key1) or reason_by_node.get(key2) or \
            next((v for k, v in reason_by_node.items() if r["node"] in str(k)), None)

    items = []
    for r in rows:
        d = _match(r) or {}
        items.append({**r, "reason": d.get("reason") or (f"今日{r['news_today']}条新闻、龙虎榜{r['lhb']}只上榜"
                      if r["lhb"] else f"今日{r['news_today']}条相关新闻"),
                      "trend": d.get("trend") or r["trend"]})
    # 利好/利空要点(LLM 汇总,失败/缺失=空,前端自动隐藏)
    brief = {"pos": [s for s in (j.get("pos") or []) if isinstance(s, str) and s.strip()][:5],
             "neg": [s for s in (j.get("neg") or []) if isinstance(s, str) and s.strip()][:5]}
    return {"headline": j.get("headline") or "今日主题热度", "brief": brief, "items": items}


def persist(date_utc8: str) -> int:
    out = generate(date_utc8)
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("""INSERT INTO hotspot_daily(report_date, headline, brief, items)
            VALUES(to_date(%s,'YYYYMMDD'), %s, %s, %s)
            ON CONFLICT(report_date) DO UPDATE SET headline=EXCLUDED.headline,
              brief=EXCLUDED.brief, items=EXCLUDED.items, generated_at=now()""",
            (date_utc8, out["headline"], json.dumps(out.get("brief") or {}, ensure_ascii=False),
             json.dumps(out["items"], ensure_ascii=False)))
    return len(out["items"])
