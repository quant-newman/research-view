"""叙述层指纹门控(2026-08-21 降本批):盘中每 15min 一档,输入没变就不该再烧 DeepSeek。

钉住两件事:
1. 指纹只认离散的叙事驱动字段——ret_1d 与净额尾数这类连续行情量若混进来,指纹恒变、
   门控形同虚设(省不下任何调用),这是最容易被后续改动悄悄破坏的地方;
2. 命中缓存时确实不调 LLM,且统计数字仍取最新一档(复用的只有叙述)。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from research_view import hotspots as H, llm, research_digest as RD  # noqa: E402

ROW = dict(node_id="n1", chain="半导体", node="存储", heat=9.0, trend="升温",
           news_today=3, news_prior=1, pos=2, neg=0, ret_1d=1.23, lhb=2, mf=3.4,
           latest_time="10:00", stocks=["兆易创新", "北京君正"], news=["A公司涨价", "B公司扩产"])


def _boom(*a, **k):
    raise AssertionError("命中缓存却仍调了 LLM")


@pytest.mark.parametrize("patch,same", [
    ({"ret_1d": 4.56}, True),    # 连续行情量:不进指纹
    ({"mf": 3.9}, True),         # 净额尾数:不进指纹
    ({"mf": 9.9}, False),        # 5亿粗档大位移:必须重算
    ({"news": ["A公司涨价", "B公司扩产", "C公司中标"]}, False),
    ({"news_today": 4}, False),
    ({"pos": 3}, False),
    ({"lhb": 5}, False),
])
def test_hotspot_sig_fields(patch, same):
    assert (H._sig([ROW]) == H._sig([{**ROW, **patch}])) is same


def test_hotspot_cache_hit_reuses_narrative_not_stats(monkeypatch):
    monkeypatch.setattr(H, "_signals", lambda d: [ROW])
    monkeypatch.setattr(H, "_cached", lambda d, s: {
        "headline": "旧总览", "pos": ["利好1"], "neg": [],
        "items": [{"node_id": "n1", "reason": "旧归因", "trend": "升温"}]})
    monkeypatch.setattr(llm, "chat_json", _boom)
    out = H.generate("20260821")
    assert out["headline"] == "旧总览" and out["brief"]["pos"] == ["利好1"]
    assert out["items"][0]["reason"] == "旧归因"
    assert out["items"][0]["heat"] == 9.0 and out["items"][0]["mf"] == 3.4  # 统计仍是最新档
    assert out["sig"] == H._sig([ROW])


def test_hotspot_llm_failure_leaves_no_sig(monkeypatch):
    """降级兜底榜不落指纹,否则会被当成"已生成"钉死一整天。"""
    monkeypatch.setattr(H, "_signals", lambda d: [ROW])
    monkeypatch.setattr(H, "_cached", lambda d, s: None)
    monkeypatch.setattr(llm, "chat_json", _boom)
    out = H.generate("20260821")
    assert out["sig"] is None and out["items"][0]["reason"]


BY_CODE = {"300661": {"name": "圣邦股份", "scope": "核心",
                      "reports": [{"title": "模拟芯片复苏", "rating": "买入", "tp": 100.0}]}}


def test_digest_views_cache_hit(monkeypatch):
    monkeypatch.setattr(RD, "_cached_views", lambda d, s: {"300661": "旧观点"})
    monkeypatch.setattr(llm, "chat_json", _boom)
    rows, sig = RD._views("20260821", BY_CODE)
    assert rows[0]["view"] == "旧观点" and rows[0]["latest_tp"] == 100.0 and sig


def test_digest_views_failure_leaves_no_sig(monkeypatch):
    monkeypatch.setattr(RD, "_cached_views", lambda d, s: None)
    monkeypatch.setattr(llm, "chat_json", _boom)
    rows, sig = RD._views("20260821", BY_CODE)
    assert rows[0]["view"] is None and sig is None


# ---- 夜间调用窗口(2026-08-24 降本批#2)----
# 钉住三件事:窗口边界(跨零点,最容易写成 and)、白天补做点的 15min 宽限(cron 火点到
# 真正执行之间隔着 flock 排队,卡死精确 HHMM 会让补做点凭空丢失)、白天静默档里叙述层
# 降级为"沿用当天上一版且不落指纹"(落了指纹就会把白天的旧叙述钉到夜间去)。
from datetime import datetime  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

from research_view import config  # noqa: E402


def _at(hhmm: str) -> datetime:
    return datetime(2026, 8, 24, int(hhmm[:2]), int(hhmm[2:]), tzinfo=ZoneInfo(config.TZ))


@pytest.mark.parametrize("hhmm,ok", [
    ("1800", True), ("2330", True), ("0000", True), ("0759", True),  # 夜间窗口(跨零点)
    ("0800", False), ("1200", False), ("1730", False), ("1759", False),  # 白天静默
    ("0945", True), ("0952", True), ("0959", True), ("1000", False),  # 补做点 + 15min 宽限
    ("1515", True), ("1529", True), ("1530", False), ("1514", False),
])
def test_llm_window(monkeypatch, hhmm, ok):
    monkeypatch.delenv("RV_LLM_FORCE", raising=False)
    monkeypatch.delenv("LLM_DAY_SLOTS", raising=False)
    assert config.llm_allowed(_at(hhmm))[0] is ok


def test_llm_window_force_and_slot_override(monkeypatch):
    monkeypatch.delenv("LLM_DAY_SLOTS", raising=False)
    monkeypatch.setenv("RV_LLM_FORCE", "1")
    assert config.llm_allowed(_at("1200"))[0] is True     # 手动补跑豁免
    monkeypatch.delenv("RV_LLM_FORCE")
    monkeypatch.setenv("LLM_DAY_SLOTS", "1300")
    assert config.llm_allowed(_at("1300"))[0] is True     # 补做点可配
    assert config.llm_allowed(_at("0945"))[0] is False    # 覆盖即替换,不是叠加


def test_hotspot_daytime_reuses_without_pinning_sig(monkeypatch):
    """白天静默档:不调 LLM,沿用当天上一版叙述,但 sig 必须置空——否则夜间开窗后
    指纹一致会直接命中这份白天的旧叙述,门控变成"一天只生成一次"。"""
    monkeypatch.setattr(H, "_signals", lambda d: [ROW])
    monkeypatch.setattr(H.config, "llm_allowed", lambda now=None: (False, "白天静默档1200"))
    monkeypatch.setattr(H.llm, "chat_json", _boom)
    monkeypatch.setattr(H, "_cached", lambda d, s: None if s else {
        "headline": "上一版总览", "pos": [], "neg": [],
        "items": [{"node_id": "n1", "reason": "上一版归因", "trend": "升温"}]})
    out = H.generate("20260824")
    assert out["sig"] is None
    assert out["headline"] == "上一版总览"
    assert out["items"][0]["reason"] == "上一版归因"
    assert out["items"][0]["ret_1d"] == 1.23  # 统计行仍是最新一档


def test_hotspot_daytime_without_any_narrative_falls_back_to_stats(monkeypatch):
    monkeypatch.setattr(H, "_signals", lambda d: [ROW])
    monkeypatch.setattr(H.config, "llm_allowed", lambda now=None: (False, "白天静默档1200"))
    monkeypatch.setattr(H.llm, "chat_json", _boom)
    monkeypatch.setattr(H, "_cached", lambda d, s: None)
    out = H.generate("20260824")
    assert out["sig"] is None and out["items"][0]["reason"]  # 统计兜底文案,不空着


def test_digest_daytime_reuses_without_pinning_sig(monkeypatch):
    by_code = {"300661": {"name": "圣邦股份", "scope": "core",
                          "reports": [{"title": "模拟芯片复苏", "rating": "买入", "tp": 100.0}]}}
    monkeypatch.setattr(RD.config, "llm_allowed", lambda now=None: (False, "白天静默档1200"))
    monkeypatch.setattr(RD.llm, "chat_json", _boom)
    monkeypatch.setattr(RD, "_cached_views", lambda d, s: None if s else {"300661": "上一版观点"})
    views, sig = RD._views("20260824", by_code)
    assert sig is None and views[0]["view"] == "上一版观点"
