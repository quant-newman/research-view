"""P0 个股机械基线修复(stock_raw_mech)回归——P0_MECH_FIX_DESIGN §8 预注册九项 + 勘误 E1。

两层覆盖:
1) 纯函数层(不连库):raw 加权和公式、E0 误差带三段(0.017 端点/0.01 带内/±0.018 带外)、
   E1 全精度 =0 机械中性、混合方向集非恒等(勘误 E1 第 1 条)、对账等式
   n_total=n_directional+n_neutral+n_indeterminate、override 四桶换 raw 符号非 alignment 符号。
2) postgres:18 临时容器真 SQL 集成:score_mature E1/E0 双路径落 mech_verdict、
   indeterminate 记 NULL 不静默消失、B8 正式 verdict 与原口径逐位一致(边界零泄漏)、
   已记分存量零 UPDATE、decision_card append-only 触发器兜底、persist 落 w1 两列。
   只连本地一次性容器,禁连生产。
运行:PYTHONPATH=src python3 -m pytest tests/test_p0_stock_raw_mech.py -v
"""
import json
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import psycopg  # noqa: E402
import pytest  # noqa: E402

from research_view import config, db, decision, llm, scorecard  # noqa: E402
from research_view.scorecard import (_W1_BAND, _e0_dir, _verdict,  # noqa: E402
                                     override_slices, raw_w1_recalc2dp,
                                     stock_baseline_stats, stock_mech_class,
                                     stock_override_slices)


def _mx(price=0.0, mf=0.0, news=0.0, lhb=0.0):
    return {"price": {"z": price}, "mf": {"z": mf}, "news": {"z": news}, "lhb": {"z": lhb}}


# ---------- 1) 纯函数层 ----------

def test_raw_directional_weights_and_negative():
    """§8-1 偏空用例:合成负向 dz → raw<0;权重逐项=w1(1.0/1.0/0.8/0.6),attn 不参与。"""
    dz = {"price": -1.0, "mf": -0.5, "news": -0.25, "lhb": -0.5}
    assert decision.raw_directional(dz) == pytest.approx(-1.0 - 0.5 - 0.2 - 0.3)
    assert decision.raw_directional({"price": 1.0, "mf": 0, "news": 0, "lhb": 0}) == 1.0
    assert decision.raw_directional({"price": 0, "mf": 0, "news": 1.0, "lhb": 0}) == 0.8
    assert decision.raw_directional({"price": 0, "mf": 0, "news": 0, "lhb": 1.0}) == 0.6
    assert decision._WEIGHT_VERSION == "w1"


def test_e0_band_endpoint_and_inside():
    """§8-2:|raw|=0.017(端点)与 0.01 → indeterminate;§8-3:±0.018 正常判向。"""
    assert _W1_BAND == 0.017
    for raw in (0.017, -0.017, 0.01, -0.01, 0.0, None):
        assert _e0_dir(raw) is None
    assert _e0_dir(0.018) == "偏多"
    assert _e0_dir(-0.018) == "偏空"
    assert _e0_dir(2.5) == "偏多"


def test_e0_matrix_recalc_paths():
    """E0 派生重算走 matrix 两位小数 z:带内/带外/缺源三态。"""
    assert raw_w1_recalc2dp(_mx(price=0.01, lhb=0.01)) == pytest.approx(0.016)
    assert stock_mech_class(None, _mx(price=0.01, lhb=0.01)) == ("e0", None)
    assert stock_mech_class(None, _mx(lhb=-0.03)) == ("e0", "偏空")  # 0.6×-0.03=-0.018 带外
    assert stock_mech_class(None, _mx(price=0.5, mf=0.3)) == ("e0", "偏多")
    # 缺源/坏 matrix → None → indeterminate,禁强判(不猜方向)
    assert raw_w1_recalc2dp({"price": {"z": 0.5}}) is None
    assert raw_w1_recalc2dp(None) is None
    assert stock_mech_class(None, {}) == ("e0", None)


