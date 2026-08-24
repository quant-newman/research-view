"""B1 新闻结构化(选择题式)。对规则漏斗判 relevant 的新闻,用 DeepSeek 提取:
sentiment / event_type / one_line / is_chain_relevant(砍消费噪音)/ tickers。

铁律:只分类不判断;无来源不编;tickers 只填原文明确出现的(公司全称也算)。

批量口径(2026-08-24 降本批#2):一次喂 BATCH 条。逐条调用日均 348 次,同一份规则块
(约 500 token)重发 348 遍是纯浪费;批量后调用数降一个数量级,且规则块前置成为公共
前缀,可被平台前缀缓存复用。判断口径一字未改——只是把"一次一条"换成"一次一批",
批内各条严格按序号对齐回写,对不上的宁可不写(留 llm_done=false 下档重跑),绝不按
位置猜,防串扰/错位把 A 条的数字安到 B 条头上。
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

from . import db, llm

SYSTEM = (
    "你是金融信息整理器,不是分析师。严禁编造原文没有的信息(数字/来源/股票都不许推断)。"
    "只做分类和提取,输出严格 JSON。"
)

BATCH = int(os.environ.get("B1_BATCH", "8"))   # 一次喂几条
BODY_CHARS = 1500                               # 单条正文截断(8 条约 12k 字符,远低于上下文上限)

# 规则块放最前面且逐字不变:既是判断口径,也是前缀缓存的命中前提(后面才接变动的新闻)。
RULES = """【任务】对下面每条新闻各做一次分类、提取、提炼(不下判断),输出JSON:
{
  "items": [
    {
      "i": 该条的序号(照抄 ### 后面的数字),
      "sentiment": "利好|利空|中性|澄清",
      "event_type": "公告|政策|涨跌异动|研报|外盘|其他",
      "one_line": "标题级一句话概括,≤40字",
      "summary": "挑正文重点:2-4个核心观点/关键数字/因果,合并成一段≤140字的要点式中文摘要,让人不看原文就懂发生了什么;只陈述事实不加判断",
      "is_chain_relevant": true/false,
      "tickers": [原文明确出现的A股公司名/代码,公司全称也算必须提取,没有则空]
    }
  ]
}
规则:
- items 必须每条新闻一项,i 与输入序号一一对应,不许漏、不许合并、不许改序号。
- 每条只依据它自己那条的标题/正文判断,严禁把别条的数字、公司、事件串到本条上。
- is_chain_relevant:该新闻是否属于【科技行业】(半导体/电子/计算机/通信/传媒/AI/算力/
  软件/消费电子/光通信/存储/机器人等泛科技,含美股科技巨头);
  排除纯消费级/玩具类(如泳池机器人、扫地机、三防手机)与非科技行业(食品/地产/银行等),这些 false。
- one_line 与 summary 都不许出现"利好X""看好Y""建议买入"等判断词,只陈述事实。
- 数字与单位原样照抄原文,禁止换算/改写单位。尤其"百分比"与"倍"不是一回事:
  "增长62204%"只能写"62204%"(或原文自己写的"622倍"),写成"6万倍"就放大了100倍(实错案例)。
  拿不准换算就照抄原文的数字+单位。
- summary 无正文时用标题合理概括,不许编造正文没有的数字/事实。
- tickers 只填原文明确出现的公司(全称也算),不许推断关联票。"""


def _prompt(items: list[tuple[str, str | None]]) -> str:
    blocks = []
    for i, (title, content) in enumerate(items):
        body = f"\n正文(截断):{content[:BODY_CHARS]}" if content else ""
        blocks.append(f"### {i}\n标题:{title}{body}")
    return f"{RULES}\n\n【本批 {len(items)} 条新闻】\n" + "\n\n".join(blocks)


def _align(j, n: int) -> dict[int, dict]:
    """按 i 严格对齐。越界/重复/缺 i 一律丢弃——错位回写会把 A 条的事实钉到 B 条上,
    比少写一条严重得多;丢掉的条目 llm_done 仍是 false,下一档自然重跑。"""
    items = j.get("items") if isinstance(j, dict) else j
    out: dict[int, dict] = {}
    for it in items or []:
        if not isinstance(it, dict):
            continue
        try:
            i = int(it["i"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= i < n and i not in out:
            out[i] = it
    return out


def _row(row, it: dict):
    news_id = row[0]
    return (
        news_id,
        it.get("sentiment"),
        it.get("event_type"),
        (it.get("one_line") or "")[:60],
        (it.get("summary") or "")[:280] or None,
        bool(it.get("is_chain_relevant")),
        it.get("tickers") or [],
    )


def _run_batch(rows: list) -> list:
    """rows=[(news_id, title, content)]。返回可回写的行。"""
    try:
        j = llm.chat_json(SYSTEM, _prompt([(t, c) for _, t, c in rows]))
    except Exception as e:  # noqa: BLE001 失败降级:不硬塞,标 llm_done=false 留待重跑
        if len(rows) == 1:
            print(f"  ! B1 失败 {rows[0][0]}: {str(e)[:80]}")
            return []
        # 整批失败可能是某条正文有毒(而非网络),拆成逐条重试,最坏退回旧行为、不卡住队列
        print(f"  ! B1 批({len(rows)}条)失败,降级逐条: {str(e)[:80]}")
        return [r for row in rows for r in _run_batch([row])]
    got = _align(j, len(rows))
    if len(got) < len(rows):
        print(f"  ! B1 批 {len(rows)} 条只对齐回 {len(got)} 条,缺的留待下档重跑")
    return [_row(rows[i], it) for i, it in sorted(got.items())]


def _fetch(limit: int | None) -> list:
    q = "SELECT news_id, title, content FROM raw_news WHERE relevant AND NOT llm_done ORDER BY pub_time DESC"
    if limit:
        q += f" LIMIT {int(limit)}"
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute(q)
        return cur.fetchall()


def _writeback(results: list) -> None:
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.executemany(
            """UPDATE raw_news SET sentiment=%s, event_type=%s, one_line=%s, summary=%s,
               is_chain_relevant=%s, llm_tickers=%s, llm_done=true WHERE news_id=%s""",
            [(s, et, ol, sm, cr, tk, nid) for nid, s, et, ol, sm, cr, tk in results],
        )


def run_structure(limit: int | None = None, workers: int = 4, batch: int | None = None) -> dict[str, int]:
    """对 relevant 且未结构化的新闻跑 B1(从正文提炼核心观点摘要)。"""
    rows = _fetch(limit)
    n = max(1, batch or BATCH)
    chunks = [rows[i:i + n] for i in range(0, len(rows), n)]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = [r for part in ex.map(_run_batch, chunks) for r in part]
    _writeback(results)
    chain_rel = sum(1 for r in results if r[5])
    return {"structured": len(results), "chain_relevant": chain_rel, "pruned": len(results) - chain_rel,
            "calls": len(chunks)}
