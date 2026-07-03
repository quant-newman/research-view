"""台北侧:抓海外基金信函/大行展望 → DeepSeek B5 中文摘要 → exports/fund_letters_DATE.json。

只能台北 AWS 机跑(国内连不了海外站)。用 .venv-taipei(含 bs4/lxml)。
源(2026-07-03 实测静态可抓):oaktree 备忘录 / blackrock BII周评(单页原地更新,按周标题去重)/
gs、ms Insights 文章流(科技词条优先)。UBS 403、Bridgewater/JPM 纯JS,接不了。
适配器返回 (fund, url) 元组走通用抽取,或返回 dict{fund,url,uid,title,text} 自带内容。
B5 铁律:只转述作者观点,不编造、不加自己的判断;评"对A股AI科技链"的相关度。

用法: ./.venv-taipei/bin/python scripts/fetch_fund_letters.py [YYYYMMDD] [源key,逗号分隔] [每源篇数]
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from research_view import config, llm  # noqa: E402

TZ = "Asia/Shanghai"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36"


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")


# 站点样板/法务段(大行页面首尾大量营销+免责声明,混进正文会吃掉 B5 的 8000 字预算)
_BOILER = ("at morgan stanley, we lead", "we harness every resource", "subscribe", "newsletter",
           "cookie", "terms of use", "privacy", "please read this page", "past performance",
           "for informational purposes", "all rights reserved", "investment involves risk",
           "this website", "enable javascript", "to reach a different blackrock site")


def _clean_text(soup: BeautifulSoup) -> str:
    """长段落 <p> 拼正文,滤样板/法务段 + 去重复段(站点 header/footer 常整段复读)。"""
    seen: set[str] = set()
    out = []
    for p in soup.find_all("p"):
        t = p.get_text(" ", strip=True)
        if len(t) <= 40 or t in seen or any(k in t.lower() for k in _BOILER):
            continue
        seen.add(t)
        out.append(t)
    return "\n".join(out)


def _article_text(url: str) -> tuple[str, str]:
    """通用抽取:og:title 优先(GS 的首个 h1 是栏目名不是文章名),正文=过滤后的长 <p>。"""
    soup = BeautifulSoup(_get(url), "lxml")
    og = soup.find("meta", property="og:title")
    h1 = soup.find("h1")
    title = (og["content"] if og and og.get("content") else
             h1.get_text(strip=True) if h1 else url)
    title = re.sub(r"\s*\|\s*(Morgan Stanley|BlackRock.*|Goldman Sachs)\s*$", "", title)
    return title, _clean_text(soup)


_TECH_HINT = re.compile(r"ai|artificial|semiconductor|chip|robot|humanoid|tech|data-?cent"
                        r"|cloud|comput|quantum|outlook|market", re.I)


def _src_article_list(list_url: str, base: str, path_pat: str, fund: str, limit: int) -> list[tuple[str, str]]:
    """通用文章流适配:列表页抓 path_pat 链接,科技词条优先、其余按页面序(≈最新在前)。"""
    soup = BeautifulSoup(_get(list_url), "lxml")
    seen: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].split("?")[0].split("#")[0]
        if re.search(path_pat, href) and href.rstrip("/") != path_pat.rstrip("/") and href not in seen:
            seen.append(href)
    ranked = [h for h in seen if _TECH_HINT.search(h)] + [h for h in seen if not _TECH_HINT.search(h)]
    return [(fund, h if h.startswith("http") else base + h) for h in ranked[:limit]]


def src_oaktree(limit: int) -> list[tuple[str, str]]:
    """Oaktree 备忘录列表 → 最新 limit 篇 (fund, url)。"""
    soup = BeautifulSoup(_get("https://www.oaktreecapital.com/insights/memos"), "lxml")
    seen: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/insights/memo/" in href and href not in seen:
            seen.append(href)
    out = []
    for href in seen[:limit]:
        url = href if href.startswith("http") else "https://www.oaktreecapital.com" + href
        out.append(("Oaktree(Howard Marks)", url))
    return out


def src_blackrock(limit: int) -> list[dict]:
    """BlackRock BII 每周评论:单页原地更新(US 站不带合规门,corporate 站是声明墙)。
    letter_id 须按周唯一 → uid 掺首个 h2(本周主题),内容随抓随带免二次请求。"""
    url = "https://www.blackrock.com/us/individual/insights/blackrock-investment-institute/weekly-commentary"
    soup = BeautifulSoup(_get(url), "lxml")
    h2 = soup.find("h2")
    week = h2.get_text(strip=True) if h2 else ""
    return [{"fund": "BlackRock(BII周评)", "url": url, "uid": f"{url}|{week}",
             "title": f"Weekly commentary: {week}" if week else "Weekly market commentary",
             "text": _clean_text(soup)}][:limit]


def src_gs(limit: int) -> list[tuple[str, str]]:
    """GS 文章列表页纯 JS 渲染(静态只剩1链),改走 sitemap:带 lastmod=真实新旧序。"""
    xml = _get("https://www.goldmansachs.com/sitemap-1.xml")
    entries = re.findall(r"<loc>(https://www\.goldmansachs\.com/insights/articles/[^<]+)</loc>"
                         r"\s*(?:<lastmod>([^<]*)</lastmod>)?", xml)
    recent = [u for u, m in sorted(entries, key=lambda e: e[1] or "", reverse=True)][:20]
    ranked = [u for u in recent if _TECH_HINT.search(u)] + [u for u in recent if not _TECH_HINT.search(u)]
    return [("Goldman Sachs(Insights)", u) for u in ranked[:limit]]


def src_ms(limit: int) -> list[tuple[str, str]]:
    return _src_article_list("https://www.morganstanley.com/insights", "https://www.morganstanley.com",
                             r"/insights/articles/[a-z0-9-]+$", "Morgan Stanley(Insights)", limit)


SOURCES = {"oaktree": src_oaktree, "blackrock": src_blackrock, "gs": src_gs, "ms": src_ms}

B5_SYSTEM = ("你是投研信息整理器,不是分析师。只提炼原文作者的观点,严禁编造原文没有的信息,"
             "不加你自己的任何判断或建议。输出严格 JSON。")


def b5(fund: str, title: str, text: str) -> dict:
    text = text[:8000]
    user = f"""【基金信函】{fund}
