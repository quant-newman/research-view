"""B7 周度成绩单(三期):研判卡到期记分 + 分源归因 + 错误归纳回灌。

记分口径与 B6 发卡口径同一:direction 是对"horizon 内节点相对全池超额"的判断,
到期用 bar_daily_raw 等权区间收益对账——统计归代码(记分/归因/命中率全代码算),
DeepSeek 只做本周错误卡的归纳(信息错/逻辑错/纯运气)与下周教训(lessons),
lessons 由 evidence.generate() 回灌下周研判 prompt,形成校准回路。

铁律「判断必须可追责」的闭环端:卡不可改(append-only),分数是行情的确定性函数
(可重算,upsert 幂等),对错都晒。已知边界:收益用未复权 close(同 heatmap 口径),
个别除权票会失真;等权平均下影响有限,忠实呈现不修饰。
"""
from __future__ import annotations

import json

from . import db, llm

_DIR_SIGN = {"偏多": 1, "偏空": -1}
_HIT_TH = 1.0        # 方向卡:|超额|>1pp 才定对错,带内=平(不给贴边判断白捡命中)
_NEUTRAL_BAND = 2.0  # 中性卡:|超额|≤2pp=对(节点确实没走出相对行情),否则=错
_SRC_CN = {"news": "新闻", "mf": "资金", "price": "行情", "lhb": "龙虎榜", "letter": "信函"}

SYSTEM = """你是投研复盘员,对上周方向判断的错误卡做归因,只归纳、不粉饰、不找借口。
错误类型只能三选一:
- 信息错:输入事实本身误导/关键信息缺失(如新闻断章、资金数据口径踩坑);
- 逻辑错:事实没错但推理不当(如单源过度自信、忽视背离、把短期波动当趋势);
- 纯运气:判断在当时证据下合理,被 horizon 内不可预知的新事件打翻。
lessons 是给下周研判员的注意事项,必须可操作(如"资金与行情背离时降置信"),不写空话。输出严格JSON。"""


# ---------- 参照层快照(留痕,记分按发卡日成分锚定) ----------

def snapshot_membership(date_utc8: str) -> int:
    """当日成分快照(幂等):参照层此后改版不追溯污染在途卡分数。含仅映射票(ts_code NULL)。"""
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM ref_membership_snap WHERE snap_date = to_date(%s,'YYYYMMDD')", (date_utc8,))
        cur.execute("""INSERT INTO ref_membership_snap(snap_date, node_id, code, ts_code, tier)
            SELECT to_date(%s,'YYYYMMDD'), sn.node_id, sn.code, s.ts_code, sn.tier
            FROM stock_node sn JOIN stock s USING(code)""", (date_utc8,))
        return cur.rowcount


def _members_asof(cur, d0) -> dict[str, list[str]] | None:
    """发卡日(或其前最近)成分快照。无快照(历史卡/快照未启用)返回 None,调用方回退当前表。"""
    cur.execute("SELECT max(snap_date) FROM ref_membership_snap WHERE snap_date <= %s", (d0,))
    sd = cur.fetchone()[0]
    if not sd:
        return None
    cur.execute("""SELECT node_id, ts_code FROM ref_membership_snap
        WHERE snap_date = %s AND ts_code IS NOT NULL""", (sd,))
    members: dict[str, list[str]] = {}
    for nid, ts in cur.fetchall():
        members.setdefault(nid, []).append(ts)
    return members or None


# ---------- 到期记分(代码算,盘后每日跑,幂等) ----------

def _horizon_end(mcur, trade_date, horizon: int):
    """发卡日后第 horizon 个开市日;日历不够返回 None。
    trade_calendar 每日期沪深两所各一行,必须 DISTINCT,否则 horizon 被折半。"""
    mcur.execute("""SELECT DISTINCT cal_date FROM md.trade_calendar
        WHERE cal_date > %s AND is_open ORDER BY cal_date LIMIT %s""", (trade_date, horizon))
    rows = mcur.fetchall()
    return rows[horizon - 1][0] if len(rows) >= horizon else None


