"""台北侧:构建美股完整数据 blob → exports/us_YYYYMMDD.json。

美股一等公民、与 A股 同权:board(行情+基本面)/温度计/热力图(四象限)/
新闻(yfinance→B1 中文)/研究(分析师一致预期)/每日报告(B3)。
只台北跑(连 Yahoo)。用 .venv-taipei。铁律同 A股:B3 主线留白、只呈现不判断。
"""
from __future__ import annotations

import hashlib
import json
import re
import statistics as st
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from research_view import llm  # noqa: E402
from fetch_us_board import US_UNIVERSE, fetch as fetch_board  # noqa: E402
from fetch_tech_wire import fetch_wire  # noqa: E402

TZ = "Asia/Shanghai"


# ---------- 温度计 ----------
def _temperature(stocks: list[dict]) -> dict:
    pcts = [s["pct"] for s in stocks if s["pct"] is not None]
    up = sum(1 for p in pcts if p > 0.05)
    down = sum(1 for p in pcts if p < -0.05)
    flat = len(pcts) - up - down
    return {"counted": len(pcts), "up": up, "down": down, "flat": flat,
            "avg_pct": round(st.mean(pcts), 2) if pcts else 0.0}


# ---------- 热力图(四象限:X=6M动量, Y=营收同比, 气泡=市值, 色=PE)----------
def _heatmap(stocks: list[dict]) -> dict:
    by_sec: dict[str, list[dict]] = {}
    for s in stocks:
        by_sec.setdefault(s["sector"], []).append(s)

    def med(vals):
        vals = [v for v in vals if v is not None]
        return round(st.median(vals), 1) if vals else None

    # 输出与 A股 HeatNode 同款字段(node_id/chain/node/n_stocks/ret_6m/or_yoy/quadrant...),前端零改复用
    nodes = []
    for sec, items in by_sec.items():
        mv = sum(s["market_cap"] or 0 for s in items)
        nodes.append({"node_id": sec, "chain": "美股", "node": sec, "n_stocks": len(items),
                      "ret_1d": med([s["pct"] for s in items]),
                      "ret_1w": med([s["ret_1w"] for s in items]),
                      "ret_1m": med([s["ret_1m"] for s in items]),
                      "ret_3m": med([s["ret_3m"] for s in items]),
                      "ret_6m": med([s["ret_6m"] for s in items]),
                      "or_yoy": med([s["rev_growth"] for s in items]),
                      "total_mv": round(mv, 1) if mv else None,
                      "pe": med([s["pe"] for s in items]), "ps": None,
                      "gross_margin": med([s["gross_margin"] for s in items])})
    xs = [n["ret_6m"] for n in nodes if n["ret_6m"] is not None]
    ys = [n["or_yoy"] for n in nodes if n["or_yoy"] is not None]
    mx, my = (st.median(xs) if xs else 0), (st.median(ys) if ys else 0)
    for n in nodes:
        x, y = n["ret_6m"], n["or_yoy"]
        n["quadrant"] = "数据不足" if x is None or y is None else (
            "核心主线" if x >= mx and y >= my else
            "潜在补涨" if x >= mx else
            "等待验证" if y >= my else "风险区")
    hs = [{"code": s["ticker"], "name": s["name"], "total_mv": s["market_cap"], "pe": s["pe"], "ps": None,
           "ret_1d": s["pct"], "ret_1w": s["ret_1w"], "ret_1m": s["ret_1m"], "ret_3m": s["ret_3m"],
           "ret_6m": s["ret_6m"], "or_yoy": s["rev_growth"],
           "gross_margin": s["gross_margin"], "pe_pct": None, "node_ids": [s["sector"]]} for s in stocks]
    return {"nodes": nodes, "stocks": hs}


