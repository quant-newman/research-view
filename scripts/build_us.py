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
from fetch_tech_wire import fetch_wire, _norm_time  # noqa: E402

TZ = "Asia/Shanghai"
ET = "America/New_York"


def _us_session() -> dict:
    """美东盘中/收盘判定(常规时段 09:30-16:00 工作日)。盘中刷新时 yfinance 最后一根
    日线是实时临时 bar,涨跌为实时数据 → 标签/报告口径必须跟着标"盘中"而非"收盘"。"""
    now = datetime.now(ZoneInfo(ET))
    live = now.weekday() < 5 and (9, 30) <= (now.hour, now.minute) < (16, 0)
    return {"live": live, "status": "盘中" if live else "收盘", "et_hhmm": now.strftime("%H:%M")}


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
    """每票最多 3 条,广度优先轮转:先收每票第1条、再第2/3条,到 60 封顶——
    否则 universe 前几只票把总名额吃光,云/软件/中概板块永远没新闻。"""
    seen: set[str] = set()
    per_ticker: dict[str, list[dict]] = {}
    for t in tickers:
        try:
            items = yf.Ticker(t).news or []
        except Exception:  # noqa: BLE001 单票新闻失败不阻塞
            continue
        bucket = per_ticker.setdefault(t, [])
        for n in items:
            if len(bucket) >= 3:
                break
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
            # 发布时间:新格式 pubDate(ISO 串),旧格式 providerPublishTime(unix)
            tm = ""
            pd = c.get("pubDate") or c.get("displayTime") if isinstance(c, dict) else None
            if pd:
                tm = _norm_time(str(pd))
            elif n.get("providerPublishTime"):
                try:
                    from datetime import datetime, timezone
                    from zoneinfo import ZoneInfo
                    tm = datetime.fromtimestamp(int(n["providerPublishTime"]), timezone.utc)\
                        .astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")
                except Exception:  # noqa: BLE001
                    tm = ""
            bucket.append({"title": title, "desc": desc, "src": src or "Yahoo", "url": url,
                           "from_ticker": t, "time": tm})
    raw = []
    for rnd in range(3):  # 轮转:所有票的第 rnd 条
        for t in tickers:
            b = per_ticker.get(t) or []
            if rnd < len(b):
                raw.append(b[rnd])
    return raw[:60]  # 控量


B1_SYS = "你是金融信息整理器,不是分析师。只翻译+分类不下判断,严禁编造,输出严格JSON。"


def _b1_news_chunk(raw: list[dict]) -> dict[int, dict]:
    """单批(≤~35条)英文标题译中文一句话+情绪,返回 {序号: 提炼}。失败返回空(降级原标题)。"""
    listing = "\n".join(
        f"{i}. 标题:{r['title']}" + (f"\n   摘要:{r['desc']}" if r["desc"] else "") for i, r in enumerate(raw))
    user = f"""下面是美股科技新闻(英文标题+摘要,带序号)。逐条输出中文提炼,JSON:
{{"items":[{{"i":序号,"one_line":"中文一句话概括≤40字","summary":"中文核心观点:基于标题和摘要挑2-3个重点/关键数字,≤120字,不看原文就懂;没摘要则据标题合理概括;只陈述不判断","sentiment":"利好|利空|中性|澄清"}}]}}
{listing}
只翻译概括,不许出现"看好/利好X/建议买入"等判断词,不许编造摘要没有的数字。"""
    try:
        j = llm.chat_json(B1_SYS, user, timeout=150)
        return {int(it["i"]): it for it in j.get("items", []) if "i" in it}
    except Exception as e:  # noqa: BLE001 B1失败降级:用原标题
        print(f"  ! 新闻B1失败,降级原标题: {str(e)[:80]}")
        return {}


def _b1_batch(raw: list[dict], batch: int = 35) -> list[dict]:
    """新闻批量中文化。分批调用(60条单次输出 JSON 会过长截断)。"""
    if not raw:
        return []
    sec_of = {t: s for t, _, s in US_UNIVERSE}
    out = []
    for s in range(0, len(raw), batch):
        chunk = raw[s:s + batch]
        m = _b1_news_chunk(chunk)
        for i, r in enumerate(chunk):
            b = m.get(i, {})
            out.append({"title": r["title"], "one_line": b.get("one_line") or r["title"],
                        "summary": (b.get("summary") or "")[:280] or None,
                        "sentiment": b.get("sentiment") or "中性", "src": r["src"], "url": r["url"],
                        "sector": sec_of.get(r["from_ticker"], "科技"), "ticker": r["from_ticker"],
                        "time": r.get("time", "")})
    return out