def test_e1_full_precision_zero_is_neutral():
    """§8-4:新卡全精度 =0 → 机械中性,记分走中性 ±2pp 口径;E0 的 0 是 indeterminate 不混同。"""
    assert stock_mech_class(0.0, {}) == ("e1", "中性")
    assert stock_mech_class(-2.5, {}) == ("e1", "偏空")
    assert stock_mech_class(1.2, {}) == ("e1", "偏多")
    assert _verdict("中性", 1.9) == "对" and _verdict("中性", -2.0) == "对"
    assert _verdict("中性", 2.1) == "错" and _verdict("中性", -2.1) == "错"
    assert stock_mech_class(None, _mx()) == ("e0", None)  # E0 全零=带内,≠中性


def test_mixed_set_not_structurally_constant():
    """§8-5 + 勘误 E1 第 1 条:混合方向合成集两纪元均产出偏多与偏空(杀死恒偏多)。"""
    e1_dirs = {stock_mech_class(r, {})[1] for r in (-2.5, -0.1, 0.0, 0.3, 4.0)}
    e0_dirs = {stock_mech_class(None, m)[1]
               for m in (_mx(price=-1.2), _mx(mf=0.8), _mx(price=0.01), _mx(lhb=-0.03))}
    assert {"偏多", "偏空"} <= e1_dirs and "中性" in e1_dirs
    assert {"偏多", "偏空"} <= e0_dirs and None in e0_dirs


def test_baseline_stats_reconcile_equation():
    """§8-8 对账等式 + §6 披露:分纪元 n_total=n_directional+n_neutral+n_indeterminate,
    indeterminate 不入 mech 样本但计数可见;legacy 块只封存 E0 原列。"""
    rows = [  # (excess, mech_verdict存量列, raw_col, matrix)
        (7.0, "对", None, _mx(price=0.5)),          # E0 带外偏多,artifact列'对'
        (-9.0, "对", None, _mx(lhb=-0.03)),         # E0 带外偏空 → 派生 mech=对
        (1.0, None, None, _mx(price=0.01)),         # E0 带内 indeterminate
        (-9.0, "错", -2.5, {}),                     # E1 偏空 → 派生 mech=对
        (3.0, None, 0.0, {}),                       # E1 中性 → |3|>2 → mech=错
        (7.0, "对", 1.2, {}),                       # E1 偏多 → mech=对
    ]
    out = stock_baseline_stats(rows)
    e0, e1 = out["e0"], out["e1"]
    assert e0["n_total"] == 3 and e0["n_directional"] == 2 \
        and e0["n_neutral"] == 0 and e0["n_indeterminate"] == 1
    assert e1["n_total"] == 3 and e1["n_directional"] == 2 \
        and e1["n_neutral"] == 1 and e1["n_indeterminate"] == 0
    for b in (e0, e1):
        assert b["n_total"] == b["n_directional"] + b["n_neutral"] + b["n_indeterminate"]
    assert e0["mech"]["n"] == 2 and e1["mech"]["n"] == 3       # indeterminate 不入样本…
    assert e0["n_total"] + e1["n_total"] == len(rows)          # …但没有静默消失
    assert e0["weight_version"] == "w1_recalc2dp" and e0["band"] == _W1_BAND
    assert e1["weight_version"] == "w1"
    assert e0["mech"] == {"n": 2, "right": 2, "wrong": 0, "flat": 0,
                          "hit_rate": 100.0, "hit_lo": e0["mech"]["hit_lo"],
                          "hit_hi": e0["mech"]["hit_hi"]}
    assert e1["mech"]["right"] == 2 and e1["mech"]["wrong"] == 1
    assert out["always_long"]["n"] == 6
    legacy = out["legacy_mech_verdict_col"]
    assert legacy["n"] == 2 and "artifact" in legacy["label"]  # E0 两条非空原列,E1 不入


