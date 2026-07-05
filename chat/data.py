"""数据层:读 webdata JSON(mtime 缓存),给路由器出目录,按选片结果切数据。

原则:大 section(news_by_node/heatmap/us/trends)必须过滤,小 section 整段给;
纯统计(个股时序涨幅/高低点)在这里用代码算好,不让 LLM 数数。
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))

_lock = threading.Lock()
_cache: dict[str, tuple[float, dict]] = {}  # name -> (mtime, obj)


def _load(name: str) -> dict:
    """带 mtime 缓存的 JSON 读取(阿里云每日同步覆盖文件,mtime 变了就重读)。"""
    p = DATA_DIR / name
    mt = p.stat().st_mtime
    with _lock:
        hit = _cache.get(name)
        if hit and hit[0] == mt:
            return hit[1]
    obj = json.loads(p.read_text(encoding="utf-8"))
    with _lock:
        _cache[name] = (mt, obj)
    return obj


def dashboard() -> dict:
    return _load("dashboard.json")


def trends() -> dict:
    return _load("trends.json")


# ---------- 路由器目录 ----------

SECTION_DESC = {
    "report": "每日收盘研判报告(头条/前三变化/证伪追踪/持仓动向)",
    "market": "A股大盘(指数/成交额/两融/大盘主力资金及近20日走势)",
    "temperature": "今日池内温度(涨跌/涨停跌停家数/均涨幅)",
    "judgment": "产业链节点级研判卡(方向/信心/论据/证伪条件)",
    "decision": "个股级决策卡(方向/买卖点/论据)",
    "scorecard": "研判成绩单(命中率/分方向分来源/周复盘)",
    "ledger": "研判台账汇总(存活/证伪计数)",
    "news_by_node": "按产业链节点分组的A股新闻(标题/摘要/情绪),需按节点或个股过滤",
    "stock_events": "个股事件日历(解禁/业绩预告/股东大会等)",
    "heatmap": "产业链热力(节点与个股的1日/1周/1月/3月/6月涨幅、PE/PS/市值/象限)",
    "moneyflow": "主力资金流(节点当日/5日/20日净流入、个股主力净额、盘中分时)",
    "hotspot": "今日热点排名与归因",
    "research": "券商研报(评级/目标价)+基金信函+研究摘要",
    "us": "美股科技看板(个股行情/新闻/X舆情/研报/板块热力)",
    "trends": "个股收盘价历史时序(近半年,统计已由代码算好),需给出个股代码",
}


def catalog() -> str:
    """给路由器看的:可选 section + 全部节点 id + 个股代码索引。"""
    d = dashboard()
    lines = ["【可选数据块】"]
    lines += [f"- {k}: {v}" for k, v in SECTION_DESC.items()]
    lines.append("\n【A股产业链节点 node_id】")
    lines.append("、".join(n["node_id"] for n in d.get("heatmap", {}).get("nodes", [])))
    lines.append("\n【美股板块】")
    us_secs = sorted({i.get("sector", "") for i in d.get("us", {}).get("board", {}).get("items", [])} - {""})
    lines.append("、".join(us_secs))
    lines.append("\n【A股个股 代码=名称】")
    lines.append(" ".join(f"{s['code']}={s['name']}" for s in d.get("heatmap", {}).get("stocks", [])))
    lines.append("\n【美股个股 代码=名称】")
    lines.append(" ".join(f"{i['ticker']}={i['name']}" for i in d.get("us", {}).get("board", {}).get("items", [])))
    return "\n".join(lines)


# ---------- 切片 ----------

def _stock_names() -> dict[str, str]:
    d = dashboard()
    m = {s["code"]: s["name"] for s in d.get("heatmap", {}).get("stocks", [])}
    m |= {i["ticker"]: i["name"] for i in d.get("us", {}).get("board", {}).get("items", [])}
    return m


def _pct(a: float, b: float) -> float | None:
    return round((b - a) / a * 100, 2) if a else None


def _trend_stats(code: str, series: list) -> dict:
    """时序统计代码算好:近1周/1月/3月/半年涨幅、高低点、周采样序列。"""
    if not series:
        return {"code": code, "error": "无数据"}
    closes = [c for _, c in series]
    last_d, last = series[-1]
    out = {
        "code": code, "name": _stock_names().get(code, ""),
        "last_date": last_d, "last_close": last,
        "ret_1w_pct": _pct(closes[-6], last) if len(closes) > 5 else None,
        "ret_1m_pct": _pct(closes[-21], last) if len(closes) > 20 else None,
        "ret_3m_pct": _pct(closes[-61], last) if len(closes) > 60 else None,
        "ret_range_pct": _pct(closes[0], last),
        "range_from": series[0][0],
        "high": max(closes), "high_date": series[max(range(len(closes)), key=closes.__getitem__)][0],
        "low": min(closes), "low_date": series[min(range(len(closes)), key=closes.__getitem__)][0],
        "weekly_series": series[::-5][::-1],  # 从最新往回每5日取一点,保证含最新日
    }
    return out


def _slice_news(d: dict, node_ids: set[str], codes: set[str]) -> list:
    """新闻:按节点/个股过滤;没给过滤条件则每节点只留2条一句话做全景。"""
    groups = d.get("news_by_node", [])
    if node_ids or codes:
        out = []
        for g in groups:
            hit = g["node_id"] in node_ids or any(codes & set(it.get("codes", [])) for it in g["items"])
            if hit:
                out.append({**g, "items": g["items"][:6]})
        return out
    return [{"node_id": g["node_id"],
             "brief": [it.get("one_line") or it.get("title") for it in g["items"][:2]]} for g in groups]


def _slice_heatmap(d: dict, node_ids: set[str], codes: set[str]) -> dict:
    h = d.get("heatmap", {})
    stocks = h.get("stocks", [])
    if node_ids or codes:
        stocks = [s for s in stocks if s["code"] in codes or (node_ids & set(s.get("node_ids", [])))]
    return {"nodes": h.get("nodes", []), "stocks": stocks[:80]}


def _slice_moneyflow(d: dict, node_ids: set[str], codes: set[str]) -> dict:
    mf = d.get("moneyflow", {})
    intraday = mf.get("intraday") or {}
    series = intraday.get("series", [])
    if node_ids:
        series = [s for s in series if s["node_id"] in node_ids]
    else:
        series = sorted(series, key=lambda s: abs(s.get("last") or 0), reverse=True)[:10]
    return {
        "date": mf.get("date"), "kind": mf.get("kind"), "pool_main_yi": mf.get("pool_main"),
        "nodes": mf.get("nodes", []), "multi": mf.get("multi"),
        "intraday": {"times": intraday.get("times"), "series": series},
        "stocks_main_yi": {c: v for c, v in (mf.get("stocks") or {}).items() if not codes or c in codes} or None,
    }


def _slice_research(d: dict, node_ids: set[str], codes: set[str]) -> dict:
    r = d.get("research", {})
    reports = r.get("reports", [])
    if node_ids or codes:
        reports = [x for x in reports if x.get("code") in codes or (node_ids & set(x.get("node_ids") or []))]
    return {**r, "reports": reports[:40]}


def _slice_us(d: dict, node_ids: set[str], codes: set[str]) -> dict:
    us = d.get("us", {})
    news = us.get("news", [])
    if node_ids or codes:
        news = [n for n in news if n.get("sector") in node_ids or n.get("ticker") in codes]
    news = [{k: n.get(k) for k in ("ticker", "sector", "one_line", "sentiment", "time")} for n in news[:40]]
    return {
        "us_session_date": us.get("us_session_date"), "session_status": us.get("session_status"),
        "temperature": us.get("temperature"), "board": us.get("board"),
        "heatmap_nodes": (us.get("heatmap") or {}).get("nodes"),
        "news": news, "research": us.get("research"),
        "wire": [{k: w.get(k) for k in ("group", "author", "one_line", "time")} for w in (us.get("wire") or [])[:30]],
    }


BUDGET = int(os.environ.get("CHAT_SLICE_BUDGET", "150000"))  # 字符预算,约合几万token


def build_slices(sections: list[str], node_ids: list[str], codes: list[str]) -> dict:
    """按路由结果组装数据切片,超预算按加入顺序截断(前面的优先级高)。"""
    d = dashboard()
    nid, cd = set(node_ids or []), set(codes or [])
    whole = {"meta", "report", "market", "temperature", "judgment", "decision",
             "scorecard", "ledger", "hotspot", "stock_events", "health"}
    out: dict = {"meta": d.get("meta")}
    used = 0
    for sec in dict.fromkeys(sections):  # 去重保序
        if sec == "trends":
            t = trends()
            pool = {**t.get("a", {}), **t.get("us", {})}
            want = [c for c in cd if c in pool][:12] or []
            piece = {"trends_stats": [_trend_stats(c, pool[c]) for c in want]} if want else \
                {"trends_stats": "未指定有效个股代码,无时序"}
        elif sec == "news_by_node":
            piece = {"news_by_node": _slice_news(d, nid, cd)}
        elif sec == "heatmap":
            piece = {"heatmap": _slice_heatmap(d, nid, cd)}
        elif sec == "moneyflow":
            piece = {"moneyflow": _slice_moneyflow(d, nid, cd)}
        elif sec == "research":
            piece = {"research": _slice_research(d, nid, cd)}
        elif sec == "us":
            piece = {"us": _slice_us(d, nid, cd)}
        elif sec in whole and sec in d:
            piece = {sec: d[sec]}
        else:
            continue
        n = len(json.dumps(piece, ensure_ascii=False))
        if used + n > BUDGET:
            out["_truncated"] = f"数据预算已满,略去 {sec} 及之后的块"
            break
        out.update(piece)
        used += n
    return out
