"""B6 节点研判卡(二期):六源证据矩阵 + 共振/背离(代码算) + DeepSeek 研判卡。

六源 = 新闻净情绪 / 资金(主力5日) / 行情(周涨幅) / 龙虎榜(净买额) / 研报(近3日覆盖) / 信函(命中)。
z-score 是 48 节点截面标准分(相对全池强弱)——方向判断的口径本来就是"相对全池超额",
截面 z 天然消解主力口径结构性净流出这类系统性偏移。统计归代码:z/共振/背离全部代码算,
DeepSeek 只做跨源综合与研判措辞,它拿到的矩阵与落库的矩阵是同一份(防 LLM 自算指标)。

铁律「判断必须可追责」:每张卡带证据链(每条可溯源到输入)+ 条件式情景(含具体证伪条件)
+ 时间窗(horizon_days),落 append-only judgment_card;B7 周度成绩单按 horizon 内
相对全池超额记分、按证据源归因错误。
"""
from __future__ import annotations

import json

from . import db, llm, moneyflow

# 方向源权重(共振分):行情/资金为主,新闻情绪次之,龙虎榜噪音大再次,信函为立场号(非z)
_W = {"price": 1.0, "mf": 1.0, "news": 0.8, "lhb": 0.6, "letter": 0.5}
_ZCAP = 3.0        # 截面z截断:研报/龙虎榜稀疏源,极端值不许单源打爆共振分
_ACTIVE = 1.0      # |z|≥1 = 激活
HORIZON_DAYS = 5   # 判断时间窗(交易日),B7 到期打分

SYSTEM = """你是投研研判员,为一位A股AI科技产业链投资者对"节点"(产业链环节)做可追责的方向研判。
你应当给出方向判断(这不是中性陈列),但每个判断必须可追责:
- 证据链每条必须可溯源到输入里的具体事实,带数字与来源(六源之一:新闻/资金/行情/龙虎榜/研报/信函);
- 必须给条件式情景,证伪条件要具体、可在1周内验证(禁止"除非大盘崩盘"式空条件);
- 证据不足或六源相互矛盾时,方向必须给"中性"并在 thesis 里点明矛盾在哪。
禁止:引用输入之外的信息、编造数字、无证据的裸断言。
你的每个判断都会按"未来5个交易日该节点相对全池的超额表现"被自动记分与归因追责。输出严格JSON。"""


# ---------- 六源矩阵(代码算) ----------

def _z(vals: dict[str, float]) -> dict[str, float]:
    """48节点截面 z-score,截断±3。全零/无差异截面 → 全 0。"""
    xs = list(vals.values())
    n = len(xs)
    if n < 3:
        return {k: 0.0 for k in vals}
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / n
    std = var ** 0.5
    if std < 1e-9:
        return {k: 0.0 for k in vals}
    return {k: max(-_ZCAP, min(_ZCAP, (v - mean) / std)) for k, v in vals.items()}


def _letter_sign(stance: str | None) -> int:
    s = stance or ""
    if any(w in s for w in ("看多", "乐观", "积极", "看好")):
        return 1
    if any(w in s for w in ("看空", "谨慎", "悲观", "防御", "回避")):
        return -1
    return 0


