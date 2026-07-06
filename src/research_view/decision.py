"""B8 个股决策层(四期,影子运行=校准期)。三层漏斗收口:大盘→板块(B6节点卡)→个股。

候选只从**当日 B6 方向卡(偏多/偏空)节点的成分股**里出——没有板块方向支撑的个股不单独发卡。
个股六源(新闻/资金/行情/龙虎榜/研报/人气榜)在核心池截面取 z,对齐分(与节点方向同向的
加权 z 和 + 注意力加成)全代码算;DeepSeek 出决策卡(方向/信心/入场/退出/证伪),带
node_card_id 追责链与发卡日收盘价锚。每张卡与节点卡同一套 B7 记分口径(5开市日相对
全池超额)——中性(放弃)也记分,漏杀好票同样要被看见。A股无做空工具:偏空卡=回避/减仓提示。
"""
from __future__ import annotations

import hashlib
import json

from . import config, db, evidence, llm
from .evidence import _z

_W = {"price": 1.0, "mf": 1.0, "news": 0.8, "lhb": 0.6}
_ATTN_W = 0.3      # 研报/人气榜注意力加成(不带方向,只加不减)
_MIN_ALIGN = 1.0   # 对齐分门槛:个股证据与节点方向不共振就不进候选
_PER_NODE = 3      # 每节点最多候选数
_CAP = 12          # 单日总候选上限(一次 LLM 调用)
HORIZON_DAYS = 5

SYSTEM = """你是投研决策员,基于"板块节点研判卡+个股证据"给个人A股投资者出具个股决策卡。
你应当给出可执行的方向判断,但每张卡必须可追责:
- 证据链每条可溯源到输入的具体事实(带数字与来源:新闻/资金/行情/龙虎榜/研报/人气榜);
- entry/exit 必须具体可观察可验证——价位只允许以给出的现价按百分比换算(写明如"现价24.50的-5%≈23.28"),
  禁止编造均线/前高等输入里没有的参照;
- falsify 是让你的方向判断作废的条件(不是判断成立的条件),5个交易日内可验证;
- 个股证据与节点方向矛盾、或证据太弱时,direction 必须"中性"(=放弃该候选)并点明原因。
A股无做空工具:偏空卡含义是"回避/持有者减仓提示",不是做空指令。
禁止引用输入之外的信息、编造数字。每张卡按"未来5个交易日该股相对全池超额"被自动记分追责。输出严格JSON。"""


# ---------- 个股六源矩阵 + 候选(代码算) ----------

