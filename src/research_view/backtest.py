"""离线回测 harness(任务#9/ROADMAP 0a,DECISIONS #22 双轨:在线链路冻结,离线向历史借数据)。

只读 marketdata + research_view 参照层,零 LLM,不写库(产出落 exports/backtest/)。
在数据节点跑:.venv/bin/python -m research_view.backtest <子命令>(需 src 在 sys.path)。

双锚收益(每个信号日 d0、节点/个股、horizon h 个开市日,d1=第h个开市日):
- judgment 锚 = close(d0)→close(d1),节点成分等权 vs 全池等权的超额 pp——B7 在线记分同口径,
  但用复权价(close×adj_factor):在线 B7 用未复权 close,5日窗撞上除权会记错分;
  回测同时算未复权变体并统计两者背离(|Δ|≥3pp)次数=在线口径的除权暴露(findings,不改在线代码)。
- executable 锚 = open(d0+1)→close(d1),复权——22:30 看到卡的人次日开盘才能买到的收益;
  另计次日开盘相对昨收高开≥9.5% 的"可能买不进"次数(不建模成交,只披露)。

已知偏差(findings 必须写明,不得掩盖):
- 幸存者免责:参照层(48节点/180股)是 2026-06/07 按当下辨识度选的,拿它回测过去=事后选样,
  结果系统性偏乐观;结论只用于校准参数先验,不用于宣称历史战绩。
- 节点归属用当前映射,历史期成分变动无法还原。
- 六源在历史段退化:全史方向源仅 3 个(行情/资金2010起/龙虎榜2005起);
  研报(rv库2026-06-01起)/新闻(2026-07-01起,仅数日,统计无效)/信函/人气榜为短窗源。
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from . import config, db

OUT_DIR = config.ROOT / "exports" / "backtest"

# 与 evidence._z 同口径:总体 std、截断±3、无差异截面全 0(向量化版)
_ZCAP = 3.0


def _z_frame(df: pd.DataFrame) -> pd.DataFrame:
    """按行(日期)对列(节点)做截面 z。"""
    mean = df.mean(axis=1)
    std = df.std(axis=1, ddof=0)
    z = df.sub(mean, axis=0).div(std.where(std > 1e-9), axis=0)
    return z.clip(-_ZCAP, _ZCAP).fillna(0.0)


# ---------- 数据装载(只读) ----------

def _pool():
    """参照层:node→成分 ts_code(仅 A 股行情票),全池 ts 列表,节点名。"""
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("""SELECT sn.node_id, s.ts_code FROM stock_node sn
            JOIN stock s USING(code) WHERE s.ts_code IS NOT NULL""")
        members: dict[str, list[str]] = {}
        for nid, ts in cur.fetchall():
            members.setdefault(nid, []).append(ts)
        cur.execute("SELECT node_id, chain || '/' || node FROM node")
        names = dict(cur.fetchall())
    pool_ts = sorted({t for v in members.values() for t in v})
    return members, pool_ts, names


def _open_days(mcur, start: str, end: str) -> list:
    mcur.execute("""SELECT DISTINCT cal_date FROM md.trade_calendar
        WHERE cal_date BETWEEN to_date(%s,'YYYYMMDD') AND to_date(%s,'YYYYMMDD')
          AND is_open ORDER BY cal_date""", (start, end))
    return [r[0] for r in mcur.fetchall()]


def load_panel(start: str, end: str, pool_ts: list[str]) -> dict[str, pd.DataFrame]:
    """行情(复权 open/close+未复权 close)/主力净额/龙虎榜净买,date×ts 宽表。"""
    with db.marketdata_conn() as mc, mc.cursor() as mcur:
        days = _open_days(mcur, start, end)
        mcur.execute("""SELECT ts_code, trade_date, open, close, pre_close FROM md.bar_daily_raw
            WHERE ts_code = ANY(%s) AND trade_date BETWEEN to_date(%s,'YYYYMMDD') AND to_date(%s,'YYYYMMDD')
              AND close > 0""", (pool_ts, start, end))
        bar = pd.DataFrame(mcur.fetchall(), columns=["ts", "d", "open", "close", "pre_close"])
        mcur.execute("""SELECT ts_code, trade_date, adj_factor FROM md.adj_factor
            WHERE ts_code = ANY(%s) AND trade_date BETWEEN to_date(%s,'YYYYMMDD') AND to_date(%s,'YYYYMMDD')""",
            (pool_ts, start, end))
        adj = pd.DataFrame(mcur.fetchall(), columns=["ts", "d", "adj"])
        mcur.execute("""SELECT ts_code, trade_date,
                (coalesce(buy_lg_amount,0)-coalesce(sell_lg_amount,0)
                 +coalesce(buy_elg_amount,0)-coalesce(sell_elg_amount,0))/1e4
            FROM md.moneyflow WHERE ts_code = ANY(%s)
              AND trade_date BETWEEN to_date(%s,'YYYYMMDD') AND to_date(%s,'YYYYMMDD')""",
            (pool_ts, start, end))
        mf = pd.DataFrame(mcur.fetchall(), columns=["ts", "d", "main"])  # 亿元,multi_day 同口径
        mcur.execute("""SELECT ts_code, trade_date, sum(net_amount)/1e8 FROM md.top_list
            WHERE ts_code = ANY(%s)
              AND trade_date BETWEEN to_date(%s,'YYYYMMDD') AND to_date(%s,'YYYYMMDD')
            GROUP BY ts_code, trade_date""", (pool_ts, start, end))
        lhb = pd.DataFrame(mcur.fetchall(), columns=["ts", "d", "net"])  # 亿元,evidence 同口径

    bar = bar.merge(adj, on=["ts", "d"], how="left").sort_values(["ts", "d"])
    bar["adj"] = bar.groupby("ts")["adj"].ffill().fillna(1.0).astype(float)
    for col in ("open", "close", "pre_close"):
        bar[col] = bar[col].astype(float)
    bar["aclose"] = bar["close"] * bar["adj"]
    bar["aopen"] = bar["open"] * bar["adj"]

    def wide(df, val):
        if df.empty:
            return pd.DataFrame(index=pd.Index(days, name="d"))
        w = df.pivot(index="d", columns="ts", values=val)
        return w.reindex(days)

    return {
        "days": days,
        "aclose": wide(bar, "aclose"), "aopen": wide(bar, "aopen"),
        "rclose": wide(bar, "close"), "pre_close": wide(bar, "pre_close"),
        "mf": wide(mf, "main").fillna(0.0).astype(float),
        "lhb": wide(lhb, "net").fillna(0.0).astype(float),
    }


# ---------- 双锚收益模块 ----------

def dual_anchor(panel: dict, members: dict[str, list[str]], d0, horizon: int) -> dict | None:
    """单个信号日的双锚节点超额。返回 None = 前向窗口不足。
    judgment: aclose(d0)→aclose(d1) / raw 变体 rclose 同窗;executable: aopen(d0+1)→aclose(d1)。"""
    days = panel["days"]
    if d0 not in days:
        return None
    i = days.index(d0)
    if i + horizon >= len(days):
        return None
    d1, dnext = days[i + horizon], days[i + 1]

    def _excess(rets: pd.Series) -> tuple[dict, float]:
        rets = rets.dropna()
        if rets.empty:
            return {}, float("nan")
        pool_ret = float(rets.mean())
        node_ex = {}
        for nid, mem in members.items():
            mr = rets.reindex(mem).dropna()
            if len(mr):
                node_ex[nid] = round(float(mr.mean()) - pool_ret, 2)
        return node_ex, pool_ret

    j_rets = (panel["aclose"].loc[d1] / panel["aclose"].loc[d0] - 1) * 100
    raw_rets = (panel["rclose"].loc[d1] / panel["rclose"].loc[d0] - 1) * 100
    e_rets = (panel["aclose"].loc[d1] / panel["aopen"].loc[dnext] - 1) * 100
    judgment, pool_j = _excess(j_rets)
    raw, _ = _excess(raw_rets)
    executable, pool_e = _excess(e_rets)
    # 除权暴露:个股层 judgment(复权) vs raw(未复权)区间收益背离≥3pp 的票数
    div = (j_rets - raw_rets).abs()
    corrupt = sorted(div[div >= 3].round(1).to_dict().items(), key=lambda x: -x[1])
    # 可执行性:次日开盘相对昨收高开≥9.5%(约=一字/近一字,买不进)
    gap = (panel["aopen"].loc[dnext] / panel["aclose"].loc[d0] - 1) * 100
    unbuyable = sorted(gap[gap >= 9.5].round(1).to_dict().items(), key=lambda x: -x[1])
    return {"d0": str(d0), "d1": str(d1), "entry": str(dnext),
            "judgment": judgment, "executable": executable, "raw_judgment": raw,
            "pool_ret_judgment": round(pool_j, 2), "pool_ret_executable": round(pool_e, 2),
            "exdiv_corrupt": corrupt, "unbuyable_gap": unbuyable}


# ---------- 信号重建(历史段可得源) ----------

def signal_panels(panel: dict, members: dict[str, list[str]]) -> dict[str, pd.DataFrame]:
    """date×node 的三全史源截面z:price(5日等权涨幅)/mf(5日累计主力)/lhb(当日净买)。"""
    r5 = (panel["aclose"] / panel["aclose"].shift(5) - 1) * 100
    mf5 = panel["mf"].rolling(5, min_periods=5).sum()
    node_cols = {}
    for nid, mem in members.items():
        cols = [t for t in mem if t in r5.columns]
        if cols:
            node_cols[nid] = cols
    def agg(df, how):
        out = pd.DataFrame(index=df.index)
        for nid, cols in node_cols.items():
            sub = df.reindex(columns=cols)  # lhb/mf 宽表只含出现过的票,缺列=无数据
            out[nid] = sub.mean(axis=1) if how == "mean" else sub.sum(axis=1)
        return out
    return {"price": _z_frame(agg(r5, "mean")),
            "mf": _z_frame(agg(mf5, "sum")),
            "lhb": _z_frame(agg(panel["lhb"], "sum"))}


def _rv_short_panels(days: list, members: dict[str, list[str]]) -> dict[str, pd.DataFrame]:
    """短窗源(rv库):研报 n3d(2026-06-01起)/新闻 pos-neg(2026-07-01起,仅数日)。"""
    nids = list(members)
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("""SELECT rr.report_date, nid, count(*) FROM research_report rr
            CROSS JOIN LATERAL unnest(rr.node_ids) nid GROUP BY 1, 2""")
        rr = pd.DataFrame(cur.fetchall(), columns=["d", "nid", "n"])
        cur.execute("""SELECT rn.pub_time::date, m.node_id,
                count(*) FILTER (WHERE rn.sentiment='利好') - count(*) FILTER (WHERE rn.sentiment='利空')
            FROM raw_news rn CROSS JOIN LATERAL unnest(rn.matched_node_ids) m(node_id)
            WHERE rn.relevant GROUP BY 1, 2""")
        nw = pd.DataFrame(cur.fetchall(), columns=["d", "nid", "net"])
    out = {}
    if not rr.empty:
        # evidence 口径:report_date >= d-3(日历日)。铺满日历日再滚4天窗,取开市日。
        w = rr.pivot(index="d", columns="nid", values="n")
        cal = pd.date_range(min(w.index.min(), min(days)), max(days), freq="D").date
        n3d = w.reindex(cal).fillna(0.0).rolling(4, min_periods=1).sum().reindex(days).fillna(0.0)
        out["research"] = _z_frame(n3d.reindex(columns=nids).fillna(0.0))
        out["_research_days"] = rr["d"]
    if not nw.empty:
        w = nw.pivot(index="d", columns="nid", values="net").reindex(days).fillna(0.0)
        out["news"] = _z_frame(w.reindex(columns=nids).fillna(0.0))
        out["_news_days"] = nw["d"]
    return out


# ---------- 诊断一:分源相关性与独立自由度 ----------

def _corr_and_dof(zs: dict[str, pd.DataFrame], days) -> dict:
    keys = list(zs)
    stacked = {k: zs[k].loc[[d for d in days if d in zs[k].index]].stack() for k in keys}
    idx = None
    for s in stacked.values():
        idx = s.index if idx is None else idx.intersection(s.index)
    mat = pd.DataFrame({k: stacked[k].reindex(idx) for k in keys}).dropna()
    c = mat.corr().fillna(0.0).to_numpy(copy=True)
    np.fill_diagonal(c, 1.0)
    corr = pd.DataFrame(c, index=keys, columns=keys)
    n = len(keys)
    off = c[~np.eye(n, dtype=bool)]
    eig = np.linalg.eigvalsh(c)
    neff_eig = float(eig.sum() ** 2 / (eig ** 2).sum())
    avg_abs = float(np.abs(off).mean()) if n > 1 else 0.0
    neff_avg = n / (1 + (n - 1) * avg_abs)
    return {"sources": keys, "n_obs": int(len(mat)),
            "corr": corr.round(3).to_dict(),
            "avg_abs_offdiag": round(avg_abs, 3),
            "neff_eigen": round(neff_eig, 2), "neff_avgcorr": round(neff_avg, 2)}


def diag1(start: str, end: str, short_start: str = "20260601") -> dict:
    members, pool_ts, names = _pool()
    panel = load_panel(start, end, pool_ts)
    zs = signal_panels(panel, members)
    days = [d for d in panel["days"][5:]]  # 前5日无 r5/mf5
    full = _corr_and_dof(zs, days)

    short_days = [d for d in days if str(d).replace("-", "") >= short_start]
    shorts = _rv_short_panels(panel["days"], members)
    zs_short = dict(zs)
    coverage = {}
    for k in ("research", "news"):
        if k in shorts:
            zs_short[k] = shorts[k]
            src_days = sorted(set(shorts[f"_{k}_days"]))
            coverage[k] = {"first": str(src_days[0]), "last": str(src_days[-1]),
                           "n_days_with_data": len(src_days)}
    short = _corr_and_dof(zs_short, short_days) if short_days else None

    out = {
        "window_full": {"start": start, "end": end, "n_open_days": len(days), "diag": full},
        "window_short": {"start": short_start, "end": end,
                         "n_open_days": len(short_days), "coverage": coverage, "diag": short},
        "n_nodes": len({n for z in zs.values() for n in z.columns}),
        "n_pool_stocks": len(pool_ts),
        "findings": [
            "全史方向源仅3个:行情/资金(2010起)/龙虎榜(2005起)——生产六源在历史段退化为3源,"
            "六源共振的历史检验上限就是这3源的组合",
            "新闻源 raw_news 仅 2026-07-01 起(3个交易日),短窗相关性对 news 统计无效,只列不采信",
            "研报源 rv 库 2026-06-01 起(约1个月),短窗结论仅供方向参考",
            "幸存者免责:参照层是 2026-06/07 按当下辨识度选的,回测过去=事后选样,结果偏乐观;"
            "节点归属用当前映射,历史成分变动未还原",
        ],
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUT_DIR / f"diag1_{start}_{end}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    print(f"\n→ {p}")
    return out


# ---------- 双锚模块对账(与在线 B7 记分交叉验证) ----------

def validate(date_utc8: str = "20260618", horizon: int = 5) -> None:
    """用未复权变体复算指定日节点超额,与 B7 事务内测试已知值对账(减速器 06-18 约 -17.5pp)。"""
    members, pool_ts, names = _pool()
    end = (pd.Timestamp(date_utc8) + pd.Timedelta(days=horizon * 2 + 10)).strftime("%Y%m%d")
    start = (pd.Timestamp(date_utc8) - pd.Timedelta(days=15)).strftime("%Y%m%d")
    panel = load_panel(start, end, pool_ts)
    d0 = next((d for d in panel["days"] if str(d).replace("-", "") == date_utc8), None)
    if d0 is None:
        print(f"{date_utc8} 非开市日"); return
    r = dual_anchor(panel, members, d0, horizon)
    if not r:
        print("前向窗口不足"); return
    print(f"信号日 {r['d0']} → 到期 {r['d1']}(judgment close→close)/入场 {r['entry']}(executable open→close)")
    rows = sorted(r["raw_judgment"].items(), key=lambda x: x[1])
    print("\nraw_judgment(未复权,=B7在线口径)节点超额 pp:")
    for nid, ex in rows:
        tag = " ←对账点" if "减速器" in names.get(nid, "") else ""
        print(f"  {names.get(nid, nid):<24} raw {ex:+7.2f} | adj {r['judgment'].get(nid, float('nan')):+7.2f}"
              f" | exec {r['executable'].get(nid, float('nan')):+7.2f}{tag}")
    print(f"\n除权背离≥3pp: {r['exdiv_corrupt'] or '无'}")
    print(f"高开≥9.5%买不进: {r['unbuyable_gap'] or '无'}")


def main() -> None:
    args = sys.argv[1:]
    cmd = args[0] if args else "diag1"
    kv = dict(a.split("=", 1) for a in args[1:] if "=" in a)
    if cmd == "diag1":
        diag1(kv.get("start", "20240701"), kv.get("end", "20260703"), kv.get("short_start", "20260601"))
    elif cmd == "validate":
        validate(kv.get("date", "20260618"), int(kv.get("horizon", 5)))
    else:
        print("用法: python -m research_view.backtest diag1 [start=YYYYMMDD end=YYYYMMDD] | validate [date=YYYYMMDD]")


if __name__ == "__main__":
    main()