def build_matrix(date_utc8: str) -> list[dict]:
    """每节点六源原始值 + 截面z + 共振分/背离。返回按 |共振分| 降序的全节点列表。"""
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT node_id, chain, node FROM node")
        meta = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
        # ① 新闻:今日条数/利好/利空 + 代表新闻(证据链原文用)
        cur.execute("""
            SELECT m.node_id,
              count(*) FILTER (WHERE rn.pub_time::date = to_date(%s,'YYYYMMDD')) AS today,
              count(*) FILTER (WHERE rn.sentiment='利好' AND rn.pub_time::date = to_date(%s,'YYYYMMDD')) AS pos,
              count(*) FILTER (WHERE rn.sentiment='利空' AND rn.pub_time::date = to_date(%s,'YYYYMMDD')) AS neg
            FROM raw_news rn CROSS JOIN LATERAL unnest(rn.matched_node_ids) m(node_id)
            WHERE rn.relevant AND rn.pub_time::date = to_date(%s,'YYYYMMDD')
            GROUP BY m.node_id""", (date_utc8,) * 4)
        news = {r[0]: {"today": r[1], "pos": r[2], "neg": r[3]} for r in cur.fetchall()}
        cur.execute("""SELECT m.node_id, rn.sentiment, COALESCE(rn.summary, rn.one_line), rn.src
            FROM raw_news rn CROSS JOIN LATERAL unnest(rn.matched_node_ids) m(node_id)
            WHERE rn.relevant AND rn.pub_time::date=to_date(%s,'YYYYMMDD')
              AND COALESCE(rn.summary, rn.one_line) IS NOT NULL
            ORDER BY rn.pub_time DESC""", (date_utc8,))
        node_news: dict[str, list[str]] = {}
        for nid, se, txt, src in cur.fetchall():
            node_news.setdefault(nid, []).append(f"[{se or '中性'}]{txt}(来源:{src})")
        # ③ 行情:heatmap 节点日/周涨幅
        cur.execute("SELECT node_id, ret_1d, ret_1w FROM heatmap_node")
        hm = {r[0]: (float(r[1]) if r[1] is not None else 0.0,
                     float(r[2]) if r[2] is not None else 0.0) for r in cur.fetchall()}
        # ⑤ 研报:近3日覆盖数 + 代表标题
        cur.execute("""SELECT nid, count(*), (array_agg(name || '《' || title || '》'))[1:2]
            FROM research_report rr CROSS JOIN LATERAL unnest(rr.node_ids) nid
            WHERE rr.report_date >= to_date(%s,'YYYYMMDD') - 3 GROUP BY nid""", (date_utc8,))
        rsch = {r[0]: {"n3d": r[1], "titles": r[2] or []} for r in cur.fetchall()}
        # ⑥ 信函:近45日 relevance≥5 的信函,核心观点文本命中节点/链名(立场作方向号)
        cur.execute("""SELECT fund_name, stance, title, core_views, relevant_points FROM fund_letter
            WHERE relevance >= 5 AND created_at >= now() - interval '45 days'""")
        letters_raw = [(fn, st, ti, f"{cv}{rp}") for fn, st, ti, cv, rp in cur.fetchall()]
        # 个股→节点(龙虎榜/资金聚合用)
        cur.execute("SELECT code, array_agg(node_id) FROM stock_node GROUP BY code")
        code_nodes = dict(cur.fetchall())
        cur.execute("SELECT ts_code, code FROM stock WHERE ts_code IS NOT NULL")
        ts2code = dict(cur.fetchall())

    # ② 资金:5日累计主力净额(multi_day,EOD权威口径)
    mf5: dict[str, dict] = {}
    try:
        md_ = moneyflow.multi_day()
        if md_:
            mf5 = {g["node_id"]: g for g in md_["nodes"]}
    except Exception as e:  # noqa: BLE001 资金失败降级为零源,不阻塞矩阵
        print(f"  ! 矩阵资金源降级: {str(e)[:80]}")
    # ④ 龙虎榜:最新交易日每节点上榜数 + 净买额合计(元→亿)
    lhb: dict[str, dict] = {}
    try:
        with db.marketdata_conn() as mc, mc.cursor() as c:
            c.execute("SELECT max(trade_date) FROM md.top_list")
            ltd = c.fetchone()[0]
            c.execute("SELECT ts_code, sum(net_amount) FROM md.top_list WHERE trade_date=%s GROUP BY ts_code", (ltd,))
            for ts, net in c.fetchall():
                for nid in code_nodes.get(ts2code.get(ts), []):
                    g = lhb.setdefault(nid, {"n": 0, "net": 0.0})
                    g["n"] += 1
                    g["net"] += float(net or 0) / 1e8
    except Exception as e:  # noqa: BLE001
        print(f"  ! 矩阵龙虎榜源降级: {str(e)[:80]}")

    # 截面 z(方向源4个 + 研报注意力源;信函=立场号不做z)
    z_news = _z({nid: float((news.get(nid) or {}).get("pos", 0) - (news.get(nid) or {}).get("neg", 0))
                 for nid in meta})
    z_mf = _z({nid: float((mf5.get(nid) or {}).get("d5", 0.0)) for nid in meta})
    z_price = _z({nid: hm.get(nid, (0.0, 0.0))[1] for nid in meta})
    z_lhb = _z({nid: float((lhb.get(nid) or {}).get("net", 0.0)) for nid in meta})
    z_rsch = _z({nid: float((rsch.get(nid) or {}).get("n3d", 0)) for nid in meta})

    _SRC_CN = {"news": "新闻", "mf": "资金", "price": "行情", "lhb": "龙虎榜"}
    rows = []
    for nid, (chain, node) in meta.items():
        nw = news.get(nid) or {"today": 0, "pos": 0, "neg": 0}
        m5 = mf5.get(nid) or {}
        r1d, r1w = hm.get(nid, (0.0, 0.0))
        lb = lhb.get(nid) or {"n": 0, "net": 0.0}
        rs = rsch.get(nid) or {"n3d": 0, "titles": []}
        hits = [(fn, st, ti) for fn, st, ti, txt in letters_raw if node in txt or chain in txt]
        lsign = 0
        for _fn, st, _ti in hits:
            lsign = lsign or _letter_sign(st)
        matrix = {
            "news": {"z": round(z_news[nid], 2), "today": nw["today"], "pos": nw["pos"], "neg": nw["neg"]},
            "mf": {"z": round(z_mf[nid], 2), "d5": m5.get("d5", 0.0), "d20": m5.get("d20", 0.0),
                   "streak": m5.get("streak", 0)},
            "price": {"z": round(z_price[nid], 2), "ret_1d": round(r1d, 2), "ret_1w": round(r1w, 2)},
            "lhb": {"z": round(z_lhb[nid], 2), "n": lb["n"], "net": round(lb["net"], 2)},
            "research": {"z": round(z_rsch[nid], 2), "n3d": rs["n3d"]},
            "letter": {"hit": bool(hits), "sign": lsign,
                       "funds": [f"{fn}《{ti}》立场:{st or '—'}" for fn, st, ti in hits[:2]]},
        }
        # 共振分 = 方向源加权 z 和(信函计立场号);n_agree = 与共振方向一致的激活方向源数
        dz = {"news": z_news[nid], "mf": z_mf[nid], "price": z_price[nid], "lhb": z_lhb[nid]}
        resonance = sum(_W[k] * v for k, v in dz.items()) + _W["letter"] * lsign
        active_dir = {k: v for k, v in dz.items() if abs(v) >= _ACTIVE}
        if hits and lsign:
            active_dir["letter"] = float(lsign)
        n_agree = sum(1 for v in active_dir.values() if v * resonance > 0) if abs(resonance) > 1e-9 else 0
        n_active = sum(1 for v in (z_news[nid], z_mf[nid], z_price[nid], z_lhb[nid], z_rsch[nid])
                       if abs(v) >= _ACTIVE) + (1 if hits else 0)
        # 背离 = 方向源两两显著且反向(客观标注,研判卡里必须被正面处理)
        div = []
        keys = [k for k in ("price", "mf", "news", "lhb") if abs(dz[k]) >= _ACTIVE]
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                a, b = keys[i], keys[j]
                if dz[a] * dz[b] < 0:
                    div.append({"pair": f"{_SRC_CN[a]}×{_SRC_CN[b]}",
                                "desc": f"{_SRC_CN[a]}z{dz[a]:+.1f} 与 {_SRC_CN[b]}z{dz[b]:+.1f} 反向"})
        rows.append({"node_id": nid, "chain": chain, "node": node, "matrix": matrix,
                     "resonance": round(resonance, 2), "n_agree": n_agree, "n_active": n_active,
                     "divergence": div, "news_texts": node_news.get(nid, [])[:3],
                     # 无A股行情数据的节点(如纯港股映射的整机/本体)不可发卡:
                     # B7 按相对全池超额记分,记不了分的判断=不可追责,违反铁律
                     "scorable": nid in hm})
    rows.sort(key=lambda r: -abs(r["resonance"]))
    return rows