def test_override_slices_uses_raw_not_alignment():
    """§8-9:四桶配对用 raw 符号;indeterminate 剔除并计数。旧口径(alignment 恒正)
    会把 LLM偏多+raw为负 误入 agree——新口径必须入 override。"""
    rows = [  # (direction, raw_col, matrix, verdict, excess)
        ("偏多", -2.5, {}, "错", -9.0),             # raw 偏空 vs LLM 偏多 → override
        ("偏多", 1.2, {}, "对", 7.0),               # agree
        ("偏多", 0.0, {}, "对", 3.0),               # E1 机械中性 → llm_only
        ("中性", -2.5, {}, "对", -1.0),             # suppress
        ("偏多", None, _mx(price=0.01), "对", 1.0),  # E0 indeterminate → 剔除+计数
    ]
    out = stock_override_slices(rows)
    assert out["n_indeterminate"] == 1
    # §6 对账三计数随桶披露:总数=方向+中性+indeterminate
    assert out["n_total"] == 5 and out["n_directional"] == 3 and out["n_neutral"] == 1
    assert out["n_total"] == out["n_directional"] + out["n_neutral"] + out["n_indeterminate"]
    assert out["override"]["llm"]["n"] == 1 and out["agree"]["llm"]["n"] == 1
    assert out["llm_only"]["llm"]["n"] == 1 and out["suppress"]["llm"]["n"] == 1
    # 同一批卡走旧口径(alignment 恒 ≥1.0):override 桶为空 → 证明配对符号已换
    old = override_slices([("偏多", 1.9, "错", "对"), ("偏多", 2.6, "对", "对"),
                           ("偏多", 1.1, "对", "错"), ("中性", 1.4, "对", "对"),
                           ("偏多", 1.2, "对", None)])
    assert old["override"]["llm"]["n"] == 0 and old["agree"]["llm"]["n"] == 4


# ---------- 2) postgres:18 临时容器真 SQL 集成 ----------

DDL = """
CREATE OR REPLACE FUNCTION ledger_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'ledger 是只读账本,不允许 % (append-only)', TG_OP;
END;
$$ LANGUAGE plpgsql;
CREATE TABLE decision_card (
    card_id      bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    trade_date   date NOT NULL, code text NOT NULL, name text, ts_code text,
    node_id text, node_card_id bigint, direction text NOT NULL, confidence text,
    subjective_prob numeric, horizon_days int NOT NULL DEFAULT 5, thesis text,
    entry_cond text, exit_cond text, evidence jsonb, falsify text, matrix jsonb,
    alignment numeric, close numeric, model text, prompt_hash text,
    raw_directional_score numeric, weight_version text,
    created_at timestamptz NOT NULL DEFAULT now());
CREATE TRIGGER trg_dcard_no_mod BEFORE UPDATE OR DELETE ON decision_card
    FOR EACH ROW EXECUTE FUNCTION ledger_append_only();
CREATE TRIGGER trg_dcard_no_trunc BEFORE TRUNCATE ON decision_card
    FOR EACH STATEMENT EXECUTE FUNCTION ledger_append_only();
CREATE TABLE decision_score (card_id bigint PRIMARY KEY, trade_date date, code text,
    end_date date, stock_ret numeric, pool_ret numeric, excess numeric,
    verdict text, mech_verdict text, created_at timestamptz DEFAULT now());
CREATE TABLE judgment_card (card_id bigint PRIMARY KEY, trade_date date, node_id text,
    direction text, horizon_days int, resonance numeric);
CREATE TABLE card_score (card_id bigint PRIMARY KEY);
CREATE TABLE stock (code text PRIMARY KEY, ts_code text);
CREATE TABLE stock_node (node_id text, code text);
CREATE TABLE ref_membership_snap (snap_date date, node_id text, code text,
    ts_code text, tier text);
CREATE SCHEMA md;
CREATE TABLE md.trade_calendar (cal_date date, is_open boolean);
CREATE TABLE md.bar_daily_raw (ts_code text, trade_date date, close numeric);
"""