def _interval_rets(mcur, ts_codes: list[str], d0, d1) -> dict[str, float]:
    """区间收益 %(未复权 close,同 heatmap 口径)。两端都有价的票才参与。"""
    mcur.execute("""SELECT ts_code, trade_date, close FROM md.bar_daily_raw
        WHERE trade_date IN (%s, %s) AND ts_code = ANY(%s) AND close > 0""", (d0, d1, ts_codes))
    px: dict[str, dict] = {}
    for ts, dt, cl in mcur.fetchall():
        px.setdefault(ts, {})[dt] = float(cl)
    return {ts: (p[d1] / p[d0] - 1) * 100 for ts, p in px.items() if d0 in p and d1 in p}


def _verdict(direction: str, excess: float) -> str:
    s = _DIR_SIGN.get(direction)
    if s is None:  # 中性卡:节点没走出相对行情=对
        return "对" if abs(excess) <= _NEUTRAL_BAND else "错"
    if excess * s >= _HIT_TH:
        return "对"
    if excess * s <= -_HIT_TH:
        return "错"
    return "平"


def _mech_dir(x) -> str:
    """机械基线方向(0b):sign(共振分/对齐分),零 LLM。"""
    if x is None:
        return "中性"
    x = float(x)
    return "偏多" if x > 0 else "偏空" if x < 0 else "中性"


def baseline_stats(rows) -> dict:
    """三列对照的两条基线。rows: [(excess, mech_verdict)]。
    mech = sign(共振/对齐)方向按同规则记分;always_long = 恒偏多(从 excess 分布直接得出)。"""
    mech = _stats([(m,) for _e, m in rows if m])
    al = [("对" if float(e) >= _HIT_TH else "错" if float(e) <= -_HIT_TH else "平",)
          for e, _m in rows if e is not None]
    return {"mech": mech, "always_long": _stats(al)}


