"""B7 统计纯函数守护:Wilson 区间 + 覆写四桶 + 版本分组。无 DB 依赖。
运行:PYTHONPATH=src python tests/test_scorecard_stats.py(兼容 pytest)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_view.scorecard import _PROMPT_LABELS, _stats, override_slices, version_stats


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


if __name__ == "__main__":
    test_wilson(); test_override_buckets(); test_version_group()
    print("OK")