# ---------- 研究:分析师一致预期 ----------
def _research(stocks: list[dict]) -> list[dict]:
    out = []
    for s in stocks:
        if s.get("target_mean") and s.get("close"):
            upside = round((s["target_mean"] / s["close"] - 1) * 100, 1)
        else:
            upside = None
        if s.get("target_mean") or s.get("rec_key"):
            out.append({"code": s["ticker"], "name": s["name"], "sector": s["sector"],
                        "target_mean": s.get("target_mean"), "upside": upside,
                        "rec_key": s.get("rec_key"), "n_analysts": s.get("n_analysts"),
                        "pe": s.get("pe")})
    out.sort(key=lambda r: (r["upside"] is None, -(r["upside"] or 0)))
    return out


# ---------- 新闻:yfinance 聚合 → B1 中文批处理 ----------
def _fetch_news_raw(tickers: list[str]) -> list[dict]:
    seen, raw = set(), []
    for t in tickers:
        try:
            items = yf.Ticker(t).news or []
        except Exception:  # noqa: BLE001 单票新闻失败不阻塞
            continue
        for n in items:
            c = n.get("content", n)
            title = (c.get("title") if isinstance(c, dict) else None) or n.get("title")
            if not title or title in seen:
                continue
            seen.add(title)
            prov = c.get("provider") if isinstance(c, dict) else None
            src = prov.get("displayName") if isinstance(prov, dict) else n.get("publisher")
            url = None
            for k in ("canonicalUrl", "clickThroughUrl"):
                v = c.get(k) if isinstance(c, dict) else None
                if isinstance(v, dict) and v.get("url"):
                    url = v["url"]; break
            desc = ""
            for k in ("summary", "description"):
                v = c.get(k) if isinstance(c, dict) else None
                if v:
                    desc = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(v))).strip()[:600]
                    break
            raw.append({"title": title, "desc": desc, "src": src or "Yahoo", "url": url, "from_ticker": t})
    return raw[:45]  # 控量


B1_SYS = "你是金融信息整理器,不是分析师。只翻译+分类不下判断,严禁编造,输出严格JSON。"


def _b1_batch(raw: list[dict]) -> list[dict]:
    """一次调用把英文标题批量译为中文一句话+情绪。"""
    if not raw:
        return []
    listing = "\n".join(
        f"{i}. 标题:{r['title']}" + (f"\n   摘要:{r['desc']}" if r["desc"] else "") for i, r in enumerate(raw))
    user = f"""下面是美股科技新闻(英文标题+摘要,带序号)。逐条输出中文提炼,JSON:
{{"items":[{{"i":序号,"one_line":"中文一句话概括≤40字","summary":"中文核心观点:基于标题和摘要挑2-3个重点/关键数字,≤120字,不看原文就懂;没摘要则据标题合理概括;只陈述不判断","sentiment":"利好|利空|中性|澄清"}}]}}
{listing}
只翻译概括,不许出现"看好/利好X/建议买入"等判断词,不许编造摘要没有的数字。"""
    try:
        j = llm.chat_json(B1_SYS, user, timeout=150)
        m = {int(it["i"]): it for it in j.get("items", []) if "i" in it}
    except Exception as e:  # noqa: BLE001 B1失败降级:用原标题
        print(f"  ! 新闻B1失败,降级原标题: {str(e)[:80]}")
        m = {}
    sec_of = {t: s for t, _, s in US_UNIVERSE}
    out = []
    for i, r in enumerate(raw):
        b = m.get(i, {})
        out.append({"title": r["title"], "one_line": b.get("one_line") or r["title"],
                    "summary": (b.get("summary") or "")[:280] or None,
                    "sentiment": b.get("sentiment") or "中性", "src": r["src"], "url": r["url"],
                    "sector": sec_of.get(r["from_ticker"], "科技"), "ticker": r["from_ticker"]})
    return out


