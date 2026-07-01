"""规则漏斗 + 翻译层(纯规则,不烧 LLM)。

把 raw_news 标题按 79 题材词 / 180 票名匹配,命中的标 relevant 并翻译到节点/票。
规则命中就不调 LLM(LLM 兜底留到后续 B2)。
"""
from __future__ import annotations

from . import db


def _load_maps(cur) -> tuple[dict[str, list[str]], dict[str, str], dict[str, list[str]]]:
    """返回 (题材词->节点ids, 票名->code, code->节点ids)。"""
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
    return theme_nodes, name_code, code_nodes


def run_funnel(only_unfiltered: bool = True) -> dict[str, int]:
    """对 raw_news 跑漏斗。only_unfiltered=True 只处理 relevant IS NULL 的。"""
    with db.rv_conn() as conn, conn.cursor() as cur:
        theme_nodes, name_code, code_nodes = _load_maps(cur)
        themes = list(theme_nodes.keys())
        names = list(name_code.keys())

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
            relevant = bool(hit_themes or codes)
            if relevant:
                n_relevant += 1
            updates.append((relevant, hit_themes, sorted(node_ids), codes, nid))

        cur.executemany(
            """UPDATE raw_news SET relevant=%s, matched_themes=%s,
               matched_node_ids=%s, matched_codes=%s WHERE news_id=%s""",
            updates,
        )
    return {"processed": len(news), "relevant": n_relevant}
