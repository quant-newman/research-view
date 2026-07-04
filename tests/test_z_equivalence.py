"""z 口径等价守护:backtest._z_frame(向量化) 必须与 evidence._z(逐节点 dict) 输出一致。
两份实现各自演化会让回测与在线共振分悄悄漂移——一次写死,永久防漂(0a 关单补测顺手项)。

运行(数据节点或任何装了 pandas 的环境):
    PYTHONPATH=src python tests/test_z_equivalence.py
兼容 pytest。容差 1e-9。

不在等价范围内:evidence._z 的 n<3 截面全 0 守卫(生产截面=全部产业链节点,触不到);
_z_frame 对 NaN 输入的 fillna(0)(evidence 侧输入 dict 无 NaN 路径)。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd

from research_view.backtest import _z_frame
from research_view.evidence import _z

TOL = 1e-9


def _assert_row_equal(row: pd.Series, msg: str) -> dict:
    expect = _z(row.to_dict())
    got = _z_frame(row.to_frame().T).iloc[0].to_dict()
    for k in expect:
        assert abs(expect[k] - got[k]) <= TOL, \
            f"{msg}: {k} evidence={expect[k]!r} backtest={got[k]!r}"
    return got


def test_random_frames():
    """随机 50日×47节点截面,逐行对拍。"""
    rng = np.random.default_rng(42)
    df = pd.DataFrame(rng.normal(0.0, 5.0, size=(50, 47)),
                      columns=[f"n{i}" for i in range(47)])
    zf = _z_frame(df)
    for d in df.index:
        expect = _z(df.loc[d].to_dict())
        for k, v in expect.items():
            assert abs(v - zf.loc[d, k]) <= TOL, f"随机截面: 行{d} {k}"


def test_all_zero_cross_section():
    got = _assert_row_equal(pd.Series({f"n{i}": 0.0 for i in range(47)}), "全零截面须全0")
    assert all(abs(v) <= TOL for v in got.values())


def test_tiny_std():
    """std<1e-9 的近常数截面:两边都须全 0(不许除以微小 std 放大噪声)。"""
    got = _assert_row_equal(
        pd.Series({f"n{i}": 7.3 + i * 1e-12 for i in range(47)}), "std<1e-9 须全0")
    assert all(abs(v) <= TOL for v in got.values())


def test_zcap_clip():
    """单极端值截面:两边都须截断到 +3(并确认本 case 真的触发了截断)。"""
    vals = {f"n{i}": 0.0 for i in range(46)}
    vals["outlier"] = 1000.0
    got = _assert_row_equal(pd.Series(vals), "极端值须截断±3")
    assert abs(got["outlier"] - 3.0) <= TOL, f"截断未触发: outlier={got['outlier']}"


if __name__ == "__main__":
    test_random_frames()
    test_all_zero_cross_section()
    test_tiny_std()
    test_zcap_clip()
    print("z 口径等价:4/4 通过(容差 1e-9)")
