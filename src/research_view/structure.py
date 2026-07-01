"""B1 新闻结构化(选择题式)。对规则漏斗判 relevant 的新闻,用 DeepSeek 提取:
sentiment / event_type / one_line / is_chain_relevant(砍消费噪音)/ tickers。

铁律:只分类不判断;无来源不编;tickers 只填原文明确出现的(公司全称也算)。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from . import db, llm

SYSTEM = (
    "你是金融信息整理器,不是分析师。严禁编造原文没有的信息(数字/来源/股票都不许推断)。"
    "只做分类和提取,输出严格 JSON。"
)


def _chains(cur) -> list[str]:
    cur.execute("SELECT DISTINCT chain FROM node ORDER BY chain")
    return [r[0] for r in cur.fetchall()]


def _prompt(title: str, content: str | None, chains: list[str]) -> str:
    body = f"\n【正文(截断)】{content[:1800]}" if content else ""
    return f"""【新闻标题】{title}{body}

【任务】只做分类、提取、提炼(不下判断),输出JSON:
{{
  "sentiment": "利好|利空|中性|澄清",
  "event_type": "公告|政策|涨跌异动|研报|外盘|其他",
  "one_line": "标题级一句话概括,≤40字",
  "summary": "挑正文重点:2-4个核心观点/关键数字/因果,合并成一段≤140字的要点式中文摘要,让人不看原文就懂发生了什么;只陈述事实不加判断",
  "is_chain_relevant": true/false,
  "tickers": [原文明确出现的A股公司名/代码,公司全称也算必须提取,没有则空]
}}
规则:
- is_chain_relevant:该新闻是否属于【科技行业】(半导体/电子/计算机/通信/传媒/AI/算力/
  软件/消费电子/光通信/存储/机器人等泛科技,含美股科技巨头);
  排除纯消费级/玩具类(如泳池机器人、扫地机、三防手机)与非科技行业(食品/地产/银行等),这些 false。
- one_line 与 summary 都不许出现"利好X""看好Y""建议买入"等判断词,只陈述事实。
- summary 无正文时用标题合理概括,不许编造正文没有的数字/事实。
- tickers 只填原文明确出现的公司(全称也算),不许推断关联票。"""


def _one(row, chains):
    news_id, title, content = row
    try:
        j = llm.chat_json(SYSTEM, _prompt(title, content, chains))
        return (
            news_id,
            j.get("sentiment"),
            j.get("event_type"),
            (j.get("one_line") or "")[:60],
            (j.get("summary") or "")[:280] or None,
            bool(j.get("is_chain_relevant")),
            j.get("tickers") or [],
        )
    except Exception as e:  # 失败降级:不硬塞,标 llm_done=false 留待重跑
        print(f"  ! B1 失败 {news_id}: {str(e)[:80]}")
        return None


def run_structure(limit: int | None = None, workers: int = 4) -> dict[str, int]:
    """对 relevant 且未结构化的新闻跑 B1(从正文提炼核心观点摘要)。"""
    with db.rv_conn() as conn, conn.cursor() as cur:
        chains = _chains(cur)
        q = "SELECT news_id, title, content FROM raw_news WHERE relevant AND NOT llm_done ORDER BY pub_time DESC"
        if limit:
            q += f" LIMIT {int(limit)}"
        cur.execute(q)
        rows = cur.fetchall()

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = [r for r in ex.map(lambda row: _one(row, chains), rows) if r]

    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.executemany(
            """UPDATE raw_news SET sentiment=%s, event_type=%s, one_line=%s, summary=%s,
               is_chain_relevant=%s, llm_tickers=%s, llm_done=true WHERE news_id=%s""",
            [(s, et, ol, sm, cr, tk, nid) for nid, s, et, ol, sm, cr, tk in results],
        )
    chain_rel = sum(1 for r in results if r[5])
    return {"structured": len(results), "chain_relevant": chain_rel, "pruned": len(results) - chain_rel}