def _stock_facts(date_utc8: str, pool_codes: set[str]):
    """全池个股六源原始值(z 在全池截面算,候选只是其中子集)。"""
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT code, name, ts_code FROM stock WHERE ts_code IS NOT NULL")
        meta = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
        cur.execute("SELECT code, ret_1d, ret_1w, total_mv FROM heatmap_stock")
        hm = {r[0]: (float(r[1] or 0), float(r[2] or 0), float(r[3] or 0)) for r in cur.fetchall()}
        cur.execute("""SELECT c.code,
              count(*) FILTER (WHERE rn.sentiment='利好') AS pos,
              count(*) FILTER (WHERE rn.sentiment='利空') AS neg,
              count(*) AS today
            FROM raw_news rn CROSS JOIN LATERAL unnest(rn.matched_codes) c(code)
            WHERE rn.relevant AND rn.pub_time::date = to_date(%s,'YYYYMMDD')
            GROUP BY c.code""", (date_utc8,))
        news = {r[0]: {"pos": r[1], "neg": r[2], "today": r[3]} for r in cur.fetchall()}
        cur.execute("""SELECT c.code, rn.sentiment, COALESCE(rn.summary, rn.one_line), rn.src
            FROM raw_news rn CROSS JOIN LATERAL unnest(rn.matched_codes) c(code)
            WHERE rn.relevant AND rn.pub_time::date = to_date(%s,'YYYYMMDD')
              AND COALESCE(rn.summary, rn.one_line) IS NOT NULL
            ORDER BY rn.pub_time DESC""", (date_utc8,))
        news_texts: dict[str, list[str]] = {}
        for code, se, txt, src in cur.fetchall():
            news_texts.setdefault(code, []).append(f"[{se or '中性'}]{txt}(来源:{src})")
        cur.execute("""SELECT code, count(*), (array_agg(org_name || '《' || title || '》'))[1]
            FROM research_report WHERE report_date >= to_date(%s,'YYYYMMDD') - 3
            GROUP BY code""", (date_utc8,))
        rsch = {r[0]: {"n3d": r[1], "title": r[2]} for r in cur.fetchall()}

    ts_of = {c: t for c, (_n, t) in meta.items()}
    pool_ts = [ts_of[c] for c in pool_codes if c in ts_of]
    mf5: dict[str, float] = {}
    lhb: dict[str, float] = {}
    close: dict[str, float] = {}
    hot: dict[str, int] = {}
    with db.marketdata_conn() as mc, mc.cursor() as c:
        c.execute("SELECT DISTINCT trade_date FROM md.moneyflow ORDER BY trade_date DESC LIMIT 5")
        d5 = [r[0] for r in c.fetchall()]
        if d5:
            c.execute("""SELECT ts_code, sum(coalesce(buy_lg_amount,0)-coalesce(sell_lg_amount,0)
                    +coalesce(buy_elg_amount,0)-coalesce(sell_elg_amount,0))/1e4
                FROM md.moneyflow WHERE trade_date >= %s AND ts_code = ANY(%s)
                GROUP BY ts_code""", (min(d5), pool_ts))
            mf5 = {ts: float(v) for ts, v in c.fetchall()}  # 亿
        c.execute("SELECT max(trade_date) FROM md.top_list")
        ltd = c.fetchone()[0]
        if ltd:
            c.execute("""SELECT ts_code, sum(net_amount)/1e8 FROM md.top_list
                WHERE trade_date=%s AND ts_code = ANY(%s) GROUP BY ts_code""", (ltd, pool_ts))
            lhb = {ts: float(v) for ts, v in c.fetchall()}
        c.execute("""SELECT ts_code, close FROM md.bar_daily_raw
            WHERE trade_date=(SELECT max(trade_date) FROM md.bar_daily_raw)
              AND ts_code = ANY(%s) AND close > 0""", (pool_ts,))
        close = {ts: float(cl) for ts, cl in c.fetchall()}
        try:  # 人气榜(同花顺100名,注意力源;表结构变了不阻塞)
            c.execute("""SELECT code, min(rank) FROM md.hot_rank
                WHERE snap_date=(SELECT max(snap_date) FROM md.hot_rank) GROUP BY code""")
            hot = {code: int(rk) for code, rk in c.fetchall()}
        except Exception as e:  # noqa: BLE001
            print(f"  ! 人气榜源降级: {str(e)[:60]}")

    # 截面 z(池内全体,含未入候选的——相对全池强弱)
    codes = [c for c in pool_codes if c in meta]
    z_price = _z({c: hm.get(c, (0, 0, 0))[1] for c in codes})
    mv = {c: hm.get(c, (0, 0, 0))[2] for c in codes}
    z_mf = _z({c: (mf5.get(ts_of[c], 0.0) / mv[c] * 100 if mv[c] else 0.0) for c in codes})
    z_news = _z({c: float((news.get(c) or {}).get("pos", 0) - (news.get(c) or {}).get("neg", 0))
                 for c in codes})
    z_lhb = _z({c: lhb.get(ts_of[c], 0.0) for c in codes})
    z_rsch = _z({c: float((rsch.get(c) or {}).get("n3d", 0)) for c in codes})
    z_hot = _z({c: float(101 - hot[c]) if c in hot else 0.0 for c in codes})

    out = {}
    for c in codes:
        name, ts = meta[c]
        r1d, r1w, _mv = hm.get(c, (0, 0, 0))
        nw = news.get(c) or {"pos": 0, "neg": 0, "today": 0}
        out[c] = {
            "code": c, "name": name, "ts_code": ts, "close": close.get(ts),
            "matrix": {
                "price": {"z": round(z_price[c], 2), "ret_1d": round(r1d, 2), "ret_1w": round(r1w, 2)},
                "mf": {"z": round(z_mf[c], 2), "d5": round(mf5.get(ts, 0.0), 2)},
                "news": {"z": round(z_news[c], 2), **nw},
                "lhb": {"z": round(z_lhb[c], 2), "net": round(lhb.get(ts, 0.0), 2)},
                "research": {"z": round(z_rsch[c], 2), "n3d": (rsch.get(c) or {}).get("n3d", 0)},
                "hot": {"rank": hot.get(c)},
            },
            "dz": {"price": z_price[c], "mf": z_mf[c], "news": z_news[c], "lhb": z_lhb[c]},
            "attn": max(z_rsch[c], 0.0) + max(z_hot[c], 0.0),
            "news_texts": news_texts.get(c, [])[:2],
            "rsch_title": (rsch.get(c) or {}).get("title"),
        }
    return out