def score_mature(conn=None) -> dict:
    """给所有已到期未记分的卡记分——节点卡(B6)与个股卡(B8)同一套口径,同窗口共享行情查询。
    每节点/每股每日只认最新 card_id(旧重跑卡不记分)。conn 传入时由调用方管事务(测试用)。"""
    own = conn is None
    if own:
        ctx = db.rv_conn()
        conn = ctx.__enter__()
    try:
        cur = conn.cursor()
        cur.execute("""WITH latest AS (
                SELECT DISTINCT ON (trade_date, node_id)
                       card_id, trade_date, node_id, direction, horizon_days, resonance
                FROM judgment_card ORDER BY trade_date, node_id, card_id DESC)
            SELECT l.card_id, l.trade_date, l.node_id, l.direction, l.horizon_days, l.resonance
            FROM latest l
            WHERE NOT EXISTS (SELECT 1 FROM card_score cs WHERE cs.card_id = l.card_id)
            ORDER BY l.trade_date""")
        ntodo = [("node", *r) for r in cur.fetchall()]
        cur.execute("""WITH latest AS (
                SELECT DISTINCT ON (trade_date, code)
                       card_id, trade_date, code, ts_code, direction, horizon_days, alignment
                FROM decision_card ORDER BY trade_date, code, card_id DESC)
            SELECT l.card_id, l.trade_date, l.code, l.ts_code, l.direction, l.horizon_days, l.alignment
            FROM latest l
            WHERE NOT EXISTS (SELECT 1 FROM decision_score ds WHERE ds.card_id = l.card_id)
            ORDER BY l.trade_date""")
        stodo = [("stock", *r) for r in cur.fetchall()]
        if not ntodo and not stodo:
            return {"scored": 0, "pending": 0, "stock_scored": 0, "stock_pending": 0}
        # 成分映射 + 全池(当前表,作发卡日快照缺失时的回退——快照 2026-07-04 起才有)
        cur.execute("""SELECT sn.node_id, s.ts_code FROM stock_node sn
            JOIN stock s USING(code) WHERE s.ts_code IS NOT NULL""")
        members_now: dict[str, list[str]] = {}
        for nid, ts in cur.fetchall():
            members_now.setdefault(nid, []).append(ts)

        n = {"scored": 0, "pending": 0, "stock_scored": 0, "stock_pending": 0}
        with db.marketdata_conn() as mc, mc.cursor() as mcur:
            mcur.execute("SELECT max(trade_date) FROM md.bar_daily_raw")
            latest_bar = mcur.fetchone()[0]
            # 同发卡日同 horizon 的卡(不分层)共享一次行情查询
            by_window: dict[tuple, list] = {}
            for card in ntodo:
                by_window.setdefault((card[2], card[5]), []).append(card)
            for card in stodo:
                by_window.setdefault((card[2], card[6]), []).append(card)
            for (d0, horizon), cards in by_window.items():
                # 记分按发卡日成分快照锚定(参照层改版不追溯污染);无快照回退当前表
                members = _members_asof(cur, d0) or members_now
                pool_ts = sorted({t for v in members.values() for t in v})
                d1 = _horizon_end(mcur, d0, horizon)
                ok_window = not (d1 is None or latest_bar is None or d1 > latest_bar)
                rets = _interval_rets(mcur, pool_ts, d0, d1) if ok_window else {}
                if not rets:
                    for card in cards:
                        n["pending" if card[0] == "node" else "stock_pending"] += 1
                    continue
                pool_ret = sum(rets.values()) / len(rets)
                for card in cards:
                    if card[0] == "node":
                        _k, card_id, _d0, nid, direction, _h, reso = card
                        node_rets = [rets[t] for t in members.get(nid, []) if t in rets]
                        if not node_rets:  # 成分无行情(不该发生:发卡有 scorable 门)
                            n["pending"] += 1
                            continue
                        node_ret = sum(node_rets) / len(node_rets)
                        excess = node_ret - pool_ret
                        cur.execute("""INSERT INTO card_score(card_id,trade_date,node_id,end_date,
                                node_ret,pool_ret,excess,n_members,verdict,mech_verdict)
                            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            ON CONFLICT(card_id) DO UPDATE SET end_date=EXCLUDED.end_date,
                                node_ret=EXCLUDED.node_ret, pool_ret=EXCLUDED.pool_ret,
                                excess=EXCLUDED.excess, n_members=EXCLUDED.n_members,
                                verdict=EXCLUDED.verdict, mech_verdict=EXCLUDED.mech_verdict,
                                created_at=now()""",
                            (card_id, d0, nid, d1, round(node_ret, 2), round(pool_ret, 2),
                             round(excess, 2), len(node_rets), _verdict(direction, excess),
                             _verdict(_mech_dir(reso), excess)))
                        n["scored"] += 1
                    else:
                        _k, card_id, _d0, code, ts, direction, _h, align = card
                        if ts not in rets:  # 停牌/退市等无区间行情
                            n["stock_pending"] += 1
                            continue
                        excess = rets[ts] - pool_ret
                        cur.execute("""INSERT INTO decision_score(card_id,trade_date,code,end_date,
                                stock_ret,pool_ret,excess,verdict,mech_verdict)
                            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            ON CONFLICT(card_id) DO UPDATE SET end_date=EXCLUDED.end_date,
                                stock_ret=EXCLUDED.stock_ret, pool_ret=EXCLUDED.pool_ret,
                                excess=EXCLUDED.excess, verdict=EXCLUDED.verdict,
                                mech_verdict=EXCLUDED.mech_verdict, created_at=now()""",
                            (card_id, d0, code, d1, round(rets[ts], 2), round(pool_ret, 2),
                             round(excess, 2), _verdict(direction, excess),
                             _verdict(_mech_dir(align), excess)))
                        n["stock_scored"] += 1
        return n
    finally:
        if own:
            ctx.__exit__(None, None, None)


# ---------- 统计与归因(代码算) ----------

_Z95 = 1.96  # 95% Wilson;全局纪律:命中率必须带区间,点估计禁裸报


def _stats(rows) -> dict:
    """rows: [(verdict,)...] → {n, right, wrong, flat, hit_rate, hit_lo, hit_hi}。
    hit_rate 只算对/(对+错);hit_lo/hi = 95% Wilson 区间(百分数,同 hit_rate 量纲)。"""
    n = len(rows)
    right = sum(1 for (v,) in rows if v == "对")
    wrong = sum(1 for (v,) in rows if v == "错")
    decided = right + wrong
    out = {"n": n, "right": right, "wrong": wrong, "flat": n - decided,
           "hit_rate": round(right / decided * 100, 1) if decided else None,
           "hit_lo": None, "hit_hi": None}
    if decided:
        p, z2 = right / decided, _Z95 * _Z95
        denom = 1 + z2 / decided
        center = (p + z2 / (2 * decided)) / denom
        half = _Z95 * ((p * (1 - p) / decided + z2 / (4 * decided * decided)) ** 0.5) / denom
        out["hit_lo"] = round(max(0.0, center - half) * 100, 1)
        out["hit_hi"] = round(min(1.0, center + half) * 100, 1)
    return out


