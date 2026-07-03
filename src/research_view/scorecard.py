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


def score_mature(conn=None) -> dict:
    """给所有已到期未记分的卡记分(每节点每日只认最新 card_id,旧重跑卡不记分)。
    conn 传入时由调用方管事务(测试用);缺省自管。"""
    own = conn is None
    if own:
        ctx = db.rv_conn()
        conn = ctx.__enter__()
    try:
        cur = conn.cursor()
        cur.execute("""WITH latest AS (
                SELECT DISTINCT ON (trade_date, node_id)
                       card_id, trade_date, node_id, direction, horizon_days
                FROM judgment_card ORDER BY trade_date, node_id, card_id DESC)
            SELECT l.card_id, l.trade_date, l.node_id, l.direction, l.horizon_days FROM latest l
            WHERE NOT EXISTS (SELECT 1 FROM card_score cs WHERE cs.card_id = l.card_id)
            ORDER BY l.trade_date""")
        todo = cur.fetchall()
        if not todo:
            return {"scored": 0, "pending": 0}
        # 成分映射 + 全池
        cur.execute("""SELECT sn.node_id, s.ts_code FROM stock_node sn
            JOIN stock s USING(code) WHERE s.ts_code IS NOT NULL""")
        members: dict[str, list[str]] = {}
        for nid, ts in cur.fetchall():
            members.setdefault(nid, []).append(ts)
        pool_ts = sorted({t for v in members.values() for t in v})

        scored = pending = 0
        with db.marketdata_conn() as mc, mc.cursor() as mcur:
            mcur.execute("SELECT max(trade_date) FROM md.bar_daily_raw")
            latest_bar = mcur.fetchone()[0]
            # 同发卡日同 horizon 的卡共享一次行情查询
            by_window: dict[tuple, list] = {}
            for card in todo:
                by_window.setdefault((card[1], card[4]), []).append(card)
            for (d0, horizon), cards in by_window.items():
                d1 = _horizon_end(mcur, d0, horizon)
                if d1 is None or latest_bar is None or d1 > latest_bar:
                    pending += len(cards)
                    continue
                rets = _interval_rets(mcur, pool_ts, d0, d1)
                if not rets:
                    pending += len(cards)
                    continue
                pool_ret = sum(rets.values()) / len(rets)
                for card_id, _d0, nid, direction, _h in cards:
                    node_rets = [rets[t] for t in members.get(nid, []) if t in rets]
                    if not node_rets:  # 成分无行情(不该发生:发卡有 scorable 门)
                        pending += 1
                        continue
                    node_ret = sum(node_rets) / len(node_rets)
                    excess = node_ret - pool_ret
                    cur.execute("""INSERT INTO card_score(card_id,trade_date,node_id,end_date,
                            node_ret,pool_ret,excess,n_members,verdict)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(card_id) DO UPDATE SET end_date=EXCLUDED.end_date,
                            node_ret=EXCLUDED.node_ret, pool_ret=EXCLUDED.pool_ret,
                            excess=EXCLUDED.excess, n_members=EXCLUDED.n_members,
                            verdict=EXCLUDED.verdict, created_at=now()""",
                        (card_id, d0, nid, d1, round(node_ret, 2), round(pool_ret, 2),
                         round(excess, 2), len(node_rets), _verdict(direction, excess)))
                    scored += 1
        return {"scored": scored, "pending": pending}
    finally:
        if own:
            ctx.__exit__(None, None, None)


# ---------- 统计与归因(代码算) ----------

def _stats(rows) -> dict:
    """rows: [(verdict,)...] → {n, right, wrong, flat, hit_rate}。hit_rate 只算对/(对+错)。"""
    n = len(rows)
    right = sum(1 for (v,) in rows if v == "对")
    wrong = sum(1 for (v,) in rows if v == "错")
    decided = right + wrong
    return {"n": n, "right": right, "wrong": wrong, "flat": n - decided,
            "hit_rate": round(right / decided * 100, 1) if decided else None}


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


# ---------- 周度收口(周日 cron:汇总 + DeepSeek 错误归纳 + lessons 回灌) ----------