def candidates(date_utc8: str) -> list[dict]:
    """当日 B6 方向节点卡 → 成分股按对齐分选 Top(代码算)。无方向卡返回空。"""
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("""SELECT DISTINCT ON (node_id) card_id, node_id, direction, confidence,
                thesis, resonance FROM judgment_card
            WHERE trade_date = to_date(%s,'YYYYMMDD') AND direction IN ('偏多','偏空')
            ORDER BY node_id, card_id DESC""", (date_utc8,))
        ncards = [{"card_id": r[0], "node_id": r[1], "direction": r[2], "confidence": r[3],
                   "thesis": r[4], "resonance": float(r[5] or 0)} for r in cur.fetchall()]
        if not ncards:
            return []
        cur.execute("SELECT node_id, chain, node FROM node")
        nmeta = {r[0]: f"{r[1]}/{r[2]}" for r in cur.fetchall()}
        cur.execute("SELECT node_id, code FROM stock_node")
        node_codes: dict[str, list[str]] = {}
        for nid, code in cur.fetchall():
            node_codes.setdefault(nid, []).append(code)
        cur.execute("SELECT code FROM stock WHERE ts_code IS NOT NULL")
        pool_codes = {r[0] for r in cur.fetchall()}

    facts = _stock_facts(date_utc8, pool_codes)
    picked: dict[str, dict] = {}
    ncards.sort(key=lambda n: -abs(n["resonance"]))
    for nc in ncards:
        s = 1 if nc["direction"] == "偏多" else -1
        scored = []
        for code in node_codes.get(nc["node_id"], []):
            f = facts.get(code)
            if not f or f["close"] is None:  # 无行情锚不可发卡(记不了分/给不了价位)
                continue
            align = s * sum(_W[k] * v for k, v in f["dz"].items()) + _ATTN_W * f["attn"]
            scored.append((align, f))
        scored.sort(key=lambda x: -x[0])
        for align, f in scored[:_PER_NODE]:
            if align < _MIN_ALIGN or f["code"] in picked:
                continue
            picked[f["code"]] = {**f, "alignment": round(align, 2),
                                 "node_id": nc["node_id"], "node_label": nmeta.get(nc["node_id"], ""),
                                 "node_card_id": nc["card_id"], "node_direction": nc["direction"],
                                 "node_thesis": nc["thesis"], "node_resonance": nc["resonance"]}
    return sorted(picked.values(), key=lambda x: -abs(x["alignment"]))[:_CAP]


# ---------- DeepSeek 决策卡 ----------

def _stock_block(i: int, f: dict) -> str:
    m = f["matrix"]
    hot_seg = f"人气榜第{m['hot']['rank']}名" if m["hot"]["rank"] else "人气榜未上榜"
    lines = [
        f"{i}. 【{f['name']}({f['code']})】节点:{f['node_label']}(节点卡:{f['node_direction']},"
        f"共振{f['node_resonance']:+.1f}——{f['node_thesis']}) 对齐分{f['alignment']:+.1f} 现价{f['close']}",
        f"   z: 行情{m['price']['z']:+.1f}(今日{m['price']['ret_1d']:+.1f}%/周{m['price']['ret_1w']:+.1f}%)"
        f" 资金{m['mf']['z']:+.1f}(5日{m['mf']['d5']:+.1f}亿) 新闻{m['news']['z']:+.1f}"
        f"(今日{m['news']['today']}条:利好{m['news']['pos']}/利空{m['news']['neg']})"
        f" 龙虎榜{m['lhb']['z']:+.1f}(净买{m['lhb']['net']:+.1f}亿) 研报{m['research']['z']:+.1f}"
        f"(近3日{m['research']['n3d']}篇) {hot_seg}",
    ]
    if f["news_texts"]:
        lines.append("   新闻: " + "；".join(f["news_texts"]))
    if f["rsch_title"]:
        lines.append(f"   研报: {f['rsch_title']}")
    return "\n".join(lines)


# user prompt 模板(规则文本,静态):prompt_hash 口径同 evidence——sha256(SYSTEM+模板+lessons段),
# 排除每日数据块与日期。
_USER_TMPL = """下面是今日({date})按"板块节点研判卡→成分股共振"筛出的个股候选(已按对齐分排序)。
z=该指标在核心池全体个股截面的标准分(相对全池强弱);对齐分=个股方向源z与节点方向的加权一致度+注意力加成,由代码算出。

【个股候选与证据】
{blocks}
{lessons}
对每个候选输出一张决策卡,JSON:
{{
  "cards": [
    {{
      "code": "照抄输入的6位代码",
      "direction": "偏多|偏空|中性",
      "confidence": "高|中|低",
      "subjective_prob": "0到1之间的两位小数(开区间,禁止0和1):你对本卡判断兑现的主观概率。兑现的精确定义——偏多/偏空卡:到期(5个交易日)该股相对全池超额×判断方向≥+1个百分点;中性卡:|超额|≤2个百分点。方向卡带内(±1pp)不算兑现。注意 subjective_prob 与 confidence 相互独立:confidence 是证据链强度的定性档位,subjective_prob 是你对兑现频率的定量估计,禁止由档位机械换算;按你的真实把握报数,系统将用Brier分数长期校验你的校准度",
      "thesis": "≤60字带方向的一句话决策逻辑(个股层面,不是复读节点卡)",
      "entry": "入场条件:具体可观察(偏多卡必填;价位只能以现价按百分比换算并写明;偏空/中性卡可留空字符串)",
      "exit": "退出/止损条件:具体可验证(偏多卡必填,含止损价位锚;偏空卡=回避解除条件;中性卡可留空)",
      "evidence": [{{"src":"新闻|资金|行情|龙虎榜|研报|人气榜","fact":"具体事实带数字,只能来自该股的输入块"}}],
      "falsify": "让你的direction判断作废的条件(不是成立条件),5个交易日内可验证"
    }}
  ]
}}
规则:direction 通常跟随节点方向;个股证据与节点方向矛盾或太弱→"中性"(放弃)并在 thesis 说明;
confidence 与个股证据强度匹配(仅靠节点惯性不给"高");每卡 evidence 2-4条;偏空=回避/减仓提示(A股无做空)。"""