def source_attrib(rows) -> dict:
    """分源归因:该源显著(|z|≥1/信函命中)且指向卡方向时,这张卡最终对了几成。
    rows: [(direction, matrix, verdict)]。中性卡与"平"不参与(源没被跟随/没分出对错)。"""
    out = {k: {"n": 0, "right": 0} for k in _SRC_CN}
    for direction, matrix, verdict in rows:
        s = _DIR_SIGN.get(direction)
        if not s or verdict == "平" or not isinstance(matrix, dict):
            continue
        for src in ("news", "mf", "price", "lhb"):
            z = float((matrix.get(src) or {}).get("z") or 0)
            if abs(z) >= 1 and z * s > 0:
                out[src]["n"] += 1
                out[src]["right"] += verdict == "对"
        lt = matrix.get("letter") or {}
        if lt.get("hit") and float(lt.get("sign") or 0) * s > 0:
            out["letter"]["n"] += 1
            out["letter"]["right"] += verdict == "对"
    return out


def _sign(x) -> int:
    if x is None:
        return 0
    x = float(x)
    return 1 if x > 0 else -1 if x < 0 else 0


def override_slices(rows) -> dict:
    """覆写切片(#30 五件套①):按 LLM 方向 vs 机械符号(共振/对齐)分四桶,
    桶内对**同一批卡**配对报告 LLM / 机械双列——比总体三列对照强一个数量级的读法。
    rows: [(direction, mech_raw, verdict, mech_verdict)]

    agree    符号一致。两列 verdict 按构造恒等,只看规模与命中,不含增量信息。
    override 符号相反。判出对错的卡上两列一对一错互补 ⇒ 本桶 LLM 去平命中率
             >50% 即 LLM 有增量、<50% 即 LLM 在帮倒忙——全平台最快先导证据。
    llm_only 机械中性、LLM 给方向。LLM 独判,同为增量证据(方向二)。
    suppress LLM 中性、机械有符号(LLM 压掉机械信号)。注意两列判定规则不对称
             (中性卡走 ±2pp 带,方向卡走 ±1pp 阈),本桶配对只作参考不作裁决。
    双中性丢弃(无信息)。"""
    buckets: dict[str, list] = {"agree": [], "override": [], "llm_only": [], "suppress": []}
    for direction, raw, verdict, mech_verdict in rows:
        ls = _DIR_SIGN.get(direction, 0)
        ms = _sign(raw)
        if ls == 0 and ms == 0:
            continue
        key = ("suppress" if ls == 0 else "llm_only" if ms == 0
               else "agree" if ls * ms > 0 else "override")
        buckets[key].append((verdict, mech_verdict))
    return {k: {"llm": _stats([(v,) for v, _m in rs]),
                "mech": _stats([(m,) for _v, m in rs if m])}  # None=存量早卡缺列,跳过
            for k, rs in buckets.items()}


# prompt_hash → 人读标签。新版本上线时在此登记一行;未登记哈希原样显示,不阻塞。
# 库内真值 07-05 实测(键=前16位,sql/024 口径):存量20卡(07-03发,早于加列)全 NULL→unversioned;
# B6 v1 模板哈希(b2f7cf70...)早于加列,库里永远不会出现,不登记。
# ⚠ 参照层 v2→v3(07-05,DECISIONS #37,截面z分母57→76)不改 prompt_hash——ffb0a6cc 组内混
#   两个截面口径的样本,本分组承担不了 #37 周报义务:07-12 周报正文仍须手写注明两次参照层变更。
_PROMPT_LABELS = {
    "ffb0a6cccf2c61b7": "B6 v2模板(07-04起;参照层v2/v3同哈希,07-05起z分母57→76)",
    "fe67e54832acdb4f": "B8 v1模板(07-04起;参照层v2/v3同哈希,同上)",
    "a778927f2c31ef56": "B6 v3模板(07-06起,+subjective_prob;DECISIONS #40)",
    "cd3655bba4858708": "B8 v2模板(07-06起,+subjective_prob;DECISIONS #40)",
    "unversioned": "07-04 加列前存量卡(参照层v1口径)",
}


