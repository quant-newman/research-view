"""台北侧:抓西方科技/财经媒体 + 社交源 → 全球科技舆情原始条目。

只能台北跑(阿里云连不了外网,同 Yahoo)。产出交给 build_us._b1_wire 做中文化。
源:华尔街日报(WSJ RSS)、路透(走 Google News RSS 绕直连封锁)、科技媒体(TechCrunch/Ars)、
   Reddit(.rss,限流→礼貌UA+退避)。推特X 预留槽位(等账号名单)。
只落原始条目,不做判断;去重键=title;按关键词过滤到 AI/科技/半导体相关。
"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from html import unescape

import requests

UA = "Mozilla/5.0 (compatible; mofangbot/1.0; +https://example.com/bot)"
TIMEOUT = 15

# (源显示名, 分组, url, 类型)  类型: rss=标准RSS<item>, atom=Atom<entry>
SOURCES = [
    ("WSJ科技", "华尔街日报", "https://feeds.a.dj.com/rss/RSSWSJD.xml", "rss"),
    ("WSJ市场", "华尔街日报", "https://feeds.a.dj.com/rss/RSSMarketsMain.xml", "rss"),
    ("路透", "路透社",
     "https://news.google.com/rss/search?q=when:1d+site:reuters.com&hl=en-US&gl=US&ceid=US:en", "rss"),
    ("TechCrunch", "科技媒体", "https://techcrunch.com/feed/", "rss"),
    ("Ars Technica", "科技媒体", "https://feeds.arstechnica.com/arstechnica/index", "rss"),
    ("r/wallstreetbets", "Reddit", "https://www.reddit.com/r/wallstreetbets/hot.rss?limit=25", "atom"),
    ("r/stocks", "Reddit", "https://www.reddit.com/r/stocks/hot.rss?limit=25", "atom"),
    ("r/technology", "Reddit", "https://www.reddit.com/r/technology/hot.rss?limit=25", "atom"),
    ("r/hardware", "Reddit", "https://www.reddit.com/r/hardware/hot.rss?limit=15", "atom"),
]

# 相关性关键词(小写子串匹配):AI/算力/半导体/大厂/宏观。命中任一才留。
KEYWORDS = [
    "ai", "artificial intelligence", "genai", "llm", "chatgpt", "openai", "anthropic", "gemini",
    "gpu", "chip", "semiconductor", "silicon", "wafer", "foundry", "hbm", "memory", "dram",
    "data center", "datacenter", "cloud", "hyperscal", "inference", "training", "model",
    "nvidia", "amd", "tsmc", "broadcom", "micron", "asml", "arm holdings", "intel", "qualcomm",
    "microsoft", "google", "alphabet", "amazon", "meta", "apple", "tesla", "oracle", "palantir",
    "coreweave", "nebius", "super micro", "supermicro", "dell", "arista", "vertiv", "snowflake",
    "optical", "networking", "robot", "autonomous", "quantum", "fab ",
    "earnings", "guidance", "capex", "fed", "rate cut", "inflation", "nasdaq", "s&p",
]
# Reddit 例行帖/水贴,过滤
REDDIT_SKIP = re.compile(
    r"daily discussion|weekend discussion|what are your moves|moves tomorrow|"
    r"megathread|rate my|gain/loss|weekly|monthly|mods? ", re.I)

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _clean(s: str | None, limit: int = 500) -> str:
    if not s:
        return ""
    return _WS.sub(" ", unescape(_TAG.sub(" ", s))).strip()[:limit]


# 词边界匹配,避免 "ai" 命中 fairly/against、"chip" 命中 chipper 等假阳性
_KW_RE = re.compile(
    r"(?<![a-z])(" + "|".join(re.escape(k.strip()) for k in KEYWORDS) + r")(?![a-z])", re.I)


def _relevant(title: str, desc: str) -> bool:
    return bool(_KW_RE.search(f"{title} {desc}"))


def _get(url: str, retries: int = 2) -> str | None:
    """带退避的 GET(Reddit 会 429)。失败返回 None,不阻塞其余源。"""
    for i in range(retries + 1):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.text
            if r.status_code in (429, 503) and i < retries:
                time.sleep(2 * (i + 1))
                continue
            return None
        except Exception:  # noqa: BLE001 单源网络失败不阻塞
            if i < retries:
                time.sleep(1.5)
                continue
            return None
    return None


def _parse(xml_text: str, kind: str) -> list[dict]:
    """解析 RSS(<item>)或 Atom(<entry>)→ [{title,desc,url}]。命名空间无关。"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out = []
    tag = "item" if kind == "rss" else "entry"

    def _local(el, name):  # 忽略命名空间取子节点文本
        for c in el.iter():
            if c.tag.rsplit("}", 1)[-1] == name and (c.text or c.attrib):
                return c
        return None

    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] != tag:
            continue
        t = _local(node, "title")
        title = _clean(t.text if t is not None else None, 300)
        if not title:
            continue
        # 链接:RSS 用<link>text;Atom 用<link href=>
        url = ""
        for c in node:
            if c.tag.rsplit("}", 1)[-1] == "link":
                url = (c.text or c.attrib.get("href") or "").strip()
                if url:
                    break
        d = _local(node, "description")
        if d is None:
            d = _local(node, "summary")
        if d is None:
            d = _local(node, "content")
        desc = _clean(d.text if d is not None else None)
        out.append({"title": title, "desc": desc, "url": url})
    return out


def fetch_x_placeholder() -> list[dict]:
    """推特/X 槽位:等用户给账号名单再实现(无免费官方API,方案待定)。"""
    return []


def fetch_wire(per_source: int = 12, total_cap: int = 60) -> list[dict]:
    seen: set[str] = set()
    items: list[dict] = []
    for name, group, url, kind in SOURCES:
        xml_text = _get(url)
        if not xml_text:
            print(f"  ! wire 源取失败,跳过: {name}")
            continue
        kept = 0
        for it in _parse(xml_text, kind):
            title, desc = it["title"], it["desc"]
            key = title.lower()
            if key in seen:
                continue
            if group == "Reddit" and REDDIT_SKIP.search(title):
                continue
            if not _relevant(title, desc):
                continue
            seen.add(key)
            items.append({"title": title, "desc": desc, "url": it["url"],
                          "src": name, "group": group})
            kept += 1
            if kept >= per_source:
                break
        print(f"  {name}({group}): {kept} 条")
    items.extend(fetch_x_placeholder())
    return items[:total_cap]


if __name__ == "__main__":
    ws = fetch_wire()
    print(f"\n共 {len(ws)} 条:")
    for w in ws[:20]:
        print(f"  [{w['group']}/{w['src']}] {w['title'][:70]}")