def prompt_hash(lessons_seg: str) -> str:
    return hashlib.sha256((SYSTEM + _USER_TMPL + lessons_seg).encode("utf-8")).hexdigest()[:16]


def generate(date_utc8: str) -> list[dict]:
    cands = candidates(date_utc8)
    if not cands:
        return []
    blocks = "\n".join(_stock_block(i, f) for i, f in enumerate(cands))
    # B7 校准回路:校准期冻结(DECISIONS #28)时 lessons 只落库不注入
    lessons_seg = ""
    if not config.calibration_freeze():
        try:
            from . import scorecard
            ls = scorecard.latest_lessons()
            if ls:
                lessons_seg = (f"\n【B7成绩单·近期错误教训(截至{ls[0]};经验校准,非事实源,不得写进evidence)】\n"
                               + "\n".join(f"- {t}" for t in ls[1]) + "\n")
        except Exception:  # noqa: BLE001
            pass
    phash = prompt_hash(lessons_seg)
    user = _USER_TMPL.format(date=date_utc8, blocks=blocks, lessons=lessons_seg)
    j = llm.chat_json(SYSTEM, user, timeout=300)
    by_code = {f["code"]: f for f in cands}
    cards = []
    for c in j.get("cards") or []:
        f = by_code.get(c.get("code"))
        if not f:
            continue
        direction = c.get("direction") if c.get("direction") in ("偏多", "偏空", "中性") else "中性"
        conf = c.get("confidence") if c.get("confidence") in ("高", "中", "低") else None
        cards.append({
            "code": f["code"], "name": f["name"], "ts_code": f["ts_code"],
            "node_id": f["node_id"], "node_card_id": f["node_card_id"],
            "direction": direction, "confidence": conf,
            "subjective_prob": evidence.parse_prob(c.get("subjective_prob")),
            "horizon_days": HORIZON_DAYS,
            "thesis": (c.get("thesis") or "").strip()[:120],
            "entry_cond": (c.get("entry") or "").strip()[:200] or None,
            "exit_cond": (c.get("exit") or "").strip()[:200] or None,
            "evidence": [e for e in (c.get("evidence") or []) if isinstance(e, dict) and e.get("fact")][:4],
            "falsify": (c.get("falsify") or "").strip()[:200] or None,
            "matrix": f["matrix"], "alignment": f["alignment"], "close": f["close"],
            "prompt_hash": phash,
        })
    return cards


def persist(date_utc8: str) -> int:
    """生成并落 decision_card(append-only:重跑同日只追加,消费方取每股最新 card_id)。"""
    cards = generate(date_utc8)
    if not cards:
        return 0
    model = config.deepseek_model()
    with db.rv_conn() as conn, conn.cursor() as cur:
        for c in cards:
            cur.execute("""INSERT INTO decision_card(trade_date,code,name,ts_code,node_id,
                    node_card_id,direction,confidence,subjective_prob,horizon_days,thesis,
                    entry_cond,exit_cond,
                    evidence,falsify,matrix,alignment,close,model,prompt_hash)
                VALUES(to_date(%s,'YYYYMMDD'),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (date_utc8, c["code"], c["name"], c["ts_code"], c["node_id"], c["node_card_id"],
                 c["direction"], c["confidence"], c["subjective_prob"], c["horizon_days"],
                 c["thesis"], c["entry_cond"], c["exit_cond"],
                 json.dumps(c["evidence"], ensure_ascii=False), c["falsify"],
                 json.dumps(c["matrix"], ensure_ascii=False), c["alignment"], c["close"],
                 model, c["prompt_hash"]))
    return len(cards)