def version_stats(rows) -> dict:
    """rows: [(prompt_hash, verdict)] → {hash: {label, ...统计}}。
    样本按 prompt/参照层版本分组不混算(#28/#31);空哈希(存量早卡)归 unversioned。"""
    grp: dict[str, list] = {}
    for h, v in rows:
        grp.setdefault(h or "unversioned", []).append((v,))
    return {h: {"label": _PROMPT_LABELS.get(h, h), **_stats(rs)} for h, rs in grp.items()}


# ---------- 校准(Brier,DECISIONS #40):subjective_prob 卡的概率校准,增量不替换 ----------

def brier_stats(rows, nbins: int = 5) -> dict:
    """rows: [(subjective_prob, verdict)] → Brier 均分 + 校准曲线数据点(等宽5桶)。
    事件E=「verdict=对」,outcome: 对=1,错/平=0——平不剔除:模型报的是"兑现"概率,
    兑现门槛(方向卡超额×方向≥+1pp)在发卡 prompt 里明示,带内=未兑现;剔平等于把概率
    条件化在"分出对错"上,与模型面对的事件不一致,校准曲线会系统性偏高。
    (与 hit_rate 只算 对/(对+错) 是两个指标两个口径。)无带 prob 样本返回 n=0。"""
    pts = [(float(p), 1.0 if v == "对" else 0.0) for p, v in rows if p is not None]
    if not pts:
        return {"n": 0, "brier": None, "bins": []}
    brier = sum((p - o) ** 2 for p, o in pts) / len(pts)
    bins = []
    for i in range(nbins):
        lo, hi = i / nbins, (i + 1) / nbins
        grp = [(p, o) for p, o in pts if lo <= p < hi]  # prob 开区间,p=1 不存在,右开安全
        if grp:
            bins.append({"lo": lo, "hi": hi, "n": len(grp),
                         "p_mean": round(sum(p for p, _ in grp) / len(grp), 3),
                         "hit_rate": round(sum(o for _, o in grp) / len(grp), 3)})
    return {"n": len(pts), "brier": round(brier, 4), "bins": bins}


def brier_by_version(rows) -> dict:
    """rows: [(prompt_hash, subjective_prob, verdict)] → 按 prompt 版本分组 Brier
    (#28 同纪律:换模板换哈希,校准样本不混算;只出 n/brier,桶看总体)。"""
    grp: dict[str, list] = {}
    for h, p, v in rows:
        if p is not None:
            grp.setdefault(h or "unversioned", []).append((p, v))
    return {h: {"label": _PROMPT_LABELS.get(h, h),
                **{k: brier_stats(rs)[k] for k in ("n", "brier")}}
            for h, rs in grp.items()}


# ---------- 周度收口(周日 cron:汇总 + DeepSeek 错误归纳 + lessons 回灌) ----------

def _week_rows(cur, week_end: str):
    cur.execute("""SELECT jc.node_id, n.chain, n.node, jc.direction, jc.confidence, jc.thesis,
               jc.evidence, jc.matrix, cs.excess, cs.node_ret, cs.pool_ret, cs.verdict
        FROM card_score cs JOIN judgment_card jc USING(card_id) JOIN node n ON n.node_id=jc.node_id
        WHERE cs.end_date > to_date(%s,'YYYYMMDD') - 7 AND cs.end_date <= to_date(%s,'YYYYMMDD')
        ORDER BY cs.excess""", (week_end, week_end))
    return cur.fetchall()


