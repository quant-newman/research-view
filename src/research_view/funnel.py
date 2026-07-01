"""规则漏斗 + 翻译层(纯规则,不烧 LLM)。

把 raw_news 标题按 79 题材词 / 180 票名匹配,命中的标 relevant 并翻译到节点/票。
规则命中就不调 LLM(LLM 兜底留到后续 B2)。
"""
from __future__ import annotations

from . import db


def _load_maps(cur):
    """返回 (题材词->节点ids, 池内票名->code, code->节点ids, 科技域票名->(code,industry))。"""
    cur.execute("SELECT theme, node_id FROM theme_node")
    theme_nodes: dict[str, list[str]] = {}
    for theme, nid in cur.fetchall():
        theme_nodes.setdefault(theme, []).append(nid)

    cur.execute("SELECT code, name FROM stock")
    name_code = {name: code for code, name in cur.fetchall()}

    cur.execute("SELECT code, node_id FROM stock_node")
    code_nodes: dict[str, list[str]] = {}
    for code, nid in cur.fetchall():
        code_nodes.setdefault(code, []).append(nid)

    # 科技域票名(池外泛科技,名字≥3字避免误命中),值=(code, 申万L2)
    cur.execute("SELECT name, code, sw_l2 FROM tech_stock WHERE in_pool=false AND length(name)>=3")
    tech_name = {nm: (c, l2) for nm, c, l2 in cur.fetchall()}
    return theme_nodes, name_code, code_nodes, tech_name


def run_funnel(only_unfiltered: bool = True) -> dict[str, int]:
    """对 raw_news 跑漏斗。命中池内票/题材→核心;命中泛科技票→标科技行业。"""
    with db.rv_conn() as conn, conn.cursor() as cur:
        theme_nodes, name_code, code_nodes, tech_name = _load_maps(cur)
        themes = list(theme_nodes.keys())
        names = list(name_code.keys())
        tech_names = list(tech_name.keys())

        where = "WHERE relevant IS NULL" if only_unfiltered else ""
        cur.execute(f"SELECT news_id, title FROM raw_news {where}")
        news = cur.fetchall()

        updates = []
        n_relevant = 0
        for nid, title in news:
            hit_themes = [t for t in themes if t in title]
            hit_names = [nm for nm in names if nm in title]
            codes = sorted({name_code[nm] for nm in hit_names})
            node_ids = set()
            for t in hit_themes:
                node_ids.update(theme_nodes[t])
            for c in codes:
                node_ids.update(code_nodes.get(c, []))
            # 泛科技票(池外)
            hit_tech = [nm for nm in tech_names if nm in title]
            tech_codes = sorted({tech_name[nm][0] for nm in hit_tech})
            tech_inds = sorted({tech_name[nm][1] for nm in hit_tech if tech_name[nm][1]})
            relevant = bool(hit_themes or codes or tech_codes)
            if relevant:
                n_relevant += 1
            updates.append((relevant, hit_themes, sorted(node_ids), codes,
                            tech_codes, tech_inds, nid))

        cur.executemany(
            """UPDATE raw_news SET relevant=%s, matched_themes=%s, matched_node_ids=%s,
               matched_codes=%s, matched_tech_codes=%s, tech_industries=%s WHERE news_id=%s""",
            updates,
        )
    return {"processed": len(news), "relevant": n_relevant}