def _week_rows(cur, week_end: str):
    cur.execute("""SELECT jc.node_id, n.chain, n.node, jc.direction, jc.confidence, jc.thesis,
               jc.evidence, jc.matrix, cs.excess, cs.node_ret, cs.pool_ret, cs.verdict
        FROM card_score cs JOIN judgment_card jc USING(card_id) JOIN node n ON n.node_id=jc.node_id
        WHERE cs.end_date > to_date(%s,'YYYYMMDD') - 7 AND cs.end_date <= to_date(%s,'YYYYMMDD')
        ORDER BY cs.excess""", (week_end, week_end))
    return cur.fetchall()


def _review_wrong(week_end: str, wrong: list) -> dict:
    """DeepSeek 归纳本周错误卡。无错误卡不烧 LLM。"""
    if not wrong:
        return {"review": [], "lessons": []}
    blocks = []
    for nid, chain, node, direction, conf, thesis, evidence, matrix, excess, nret, pret, _v in wrong:
        zs = " ".join(f"{_SRC_CN[k]}z{float((matrix.get(k) or {}).get('z') or 0):+.1f}"
                      for k in ("news", "mf", "price", "lhb")) if isinstance(matrix, dict) else ""
        ev = "；".join(f"[{e.get('src')}]{e.get('fact')}" for e in (evidence or []) if isinstance(e, dict))
        blocks.append(f"- 【{chain}/{node}】(node_id={nid}) 判「{direction}·置信{conf or '—'}」:{thesis}\n"
                      f"  当时证据:{ev or '(无)'}\n  z矩阵:{zs}\n"
                      f"  实际:节点{float(nret):+.1f}% vs 全池{float(pret):+.1f}%,超额{float(excess):+.1f}pp → 判断错")
    user = f"""下面是截至 {week_end} 一周内到期且判错的节点研判卡(当时的判断、证据、z矩阵 与 实际超额)。
逐卡归因错误类型,并给下周研判员可操作的教训。JSON:
{{
  "review": [{{"node_id":"照抄","error_type":"信息错|逻辑错|纯运气","why":"≤50字,指出具体错在哪(哪个源误导/哪步推理不当)"}}],
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


def weekly(date_utc8: str) -> dict:
    """周度成绩单:累计+本周命中率、分方向、分源归因(代码算)+错误归纳(DeepSeek)。
    无已记分卡时落诚实空单(不烧 LLM)。"""
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT verdict FROM card_score")
        cum = _stats(cur.fetchall())
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
        wrong = [r for r in wk if r[-1] == "错"]
    rv = _review_wrong(date_utc8, wrong)
    stats = {"cum": cum, "week": week, "by_direction": by_dir, "by_source": by_src}
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("""INSERT INTO b7_weekly(week_end, stats, review, lessons)
            VALUES(to_date(%s,'YYYYMMDD'), %s, %s, %s)
            ON CONFLICT(week_end) DO UPDATE SET stats=EXCLUDED.stats,
                review=EXCLUDED.review, lessons=EXCLUDED.lessons, generated_at=now()""",
            (date_utc8, json.dumps(stats, ensure_ascii=False),
             json.dumps(rv["review"], ensure_ascii=False),
             json.dumps(rv["lessons"], ensure_ascii=False)))
    return {"week_scored": week["n"], "wrong": len(wrong), "lessons": len(rv["lessons"]),
            "cum_hit": cum["hit_rate"]}


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
        cur.execute("SELECT week_end, review, lessons FROM b7_weekly ORDER BY week_end DESC LIMIT 1")
        row = cur.fetchone()
        weekly_out = ({"week_end": str(row[0]), "review": row[1] or [], "lessons": row[2] or []}
                      if row else None)
    return {"pending": pending, "cum": cum, "by_direction": by_dir, "by_source": by_src,
            "curve": curve, "recent": recent, "weekly": weekly_out}


def latest_lessons() -> tuple[str, list[str]] | None:
    """最新一份非空 lessons(evidence.generate 回灌用)。返回 (week_end, lessons)。"""
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("""SELECT week_end, lessons FROM b7_weekly
            WHERE jsonb_array_length(lessons) > 0 ORDER BY week_end DESC LIMIT 1""")
        row = cur.fetchone()
    return (str(row[0]), list(row[1])) if row else None