# ---------- DeepSeek 研判卡 ----------

def _node_block(i: int, r: dict) -> str:
    m = r["matrix"]
    zs = (f"新闻{m['news']['z']:+.1f} 资金{m['mf']['z']:+.1f} 行情{m['price']['z']:+.1f}"
          f" 龙虎榜{m['lhb']['z']:+.1f} 研报{m['research']['z']:+.1f}"
          + (f" 信函:命中({'看多' if m['letter']['sign'] > 0 else '看空' if m['letter']['sign'] < 0 else '中性'})"
             if m["letter"]["hit"] else ""))
    div = "；".join(d["desc"] for d in r["divergence"]) or "无"
    lines = [
        f"{i}. 【{r['chain']}/{r['node']}】(node_id={r['node_id']}) 共振分{r['resonance']:+.1f}"
        f"(激活{r['n_active']}源,同向{r['n_agree']}源) 背离:{div}",
        f"   z矩阵: {zs}",
        f"   新闻: 今日{m['news']['today']}条(利好{m['news']['pos']}/利空{m['news']['neg']})"
        + (f" 代表: {'；'.join(r['news_texts'])}" if r["news_texts"] else ""),
        f"   资金: 主力5日{m['mf']['d5']:+.1f}亿/20日{m['mf']['d20']:+.1f}亿"
        + (f",连续{abs(m['mf']['streak'])}日净{'流入' if m['mf']['streak'] > 0 else '流出'}"
           if abs(m["mf"]["streak"]) >= 3 else ""),
        f"   行情: 今日{m['price']['ret_1d']:+.1f}% / 近一周{m['price']['ret_1w']:+.1f}%",
        f"   龙虎榜: {m['lhb']['n']}只上榜,净买{m['lhb']['net']:+.1f}亿" if m["lhb"]["n"] else "   龙虎榜: 无上榜",
        f"   研报: 近3日{m['research']['n3d']}篇",
    ]
    if m["letter"]["funds"]:
        lines.append("   信函: " + "；".join(m["letter"]["funds"]))
    return "\n".join(lines)


