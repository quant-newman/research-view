"""07-10 复权双口径核查(只读,不写任何表)——按 scorecard.score_mature 完整逻辑重走。

每张未记分卡(B6 节点卡/B8 个股卡)用其真实成员快照池(_members_asof,无快照回退当前表)、
同一窗口(发卡日收盘→第 horizon 开市日收盘,_horizon_end 同款 DISTINCT 日历),分别以:
  - raw close(现行生产口径,_interval_rets 原函数)
  - adj_factor 复权价(close×adj_factor,两端都有 close>0 且 af>0 的票才参与——
    缺价剔除规则与 raw 腿同构)
计算 excess 与 verdict,逐卡对照。窗口不完整(d1 缺/超 latest_bar)→ pending,同生产行为。

直接 import 生产 scorecard 的 _members_asof/_horizon_end/_verdict/_interval_rets,
不复制逻辑,保证与今晚记分 cron 走的是同一套代码路径。

用法(数据节点): PYTHONPATH=src .venv/bin/python audit_adj_dual.py [--horizon-override N]
  --horizon-override 仅供管路演练(如用 4 使 07-03 批窗口落在已有行情内),正式核查不带。
输出: JSON 到 stdout。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta

from research_view import db
from research_view.scorecard import _members_asof, _horizon_end, _interval_rets, _verdict


def _interval_rets_adj(mcur, ts_codes: list[str], d0, d1) -> tuple[dict[str, float], list[str]]:
    """区间收益 %(close×adj_factor 复权口径)。两端都有 close>0 且 adj_factor>0 的票才参与。
    返回 (rets, 因缺 adj_factor 而被剔除但 raw 腿有价的票清单)。"""
    mcur.execute("""SELECT b.ts_code, b.trade_date, b.close, a.adj_factor
        FROM md.bar_daily_raw b
        LEFT JOIN md.adj_factor a ON a.ts_code = b.ts_code AND a.trade_date = b.trade_date
        WHERE b.trade_date IN (%s, %s) AND b.ts_code = ANY(%s) AND b.close > 0""",
        (d0, d1, ts_codes))
    px: dict[str, dict] = {}
    raw_ok: dict[str, set] = {}
    for ts, dt, cl, af in mcur.fetchall():
        raw_ok.setdefault(ts, set()).add(dt)
        if af is not None and float(af) > 0:
            px.setdefault(ts, {})[dt] = float(cl) * float(af)
    rets = {ts: (p[d1] / p[d0] - 1) * 100 for ts, p in px.items() if d0 in p and d1 in p}
    dropped = sorted(ts for ts, ds in raw_ok.items()
                     if d0 in ds and d1 in ds and ts not in rets)
    return rets, dropped


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon-override", type=int, default=None,
                    help="演练用:覆盖所有卡的 horizon(正式核查不带)")
    args = ap.parse_args()

    out: dict = {
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "mode": "DRILL(horizon-override=%d)" % args.horizon_override if args.horizon_override else "OFFICIAL",
        "windows": [], "node_cards": [], "stock_cards": [], "pending": [],
    }

    with db.rv_conn() as conn, conn.cursor() as cur:
        # —— todo 集与 score_mature 逐字同构(未记分的最新卡) ——
        cur.execute("""WITH latest AS (
                SELECT DISTINCT ON (trade_date, node_id)
                       card_id, trade_date, node_id, direction, horizon_days, resonance
                FROM judgment_card ORDER BY trade_date, node_id, card_id DESC)
            SELECT l.card_id, l.trade_date, l.node_id, l.direction, l.horizon_days
            FROM latest l
            WHERE NOT EXISTS (SELECT 1 FROM card_score cs WHERE cs.card_id = l.card_id)
            ORDER BY l.trade_date""")
        ntodo = [("node", *r) for r in cur.fetchall()]
        cur.execute("""WITH latest AS (
                SELECT DISTINCT ON (trade_date, code)
                       card_id, trade_date, code, ts_code, direction, horizon_days, alignment
                FROM decision_card ORDER BY trade_date, code, card_id DESC)
            SELECT l.card_id, l.trade_date, l.code, l.ts_code, l.direction, l.horizon_days
            FROM latest l
            WHERE NOT EXISTS (SELECT 1 FROM decision_score ds WHERE ds.card_id = l.card_id)
            ORDER BY l.trade_date""")
        stodo = [("stock", *r) for r in cur.fetchall()]

        cur.execute("""SELECT sn.node_id, s.ts_code FROM stock_node sn
            JOIN stock s USING(code) WHERE s.ts_code IS NOT NULL""")
        members_now: dict[str, list[str]] = {}
        for nid, ts in cur.fetchall():
            members_now.setdefault(nid, []).append(ts)

        with db.marketdata_conn() as mc, mc.cursor() as mcur:
            mcur.execute("SELECT max(trade_date) FROM md.bar_daily_raw")
            latest_bar = mcur.fetchone()[0]
            out["latest_bar"] = str(latest_bar)

            by_window: dict[tuple, list] = {}
            for card in ntodo:
                h = args.horizon_override or card[5]
                by_window.setdefault((card[2], h), []).append(card)
            for card in stodo:
                h = args.horizon_override or card[6]
                by_window.setdefault((card[2], h), []).append(card)

            for (d0, horizon), cards in sorted(by_window.items()):
                members = _members_asof(cur, d0) or members_now
                snap_used = "snapshot" if _members_asof(cur, d0) else "current_table_fallback"
                pool_ts = sorted({t for v in members.values() for t in v})
                d1 = _horizon_end(mcur, d0, horizon)
                ok_window = not (d1 is None or latest_bar is None or d1 > latest_bar)
                if not ok_window:
                    for card in cards:
                        out["pending"].append({"kind": card[0], "card_id": card[1],
                                               "trade_date": str(d0), "reason": "window_incomplete",
                                               "d1": str(d1) if d1 else None})
                    continue
                rets_raw = _interval_rets(mcur, pool_ts, d0, d1)
                rets_adj, dropped_no_af = _interval_rets_adj(mcur, pool_ts, d0, d1)
                if not rets_raw:
                    for card in cards:
                        out["pending"].append({"kind": card[0], "card_id": card[1],
                                               "trade_date": str(d0), "reason": "no_rets"})
                    continue
                pool_raw = sum(rets_raw.values()) / len(rets_raw)
                pool_adj = sum(rets_adj.values()) / len(rets_adj) if rets_adj else None
                out["windows"].append({
                    "d0": str(d0), "horizon": horizon, "d1": str(d1),
                    "membership": snap_used, "pool_size": len(pool_ts),
                    "n_priced_raw": len(rets_raw), "n_priced_adj": len(rets_adj),
                    "dropped_no_af": dropped_no_af,
                    "pool_ret_raw": round(pool_raw, 4), "pool_ret_adj": round(pool_adj, 4) if pool_adj is not None else None,
                })
                for card in cards:
                    if card[0] == "node":
                        _k, card_id, _d0, nid, direction, _h = card
                        nr = [rets_raw[t] for t in members.get(nid, []) if t in rets_raw]
                        na = [rets_adj[t] for t in members.get(nid, []) if t in rets_adj]
                        if not nr:
                            out["pending"].append({"kind": "node", "card_id": card_id,
                                                   "trade_date": str(d0), "reason": "no_member_rets"})
                            continue
                        e_raw = sum(nr) / len(nr) - pool_raw
                        e_adj = (sum(na) / len(na) - pool_adj) if (na and pool_adj is not None) else None
                        v_raw = _verdict(direction, e_raw)
                        v_adj = _verdict(direction, e_adj) if e_adj is not None else None
                        out["node_cards"].append({
                            "card_id": card_id, "trade_date": str(d0), "node_id": nid,
                            "direction": direction, "n_members_raw": len(nr), "n_members_adj": len(na),
                            "excess_raw": round(e_raw, 4), "excess_adj": round(e_adj, 4) if e_adj is not None else None,
                            "verdict_raw": v_raw, "verdict_adj": v_adj,
                            "dev": round(abs(e_adj - e_raw), 4) if e_adj is not None else None,
                            "flip": bool(v_adj is not None and v_adj != v_raw),
                        })
                    else:
                        _k, card_id, _d0, code, ts, direction, _h = card
                        if ts not in rets_raw:
                            out["pending"].append({"kind": "stock", "card_id": card_id,
                                                   "trade_date": str(d0), "reason": "no_price"})
                            continue
                        e_raw = rets_raw[ts] - pool_raw
                        e_adj = (rets_adj[ts] - pool_adj) if (ts in rets_adj and pool_adj is not None) else None
                        v_raw = _verdict(direction, e_raw)
                        v_adj = _verdict(direction, e_adj) if e_adj is not None else None
                        out["stock_cards"].append({
                            "card_id": card_id, "trade_date": str(d0), "code": code, "ts_code": ts,
                            "direction": direction,
                            "excess_raw": round(e_raw, 4), "excess_adj": round(e_adj, 4) if e_adj is not None else None,
                            "verdict_raw": v_raw, "verdict_adj": v_adj,
                            "dev": round(abs(e_adj - e_raw), 4) if e_adj is not None else None,
                            "flip": bool(v_adj is not None and v_adj != v_raw),
                        })

    allc = out["node_cards"] + out["stock_cards"]
    devs = [c["dev"] for c in allc if c["dev"] is not None]
    out["summary"] = {
        "n_node": len(out["node_cards"]), "n_stock": len(out["stock_cards"]),
        "n_pending": len(out["pending"]),
        "flips": [{"kind": "node" if c in out["node_cards"] else "stock",
                   "card_id": c["card_id"], "target": c.get("node_id") or c.get("code"),
                   "direction": c["direction"], "excess_raw": c["excess_raw"],
                   "excess_adj": c["excess_adj"], "raw": c["verdict_raw"], "adj": c["verdict_adj"]}
                  for c in allc if c["flip"]],
        "max_dev": max(devs) if devs else None,
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
