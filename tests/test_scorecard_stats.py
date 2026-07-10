"""B7 统计纯函数守护:Wilson 区间 + 覆写四桶 + 版本分组。无 DB 依赖。
运行:PYTHONPATH=src python tests/test_scorecard_stats.py(兼容 pytest)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from decimal import Decimal

from research_view.evidence import parse_prob
from research_view.scorecard import (_PROMPT_LABELS, _stats, brier_by_version,
                                     brier_stats, calibration_block, headline_stats,
                                     override_slices, version_stats)


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
    # 16位真值键(sql/024 口径,#41 重登后:07-06 复合版本纪元)+ 存量 NULL 卡归 unversioned
    out = version_stats([("8528ca795ca4c6b8", "对"), ("8528ca795ca4c6b8", "错"), (None, "对")])
    assert out["8528ca795ca4c6b8"]["n"] == 2 and out["8528ca795ca4c6b8"]["hit_rate"] == 50.0
    assert out["8528ca795ca4c6b8"]["label"].startswith("B6 v3·07-06起")
    assert _PROMPT_LABELS["780916554dc9be8b"].startswith("B8 v2·07-06起")
    assert out["unversioned"]["n"] == 1
    assert out["unversioned"]["label"] == _PROMPT_LABELS["unversioned"]
    # 死键已删(库内永不出现:0b 周末零卡 + 0a 质检修正前零卡)
    for dead in ("ffb0a6cccf2c61b7", "fe67e54832acdb4f", "a778927f2c31ef56", "cd3655bba4858708"):
        assert dead not in _PROMPT_LABELS
    # 未登记哈希原样显示,不阻塞
    assert version_stats([("deadbeef00000000", "对")])["deadbeef00000000"]["label"] == "deadbeef00000000"


def test_brier():
    # BRIER_SPEC 口径:样本域=对/错,平剔除但必报未判定率(SPEC第1条);对=1/错=0(第2条)
    # 人工复算(SPEC第5条审计口径):((0.7-1)²+(0.7-0)²)/2 = (0.09+0.49)/2 = 0.29
    s = brier_stats([(Decimal("0.7"), "对"), (0.7, "错"), (0.55, "平")])
    assert s["n"] == 2 and s["brier"] == 0.29
    assert s["n_flat"] == 1 and s["flat_rate"] == round(1 / 3, 3)
    # 固定边界桶(SPEC第4条):0.7×2 落 [0.7,0.8);0.55(平)已剔除不进桶
    b = {(x["lo"], x["hi"]): x for x in s["bins"]}
    assert b[(0.7, 0.8)]["n"] == 2 and b[(0.7, 0.8)]["hit_rate"] == 0.5
    assert (0.5, 0.6) not in b
    # NULL prob 卡跳过(存量旧卡,SPEC第1条);全 NULL/空 = 诚实空态
    assert brier_stats([(None, "对")])["n"] == 0
    assert brier_stats([])["brier"] is None and brier_stats([])["flat_rate"] is None
    # 全平:Brier 无样本但未判定率必报
    allflat = brier_stats([(0.8, "平")])
    assert allflat["n"] == 0 and allflat["n_flat"] == 1 and allflat["flat_rate"] == 1.0
    # 卡型分层(SPEC第3条):中性卡与方向卡禁混桶
    cb = calibration_block([("8528ca795ca4c6b8", "偏多", 0.7, "对"),
                            ("8528ca795ca4c6b8", "偏空", 0.7, "错"),
                            ("8528ca795ca4c6b8", "中性", 0.8, "对")])
    assert cb["direction"]["n"] == 2 and cb["direction"]["brier"] == 0.29
    assert cb["neutral"]["n"] == 1 and cb["neutral"]["brier"] == 0.04
    assert cb["by_version"]["8528ca795ca4c6b8"]["n"] == 3  # 版本标量跨卡型,仅漂移检测
    # 版本分组:NULL 哈希归 unversioned,已登记哈希带标签,平剔除同口径
    bv = brier_by_version([("8528ca795ca4c6b8", 0.6, "对"), (None, None, "错"),
                           (None, 0.8, "错"), (None, 0.9, "平")])
    assert bv["8528ca795ca4c6b8"]["n"] == 1 and bv["8528ca795ca4c6b8"]["brier"] == 0.16
    assert bv["8528ca795ca4c6b8"]["label"].startswith("B6 v3·07-06起")
    assert bv["unversioned"]["n"] == 1 and bv["unversioned"]["brier"] == 0.64
    assert bv["unversioned"]["n_flat"] == 1


def test_brier_uncond():
    # vNext 主指标(VNEXT_MEASUREMENT a):无条件口径——平计入样本,outcome 对=1/错=0/平=0
    # 人工复算:((0.8-1)²+(0.7-0)²+(0.6-0)²)/3 = (0.04+0.49+0.36)/3 = 0.296667→0.2967
    rows = [(Decimal("0.8"), "对"), (0.7, "错"), (0.6, "平")]
    u = brier_stats(rows, unconditional=True)
    assert u["n"] == 3 and u["brier"] == 0.2967
    assert u["n_flat"] == 1 and u["flat_rate"] == round(1 / 3, 3)  # 分母=含平样本数
    # 平进桶且 outcome=0:0.6 落 [0.6,0.7) 桶,hit_rate=0(未兑现)
    b = {(x["lo"], x["hi"]): x for x in u["bins"]}
    assert b[(0.6, 0.7)]["n"] == 1 and b[(0.6, 0.7)]["hit_rate"] == 0.0
    # 默认参数=现行条件口径,行为零变化(同批 rows:平剔除,(0.04+0.49)/2=0.265)
    c = brier_stats(rows)
    assert c["n"] == 2 and c["brier"] == 0.265 and c["flat_rate"] == round(1 / 3, 3)
    # 两序列并列:条件 flat_rate 分母=n+n_flat,无条件分母=n(平已在 n 内)
    allflat = brier_stats([(0.8, "平")], unconditional=True)
    assert allflat["n"] == 1 and allflat["brier"] == 0.64 and allflat["flat_rate"] == 1.0
    # calibration_block 透传:分层与版本组同口径切换
    cb = calibration_block([("8528ca795ca4c6b8", "偏多", 0.7, "平")], unconditional=True)
    assert cb["direction"]["n"] == 1 and cb["direction"]["brier"] == 0.49
    assert cb["by_version"]["8528ca795ca4c6b8"]["n"] == 1
    assert calibration_block([("8528ca795ca4c6b8", "偏多", 0.7, "平")])["direction"]["n"] == 0
    # NULL prob 跳过与空态同现行
    assert brier_stats([(None, "对")], unconditional=True)["n"] == 0
    assert brier_stats([], unconditional=True)["brier"] is None


def test_headline():
    # vNext headline 三件套(VNEXT_MEASUREMENT b):方向卡命中率(Wilson)+覆盖率+中性率
    rows = [("偏多", "对"), ("偏多", "平"), ("偏空", "错"), ("中性", "对")]
    h = headline_stats(rows)
    assert h["directional"]["n"] == 3 and h["directional"]["right"] == 1
    assert h["directional"]["hit_rate"] == 50.0          # 1/(1+1),平不进分母
    assert h["directional"]["hit_lo"] is not None        # Wilson 随 _stats 自动继承
    assert h["coverage"] == round(2 / 3 * 100, 1)        # (对+错)/方向卡数
    assert h["neutral_rate"] == 25.0                     # 1/4
    # 全中性/空态:方向层诚实空,不除零
    allneutral = headline_stats([("中性", "对")])
    assert allneutral["directional"]["n"] == 0 and allneutral["coverage"] is None
    assert allneutral["neutral_rate"] == 100.0
    empty = headline_stats([])
    assert empty["coverage"] is None and empty["neutral_rate"] is None


def test_parse_prob():
    # 开区间(同 sql/028 CHECK):0/1/越界/垃圾 → None 不阻塞发卡
    assert parse_prob(0.55) == 0.55
    assert parse_prob("0.62") == 0.62  # LLM 偶发字符串数字
    for bad in (0, 1, 1.2, -0.1, "high", None, "", [0.5]):
        assert parse_prob(bad) is None


if __name__ == "__main__":
    test_wilson(); test_override_buckets(); test_version_group()
    test_brier(); test_brier_uncond(); test_headline(); test_parse_prob()
    print("OK")