def _wrong_block(label: str, key: str, direction, conf, thesis, evidence, matrix,
                 excess, ret, pret) -> str:
    """一张错误卡的复盘输入块(节点卡/个股卡通用)。"""
    zs = " ".join(f"{_SRC_CN[k]}z{float((matrix.get(k) or {}).get('z') or 0):+.1f}"
                  for k in ("news", "mf", "price", "lhb") if k in matrix) if isinstance(matrix, dict) else ""
    ev = "；".join(f"[{e.get('src')}]{e.get('fact')}" for e in (evidence or []) if isinstance(e, dict))
    return (f"- {label}(target={key}) 判「{direction}·置信{conf or '—'}」:{thesis}\n"
            f"  当时证据:{ev or '(无)'}\n  z矩阵:{zs}\n"
            f"  实际:{float(ret):+.1f}% vs 全池{float(pret):+.1f}%,超额{float(excess):+.1f}pp → 判断错")


def _review_wrong(week_end: str, blocks: list[str]) -> dict:
    """DeepSeek 归纳本周错误卡(节点+个股)。无错误卡不烧 LLM。"""
    if not blocks:
        return {"review": [], "lessons": []}
    user = f"""下面是截至 {week_end} 一周内到期且判错的研判卡(【节点】=板块层,【个股】=决策层;
含当时的判断、证据、z矩阵 与 实际超额)。逐卡归因错误类型,并给下周研判员可操作的教训。JSON:
{{
  "review": [{{"target":"照抄 target","error_type":"信息错|逻辑错|纯运气","why":"≤50字,指出具体错在哪(哪个源误导/哪步推理不当)"}}],
  "lessons": ["下周研判注意事项,≤40字,可操作,2-5条(从错误里提炼共性,不逐卡复述)"]
}}
只基于给出的信息归因,不引入外部知识。
【错误卡】
{chr(10).join(blocks)}"""
    j = llm.chat_json(SYSTEM, user, timeout=240)
    review = [r for r in (j.get("review") or []) if isinstance(r, dict) and
              r.get("error_type") in ("信息错", "逻辑错", "纯运气")]
    lessons = [s.strip() for s in (j.get("lessons") or []) if isinstance(s, str) and s.strip()][:5]
    return {"review": review, "lessons": lessons}


def _week_stock_rows(cur, week_end: str):
    cur.execute("""SELECT dc.code, dc.name, dc.direction, dc.confidence, dc.thesis,
               dc.evidence, dc.matrix, ds.excess, ds.stock_ret, ds.pool_ret, ds.verdict
        FROM decision_score ds JOIN decision_card dc USING(card_id)
        WHERE ds.end_date > to_date(%s,'YYYYMMDD') - 7 AND ds.end_date <= to_date(%s,'YYYYMMDD')
        ORDER BY ds.excess""", (week_end, week_end))
    return cur.fetchall()


