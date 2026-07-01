"""个股事件采集:读 marketdata 结构化公告 + 龙虎榜,写 research_view.stock_event。零 LLM。

marketdata 只读(rv_rw 在 DB 层无写权限)。方向(direction)是基于事实的客观标注,非投资判断。
"""
from __future__ import annotations

import hashlib
import json

from .. import db

# 业绩预告类型 → 事实方向
_FORECAST_DIR = {
    "预增": "利好", "略增": "利好", "扭亏": "利好", "续盈": "利好", "减亏": "利好",
    "预减": "利空", "略减": "利空", "首亏": "利空", "续亏": "利空", "不确定": "中性",
}


def _eid(*parts) -> str:
    return "e:" + hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:20]


def _maps(cur):
    cur.execute("SELECT ts_code, code FROM stock WHERE ts_code IS NOT NULL")
    ts2code = dict(cur.fetchall())
    cur.execute("SELECT code, array_agg(node_id) FROM stock_node GROUP BY code")
    code2nodes = dict(cur.fetchall())
    return ts2code, code2nodes


def collect_events(days: int = 120) -> dict[str, int]:
    # 池子 ts_code
    with db.rv_conn() as conn, conn.cursor() as cur:
        ts2code, code2nodes = _maps(cur)
    pool_ts = list(ts2code.keys())

    rows: list[tuple] = []

    def add(ts_code, etype, direction, edate, summary, detail, key):
        # event_id 用稳定自然键(etype|ts|date|key),与 summary 文案无关,避免改文案生成重复行
        code = ts2code.get(ts_code)
        nodes = code2nodes.get(code, []) if code else []
        rows.append((_eid(etype, ts_code, edate, key), code, ts_code, nodes,
                     etype, direction, edate, summary, json.dumps(detail, ensure_ascii=False, default=str)))

    with db.marketdata_conn() as mc, mc.cursor() as cur:
        # 业绩预告(ann_date 为 DATE 类型,直接按日期比较)
        cur.execute("""SELECT ts_code,ann_date,type,p_change_min,p_change_max,change_reason
            FROM md.forecast WHERE ts_code = ANY(%s)
            AND ann_date >= current_date - %s""", (pool_ts, days))
        for ts, ann, typ, pmin, pmax, reason in cur.fetchall():
            rng = f"{pmin}~{pmax}%" if pmin is not None else ""
            add(ts, "业绩预告", _FORECAST_DIR.get(typ, "中性"), ann,
                f"业绩预告·{typ} 净利变动{rng}".strip("·"), {"type": typ, "reason": reason}, key=str(typ))

        # 业绩快报
        cur.execute("""SELECT ts_code,ann_date,yoy_net_profit,perf_summary
            FROM md.express WHERE ts_code = ANY(%s)
            AND ann_date >= current_date - %s""", (pool_ts, days))
        for ts, ann, yoy, summ in cur.fetchall():
            d = "利好" if (yoy or 0) > 0 else "利空" if (yoy or 0) < 0 else "中性"
            add(ts, "业绩快报", d, ann, f"业绩快报·净利同比{yoy}%", {"perf_summary": summ}, key="express")

        # 增减持
        cur.execute("""SELECT ts_code,ann_date,holder_name,in_de,change_ratio
            FROM md.holder_trade WHERE ts_code = ANY(%s)
            AND ann_date >= current_date - %s""", (pool_ts, min(days, 60)))
        for ts, ann, holder, inde, ratio in cur.fetchall():
            act = "增持" if inde == "IN" else "减持"
            add(ts, "增减持", "利好" if inde == "IN" else "利空", ann,
                f"{holder or ''} {act} {ratio}%".strip(), {"in_de": inde},
                key=f"{holder}|{inde}|{ratio}")

        # 解禁(未来日历)
        cur.execute("""SELECT ts_code,float_date,float_ratio,share_type
            FROM md.share_float WHERE ts_code = ANY(%s)
            AND float_date >= current_date
            AND float_date <= current_date + 60""", (pool_ts,))
        for ts, fdate, ratio, stype in cur.fetchall():
            add(ts, "解禁", "中性", fdate, f"解禁 {ratio}% ({stype or ''})".strip(), {},
                key=f"{ratio}|{stype}")

        # 龙虎榜(最新交易日)
        cur.execute("SELECT max(trade_date) FROM md.top_list")
        latest = cur.fetchone()[0]
        cur.execute("""SELECT ts_code,trade_date,reason,net_amount,pct_change
            FROM md.top_list WHERE ts_code = ANY(%s) AND trade_date = %s""", (pool_ts, latest))
        for ts, td, reason, net, pct in cur.fetchall():
            net = float(net) if net is not None else 0.0
            d = "利好" if net > 0 else "利空" if net < 0 else "中性"
            net_yi = round(net / 1e8, 2)  # net_amount 单位为元,换算成亿
            add(ts, "龙虎榜", d, td, f"龙虎榜·{reason or ''} 净额{net_yi}亿".strip(), {"pct": pct, "net": net},
                key=str(reason))

    if not rows:
        return {"events": 0}
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO stock_event(event_id,code,ts_code,node_ids,event_type,direction,
               event_date,summary,detail) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
               ON CONFLICT(event_id) DO UPDATE SET summary=EXCLUDED.summary,direction=EXCLUDED.direction""",
            rows,
        )
    return {"events": len(rows)}
