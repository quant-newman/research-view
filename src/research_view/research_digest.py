"""研报深化:评级/目标价变动榜(统计,对比同股历史)+ 机构观点提炼(DeepSeek 从标题综述)。

Tushare report_rc 只有标题+评级+目标价(无正文),故:
- 变动榜=同股近30天多篇研报里,最新评级/目标价 vs 之前的对比(上调/下调)。
- 观点提炼=把某股近期研报标题交给 DeepSeek 综合"机构在说什么"(标题含论点)。
铁律:只转述"机构说了什么"的客观事实,不下自己的投资判断。
"""
from __future__ import annotations

import hashlib
import json

from . import db, llm

# 评级分档(数值越大越积极)
RATING_SCORE = {
    "卖出": 0, "强烈卖出": 0, "减持": 1, "回避": 1, "跑输": 1, "弱于大市": 1, "弱于大盘": 1,
    "中性": 2, "持有": 2, "同步大市": 2, "审慎": 2, "观望": 2,
    "增持": 3, "推荐": 3, "谨慎推荐": 3, "优于大市": 3, "跑赢": 3, "优于大盘": 3,
    "买入": 4, "强烈推荐": 5, "强推": 5, "强烈买入": 5,
}
SYS = ("你是投研信息整理器,不是分析师。只综合转述给定研报标题里机构的观点,"
       "不下自己的判断、不出买卖建议。输出严格 JSON。")


def _score(r):
    return RATING_SCORE.get((r or "").strip())


def _collect(date_utc8: str, days: int = 30):
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("""SELECT code, name, report_date, rating, tp, org_name, title, scope
            FROM research_report
            WHERE report_date >= to_date(%s,'YYYYMMDD') - %s AND report_date IS NOT NULL
            ORDER BY code, report_date""", (date_utc8, days))
        rows = cur.fetchall()
    by_code: dict[str, dict] = {}
    for code, name, rd, rating, tp, org, title, scope in rows:
        tpf = float(tp) if tp and 0 < float(tp) < 2000 else None
        by_code.setdefault(code, {"name": name, "scope": scope, "reports": []})["reports"].append(
            {"date": str(rd), "rating": rating, "tp": tpf, "org": org, "title": title})
    return by_code


def _changes(by_code: dict, top: int = 20):
    """评级/目标价变动榜。只认**同一机构**自身前后两篇的变化——跨机构比较是假动作
    (A券商最新tp对比B券商更早的tp,不是任何一家的真实调价,输出"机构下调"会失真,
    与零幻觉铁律冲突)。同票多家机构都有变动时取最近一条。"""
    out = []
    for code, d in by_code.items():
        by_org: dict[str, list] = {}
        for r in d["reports"]:  # reports 已按 report_date 升序
            if r["org"]:
                by_org.setdefault(r["org"], []).append(r)
        best = None
        for org, reps in by_org.items():
            if len(reps) < 2:
                continue
            latest, prior = reps[-1], reps[:-1]
            lat_s = _score(latest["rating"])
            prior_rated = next((r for r in reversed(prior) if _score(r["rating"]) is not None), None)
            rating_dir = None
            if prior_rated and lat_s is not None:
                ps = _score(prior_rated["rating"])
                rating_dir = "上调" if lat_s > ps else "下调" if lat_s < ps else None
            prior_tp = next((r["tp"] for r in reversed(prior) if r["tp"]), None)
            tp_chg = round((latest["tp"] / prior_tp - 1) * 100, 1) if latest["tp"] and prior_tp else None
            if rating_dir or (tp_chg is not None and abs(tp_chg) >= 1):
                cand = {"code": code, "name": d["name"], "scope": d["scope"], "n": len(d["reports"]),
                        "rating_dir": rating_dir, "latest_rating": latest["rating"],
                        "prior_rating": prior_rated["rating"] if prior_rated else None,
                        "latest_tp": latest["tp"], "prior_tp": prior_tp, "tp_chg": tp_chg,
                        "latest_org": org, "latest_date": latest["date"]}
                if best is None or cand["latest_date"] > best["latest_date"]:
                    best = cand
        if best:
            out.append(best)
    # 上调优先,其次目标价上调幅度
    out.sort(key=lambda c: (c["rating_dir"] != "上调", -(c["tp_chg"] if c["tp_chg"] is not None else -999)))
    return out[:top]


