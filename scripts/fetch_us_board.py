"""台北侧:抓美股 AI 科技板块行情/估值 → exports/us_board_YYYYMMDD.json。

只能台北跑(国内连不了 Yahoo)。用 .venv-taipei。P1=数据板块(价/涨跌/6M/52W位置/市值/PE)。
定位=领先指标外盘板块(AI 叙事美股主导,A股 AI 链常跟随),非 A股 镜像克隆。
按板块分组(类似 A股 链条但更轻)。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
TZ = "Asia/Shanghai"

# (ticker, 中文名, 板块)
US_UNIVERSE = [
    ("NVDA", "英伟达", "AI算力芯片"), ("AMD", "AMD", "AI算力芯片"),
    ("AVGO", "博通", "AI算力/网络"), ("TSM", "台积电", "晶圆代工"),
    ("MRVL", "迈威尔", "AI网络/定制"), ("ARM", "Arm", "IP/端侧"),
    ("MU", "美光", "存储"),
    ("ASML", "阿斯麦", "半导体设备"), ("AMAT", "应用材料", "半导体设备"),
    ("LRCX", "泛林", "半导体设备"), ("KLAC", "科天", "半导体设备"),
    ("MSFT", "微软", "云/超大规模"), ("GOOGL", "谷歌", "云/超大规模"),
    ("AMZN", "亚马逊", "云/超大规模"), ("META", "Meta", "云/超大规模"),
    ("SMCI", "超微", "AI服务器"), ("DELL", "戴尔", "AI服务器"),
    ("ANET", "Arista", "AI网络"), ("VRT", "Vertiv", "AI电源/散热"),
    ("PLTR", "Palantir", "AI软件"), ("NOW", "ServiceNow", "AI软件"),
    ("AAPL", "苹果", "消费电子/端侧"), ("TSLA", "特斯拉", "AI/机器人"),
    ("BABA", "阿里巴巴", "中概科技"), ("PDD", "拼多多", "中概科技"),
    ("BIDU", "百度", "中概/AI"), ("KWEB", "中概互联ETF", "中概情绪"),
    ("^IXIC", "纳斯达克综指", "指数参照"), ("^SOX", "费城半导体", "指数参照"),
]


def fetch() -> dict:
    tickers = [t for t, _, _ in US_UNIVERSE]
    hist = yf.download(tickers, period="1y", interval="1d", progress=False, auto_adjust=True)
    close = hist["Close"]
    us_date = str(close.dropna(how="all").index[-1].date())

    items = []
    for t, name, sector in US_UNIVERSE:
        s = close[t].dropna() if t in close else None
        row: dict = {"ticker": t, "name": name, "sector": sector,
                     "close": None, "pct": None, "ret_6m": None, "pos_52w": None,
                     "market_cap": None, "pe": None, "rev_growth": None, "gross_margin": None,
                     "target_mean": None, "rec_key": None, "n_analysts": None}
        if s is not None and len(s) >= 2:
            last = float(s.iloc[-1])
            row["close"] = round(last, 2)
            row["pct"] = round((last / float(s.iloc[-2]) - 1) * 100, 2)
            if len(s) >= 126:  # ~6 月
                row["ret_6m"] = round((last / float(s.iloc[-126]) - 1) * 100, 1)
            hi, lo = float(s.max()), float(s.min())
            if hi > lo:
                row["pos_52w"] = round((last - lo) / (hi - lo) * 100, 0)
        # 市值/PE:指数没有;个股一次 info 调用同时取(marketCap 十亿美元 / trailingPE)
        if not t.startswith("^"):
            try:
                info = yf.Ticker(t).info
                mc = info.get("marketCap")
                row["market_cap"] = round(mc / 1e9, 1) if mc else None
                pe = info.get("trailingPE")
                row["pe"] = round(float(pe), 1) if pe else None
                rg = info.get("revenueGrowth")  # 营收同比(小数)
                row["rev_growth"] = round(rg * 100, 1) if rg is not None else None
                gm = info.get("grossMargins")
                row["gross_margin"] = round(gm * 100, 1) if gm is not None else None
                tm = info.get("targetMeanPrice")
                row["target_mean"] = round(float(tm), 2) if tm else None
                row["rec_key"] = info.get("recommendationKey")  # strong_buy/buy/hold/...
                row["n_analysts"] = info.get("numberOfAnalystOpinions")
            except Exception:  # noqa: BLE001 单票 info 取失败不阻塞其余
                pass
        items.append(row)

    ok = sum(1 for it in items if it["pct"] is not None)
    return {"us_session_date": us_date, "items": items, "n_ok": ok,
            "fetched_at": datetime.now(ZoneInfo(TZ)).isoformat()}


def main() -> None:
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.now(ZoneInfo(TZ)).strftime("%Y%m%d")
    out = fetch()
    d = ROOT / "exports"
    d.mkdir(exist_ok=True)
    p = d / f"us_board_{date}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{p}  (美东{out['us_session_date']}, {out['n_ok']}/{len(US_UNIVERSE)} 票)")


if __name__ == "__main__":
    main()