【标题】{title}
【正文(可能截断)】
{text}

提炼为中文 JSON(只转述作者说了什么,不加判断):
{{
  "period": "信函期间(如 2026Q2 / 2026-07;判断不了就从标题取线索)",
  "core_views": ["作者核心观点1","观点2","观点3"],
  "stance": "看多|看空|谨慎|混合",
  "strategy": "全球宏观|多空|价值|困境债|量化|多策略|其他",
  "relevance": 相关度整数0-10(该信对"A股AI科技产业链"决策的启发程度),
  "relevant_points": ["与AI/算力/半导体/科技相关的具体点,没有则空数组"]
}}
core_views 中性转述作者观点,不许出现"因此应买X""看好Y"这类你自己的判断词。"""
    return llm.chat_json(B5_SYSTEM, user, timeout=240)


def main() -> None:
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.now(ZoneInfo(TZ)).strftime("%Y%m%d")
    which = sys.argv[2] if len(sys.argv) > 2 else "oaktree,blackrock,gs,ms"
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 2

    letters = []
    for key in which.split(","):
        fn = SOURCES.get(key)
        if not fn:
            print(f"  跳过未知源 {key}(可选: {list(SOURCES)})")
            continue
        try:
            targets = fn(limit)
        except Exception as e:  # noqa: BLE001 单源列表页失败不阻塞其余
            print(f"  ! 源 {key} 列表页失败: {str(e)[:100]}")
            continue
        for t in targets:
            fund, url = (t["fund"], t["url"]) if isinstance(t, dict) else t
            try:
                if isinstance(t, dict):  # 适配器自带内容(如 BlackRock 单页周评)
                    title, text, uid = t["title"], t["text"], t.get("uid") or url
                else:
                    title, text = _article_text(url)
                    uid = url
                if len(text) < 200:
                    print(f"  · 正文太短跳过 {url}")
                    continue
                s = b5(fund, title, text)
                lid = "fl:" + hashlib.sha1(uid.encode()).hexdigest()[:20]
                letters.append({
                    "letter_id": lid, "fund_name": fund, "title": title, "url": url,
                    "period": s.get("period"), "core_views": s.get("core_views") or [],
                    "stance": s.get("stance"), "strategy": s.get("strategy"),
                    "relevance": s.get("relevance"), "relevant_points": s.get("relevant_points") or [],
                    "status": "已摘要",
                })
                print(f"  ✓ {fund} | {title[:40]} | 相关度 {s.get('relevance')}")
            except Exception as e:  # noqa: BLE001 单篇失败不阻塞
                print(f"  ! 失败 {url}: {str(e)[:100]}")

    out = {"date": date, "n": len(letters), "letters": letters,
           "fetched_at": datetime.now(ZoneInfo(TZ)).isoformat()}
    d = ROOT / "exports"
    d.mkdir(exist_ok=True)
    p = d / f"fund_letters_{date}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{p}  ({len(letters)} 封)")


if __name__ == "__main__":
    main()