# 池=7 票,d0=2026-06-01,horizon 5 → d1=2026-06-08;区间收益(%)如下,池均值=-1。
# 各卡 excess 须离 ±1pp/±2pp 判定端点 ≥1pp:verdict 按全精度 excess 判、存档才 round 2dp,
# 端点上池均值的浮点误差会让两侧读数分叉(线上先例 card_id=129)。
_RETS = {"A0": 2.0, "A1": -10.0, "A2": 2.0, "A3": 6.0, "A4": 4.0, "A5": -10.0, "A6": -1.0}
_POOL_RET = -1.0

# (code, LLM方向, raw列, matrix, 期望mech_verdict, 期望verdict)——excess = ret-池
_CARDS = [
    ("A1", "偏多", -2.5, {}, "对", "错"),                    # E1 偏空,excess -9
    ("A2", "偏多", 0.0, {}, "错", "对"),                     # E1 中性,|+3|>2pp
    ("A3", "偏多", 1.2, {}, "对", "对"),                     # E1 偏多,excess +7
    ("A4", "偏多", None, _mx(price=0.01, lhb=0.01), None, "对"),  # E0 带内 0.016→NULL,excess +5
    ("A5", "偏多", None, _mx(lhb=-0.03), "对", "错"),        # E0 带外 -0.018 偏空,excess -9
    ("A6", "中性", 0.0, {}, "对", "对"),                     # E1 中性,excess 0 带内
]


@pytest.fixture(scope="module")
def pg():
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        pytest.skip("docker 不可用(本批验收须实跑容器层)")
    name = f"rvtest-{uuid.uuid4().hex[:8]}"
    subprocess.run(["docker", "run", "-d", "--rm", "--name", name,
                    "-e", "POSTGRES_PASSWORD=rvtest", "-p", "127.0.0.1:0:5432",
                    "postgres:18"], check=True, capture_output=True)
    try:
        dsn = None
        for _ in range(60):
            out = subprocess.run(["docker", "port", name, "5432"],
                                 capture_output=True, text=True)
            if out.returncode == 0 and out.stdout.strip():
                port = out.stdout.strip().splitlines()[0].rsplit(":", 1)[1]
                dsn = f"host=127.0.0.1 port={port} user=postgres password=rvtest"
                try:
                    with psycopg.connect(dsn, connect_timeout=2):
                        break
                except psycopg.OperationalError:
                    dsn = None
            time.sleep(1)
        if not dsn:
            pytest.fail("postgres 容器未就绪")
        yield dsn
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)



