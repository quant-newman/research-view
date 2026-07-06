"""台北侧:拉隔夜美股科技链(yfinance)→ exports/us_overnight_YYYYMMDD.json。

只能在台北 AWS 机跑(阿里云在国内连不了 Yahoo)。用 .venv-taipei 的 python:
    ./.venv-taipei/bin/python scripts/fetch_us_overnight.py [YYYYMMDD]

隔夜涨跌 = 最近一个美股完整交易日的日线涨跌%(取最后两日收盘)。
mapping 仅为供人读的中性"对A股链条参照"标签,不含任何判断。
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

# 宏观锚(参照线,展示层专用——不进 B6 矩阵不喂任何 prompt,同 chip_cost 先例 DECISIONS #22):
# ^TNX 值即收益率%(变化以 bp 计);CNY=X 为 USDCNY 在岸价,数值涨=人民币贬
# (离岸 CNH=X Yahoo 历史只回 1 行不可用,2026-07-06 实测,故用在岸替代)。
MACRO = [
    ("^TNX", "美债10Y收益率", "%", "bp"),
    ("DX-Y.NYB", "美元指数", "", "pct"),
    ("CNY=X", "人民币USDCNY", "", "pct"),
]

# (ticker, 名称, 对A股链条的中性映射标签)
INSTRUMENTS = [
    ("^IXIC", "纳斯达克综指", "美股科技大盘/风险偏好"),
    ("^SOX", "费城半导体指数", "半导体链总体"),
    ("NVDA", "英伟达", "AI算力芯片→CoWoS/光模块/PCB"),
    ("AMD", "AMD", "AI算力芯片"),
    ("AVGO", "博通", "ASIC/交换芯片/光通信"),
    ("MU", "美光", "存储链"),
    ("TSM", "台积电", "晶圆代工/先进封装"),
    ("ASML", "阿斯麦", "半导体设备/光刻"),
    ("ARM", "Arm", "IP/端侧算力"),
    ("KWEB", "中概互联ETF", "中概/A股AI应用情绪"),
]


def fetch_macro() -> dict | None:
    """宏观锚:各标的取自身最近两个有值交易日(FX 与美债/美元指数收盘节奏不同,不共用行)。"""
    try:
        df = yf.download([t for t, _, _, _ in MACRO], period="1mo", interval="1d",
                         progress=False, auto_adjust=True)
        close = df["Close"]
    except Exception:  # noqa: BLE001 宏观锚失败不阻塞隔夜美股主体
        return None
    items = []
    for t, name, unit, chg_mode in MACRO:
        try:
            s = close[t].dropna()
            if len(s) < 2:
                continue
            val, prev = float(s.iloc[-1]), float(s.iloc[-2])
            it = {"ticker": t, "name": name, "unit": unit,
                  "value": round(val, 4), "date": str(s.index[-1].date()),
                  "spark": [round(float(v), 4) for v in s.tail(20)]}
            if chg_mode == "bp":
                it["chg_bp"] = round((val - prev) * 100, 1)  # 收益率百分点差→bp
            else:
                it["chg_pct"] = round((val / prev - 1) * 100, 2)
            items.append(it)
        except Exception:  # noqa: BLE001 个别标的缺数不阻塞其余
            continue
    return {"items": items} if items else None


def fetch() -> dict:
    tickers = [t for t, _, _ in INSTRUMENTS]
    df = yf.download(tickers, period="7d", interval="1d", progress=False, auto_adjust=True)
    close = df["Close"].dropna(how="all")
    if len(close) < 2:
        raise RuntimeError("行情不足两日,无法算隔夜涨跌")
    last_row, prev_row = close.iloc[-1], close.iloc[-2]
    us_date = str(close.index[-1].date())
    items = []
    for t, name, mapping in INSTRUMENTS:
        lc = pc = pct = None
        try:
            lc, pc = float(last_row[t]), float(prev_row[t])
            pct = round((lc / pc - 1) * 100, 2)
        except Exception:  # noqa: BLE001 个别标的缺数不阻塞其余
            pass
        items.append({"ticker": t, "name": name, "mapping": mapping,
                      "close": round(lc, 2) if lc is not None else None, "pct": pct})
    got = sum(1 for it in items if it["pct"] is not None)
    out = {"us_session_date": us_date, "items": items, "n_ok": got,
           "fetched_at": datetime.now(ZoneInfo(TZ)).isoformat()}
    import source_status
    macro = fetch_macro() if source_status.enabled("macro_anchor") else None
    if macro:
        out["macro"] = macro
    return out


def main() -> None:
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.now(ZoneInfo(TZ)).strftime("%Y%m%d")
    out = fetch()
    d = ROOT / "exports"
    d.mkdir(exist_ok=True)
    p = d / f"us_overnight_{date}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{p}  (美东{out['us_session_date']}, {out['n_ok']}/{len(INSTRUMENTS)} 标的)")
    import source_status
    n_macro = len(out.get("macro", {}).get("items", []))
    source_status.report([
        {"key": "us_overnight", "ok": out["n_ok"] > 0, "n": out["n_ok"],
         "err": "" if out["n_ok"] > 0 else "yfinance 0/全部标的失败"},
        {"key": "macro_anchor", "ok": n_macro > 0, "n": n_macro,
         "err": "" if n_macro > 0 else "yfinance 宏观锚 0/全部标的失败"},
    ])


if __name__ == "__main__":
    main()
