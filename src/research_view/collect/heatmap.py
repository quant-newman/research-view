"""AI热力图计算:读 marketdata 行情/估值/财务,算每票指标 + 聚合到节点四象限。

叙事强度=6M涨幅%(X), 财报兑现=营收同比%(Y), 气泡大小=市值, 气泡色=PE分位。
象限按池内节点中位切分(相对定位)。6M涨幅用原始收盘价近似(未做复权,v1 可接受)。
"""
from __future__ import annotations

from statistics import median

from .. import db


def _pct(vals: list[float], v: float) -> float:
    """v 在 vals 中的百分位 0-100。"""
    vals = sorted(x for x in vals if x is not None)
    if not vals:
        return 0.0
    below = sum(1 for x in vals if x < v)
    return round(below / len(vals) * 100, 1)


_WINDOWS = {"1d": 1, "1w": 7, "1m": 30, "3m": 90, "6m": 182}


def _returns(bars: dict[str, list[tuple]]) -> dict[str, dict[str, float | None]]:
    """每 ts_code 的多窗口涨幅% {1d,1w,1m,3m,6m}。bars: ts_code -> [(date, close)...]。"""
    out = {}
    for ts, series in bars.items():
        if len(series) < 2:
            out[ts] = {k: None for k in _WINDOWS}; continue
        series.sort(key=lambda x: x[0])
        last_date, last_close = series[-1]
        if not last_close:
            out[ts] = {k: None for k in _WINDOWS}; continue

        def ret(days):
            cutoff = last_date.toordinal() - days
            past = None
            for dt, cl in series:
                if dt.toordinal() <= cutoff and cl:
                    past = cl
            return round((float(last_close) - float(past)) / float(past) * 100, 2) if past else None
        out[ts] = {k: ret(d) for k, d in _WINDOWS.items()}
    return out


def compute() -> dict[str, int]:
    # 池子
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT code, ts_code, name FROM stock WHERE ts_code IS NOT NULL")
        pool = cur.fetchall()
        cur.execute("SELECT code, array_agg(node_id) FROM stock_node GROUP BY code")
        code_nodes = dict(cur.fetchall())
        cur.execute("SELECT node_id, chain, node FROM node")
        node_meta = {nid: (ch, nd) for nid, ch, nd in cur.fetchall()}
    pool_ts = [t for _, t, _ in pool]
    ts2code = {t: c for c, t, _ in pool}
    ts2name = {t: n for _, t, n in pool}

    with db.marketdata_conn() as mc, mc.cursor() as cur:
        # 最新 daily_basic
        cur.execute("""SELECT DISTINCT ON (ts_code) ts_code, pe_ttm, pe, ps_ttm, total_mv
            FROM md.daily_basic WHERE ts_code = ANY(%s) ORDER BY ts_code, trade_date DESC""", (pool_ts,))
        basic = {r[0]: r for r in cur.fetchall()}
        # 近220天行情算涨幅
        cur.execute("""SELECT ts_code, trade_date, close FROM md.bar_daily_raw
            WHERE ts_code = ANY(%s) AND trade_date >= current_date - 220""", (pool_ts,))
        bars: dict[str, list] = {}
        for ts, dt, cl in cur.fetchall():
            bars.setdefault(ts, []).append((dt, cl))
        # 最新财务
        cur.execute("""SELECT DISTINCT ON (ts_code) ts_code, or_yoy, grossprofit_margin, netprofit_yoy
            FROM md.fina_indicator WHERE ts_code = ANY(%s) ORDER BY ts_code, end_date DESC""", (pool_ts,))
        fina = {r[0]: r for r in cur.fetchall()}

    rets = _returns(bars)
    pe_vals = [float(basic[t][1] or basic[t][2]) for t in basic if (basic[t][1] or basic[t][2])]

    # 每票
    stock_rows = []
    per_node: dict[str, list] = {}
    for ts in pool_ts:
        b = basic.get(ts); f = fina.get(ts)
        pe = float(b[1] or b[2]) if b and (b[1] or b[2]) else None
        ps = float(b[3]) if b and b[3] else None
        mv = float(b[4]) if b and b[4] else None
        rr = rets.get(ts, {})
        r1d, r1w, r1, r3, r6 = rr.get("1d"), rr.get("1w"), rr.get("1m"), rr.get("3m"), rr.get("6m")
        or_yoy = float(f[1]) if f and f[1] is not None else None
        gm = float(f[2]) if f and f[2] is not None else None
        np_yoy = float(f[3]) if f and f[3] is not None else None
        pe_pct = _pct(pe_vals, pe) if pe else None
        code = ts2code[ts]
        stock_rows.append((code, ts, ts2name[ts], mv, pe, ps, r1d, r1w, r1, r3, r6, or_yoy, gm, np_yoy, pe_pct))
        for nid in code_nodes.get(code, []):
            per_node.setdefault(nid, []).append({"mv": mv, "pe": pe, "ps": ps, "r1d": r1d, "r1w": r1w,
                                                 "r1": r1, "r3": r3, "r6": r6, "or_yoy": or_yoy, "gm": gm})

    # 节点聚合(中位)
    def med(items, key):
        vals = [it[key] for it in items if it[key] is not None]
        return round(median(vals), 2) if vals else None

    node_agg = {}
    for nid, items in per_node.items():
        ch, nd = node_meta.get(nid, ("", ""))
        node_agg[nid] = {
            "chain": ch, "node": nd, "n": len(items),
            "mv": round(sum(it["mv"] for it in items if it["mv"]), 0) if any(it["mv"] for it in items) else None,
            "r1d": med(items, "r1d"), "r1w": med(items, "r1w"), "r1": med(items, "r1"),
            "r3": med(items, "r3"), "r6": med(items, "r6"), "or_yoy": med(items, "or_yoy"),
            "gm": med(items, "gm"), "pe": med(items, "pe"), "ps": med(items, "ps"),
        }
    # 象限切分:节点 r6 / or_yoy 的池内中位
    r6_split = median([n["r6"] for n in node_agg.values() if n["r6"] is not None] or [0])
    y_split = median([n["or_yoy"] for n in node_agg.values() if n["or_yoy"] is not None] or [0])

    def quad(r6, y):
        if r6 is None or y is None:
            return "数据不足"
        strong = r6 >= r6_split  # 叙事强(右)
        deliver = y >= y_split   # 兑现好(上)
        return ("核心主线" if strong and deliver else "等待验证" if not strong and deliver
                else "潜在补涨" if strong and not deliver else "风险区")

    node_rows = [(nid, n["chain"], n["node"], n["n"], n["mv"], n["r1d"], n["r1w"], n["r1"], n["r3"], n["r6"],
                  n["or_yoy"], n["gm"], n["pe"], n["ps"], quad(n["r6"], n["or_yoy"]))
                 for nid, n in node_agg.items()]

    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE heatmap_stock"); cur.execute("TRUNCATE heatmap_node")
        cur.executemany("""INSERT INTO heatmap_stock(code,ts_code,name,total_mv,pe,ps,ret_1d,ret_1w,ret_1m,ret_3m,ret_6m,
            or_yoy,gross_margin,netprofit_yoy,pe_pct)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", stock_rows)
        cur.executemany("""INSERT INTO heatmap_node(node_id,chain,node,n_stocks,total_mv,ret_1d,ret_1w,ret_1m,ret_3m,ret_6m,
            or_yoy,gross_margin,pe,ps,quadrant)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", node_rows)
    return {"stocks": len(stock_rows), "nodes": len(node_rows)}