# ---------- 全球科技舆情:西媒+社交源 → B1 中文化 ----------
def _b1_wire_chunk(raw: list[dict]) -> dict:
    """单批(≤~45条)调 DeepSeek 中文化,返回 {序号: 提炼}。失败返回空(降级原标题)。"""
    listing = "\n".join(
        f"{i}. [{r['group']}] 标题:{r['title']}" + (f"\n   摘要:{r['desc']}" if r["desc"] else "")
        for i, r in enumerate(raw))
    user = f"""下面是西方媒体/Reddit/推特X 的条目(带序号+来源分组,中英混合;Reddit/X 可能已是中文)。逐条中文提炼,JSON:
{{"items":[{{"i":序号,"one_line":"中文一句话概括≤40字,已是中文则精简","summary":"中文核心:据标题/摘要挑1-2个重点,≤80字,不看原文就懂;只陈述不判断","sentiment":"利好|利空|中性|澄清","market":"A股|美股|其他"}}]}}
{listing}
market 判断:主要讲 A股上市公司/A股板块/中国境内市场→"A股";讲美股/美国科技公司/全球AI→"美股";都不明确→"其他"。
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
            mk = b.get("market")
            out.append({"title": r["title"], "one_line": b.get("one_line") or r["title"],
                        "summary": (b.get("summary") or "")[:200] or None,
                        "sentiment": b.get("sentiment") or "中性",
                        "src": r["src"], "group": r["group"], "url": r["url"],
                        "time": r.get("time", ""),
                        "market": mk if mk in ("A股", "美股", "其他") else "其他",
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


# ---------- 今日热点(DeepSeek 版,口径同 A股 hotspots.py)----------
HOT_SYS = (
    "你是投研信息整理器,不是分析师。基于给定的统计信号和新闻,综合'今天美股科技在炒什么主题',"
    "只陈述事实、不下判断、不出买卖建议。输出严格 JSON。"
)


def _prior_news_counts(date: str) -> dict[str, int]:
    """上一交易日 us blob 的每板块新闻数(供升温/降温对比)。找不到/损坏返回空。"""
    prior = None
    for p in sorted((ROOT / "exports").glob("us_*.json")):
        d = p.stem[3:]
        if len(d) == 8 and d.isdigit() and d < date:
            prior = p
    if prior is None:
        return {}
    try:
        blob = json.loads(prior.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 旧文件损坏不阻塞
        return {}
    counts: dict[str, int] = {}
    for n in blob.get("news") or []:
        sec = n.get("sector")
        if sec:
            counts[sec] = counts.get(sec, 0) + 1
    return counts


def _hotspot(stocks: list[dict], news: list[dict], nodes: list[dict], date: str) -> dict | None:
    """美股今日热点:统计信号(板块新闻量/情绪+板块涨跌+个股异动)算热度选 Top →
    DeepSeek 中性归因+升温降温。铁律同 A股:热度统计的、归因提炼的,不下判断。
    US 无龙虎榜,lhb 恒 0;大跌也是热点故涨跌取绝对值计热度。"""
    prior_counts = _prior_news_counts(date)
    ret1d = {n["node"]: n["ret_1d"] for n in nodes}
    sec_stocks: dict[str, list[dict]] = {}
    for s in stocks:
        sec_stocks.setdefault(s["sector"], []).append(s)
    by_sec: dict[str, dict] = {}
    for n in news:
        b = by_sec.setdefault(n["sector"], {"news": [], "today": 0, "pos": 0, "neg": 0, "latest": ""})
        b["today"] += 1
        if n["sentiment"] == "利好":
            b["pos"] += 1
        elif n["sentiment"] == "利空":
            b["neg"] += 1
        if (n.get("time") or "") > b["latest"]:
            b["latest"] = n["time"]
        if len(b["news"]) < 3:
            b["news"].append(n.get("summary") or n["one_line"])
    rows, movers_of = [], {}
    for sec, b in by_sec.items():
        r1 = ret1d.get(sec)
        movers = sorted((s for s in sec_stocks.get(sec, []) if s["pct"] is not None),
                        key=lambda s: -abs(s["pct"]))
        movers_of[sec] = movers
        prior = prior_counts.get(sec)
        rows.append({"node_id": sec, "chain": "美股", "node": sec,
                     "heat": round(b["today"] * 1.0 + abs(r1 or 0) * 0.3, 1),
                     "trend": ("持平" if prior is None else
                               "升温" if b["today"] > prior else
                               "降温" if b["today"] < prior else "持平"),
                     "news_today": b["today"], "news_prior": prior,
                     "pos": b["pos"], "neg": b["neg"], "ret_1d": r1, "lhb": 0,
                     "latest_time": b["latest"],
                     "stocks": [s["name"] for s in movers[:5]], "news": b["news"]})
    rows.sort(key=lambda x: -x["heat"])
    rows = rows[:10]
    if not rows:
        return None

    blocks = []
    for i, r in enumerate(rows):
        mv = "、".join(f"{s['name']}{s['pct']:+.1f}%" for s in movers_of[r["node"]][:3])
        prior_txt = f"(昨日{r['news_prior']})" if r["news_prior"] is not None else ""
        nl = "；".join(r["news"]) if r["news"] else "(无当日新闻)"
        blocks.append(
            f"{i}. 【{r['node']}】热度{r['heat']} | 今日新闻{r['news_today']}条{prior_txt}"
            f" 利好{r['pos']}/利空{r['neg']} | 板块今日涨跌{r['ret_1d']}%"
            f" | 异动个股:{mv or '(无)'} | 新闻:{nl}")
    user = f"""下面是今日美股科技各板块的统计热度信号(已按热度排序)。请综合成"今日热点榜",JSON:
{{
  "headline": "一句话总览今天美股科技在炒哪些主题(中性事实,如'资金聚焦光模块业绩与算力芯片新品'),≤50字",
  "items": [
    {{"node_id":"照抄输入的板块名","reason":"该板块为什么热的中性归因,必须基于给的信号/新闻(带具体数字/个股),≤50字","trend":"升温|降温|持平"}}
  ]
}}
规则:items 顺序与条数尽量对应输入(可略去信号极弱的);reason 只陈述事实,禁止"看好/建议买入/值得关注"等判断词;trend 参考输入里"今日vs昨日新闻数"。
【信号】
{chr(10).join(blocks)}"""
    try:
        j = llm.chat_json(HOT_SYS, user, timeout=120)
    except Exception as e:  # noqa: BLE001 综述失败降级:用统计信号直接出榜
        print(f"  ! 美股热点综述失败,降级统计榜: {str(e)[:80]}")
        j = {"headline": "今日美股科技热度(统计榜)", "items": []}
    by_node = {str(it.get("node_id")): it for it in j.get("items", []) if it.get("node_id")}
    items = []
    for r in rows:
        d = by_node.get(r["node_id"]) or by_node.get(f"美股/{r['node_id']}") or {}
        items.append({**r, "reason": d.get("reason") or f"今日{r['news_today']}条相关新闻",
                      "trend": d.get("trend") or r["trend"]})
    return {"headline": j.get("headline") or "今日美股科技主题热度", "items": items}


# ---------- 每日报告 B3 ----------
B3_SYS = """你是投研信息整理器,为关注美股AI科技的投资者服务。只呈现变化,不做投资判断。
铁律:每个事实带来源[来源:xxx];headline.fact 中性事实陈述,user_judgment 永远填"<待填>";
只用提供数据不外部补充;证伪条件具体可1-2周验证。输出严格JSON。"""


def _report(stocks: list[dict], news: list[dict], wire: list[dict], us_date: str,
            session: dict) -> dict:
    movers = sorted([s for s in stocks if s["pct"] is not None], key=lambda s: s["pct"])
    top_dn = movers[:5]
    top_up = movers[-5:][::-1]
    mv_lines = [f"- {s['name']}({s['ticker']}) {s['pct']:+.2f}% [板块:{s['sector']}]"
                for s in top_up + top_dn]
    news_lines = [f"- [{n['sector']}] {n['one_line']}(情绪:{n['sentiment']},来源:{n['src']})"
                  for n in news[:30]]
    # 舆情高信号:权威媒体优先喂报告;Reddit 不喂
    auth = [w for w in wire if w["group"] in ("华尔街日报", "路透社", "科技媒体")][:12]
    wire_lines = [f"- [{w['group']}] {w['one_line']}(来源:{w['src']})" for w in auth]
    # 推特X 按 market 拆分(重点号 serenity 优先),给报告统一总结
    x_all = [w for w in wire if w["group"] == "推特X"]
    x_all.sort(key=lambda w: -w.get("weight", 1))
    x_us = [w for w in x_all if w.get("market") != "A股"][:12]
    x_a = [w for w in x_all if w.get("market") == "A股"][:12]
    xl = lambda ws: "\n".join(f"- {w['src']}{'(重点)' if w.get('weight',1)>=2 else ''}:{w['one_line']}" for w in ws)
    block = ("【今日美股科技涨跌(前5涨/前5跌)】\n" + "\n".join(mv_lines) +
             "\n\n【美股科技新闻】\n" + ("\n".join(news_lines) or "(无)") +
             "\n\n【全球科技舆情(西方媒体)】\n" + ("\n".join(wire_lines) or "(无)") +
             "\n\n【推特X·美股/全球观点(个人观点,serenity权重最高)】\n" + (xl(x_us) or "(无)") +
             "\n\n【推特X·A股相关观点】\n" + (xl(x_a) or "(无)"))
    # 盘中刷新:涨跌为实时数据,口径必须标"盘中截至此刻"不能说"收盘"
    cutoff = (f"美东 {us_date} 盘中 {session['et_hhmm']}" if session["live"]
              else f"美东 {us_date} 收盘")
    view = ("美股盘中,涨跌为截至此刻的实时数据,表述用'截至此刻'不许说'收盘'"
            if session["live"] else "美股盘后")
    user = f"""【数据截止 {cutoff}】
{block}

