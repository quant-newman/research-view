"""台北侧:抓西方科技/财经媒体 + 社交源 → 全球科技舆情原始条目。

只能台北跑(阿里云连不了外网,同 Yahoo)。产出交给 build_us._b1_wire 做中文化。
源:华尔街日报(WSJ RSS)、路透(走 Google News RSS 绕直连封锁)、科技媒体(TechCrunch/Ars)、
   Reddit(.rss,限流→礼貌UA+退避)。推特X 预留槽位(等账号名单)。
只落原始条目,不做判断;去重键=title;按关键词过滤到 AI/科技/半导体相关。
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from html import unescape
from pathlib import Path

import requests

# 复用 research_view.config 的 .env 加载(读 X cookie),standalone 运行时补 path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
try:
    from research_view import config as _cfg  # noqa: E402
    _cfg._load_dotenv()
except Exception:  # noqa: BLE001 config 不可用时退化为纯 os.environ
    pass

UA = "Mozilla/5.0 (compatible; mofangbot/1.0; +https://example.com/bot)"
TIMEOUT = 15

# (注册表key, 源显示名, 分组, url, 类型)  类型: rss=标准RSS<item>, atom=Atom<entry>
# key 对应 data/sources.json(enabled 开关/停更阈值),状态逐源上报 source_status
SOURCES = [
    ("wire_wsj_tech", "WSJ科技", "华尔街日报", "https://feeds.a.dj.com/rss/RSSWSJD.xml", "rss"),
    ("wire_wsj_markets", "WSJ市场", "华尔街日报", "https://feeds.a.dj.com/rss/RSSMarketsMain.xml", "rss"),
    ("wire_reuters", "路透", "路透社",
     "https://news.google.com/rss/search?q=when:1d+site:reuters.com&hl=en-US&gl=US&ceid=US:en", "rss"),
    ("wire_techcrunch", "TechCrunch", "科技媒体", "https://techcrunch.com/feed/", "rss"),
    ("wire_ars", "Ars Technica", "科技媒体", "https://feeds.arstechnica.com/arstechnica/index", "rss"),
    ("wire_reddit_wsb", "r/wallstreetbets", "Reddit", "https://www.reddit.com/r/wallstreetbets/hot.rss?limit=25", "atom"),
    ("wire_reddit_stocks", "r/stocks", "Reddit", "https://www.reddit.com/r/stocks/hot.rss?limit=25", "atom"),
    ("wire_reddit_tech", "r/technology", "Reddit", "https://www.reddit.com/r/technology/hot.rss?limit=25", "atom"),
    ("wire_reddit_hw", "r/hardware", "Reddit", "https://www.reddit.com/r/hardware/hot.rss?limit=15", "atom"),
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


def _norm_time(s: str | None) -> str:
    """把各种时间串(RSS RFC822 / ISO / X 'Thu Jul 02 ...')统一成 UTC+8 'YYYY-MM-DD HH:MM'。
    解析失败返回空串(前端不显示)。全系统时间口径 UTC+8,与 A股 新闻一致。"""
    if not s or not s.strip():
        return ""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    s = s.strip()
    dt = None
    try:  # RFC822: 'Wed, 02 Jul 2026 10:34:00 GMT'
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(s)
    except Exception:  # noqa: BLE001
        dt = None
    if dt is None:
        for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                dt = datetime.strptime(s.replace("Z", "+0000") if fmt.endswith("z") else s, fmt)
                break
            except Exception:  # noqa: BLE001
                continue
    if dt is None:
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:  # noqa: BLE001
            return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")


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
        pt = _local(node, "pubDate") or _local(node, "published") or _local(node, "updated")
        out.append({"title": title, "desc": desc, "url": url,
                    "time": _norm_time(pt.text if pt is not None else None)})
    return out


# 推特/X 监控名单(handle, 权重)。weight=2 为重点号,消息权重最高。
# 2026 免费抓取现状:nitter 大面积阵亡、RSSHub twitter 路由需鉴权、x.com 正文在鉴权GraphQL后。
# 抓取方案待定(xcancel白名单 / twikit+小号cookie / 官方API付费),定了再实现 _fetch_x。
X_ACCOUNTS = [
    ("aleabitoreddit", 2),  # serenity — 重点,最高权重
    ("wuxin_sir", 1), ("111_114390", 1), ("Kay2289123", 1), ("leto_bao", 1),
    ("xingpt", 1), ("RYANHINGSHING", 1), ("jimmyhuli", 1), ("EliasVanceQuant", 1),
    ("ohiain", 1), ("dons_korea", 1), ("_FORAB", 1), ("xiaomustock", 1),
    ("iamai_omni", 1), ("op7418", 1), ("Money_or_Life_X", 1), ("BiteyeCN", 1),
    ("leopoldasch", 1), ("hanking66", 1), ("wadezone", 1),
]


_INDICES_RE = re.compile(r"\(\w\[(\d{1,2})\],\s*16\)")


def _patch_twikit_ondemand() -> None:
    """X 2026 改了 webpack manifest:ondemand.s 的 hash 不再内联,而是 chunk-id→name +
    chunk-id→hash 两张表。twikit/tweety 的老正则失效→'KEY_BYTE indices' 报错。
    这里覆写 get_indices,按新格式重建 ondemand.s.<hash>a.js 再解析索引。X 若再改需跟着调。"""
    from twikit.x_client_transaction import transaction as _t

    async def get_indices(self, home_page_response, session, headers):  # noqa: ANN001
        page = str(self.validate_response(home_page_response) or self.home_page_response)
        mid = re.search(r'(\d+):"ondemand\.s"', page)
        mhash = re.search(rf'{mid.group(1)}:"([a-f0-9]+)"', page) if mid else None
        if not mhash:
            raise Exception("Couldn't get KEY_BYTE indices (manifest 格式又变了)")
        url = f"https://abs.twimg.com/responsive-web/client-web/ondemand.s.{mhash.group(1)}a.js"
        resp = await session.request(method="GET", url=url, headers=headers)
        idx = [int(x) for x in _INDICES_RE.findall(str(resp.text))]
        if not idx:
            raise Exception("Couldn't get KEY_BYTE indices")
        return idx[0], idx[1:]

    _t.ClientTransaction.get_indices = get_indices


X_MAX_AGE_DAYS = 14  # 超过此天数的推文视为陈旧,丢弃(冷门号别灌旧内容);解析失败则保留


def _too_old(created: str) -> bool:
    """created 形如 'Thu Jul 02 10:34:00 +0000 2026'。解析失败/为空→不判旧(保留)。"""
    if not created:
        return False
    try:
        from datetime import datetime, timedelta, timezone
        dt = datetime.strptime(created, "%a %b %d %H:%M:%S %z %Y")
        return (datetime.now(timezone.utc) - dt) > timedelta(days=X_MAX_AGE_DAYS)
    except Exception:  # noqa: BLE001 格式异动不误删
        return False


def _tweets_from_timeline(resp: dict) -> list[dict]:
    """从 user_tweets 原始 GraphQL 响应里挖推文,只取需要的字段(绕开 twikit 易腐的模型层)。"""
    tl = resp["data"]["user"]["result"]
    tl = tl.get("timeline_v2") or tl.get("timeline") or {}
    instrs = (tl.get("timeline") or {}).get("instructions", [])
    entries = next((i.get("entries", []) for i in instrs if i.get("type") == "TimelineAddEntries"), [])
    rows = []
    for e in entries:
        if not str(e.get("entryId", "")).startswith("tweet-"):
            continue
        try:
            tr = e["content"]["itemContent"]["tweet_results"]["result"]
        except (KeyError, TypeError):
            continue
        tw = tr.get("tweet", tr)
        lg = tw.get("legacy", {})
        if not lg or lg.get("retweeted_status_result") or lg.get("in_reply_to_status_id_str"):
            continue  # 跳过纯转推/回复,只留原创+引用
        if _too_old(lg.get("created_at", "")):
            continue
        note = (((tw.get("note_tweet") or {}).get("note_tweet_results") or {}).get("result") or {}).get("text")
        text = _clean(note or lg.get("full_text", ""), 500)
        rid = tw.get("rest_id") or lg.get("id_str")
        if text and rid:
            rows.append({"text": text, "id": rid, "created": lg.get("created_at", "")})
    return rows


async def _fetch_x_async(cookies: dict, per_high: int, per_norm: int) -> list[dict]:
    from twikit import Client  # 延迟导入,未装/未启用 X 时不影响其余源
    _patch_twikit_ondemand()
    client = Client("en-US")
    client.set_cookies(cookies)
    out: list[dict] = []
    for handle, weight in X_ACCOUNTS:
        want = per_high if weight >= 2 else per_norm
        try:
            uresp, _ = await client.gql.user_by_screen_name(handle)
            res = uresp["data"]["user"]["result"]
            if res.get("__typename") != "User" or not res.get("rest_id"):
                raise RuntimeError(res.get("__typename") or "no rest_id")
            tresp, _ = await client.gql.user_tweets(res["rest_id"], max(want * 3, 12), None)
            tweets = _tweets_from_timeline(tresp)
        except Exception as e:  # noqa: BLE001 单账号失败(风控/改名/私密)不阻塞其余
            print(f"  ! X @{handle} 取失败: {str(e)[:60]}")
            await asyncio.sleep(1.5)
            continue
        for tw in tweets[:want]:
            out.append({"title": tw["text"][:120], "desc": tw["text"],
                        "url": f"https://x.com/{handle}/status/{tw['id']}",
                        "src": f"@{handle}", "group": "推特X", "weight": weight,
                        "time": _norm_time(tw.get("created", ""))})
        print(f"  X @{handle}(w{weight}): {min(len(tweets), want)} 条")
        await asyncio.sleep(1.2)  # 礼貌间隔,降风控概率
    out.sort(key=lambda x: -x.get("weight", 1))  # 重点号(weight2)排前
    return out


def fetch_x(per_high: int = 8, per_norm: int = 3) -> tuple[list[dict], str]:
    """推特/X:twikit + 小号 cookie(.env 的 X_AUTH_TOKEN/X_CT0)。未配置则跳过不阻塞。
    返回 (items, 错误串);错误串非空=本轮 X 不可用,供信源面板可视化(X 会不定期挂)。"""
    auth, ct0 = os.environ.get("X_AUTH_TOKEN"), os.environ.get("X_CT0")
    if not (auth and ct0):
        print("  ! X 未配置 cookie(.env 缺 X_AUTH_TOKEN/X_CT0),跳过 X")
        return [], "未配置 cookie"
    try:
        return asyncio.run(_fetch_x_async({"auth_token": auth, "ct0": ct0}, per_high, per_norm)), ""
    except Exception as e:  # noqa: BLE001 X 整体失败(cookie 失效等)不阻塞其余源
        print(f"  ! X 抓取整体失败,跳过: {str(e)[:80]}")
        return [], str(e)[:120]


def fetch_wire(per_source: int = 12, rss_cap: int = 48) -> list[dict]:
    import source_status
    seen: set[str] = set()
    items: list[dict] = []
    stats: list[dict] = []
    for skey, name, group, url, kind in SOURCES:
        if not source_status.enabled(skey):
            print(f"  · 已停用(注册表),跳过: {name}")
            continue
        xml_text = _get(url)
        if not xml_text:
            print(f"  ! wire 源取失败,跳过: {name}")
            stats.append({"key": skey, "ok": False, "n": 0, "err": "取不到(超时/非200)"})
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
                          "src": name, "group": group, "time": it.get("time", "")})
            kept += 1
            if kept >= per_source:
                break
        print(f"  {name}({group}): {kept} 条")
        stats.append({"key": skey, "ok": True, "n": kept})
    # RSS 部分单独限量,X 全量保留(尤其 serenity 重点号不能被截掉)
    if source_status.enabled("wire_x"):
        xs, xerr = fetch_x()
        stats.append({"key": "wire_x", "ok": not xerr, "n": len(xs), "err": xerr})
    else:
        xs = []
        print("  · 已停用(注册表),跳过: X推特")
    source_status.report(stats)
    return items[:rss_cap] + xs


if __name__ == "__main__":
    ws = fetch_wire()
    print(f"\n共 {len(ws)} 条:")
    for w in ws[:20]:
        print(f"  [{w['group']}/{w['src']}] {w['title'][:70]}")
