"""大盘仪表(三层漏斗第一层·环境读数)。

全部从 marketdata 结构化数据算——替掉报告第一段从新闻文本转述指数的做法。
指数=md.index_daily(pct_chg 已是%);宽度/成交额=md.bar_daily_raw 全A(涨停阈值同温度计,
ST 无法识别按普通阈值,少量误差可接受);两融=md.margin_detail rzrqye 合计(元,T-1 落地);
主力=md.moneyflow 全A 大单+超大单净额(万元,T日~22:15落地,缺当日则标最近一日)。
盘中看到的是上一收盘状态,以 trade_date 标注口径,不冒充实时。
"""
from __future__ import annotations

from . import db

INDEXES = [("000001.SH", "上证"), ("399001.SZ", "深成"), ("399006.SZ", "创业板"),
           ("000300.SH", "沪深300"), ("000905.SH", "中证500")]


def _limit_threshold(ts_code: str) -> float:
    if ts_code[:2] in ("30", "68"):
        return 19.5  # 创业板/科创 20%
    if ts_code[0] in ("4", "8"):
        return 29.5  # 北交所 30%
    return 9.8


def gauge() -> dict | None:
    with db.marketdata_conn() as mc, mc.cursor() as cur:
        cur.execute("SELECT max(trade_date) FROM md.index_daily")
        d = cur.fetchone()[0]
        if d is None:
            return None
        # 指数:当日读数 + 近20交易日收盘(前端 sparkline)
        cur.execute("""SELECT ts_code, trade_date, close, pct_chg FROM md.index_daily
            WHERE ts_code = ANY(%s) AND trade_date >= %s - 40 ORDER BY trade_date""",
            ([c for c, _ in INDEXES], d))
        ihist: dict[str, list] = {}
        for ts, td, cl, pc in cur.fetchall():
            ihist.setdefault(ts, []).append((td, float(cl), float(pc or 0)))
        idx = []
        for c, n in INDEXES:
            h = ihist.get(c) or []
            if h and h[-1][0] == d:
                idx.append({"code": c, "name": n, "close": round(h[-1][1], 2),
                            "pct": round(h[-1][2], 2),
                            "spark": [round(x[1], 2) for x in h[-20:]]})

        # 全A宽度 + 成交额:近20交易日逐日(当日读数=末位;千元→亿)
        cur.execute("""SELECT trade_date,
                count(*) FILTER (WHERE (close-pre_close)/pre_close*100 > 0.05)  AS up,
                count(*) FILTER (WHERE (close-pre_close)/pre_close*100 < -0.05) AS down,
                count(*) FILTER (WHERE abs((close-pre_close)/pre_close*100) <= 0.05) AS flat,
                sum(amount)/1e5 AS turnover
            FROM md.bar_daily_raw WHERE trade_date >= %s - 40 AND pre_close > 0
            GROUP BY 1 ORDER BY 1""", (d,))
        days = cur.fetchall()[-20:]
        up = down = flat = 0
        turnover, turn_chg = 0.0, None
        net_hist: list[int] = []
        turn_hist: list[float] = []
        if days:
            up, down, flat = days[-1][1], days[-1][2], days[-1][3]
            turnover = float(days[-1][4])
            if len(days) > 1:
                turn_chg = turnover - float(days[-2][4])
            net_hist = [int(r[1] - r[2]) for r in days]
            turn_hist = [round(float(r[4])) for r in days]
        # 涨停/跌停家数只算当日(阈值逐票判定,不进历史小图)
        cur.execute("""SELECT ts_code, (close-pre_close)/pre_close*100
            FROM md.bar_daily_raw WHERE trade_date=%s AND pre_close>0""", (d,))
        lu = ld = 0
        for ts, pct in cur.fetchall():
            pct = float(pct)
            thr = _limit_threshold(ts)
            if pct >= thr:
                lu += 1
            elif pct <= -thr:
                ld += 1

        # 两融余额:近20交易日逐日合计(常态 T-1;元→亿)
        cur.execute("""SELECT trade_date, sum(rzrqye)/1e8 FROM md.margin_detail
            WHERE trade_date >= %s - 40 GROUP BY 1 ORDER BY 1""", (d,))
        mrows = cur.fetchall()[-20:]
        margin = None
        margin_hist: list[float] = []
        if mrows:
            prev = float(mrows[-2][1]) if len(mrows) > 1 else None
            margin = {"date": str(mrows[-1][0]), "balance": round(float(mrows[-1][1])),
                      "chg": round(float(mrows[-1][1]) - prev) if prev is not None else None}
            margin_hist = [round(float(r[1])) for r in mrows]

        # 全A主力净额:近20交易日逐日(万元→亿)
        cur.execute("""SELECT trade_date,
                sum(buy_lg_amount-sell_lg_amount+buy_elg_amount-sell_elg_amount)/1e4
            FROM md.moneyflow WHERE trade_date >= %s - 40 GROUP BY 1 ORDER BY 1""", (d,))
        fr = cur.fetchall()[-20:]
        mf = None
        main_hist: list[float] = []
        if fr:
            mf = {"date": str(fr[-1][0]), "main": round(float(fr[-1][1]))}
            main_hist = [round(float(r[1])) for r in fr]

    return {"trade_date": str(d), "indexes": idx,
            "breadth": {"up": up, "down": down, "flat": flat, "limit_up": lu, "limit_down": ld},
            "turnover": round(turnover), "turnover_chg": round(turn_chg) if turn_chg is not None else None,
            "margin": margin, "moneyflow": mf,
            "history": {"net": net_hist, "turnover": turn_hist,
                        "margin": margin_hist, "main": main_hist}}


def lines(g: dict) -> list[str]:
    """LLM 输入块行——报告第一段"大盘温度"的结构化依据。"""
    b = g["breadth"]
    out = [
        "- 指数(" + g["trade_date"] + "收盘): "
        + "  ".join(f"{i['name']}{i['pct']:+.2f}%({i['close']})" for i in g["indexes"]),
        f"- 全A宽度: 涨{b['up']}/跌{b['down']}/平{b['flat']},涨停{b['limit_up']}/跌停{b['limit_down']}",
        f"- 两市成交额: {g['turnover']:.0f}亿"
        + (f"(较前日{g['turnover_chg']:+.0f}亿)" if g.get("turnover_chg") is not None else ""),
    ]
    if g.get("margin"):
        m = g["margin"]
        out.append(f"- 两融余额: {m['balance']:.0f}亿(截至{m['date']}"
                   + (f",较前日{m['chg']:+.0f}亿" if m.get("chg") is not None else "") + ")")
    if g.get("moneyflow"):
        out.append(f"- 全A主力净额: {g['moneyflow']['main']:+.0f}亿({g['moneyflow']['date']} EOD;"
                   "该口径结构性偏净流出,读相对变化不是绝对买卖量)")
    return out