输出JSON({view},呈现"美股AI科技今天发生了什么、哪些方向强弱"):
{{
  "data_cutoff": "{cutoff}",
  "session": "us",
  "headline": {{"fact":"基于上述数据的中性事实陈述,不带倾向","user_judgment":"<待填>","confidence":"高|中|低"}},
  "narrative": "约500字的今日综述,分3-4个自然段(段间用\\n\\n分隔):①大盘与板块涨跌概况(点名强弱板块+代表个股数据);②今日重要新闻事件(半导体/云/光模块/存储/Neocloud等,按重要性展开2-4条,带来源);③舆情要点(权威媒体口径 + 推特X的美股与A股两方观点分歧,注明谁说的)。只陈述事实与各方说法,不下投资判断,不编造数字。",
  "top3": [{{"change":"变化描述","evidence":"[来源:xxx]","node_ids":[],"related_stocks":[]}}],
  "sectors": [{{"chain":"半导体","status":"一句状态[来源]"}}],
  "x_takes": {{"us_global":"综述推特X在美股/全球AI上的主要观点分歧≤120字,注明谁说的;无则填(无)","a_share":"综述推特X在A股上的主要观点≤120字,注明谁说的;无则填(无)"}},
  "falsification": [{{"claim":"可证伪观察","condition":"1-2周内可验证条件","draft_by":"deepseek"}}]
}}
只用上面数据。narrative 约500字(控制在480-620字,充实但别啰嗦);top3 选今天最值得注意的3个变化;x_takes 是对推特X两组观点的中性综述(转述不背书)。"""
    try:
        return llm.chat_json(B3_SYS, user, timeout=180)
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

    session = _us_session()
    heatmap = _heatmap(stocks)

    print(f"[build_us] 生成美股热点(DeepSeek,{session['status']})...")
    hotspot = _hotspot(stocks, news, heatmap["nodes"], date)
    print(f"  热点 {len(hotspot['items']) if hotspot else 0} 板块")

    print("[build_us] 合成美股报告 B3 ...")
    report = _report(stocks, news, wire, us_date, session)

    print("[build_us] 拉美股 6M 走势 ...")
    trends = _trends([t for t, _, _ in US_UNIVERSE])
    print(f"  走势 {len(trends)} 只")

    us = {
        "us_session_date": us_date,
        "session_status": session["status"],
        "board": {"items": board["items"], "n_ok": board["n_ok"]},
        "temperature": _temperature(stocks),
        "heatmap": heatmap,
        "research": _research(stocks),
        "news": news,
        "wire": wire,
        "hotspot": hotspot,
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