@pytest.fixture(scope="module")
def scored(pg):
    """建 schema+数据 → 快照 decision_card → 跑真 score_mature() → 交断言。"""
    conn = psycopg.connect(pg, autocommit=True)
    cur = conn.cursor()
    cur.execute(DDL)
    # 行情:工作日开市,d0=06-01(一)后第5开市日=06-08
    for d in ("2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05",
              "2026-06-08", "2026-06-09"):
        cur.execute("INSERT INTO md.trade_calendar VALUES (%s, true)", (d,))
    for code, ret in _RETS.items():
        ts = f"{code}.SZ"
        cur.execute("INSERT INTO stock VALUES (%s,%s)", (code, ts))
        cur.execute("INSERT INTO stock_node VALUES ('n1',%s)", (code,))
        cur.execute("INSERT INTO md.bar_daily_raw VALUES (%s,'2026-06-01',100)", (ts,))
        cur.execute("INSERT INTO md.bar_daily_raw VALUES (%s,'2026-06-08',%s)",
                    (ts, 100 * (1 + ret / 100)))
    # 已记分存量卡 A0(修复前 artifact:mech_verdict='对' 恒多产物)——本轮必须零触碰
    cur.execute("""INSERT INTO decision_card(card_id,trade_date,code,ts_code,direction,
            horizon_days,matrix,alignment) OVERRIDING SYSTEM VALUE
        VALUES (100,'2026-06-01','A0','A0.SZ','偏多',5,%s,1.9)""",
                (json.dumps(_mx(price=0.5)),))
    cur.execute("""INSERT INTO decision_score VALUES
        (100,'2026-06-01','A0','2026-06-08',6.0,-1.0,7.0,'对','对')""")
    for i, (code, ldir, raw, mx, _mv, _v) in enumerate(_CARDS):
        cur.execute("""INSERT INTO decision_card(card_id,trade_date,code,ts_code,direction,
                horizon_days,matrix,alignment,raw_directional_score,weight_version)
                OVERRIDING SYSTEM VALUE
            VALUES (%s,'2026-06-01',%s,%s,%s,5,%s,1.5,%s,%s)""",
                    (101 + i, code, f"{code}.SZ", ldir, json.dumps(mx), raw,
                     "w1" if raw is not None else None))
    cur.execute("SELECT * FROM decision_card ORDER BY card_id")
    before = cur.fetchall()

    @contextmanager
    def fake_conn():
        c = psycopg.connect(pg)
        try:
            yield c
            c.commit()
        finally:
            c.close()
    mp = pytest.MonkeyPatch()
    mp.setattr(db, "rv_conn", fake_conn)
    mp.setattr(db, "marketdata_conn", fake_conn)
    try:
        n = scorecard.score_mature()
    finally:
        mp.undo()
    yield {"cur": cur, "before": before, "n": n}
    conn.close()


def _score_rows(cur):
    cur.execute("""SELECT dc.code, dc.direction, ds.excess, ds.verdict, ds.mech_verdict,
            dc.raw_directional_score, dc.matrix
        FROM decision_score ds JOIN decision_card dc USING(card_id) ORDER BY dc.code""")
    return {r[0]: r for r in cur.fetchall()}


def test_score_mature_mech_both_epochs(scored):
    """§8-1/3/4 集成:E1 负 raw 判空、=0 机械中性 ±2pp、E0 带外判向——mech 两侧非恒多。"""
    assert scored["n"]["stock_scored"] == len(_CARDS)
    rows = _score_rows(scored["cur"])
    for code, _ldir, _raw, _mx2, mech_expect, _v in _CARDS:
        assert rows[code][4] == mech_expect, f"{code} mech_verdict"
    # 方向层面复核:分类函数对库内行产出偏多/偏空/中性/indeterminate 全谱
    dirs = {scorecard.stock_mech_class(
        float(r[5]) if r[5] is not None else None, r[6])[1] for r in rows.values()}
    assert {"偏多", "偏空", "中性", None} <= dirs


def test_indeterminate_not_silently_lost(scored):
    """§8-2/8 集成:带内卡 mech_verdict=NULL 且在披露计数里可见,对账等式成立。"""
    rows = _score_rows(scored["cur"])
    assert rows["A4"][4] is None
    stats = stock_baseline_stats([(r[2], r[4], r[5], r[6]) for r in rows.values()])
    assert stats["e0"]["n_indeterminate"] == 1 and stats["e0"]["n_total"] == 3
    assert stats["e1"]["n_total"] == 4 and stats["e1"]["n_neutral"] == 2
    for b in (stats["e0"], stats["e1"]):
        assert b["n_total"] == b["n_directional"] + b["n_neutral"] + b["n_indeterminate"]
    assert stats["e0"]["n_total"] + stats["e1"]["n_total"] == len(rows)