def generate(date_utc8: str, top: int = 8) -> list[dict]:
    """六源矩阵 → 取激活≥2源的 Top 节点 → DeepSeek 出研判卡。返回带矩阵快照的卡列表。"""
    rows = build_matrix(date_utc8)
    cands = [r for r in rows if r["n_active"] >= 2 and r["scorable"]][:top]
    if not cands:
        return []
    blocks = "\n".join(_node_block(i, r) for i, r in enumerate(cands))
    # B7 校准回路:最新一份周度成绩单的错误教训回灌(经验层,不是事实源)
    lessons_seg = ""
    try:
        from . import scorecard
        ls = scorecard.latest_lessons()
        if ls:
            lessons_seg = (f"\n【B7成绩单·近期错误教训(截至{ls[0]};经验校准,只用于调整你的谨慎度"
                           f"与矛盾处理方式——不是事实源,不得写进 evidence)】\n"
                           + "\n".join(f"- {t}" for t in ls[1]) + "\n")
    except Exception:  # noqa: BLE001 成绩单不可用不阻塞发卡
        pass
    user = f"""下面是今日({date_utc8})A股AI科技产业链各节点的六源证据矩阵(已按共振分绝对值排序)。
z = 该源指标在48节点截面的标准分(衡量相对全池强弱,|z|≥1为显著);共振分 = 方向源(新闻/资金/行情/龙虎榜/信函)加权z和,由代码算出仅供参考——你可以不同意共振方向,但必须在 thesis 里说明理由。

【六源矩阵与事实】
{blocks}
{lessons_seg}
对每个节点输出一张研判卡,JSON:
{{
  "cards": [
    {{
      "node_id": "照抄输入的 node_id",
      "direction": "偏多|偏空|中性",
      "confidence": "高|中|低",
      "thesis": "≤60字带方向的一句话研判(是判断不是陈列;有背离必须正面处理:说明你信哪一源、为什么)",
      "evidence": [{{"src":"新闻|资金|行情|龙虎榜|研报|信函","fact":"支撑方向的具体事实,带数字,只能来自该节点的输入块"}}],
      "scenarios": [{{"cond":"若未来1周出现X(具体可观察)","expect":"则方向判断成立/强化","falsify":"什么情况说明你上面的 direction 判断错了(注意:是让你的判断作废的条件,不是判断成立的条件),具体、1周内可验证(如偏多卡:'主力连续3日净流出且周涨幅落后全池')"}}]
    }}
  ]
}}
规则:direction 是对该节点未来5个交易日"相对全池超额"的方向判断;evidence 每节点2-4条、scenarios 1-2条;
六源矛盾或激活源都很弱时 direction 必须"中性"且 thesis 点明矛盾;confidence 与同向源数/z强度匹配(单源驱动不给"高");
禁止使用输入之外的任何信息。"""
    j = llm.chat_json(SYSTEM, user, timeout=300)
    by_node = {r["node_id"]: r for r in cands}
    cards = []
    for c in j.get("cards") or []:
        r = by_node.get(c.get("node_id"))
        if not r:
            continue
        direction = c.get("direction") if c.get("direction") in ("偏多", "偏空", "中性") else "中性"
        conf = c.get("confidence") if c.get("confidence") in ("高", "中", "低") else None
        cards.append({
            "node_id": r["node_id"], "chain": r["chain"], "node": r["node"],
            "direction": direction, "confidence": conf, "horizon_days": HORIZON_DAYS,
            "thesis": (c.get("thesis") or "").strip()[:120],
            "evidence": [e for e in (c.get("evidence") or []) if isinstance(e, dict) and e.get("fact")][:4],
            "scenarios": [s for s in (c.get("scenarios") or []) if isinstance(s, dict)][:2],
            "matrix": r["matrix"], "resonance": r["resonance"],
            "n_agree": r["n_agree"], "n_active": r["n_active"], "divergence": r["divergence"],
        })
    return cards


def persist(date_utc8: str) -> int:
    """生成并落 judgment_card(append-only:重跑同日只追加,消费方取每节点最新 card_id)。"""
    from . import config
    cards = generate(date_utc8)
    if not cards:
        return 0
    model = config.deepseek_model()
    with db.rv_conn() as conn, conn.cursor() as cur:
        for c in cards:
            cur.execute("""INSERT INTO judgment_card(trade_date,node_id,direction,confidence,
                    horizon_days,thesis,evidence,scenarios,matrix,resonance,n_agree,n_active,divergence,model)
                VALUES(to_date(%s,'YYYYMMDD'),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (date_utc8, c["node_id"], c["direction"], c["confidence"], c["horizon_days"],
                 c["thesis"], json.dumps(c["evidence"], ensure_ascii=False),
                 json.dumps(c["scenarios"], ensure_ascii=False),
                 json.dumps(c["matrix"], ensure_ascii=False), c["resonance"],
                 c["n_agree"], c["n_active"],
                 json.dumps(c["divergence"], ensure_ascii=False), model))
    return len(cards)