def weekly(date_utc8: str) -> dict:
    """周度成绩单:节点卡+个股卡 累计/本周命中率、分方向、分源归因(代码算)
    + 双层错误归纳(DeepSeek)。无已记分卡时落诚实空单(不烧 LLM)。"""
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT verdict FROM card_score")
        cum = _stats(cur.fetchall())
        cur.execute("SELECT verdict FROM decision_score")
        stock_cum = _stats(cur.fetchall())
        cur.execute("""SELECT jc.direction, jc.matrix, cs.verdict
            FROM card_score cs JOIN judgment_card jc USING(card_id)""")
        by_src = source_attrib(cur.fetchall())
        cur.execute("""SELECT jc.direction, cs.verdict FROM card_score cs
            JOIN judgment_card jc USING(card_id)""")
        by_dir_rows: dict[str, list] = {}
        for d, v in cur.fetchall():
            by_dir_rows.setdefault(d, []).append((v,))
        by_dir = {d: _stats(rows) for d, rows in by_dir_rows.items()}
        wk = _week_rows(cur, date_utc8)
        week = _stats([(r[-1],) for r in wk])
        swk = _week_stock_rows(cur, date_utc8)
        stock_week = _stats([(r[-1],) for r in swk])
        # 0b 三列对照:LLM方向 vs 机械基线(sign共振/对齐) vs 恒多基线
        cur.execute("SELECT excess, mech_verdict FROM card_score")
        baseline = baseline_stats(cur.fetchall())
        cur.execute("SELECT excess, mech_verdict FROM decision_score")
        stock_baseline = baseline_stats(cur.fetchall())
        # 覆写切片:LLM vs 机械符号 四桶配对(#30 五件套①,值班期唯一新增测量)
        cur.execute("""SELECT jc.direction, jc.resonance, cs.verdict, cs.mech_verdict
            FROM card_score cs JOIN judgment_card jc USING(card_id)""")
        override = override_slices(cur.fetchall())
        cur.execute("""SELECT dc.direction, dc.alignment, ds.verdict, ds.mech_verdict
            FROM decision_score ds JOIN decision_card dc USING(card_id)""")
        stock_override = override_slices(cur.fetchall())
        # 版本分组:prompt_hash 同界标记 prompt/参照层变更(#28/#31 周报义务)
        cur.execute("""SELECT jc.prompt_hash, cs.verdict
            FROM card_score cs JOIN judgment_card jc USING(card_id)""")
        by_version = version_stats(cur.fetchall())
        cur.execute("""SELECT dc.prompt_hash, ds.verdict
            FROM decision_score ds JOIN decision_card dc USING(card_id)""")
        stock_by_version = version_stats(cur.fetchall())
        # 校准(#40):带 subjective_prob 的到期卡累积 Brier + 校准曲线数据点(按版本分组同 #28)
        cur.execute("""SELECT jc.prompt_hash, jc.subjective_prob, cs.verdict
            FROM card_score cs JOIN judgment_card jc USING(card_id)
            WHERE jc.subjective_prob IS NOT NULL""")
        prows = cur.fetchall()
        calibration = {**brier_stats([(p, v) for _h, p, v in prows]),
                       "by_version": brier_by_version(prows)}
        cur.execute("""SELECT dc.prompt_hash, dc.subjective_prob, ds.verdict
            FROM decision_score ds JOIN decision_card dc USING(card_id)
            WHERE dc.subjective_prob IS NOT NULL""")
        sprows = cur.fetchall()
        stock_calibration = {**brier_stats([(p, v) for _h, p, v in sprows]),
                             "by_version": brier_by_version(sprows)}
        blocks = [_wrong_block(f"【节点】{chain}/{node}", nid, d, cf, th, ev, mx, ex, nr, pr)
                  for nid, chain, node, d, cf, th, ev, mx, ex, nr, pr, v in wk if v == "错"]
        blocks += [_wrong_block(f"【个股】{name}({code})", code, d, cf, th, ev, mx, ex, sr, pr)
                   for code, name, d, cf, th, ev, mx, ex, sr, pr, v in swk if v == "错"]
        wrong = blocks
    rv = _review_wrong(date_utc8, wrong)
    stats = {"cum": cum, "week": week, "by_direction": by_dir, "by_source": by_src,
             "stock_cum": stock_cum, "stock_week": stock_week,
             "baseline": baseline, "stock_baseline": stock_baseline,
             "override": override, "stock_override": stock_override,
             "by_version": by_version, "stock_by_version": stock_by_version,
             "calibration": calibration, "stock_calibration": stock_calibration}
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("""INSERT INTO b7_weekly(week_end, stats, review, lessons)
            VALUES(to_date(%s,'YYYYMMDD'), %s, %s, %s)
            ON CONFLICT(week_end) DO UPDATE SET stats=EXCLUDED.stats,
                review=EXCLUDED.review, lessons=EXCLUDED.lessons, generated_at=now()""",
            (date_utc8, json.dumps(stats, ensure_ascii=False),
             json.dumps(rv["review"], ensure_ascii=False),
             json.dumps(rv["lessons"], ensure_ascii=False)))
    return {"week_scored": week["n"], "stock_week_scored": stock_week["n"], "wrong": len(wrong),
            "lessons": len(rv["lessons"]), "cum_hit": cum["hit_rate"],
            "stock_cum_hit": stock_cum["hit_rate"]}


