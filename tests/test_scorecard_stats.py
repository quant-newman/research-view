"""B7 统计纯函数守护:Wilson 区间 + 覆写四桶 + 版本分组。无 DB 依赖。
运行:PYTHONPATH=src python tests/test_scorecard_stats.py(兼容 pytest)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from decimal import Decimal

from research_view.evidence import parse_prob
from research_view.scorecard import (_PROMPT_LABELS, _stats, brier_by_version,
                                     brier_stats, override_slices, version_stats)


def test_wilson():
    s = _stats([("对",)] * 7 + [("错",)] * 3 + [("平",)] * 2)
    assert s["n"] == 12 and s["right"] == 7 and s["flat"] == 2
    assert s["hit_rate"] == 70.0
    assert 39.0 < s["hit_lo"] < 41.0   # 7/10 Wilson95 ≈ [39.7, 89.2]
    assert 88.0 < s["hit_hi"] < 90.0
    empty = _stats([("平",)])
    assert empty["hit_rate"] is None and empty["hit_lo"] is None


def test_override_buckets():
    rows = [
        ("偏多",  1.2, "对", "对"),   # agree
        ("偏空",  0.8, "对", "错"),   # override:LLM对/机械错
        ("偏多",  0.0, "错", "错"),   # llm_only(机械中性)
        ("中性", -0.5, "对", "对"),   # suppress
        ("中性",  0.0, "对", "对"),   # 双中性 → 丢弃
        ("偏多", None, "平", None),   # raw None→机械中性→llm_only;mech 列跳 None
    ]
    out = override_slices(rows)
    assert out["agree"]["llm"]["n"] == 1
    assert out["override"]["llm"]["right"] == 1 and out["override"]["mech"]["wrong"] == 1
    assert out["llm_only"]["llm"]["n"] == 2 and out["llm_only"]["mech"]["n"] == 1
    assert out["suppress"]["llm"]["n"] == 1
    assert sum(b["llm"]["n"] for b in out.values()) == 5  # 双中性已剔


def test_version_group():
    # 16位真值键(sql/024 口径)+ 存量 NULL 卡归 unversioned
    out = version_stats([("ffb0a6cccf2c61b7", "对"), ("ffb0a6cccf2c61b7", "错"), (None, "对")])
    assert out["ffb0a6cccf2c61b7"]["n"] == 2 and out["ffb0a6cccf2c61b7"]["hit_rate"] == 50.0
    assert out["ffb0a6cccf2c61b7"]["label"].startswith("B6 v2模板")
    assert out["unversioned"]["n"] == 1
    assert out["unversioned"]["label"] == _PROMPT_LABELS["unversioned"]
    # 未登记哈希原样显示,不阻塞
    assert version_stats([("deadbeef00000000", "对")])["deadbeef00000000"]["label"] == "deadbeef00000000"


def test_brier():
    # 人工复算(#40 验收口径):对=1,错/平=0,平不剔除
    # ((0.7-1)²+(0.7-0)²+(0.5-0)²)/3 = (0.09+0.49+0.25)/3 = 0.2767
    s = brier_stats([(Decimal("0.7"), "对"), (0.7, "错"), (0.5, "平")])
    assert s["n"] == 3 and s["brier"] == 0.2767
    # 校准桶:0.7×2 落 [0.6,0.8) 实际兑现率 0.5;0.5 落 [0.4,0.6) 兑现率 0
    b = {(x["lo"], x["hi"]): x for x in s["bins"]}
    assert b[(0.6, 0.8)]["n"] == 2 and b[(0.6, 0.8)]["hit_rate"] == 0.5
    assert b[(0.4, 0.6)]["p_mean"] == 0.5 and b[(0.4, 0.6)]["hit_rate"] == 0.0
    # NULL prob 卡不参与;全 NULL = 诚实空态
    assert brier_stats([(None, "对")])["n"] == 0
    assert brier_stats([])["brier"] is None
    # 版本分组:NULL 哈希归 unversioned,已登记哈希带标签
    bv = brier_by_version([("a778927f2c31ef56", 0.6, "对"), (None, None, "错"),
                           (None, 0.8, "错")])
    assert bv["a778927f2c31ef56"]["n"] == 1 and bv["a778927f2c31ef56"]["brier"] == 0.16
    assert bv["a778927f2c31ef56"]["label"].startswith("B6 v3模板")
    assert bv["unversioned"]["n"] == 1 and bv["unversioned"]["brier"] == 0.64


def test_parse_prob():
    # 开区间(同 sql/028 CHECK):0/1/越界/垃圾 → None 不阻塞发卡
    assert parse_prob(0.55) == 0.55
    assert parse_prob("0.62") == 0.62  # LLM 偶发字符串数字
    for bad in (0, 1, 1.2, -0.1, "high", None, "", [0.5]):
        assert parse_prob(bad) is None


if __name__ == "__main__":
    test_wilson(); test_override_buckets(); test_version_group()
    test_brier(); test_parse_prob()
    print("OK")
