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