def dashboard_block() -> dict | None:
    """dash.scorecard:待记分数/累计命中/分方向/分源归因/周命中率曲线/最近记分卡/最新周报。
    一张卡都没发过返回 None(前端不显);发了未到期=诚实待记分空态。"""
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("""WITH latest AS (
                SELECT DISTINCT ON (trade_date, node_id) card_id
                FROM judgment_card ORDER BY trade_date, node_id, card_id DESC)
            SELECT count(*) FROM latest l
            WHERE NOT EXISTS (SELECT 1 FROM card_score cs WHERE cs.card_id = l.card_id)""")
        pending = cur.fetchone()[0]
        cur.execute("SELECT verdict FROM card_score")
        cum = _stats(cur.fetchall())
        if pending == 0 and cum["n"] == 0:
            return None
        cur.execute("""SELECT jc.direction, jc.matrix, cs.verdict
            FROM card_score cs JOIN judgment_card jc USING(card_id)""")
        rows = cur.fetchall()
        by_src = source_attrib(rows)
        bd: dict[str, list] = {}
        for d, _m, v in rows:
            bd.setdefault(d, []).append((v,))
        by_dir = {d: _stats(r) for d, r in bd.items()}
        # 周命中率曲线(按到期周分桶,标签=该周周日)
        cur.execute("""SELECT to_char(date_trunc('week', end_date)::date + 6, 'YYYY-MM-DD'), verdict
            FROM card_score""")
        cw: dict[str, list] = {}
        for wk, v in cur.fetchall():
            cw.setdefault(wk, []).append((v,))
        curve = [{"week": wk, **_stats(r)} for wk, r in sorted(cw.items())]
        cur.execute("""SELECT cs.card_id, n.chain, n.node, jc.direction, jc.confidence,
                cs.excess, cs.verdict, cs.trade_date, cs.end_date
            FROM card_score cs JOIN judgment_card jc USING(card_id)
            JOIN node n ON n.node_id = jc.node_id
            ORDER BY cs.end_date DESC, abs(cs.excess) DESC LIMIT 12""")
        recent = [{"card_id": r[0], "chain": r[1], "node": r[2], "direction": r[3],
                   "confidence": r[4], "excess": float(r[5]), "verdict": r[6],
                   "trade_date": str(r[7]), "end_date": str(r[8])} for r in cur.fetchall()]
        # 0b 三列对照(累计)
        cur.execute("SELECT excess, mech_verdict FROM card_score")
        baseline = baseline_stats(cur.fetchall())
        cur.execute("SELECT week_end, review, lessons FROM b7_weekly ORDER BY week_end DESC LIMIT 1")
        row = cur.fetchone()
        weekly_out = ({"week_end": str(row[0]), "review": row[1] or [], "lessons": row[2] or []}
                      if row else None)
        # 个股卡(B8)子块:待记分/累计/最近
        cur.execute("""WITH latest AS (
                SELECT DISTINCT ON (trade_date, code) card_id
                FROM decision_card ORDER BY trade_date, code, card_id DESC)
            SELECT count(*) FROM latest l
            WHERE NOT EXISTS (SELECT 1 FROM decision_score ds WHERE ds.card_id = l.card_id)""")
        s_pending = cur.fetchone()[0]
        cur.execute("SELECT verdict FROM decision_score")
        s_cum = _stats(cur.fetchall())
        cur.execute("""SELECT ds.card_id, dc.code, dc.name, dc.direction, ds.excess, ds.verdict,
                ds.trade_date, ds.end_date
            FROM decision_score ds JOIN decision_card dc USING(card_id)
            ORDER BY ds.end_date DESC, abs(ds.excess) DESC LIMIT 8""")
        s_recent = [{"card_id": r[0], "code": r[1], "name": r[2], "direction": r[3],
                     "excess": float(r[4]), "verdict": r[5], "trade_date": str(r[6]),
                     "end_date": str(r[7])} for r in cur.fetchall()]
        cur.execute("SELECT excess, mech_verdict FROM decision_score")
        s_baseline = baseline_stats(cur.fetchall())
        stock = ({"pending": s_pending, "cum": s_cum, "recent": s_recent, "baseline": s_baseline}
                 if (s_pending or s_cum["n"]) else None)
    return {"pending": pending, "cum": cum, "by_direction": by_dir, "by_source": by_src,
            "curve": curve, "recent": recent, "weekly": weekly_out, "stock": stock,
            "baseline": baseline}


def latest_lessons() -> tuple[str, list[str]] | None:
    """最新一份非空 lessons(evidence.generate 回灌用)。返回 (week_end, lessons)。"""
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("""SELECT week_end, lessons FROM b7_weekly
            WHERE jsonb_array_length(lessons) > 0 ORDER BY week_end DESC LIMIT 1""")
        row = cur.fetchone()
    return (str(row[0]), list(row[1])) if row else None
