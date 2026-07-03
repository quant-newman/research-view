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
        cur.execute("""SELECT ts_code, close, pct_chg FROM md.index_daily
            WHERE ts_code = ANY(%s) AND trade_date = %s""",
            ([c for c, _ in INDEXES], d))
        got = {ts: (float(cl), float(pc or 0)) for ts, cl, pc in cur.fetchall()}
        idx = [{"code": c, "name": n, "close": round(got[c][0], 2), "pct": round(got[c][1], 2)}
               for c, n in INDEXES if c in got]

        # 全A宽度 + 成交额(近两日,千元→亿)
        cur.execute("""SELECT trade_date, sum(amount)/1e5 FROM md.bar_daily_raw
            WHERE trade_date >= %s - 7 GROUP BY 1 ORDER BY 1 DESC LIMIT 2""", (d,))
        trows = cur.fetchall()
        turnover = float(trows[0][1]) if trows else 0.0
        turn_chg = turnover - float(trows[1][1]) if len(trows) > 1 else None
        cur.execute("""SELECT ts_code, (close-pre_close)/pre_close*100
            FROM md.bar_daily_raw WHERE trade_date=%s AND pre_close>0""", (d,))
        up = down = flat = lu = ld = 0
        for ts, pct in cur.fetchall():
            pct = float(pct)
            thr = _limit_threshold(ts)
            if pct >= thr:
                lu += 1
            elif pct <= -thr:
                ld += 1
            if pct > 0.05:
                up += 1
            elif pct < -0.05:
                down += 1
            else:
                flat += 1

        # 两融余额(常态 T-1;元→亿)
        cur.execute("""SELECT trade_date, sum(rzrqye) FROM md.margin_detail
            WHERE trade_date >= %s - 10 GROUP BY 1 ORDER BY 1 DESC LIMIT 2""", (d,))
        mrows = cur.fetchall()
        margin = None
        if mrows:
            prev = float(mrows[1][1]) if len(mrows) > 1 else None
            margin = {"date": str(mrows[0][0]), "balance": round(float(mrows[0][1]) / 1e8),
                      "chg": round((float(mrows[0][1]) - prev) / 1e8) if prev is not None else None}

        # 全A主力净额(万元→亿)
        cur.execute("SELECT max(trade_date) FROM md.moneyflow")
        mfd = cur.fetchone()[0]
        mf = None
        if mfd:
            cur.execute("""SELECT sum(buy_lg_amount-sell_lg_amount+buy_elg_amount-sell_elg_amount)
                FROM md.moneyflow WHERE trade_date=%s""", (mfd,))
            v = cur.fetchone()[0]
            if v is not None:
                mf = {"date": str(mfd), "main": round(float(v) / 1e4)}

    return {"trade_date": str(d), "indexes": idx,
            "breadth": {"up": up, "down": down, "flat": flat, "limit_up": lu, "limit_down": ld},
            "turnover": round(turnover), "turnover_chg": round(turn_chg) if turn_chg is not None else None,
            "margin": margin, "moneyflow": mf}


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