def _cached_views(date_utc8: str, sig: str) -> dict[str, str] | None:
    """指纹一致(研报标题集合没变)则复用上一版观点提炼,返回 {code: view},不调 LLM。"""
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("""SELECT views FROM research_digest
            WHERE report_date = to_date(%s,'YYYYMMDD') AND views_sig = %s""", (date_utc8, sig))
        row = cur.fetchone()
    if not row:
        return None
    return {v["code"]: v.get("view") for v in (row[0] or []) if isinstance(v, dict) and v.get("code")}


def _views(date_utc8: str, by_code: dict, top: int = 15):
    """返回 (观点行, 指纹)。指纹=喂给 LLM 的研报标题块——盘中每 15min 调一次,
    而标题集合只在新研报入库时才变,不变就复用已落库的 view。"""
    ranked = sorted(by_code.items(), key=lambda kv: -len(kv[1]["reports"]))[:top]
    ranked = [(c, d) for c, d in ranked if d["reports"]]
    if not ranked:
        return [], None
    blocks = []
    for i, (code, d) in enumerate(ranked):
        titles = "；".join(r["title"] for r in d["reports"][-4:] if r["title"])
        blocks.append(f"{i}. {d['name']}({code}) 近{len(d['reports'])}篇研报标题:{titles}")
    sig = hashlib.sha1("\n".join(blocks).encode("utf-8")).hexdigest()
    hit = _cached_views(date_utc8, sig)
    if hit is not None:
        print("  研报观点提炼:输入指纹未变,复用上一版(省 1 次 LLM)")
        return [{"code": code, "name": d["name"], "scope": d["scope"], "n": len(d["reports"]),
                 "view": hit.get(code), "latest_rating": d["reports"][-1]["rating"],
                 "latest_tp": d["reports"][-1]["tp"]} for code, d in ranked], sig
    user = f"""下面每只票近期卖方研报标题(标题含机构论点)。逐条综合"机构观点",JSON:
{{"items":[{{"i":序号,"view":"综合这些研报机构在说什么的中性一句话(如'多家看好MLCC超级周期、镍粉量价齐升'),≤50字,只转述不加判断"}}]}}
{chr(10).join(blocks)}
不许出现"建议买入/值得关注"等你自己的判断词。"""
    try:
        j = llm.chat_json(SYS, user, timeout=240)
        items = j.get("items", []) if isinstance(j, dict) else (j if isinstance(j, list) else [])
        m = {int(it["i"]): it.get("view") for it in items if isinstance(it, dict) and "i" in it}
    except Exception as e:  # noqa: BLE001 提炼失败降级:空 view
        print(f"  ! 研报观点提炼失败: {str(e)[:80]}")
        m = {}
        sig = None  # 失败不落指纹:下一档必须重试,别把空 view 钉死一整天
    return [{"code": code, "name": d["name"], "scope": d["scope"], "n": len(d["reports"]),
             "view": m.get(i), "latest_rating": d["reports"][-1]["rating"],
             "latest_tp": d["reports"][-1]["tp"]} for i, (code, d) in enumerate(ranked)], sig


def compute(date_utc8: str) -> dict:
    by_code = _collect(date_utc8)
    views, views_sig = _views(date_utc8, by_code)
    return {"changes": _changes(by_code), "views": views, "views_sig": views_sig}


def persist(date_utc8: str) -> dict:
    out = compute(date_utc8)
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("""INSERT INTO research_digest(report_date, changes, views, views_sig)
            VALUES(to_date(%s,'YYYYMMDD'), %s, %s, %s)
            ON CONFLICT(report_date) DO UPDATE SET changes=EXCLUDED.changes,
              views=EXCLUDED.views, views_sig=EXCLUDED.views_sig, generated_at=now()""",
            (date_utc8, json.dumps(out["changes"], ensure_ascii=False),
             json.dumps(out["views"], ensure_ascii=False), out["views_sig"]))
    return {"changes": len(out["changes"]), "views": len(out["views"])}
