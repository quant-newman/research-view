"""台北侧:抓海外基金信函/大行展望 → DeepSeek B5 中文摘要 → exports/fund_letters_DATE.json。

只能台北 AWS 机跑(国内连不了海外站)。用 .venv-taipei(含 bs4/lxml)。
v1 源:Oaktree/霍华德·马克斯备忘录(静态 HTML,可解析)。SOURCES 里加适配器即可扩展。
B5 铁律:只转述作者观点,不编造、不加自己的判断;评"对A股AI科技链"的相关度。

用法: ./.venv-taipei/bin/python scripts/fetch_fund_letters.py [YYYYMMDD] [源key,逗号分隔] [每源篇数]
"""
from __future__ import annotations

import hashlib
import json
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


def _article_text(url: str) -> tuple[str, str]:
    """通用正文抽取:h1 作标题,长段落 <p> 拼正文。"""
    soup = BeautifulSoup(_get(url), "lxml")
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else url
    ps = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    text = "\n".join(p for p in ps if len(p) > 40)
    return title, text


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


SOURCES = {"oaktree": src_oaktree}

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
    which = sys.argv[2] if len(sys.argv) > 2 else "oaktree"
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
        for fund, url in targets:
            try:
                title, text = _article_text(url)
                if len(text) < 200:
                    print(f"  · 正文太短跳过 {url}")
                    continue
                s = b5(fund, title, text)
                lid = "fl:" + hashlib.sha1(url.encode()).hexdigest()[:20]
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