# ---------- 全球科技舆情:西媒+社交源 → B1 中文化 ----------
def _b1_wire_chunk(raw: list[dict]) -> dict:
    """单批(≤~45条)调 DeepSeek 中文化,返回 {序号: 提炼}。失败返回空(降级原标题)。"""
    listing = "\n".join(
        f"{i}. [{r['group']}] 标题:{r['title']}" + (f"\n   摘要:{r['desc']}" if r["desc"] else "")
        for i, r in enumerate(raw))
    user = f"""下面是西方媒体/Reddit/推特X 的条目(带序号+来源分组,中英混合;Reddit/X 可能已是中文)。逐条中文提炼,JSON:
{{"items":[{{"i":序号,"one_line":"中文一句话概括≤40字,已是中文则精简","summary":"中文核心:据标题/摘要挑1-2个重点,≤80字,不看原文就懂;只陈述不判断","sentiment":"利好|利空|中性|澄清"}}]}}
{listing}
只翻译概括,不许出现"看好/建议买入"等判断词,不许编造原文没有的数字。Reddit/推特X 是个人观点,如实转述不背书。"""
    try:
        j = llm.chat_json(B1_SYS, user, timeout=150)
        return {int(it["i"]): it for it in j.get("items", []) if "i" in it}
    except Exception as e:  # noqa: BLE001 单批失败降级:用原标题
        print(f"  ! 舆情B1失败,降级原标题: {str(e)[:80]}")
        return {}


def _b1_wire(raw: list[dict], batch: int = 40) -> list[dict]:
    """西媒+社交源批量中文化。分批调用(条数多时避免单次 JSON 过大截断)。"""
    if not raw:
        return []
    out = []
    for s in range(0, len(raw), batch):
        chunk = raw[s:s + batch]
        m = _b1_wire_chunk(chunk)
        for i, r in enumerate(chunk):
            b = m.get(i, {})
            out.append({"title": r["title"], "one_line": b.get("one_line") or r["title"],
                        "summary": (b.get("summary") or "")[:200] or None,
                        "sentiment": b.get("sentiment") or "中性",
                        "src": r["src"], "group": r["group"], "url": r["url"],
                        **({"weight": r["weight"]} if "weight" in r else {})})
    return out


# ---------- 走势小图:6M 日线收盘 ----------
def _trends(tickers: list[str]) -> dict:
    """批量拉 6 个月日线收盘 → {ticker: [[YYYYMMDD, close], ...]}。供个股详情走势小图。"""
    try:
        data = yf.download(tickers, period="6mo", interval="1d", progress=False,
                           group_by="ticker", auto_adjust=True, threads=True)
    except Exception as e:  # noqa: BLE001 走势拉取失败不阻塞整个 blob
        print(f"  ! 美股走势拉取失败: {str(e)[:80]}")
        return {}
    out: dict[str, list] = {}
    multi = len(tickers) > 1
    for t in tickers:
        try:
            closes = (data[t]["Close"] if multi else data["Close"]).dropna()
        except Exception:  # noqa: BLE001 单票缺失跳过
            continue
        series = [[d.strftime("%Y%m%d"), round(float(v), 2)] for d, v in closes.items()]
        if series:
            out[t] = series
    return out


# ---------- 每日报告 B3 ----------
B3_SYS = """你是投研信息整理器,为关注美股AI科技的投资者服务。只呈现变化,不做投资判断。
铁律:每个事实带来源[来源:xxx];headline.fact 中性事实陈述,user_judgment 永远填"<待填>";
只用提供数据不外部补充;证伪条件具体可1-2周验证。输出严格JSON。"""