def test_b8_verdict_bitwise_unchanged(scored):
    """B8 正式判断边界零泄漏:verdict 逐位=原口径 _verdict(direction, excess),
    与 mech 列/raw 列/matrix 全无耦合(含修复前已记分行)。"""
    rows = _score_rows(scored["cur"])
    for code, r in rows.items():
        assert r[3] == _verdict(r[1], float(r[2])), f"{code} verdict"
    for code, _ldir, _raw, _mx2, _mv, v_expect in _CARDS:
        assert rows[code][3] == v_expect, f"{code} 与手算期望不符"


def test_prescored_row_zero_touch(scored):
    """已记分存量(card 100)零改写:verdict/mech_verdict/created_at 原样。"""
    cur = scored["cur"]
    cur.execute("""SELECT verdict, mech_verdict, stock_ret, pool_ret, excess
        FROM decision_score WHERE card_id=100""")
    v, mv, sr, pr, ex = cur.fetchone()
    assert (v, mv) == ("对", "对") and (float(sr), float(pr), float(ex)) == (6.0, -1.0, 7.0)


def test_decision_card_zero_update(scored):
    """§8-7 append-only:实施路径对 decision_card 零 UPDATE(快照逐行相等),
    触发器兜底(显式 UPDATE/DELETE 必抛)。"""
    cur = scored["cur"]
    cur.execute("SELECT * FROM decision_card ORDER BY card_id")
    assert cur.fetchall() == scored["before"]
    with pytest.raises(psycopg.errors.RaiseException):
        cur.execute("UPDATE decision_card SET weight_version='hack' WHERE card_id=100")
    with pytest.raises(psycopg.errors.RaiseException):
        cur.execute("DELETE FROM decision_card WHERE card_id=100")


def test_persist_writes_w1_columns(scored, pg, monkeypatch):
    """§8-6:persist 新卡落 raw_directional_score(全精度)+weight_version='w1';
    candidates 数学由纯函数测试覆盖,此处证明 generate→persist 全链路传递与落库。"""
    dz = {"price": 1.234567, "mf": -0.5, "news": 0.1, "lhb": 0.0}
    raw = decision.raw_directional(dz)
    # 完整 matrix 形状(_stock_block 拼 prompt 要读全部展示键,缺键即 KeyError)
    full_mx = {"price": {"z": 1.23, "ret_1d": 1.0, "ret_1w": 2.0},
               "mf": {"z": -0.5, "d5": -0.3}, "news": {"z": 0.1, "pos": 1, "neg": 0, "today": 1},
               "lhb": {"z": 0.0, "net": 0.0}, "research": {"z": 0.0, "n3d": 0},
               "hot": {"rank": None}}
    fake_cand = {"code": "A9", "name": "测九", "ts_code": "A9.SZ", "close": 10.0,
                 "node_id": "n1", "node_card_id": None, "matrix": full_mx,
                 "raw_directional_score": raw, "dz": dz, "attn": 0.0,
                 "node_label": "n", "node_direction": "偏多", "node_thesis": "t",
                 "node_resonance": 1.0, "news_texts": [], "rsch_title": None,
                 "alignment": 2.13}
    monkeypatch.setattr(decision, "candidates", lambda d: [fake_cand])
    monkeypatch.setattr(decision.llm, "chat_json", lambda *a, **k: {"cards": [
        {"code": "A9", "direction": "偏多", "confidence": "中", "thesis": "t"}]})
    monkeypatch.setattr(config, "calibration_freeze", lambda: True)
    monkeypatch.setattr(config, "deepseek_model", lambda: "test-model")

    @contextmanager
    def fake_conn():
        c = psycopg.connect(pg)
        try:
            yield c
            c.commit()
        finally:
            c.close()
    monkeypatch.setattr(db, "rv_conn", fake_conn)
    assert decision.persist("20260602") == 1
    cur = scored["cur"]
    cur.execute("""SELECT raw_directional_score, weight_version FROM decision_card
        WHERE trade_date='2026-06-02' AND code='A9'""")
    got_raw, got_wv = cur.fetchone()
    assert float(got_raw) == pytest.approx(raw) and got_wv == "w1"