def _report(stocks: list[dict], news: list[dict], wire: list[dict], us_date: str) -> dict:
    movers = sorted([s for s in stocks if s["pct"] is not None], key=lambda s: s["pct"])
    top_dn = movers[:5]
    top_up = movers[-5:][::-1]
    mv_lines = [f"- {s['name']}({s['ticker']}) {s['pct']:+.2f}% [板块:{s['sector']}]"
                for s in top_up + top_dn]
    news_lines = [f"- [{n['sector']}] {n['one_line']}(情绪:{n['sentiment']},来源:{n['src']})"
                  for n in news[:30]]
    # 舆情高信号:权威媒体优先,外加重点 X 号(serenity,weight2)作情绪信号;Reddit 不喂报告
    auth = [w for w in wire if w["group"] in ("华尔街日报", "路透社", "科技媒体")][:12]
    key_x = [w for w in wire if w["group"] == "推特X" and w.get("weight", 1) >= 2][:4]
    wire_lines = [f"- [{w['group']}] {w['one_line']}(来源:{w['src']})" for w in auth + key_x]
    block = ("【今日美股科技涨跌(前5涨/前5跌)】\n" + "\n".join(mv_lines) +
             "\n\n【美股科技新闻】\n" + ("\n".join(news_lines) or "(无)") +
             "\n\n【全球科技舆情(西方媒体)】\n" + ("\n".join(wire_lines) or "(无)"))
    user = f"""【数据截止 美东 {us_date} 收盘】
{block}

输出JSON(美股盘后,呈现"美股AI科技今天发生了什么、哪些方向强弱"):
{{
  "data_cutoff": "美东 {us_date} 收盘",
  "session": "us",
  "headline": {{"fact":"基于上述数据的中性事实陈述,不带倾向","user_judgment":"<待填>","confidence":"高|中|低"}},
  "top3": [{{"change":"变化描述","evidence":"[来源:xxx]","node_ids":[],"related_stocks":[]}}],
  "sectors": [{{"chain":"半导体","status":"一句状态[来源]"}}],
  "falsification": [{{"claim":"可证伪观察","condition":"1-2周内可验证条件","draft_by":"deepseek"}}]
}}
只用上面数据,top3 选今天最值得注意的3个变化。"""
    try:
        return llm.chat_json(B3_SYS, user, timeout=120)
    except Exception as e:  # noqa: BLE001 报告失败不阻塞整个blob
        print(f"  ! 美股B3报告失败: {str(e)[:80]}")
        return None


def main() -> None:
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.now(ZoneInfo(TZ)).strftime("%Y%m%d")
    print("[build_us] 拉美股行情+基本面 ...")
    board = fetch_board()
    stocks = [s for s in board["items"] if not s["ticker"].startswith("^")]
    idx = [s for s in board["items"] if s["ticker"].startswith("^")]
    us_date = board["us_session_date"]

    print("[build_us] 拉美股新闻 + B1 中文 ...")
    news = _b1_batch(_fetch_news_raw([t for t, _, _ in US_UNIVERSE]))
    print(f"  新闻 {len(news)} 条")

    print("[build_us] 拉全球科技舆情(WSJ/路透/科技媒体/Reddit)+ B1 中文 ...")
    wire = _b1_wire(fetch_wire())
    print(f"  舆情 {len(wire)} 条")

    print("[build_us] 合成美股报告 B3 ...")
    report = _report(stocks, news, wire, us_date)

    print("[build_us] 拉美股 6M 走势 ...")
    trends = _trends([t for t, _, _ in US_UNIVERSE])
    print(f"  走势 {len(trends)} 只")

    us = {
        "us_session_date": us_date,
        "board": {"items": board["items"], "n_ok": board["n_ok"]},
        "temperature": _temperature(stocks),
        "heatmap": _heatmap(stocks),
        "research": _research(stocks),
        "news": news,
        "wire": wire,
        "report": report,
        "trends": trends,
        "indices": idx,
        "fetched_at": datetime.now(ZoneInfo(TZ)).isoformat(),
    }
    d = ROOT / "exports"
    d.mkdir(exist_ok=True)
    p = d / f"us_{date}.json"
    p.write_text(json.dumps(us, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[build_us] {p}  (股{len(stocks)} 新闻{len(news)} 舆情{len(wire)} 报告{'有' if report else '无'})")


if __name__ == "__main__":
    main()
