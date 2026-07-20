"""f-1 历史维表不丢行护栏 + 常驻 card_id 对账哨兵回归(07-20 第一批施工令 四.C/D/E)。

三层覆盖:
1) postgres:18 临时容器真 SQL 回归——07-12 事故形状复现(旧 INNER JOIN=4/14)→
   修复形状(8/18+fallback)、07-19 健康形状(B6 40/B8 60)哨兵不误报、
   dashboard recent 不吞历史行且排序/LIMIT 语义不变。只连本地一次性容器,禁连生产。
2) 合成游标 fail-hard(不连接任何数据库):对账不闭合时明确异常 +
   _review_wrong=0 / LLM=0 / b7_weekly 写=0 / 无成功返回;B6/B8 分侧不可互抵。
3) shell 静态验证:bash -n run_scorecard.sh + set -euo pipefail/ERR trap 存在 +
   隔离 stub 片段证明非零退出进 trap(不跑真实脚本,不实发告警)。
运行:PYTHONPATH=src python3 -m pytest tests/test_week_guardrail.py -v
"""
import os
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

from research_view import db, llm, scorecard  # noqa: E402
from research_view.scorecard import (WeekReconcileError, _reconcile_week_ids,  # noqa: E402
                                     _stats, _week_rows, _week_stock_rows,
                                     _wrong_block, dashboard_block, weekly)

# ---------- 1) postgres:18 临时容器真 SQL 回归 ----------

DDL = """
CREATE TABLE node(node_id text PRIMARY KEY, chain text, node text);
CREATE TABLE judgment_card(card_id int PRIMARY KEY, node_id text, direction text,
    confidence text, thesis text, evidence jsonb DEFAULT '[]', matrix jsonb DEFAULT '{}',
    resonance numeric, prompt_hash text, subjective_prob numeric, trade_date date);
CREATE TABLE card_score(card_id int PRIMARY KEY, trade_date date, end_date date,
    excess numeric, node_ret numeric, pool_ret numeric, verdict text, mech_verdict text);
CREATE TABLE decision_card(card_id int PRIMARY KEY, code text, name text, direction text,
    confidence text, thesis text, evidence jsonb DEFAULT '[]', matrix jsonb DEFAULT '{}',
    alignment numeric, prompt_hash text, subjective_prob numeric, trade_date date);
CREATE TABLE decision_score(card_id int PRIMARY KEY, trade_date date, end_date date,
    excess numeric, stock_ret numeric, pool_ret numeric, verdict text, mech_verdict text);
CREATE TABLE b7_weekly(week_end date PRIMARY KEY, stats jsonb, review jsonb, lessons jsonb,
    generated_at timestamptz DEFAULT now());
"""

# 07-12 事故形状(与红/绿档生产取证同构):B6 8 张,其中 4 张(1/5/6/8)的
# robotics v1 旧 node_id 已被参照层 v2 重组从 node 维表删除;1 对 7 错。
HIST_NODES = {1: "robotics::减速器", 5: "robotics::伺服/电机",
              6: "robotics::执行器/结构件", 8: "robotics::丝杠/传动"}
LIVE_NODES = {2: "fiber::光纤光缆", 3: "chip::先进封测", 4: "chip::存储", 7: "ai::算力租赁"}

# 施工令前旧病灶 SQL 形状(仅测试内复刻,用于先复现旧症状;生产代码已无此形状)
OLD_WEEK_SQL = """SELECT jc.node_id, n.chain, n.node, jc.direction, jc.confidence, jc.thesis,
           jc.evidence, jc.matrix, cs.excess, cs.node_ret, cs.pool_ret, cs.verdict
    FROM card_score cs JOIN judgment_card jc USING(card_id) JOIN node n ON n.node_id=jc.node_id
    WHERE cs.end_date > to_date(%s,'YYYYMMDD') - 7 AND cs.end_date <= to_date(%s,'YYYYMMDD')
    ORDER BY cs.excess"""


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
                    psycopg.connect(dsn + " dbname=postgres", connect_timeout=2).close()
                    break
                except psycopg.OperationalError:
                    pass
            time.sleep(1)
        else:
            pytest.fail("postgres:18 容器未就绪")
        yield dsn
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def _seed(dsn: str, dbname: str, healthy: bool) -> str:
    with psycopg.connect(dsn + " dbname=postgres", autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {dbname}")
        c.execute(f"CREATE DATABASE {dbname}")
    with psycopg.connect(dsn + f" dbname={dbname}") as conn:
        conn.execute(DDL)
        for cid, nid in LIVE_NODES.items():
            chain, node = nid.split("::")
            conn.execute("INSERT INTO node VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                         (nid, chain, node))
            _ = cid
        # B6 07-12 窗口:8 张(end_date=07-10),card 2 对,其余 7 错
        for cid in range(1, 9):
            nid = HIST_NODES.get(cid) or LIVE_NODES[cid]
            v = "对" if cid == 2 else "错"
            conn.execute("""INSERT INTO judgment_card(card_id, node_id, direction, confidence,
                    thesis, trade_date) VALUES(%s,%s,'偏多','高','论点','2026-07-03')""",
                         (cid, nid))
            conn.execute("""INSERT INTO card_score VALUES(%s,'2026-07-03','2026-07-10',
                    %s,-2.0,1.0,%s,'错')""", (cid, -3.0 - cid * 0.1, v))
        # B8 07-12 窗口:12 张,card 1 对,其余 11 错
        for cid in range(1, 13):
            v = "对" if cid == 1 else "错"
            conn.execute("""INSERT INTO decision_card(card_id, code, name, direction,
                    confidence, thesis, trade_date)
                    VALUES(%s,%s,%s,'偏多','中','论点','2026-07-03')""",
                         (cid, f"6{cid:05d}", f"个股{cid}"))
            conn.execute("""INSERT INTO decision_score VALUES(%s,'2026-07-03','2026-07-10',
                    %s,-2.0,1.0,%s,'错')""", (cid, -2.0 - cid * 0.1, v))
        if healthy:
            # 07-19 健康窗口(哨兵不应误报):B6 40 张 + B8 60 张,node 全在维表
            live = sorted(LIVE_NODES.values())
            for cid in range(101, 141):
                nid = live[cid % 4]
                conn.execute("""INSERT INTO judgment_card(card_id, node_id, direction,
                        confidence, thesis, trade_date)
                        VALUES(%s,%s,'偏多','高','论点','2026-07-10')""", (cid, nid))
                conn.execute("""INSERT INTO card_score VALUES(%s,'2026-07-10','2026-07-17',
                        %s,1.0,0.5,%s,'对')""",
                             (cid, 0.5 + cid * 0.01, "对" if cid % 2 else "错"))
            for cid in range(201, 261):
                conn.execute("""INSERT INTO decision_card(card_id, code, name, direction,
                        confidence, thesis, trade_date)
                        VALUES(%s,%s,%s,'偏空','中','论点','2026-07-10')""",
                             (cid, f"3{cid:05d}", f"个股{cid}"))
                conn.execute("""INSERT INTO decision_score VALUES(%s,'2026-07-10','2026-07-17',
                        %s,1.0,0.5,%s,'对')""",
                             (cid, 0.3 + cid * 0.01, "对" if cid % 3 else "错"))
        conn.commit()
    return dsn + f" dbname={dbname}"


@pytest.fixture(scope="module")
def incident_dsn(pg):
    """仅 07-12 事故形状(dashboard recent 层可直接看到历史卡)。"""
    return _seed(pg, "rv_incident", healthy=False)


@pytest.fixture(scope="module")
def full_dsn(pg):
    """07-12 事故形状 + 07-19 健康窗口(与生产绿档同构)。"""
    return _seed(pg, "rv_full", healthy=True)


@contextmanager
def _conn_cm(dsn: str):
    conn = psycopg.connect(dsn)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _use_db(monkeypatch, dsn: str):
    monkeypatch.setattr(db, "rv_conn", lambda: _conn_cm(dsn))


def test_old_inner_join_reproduces_incident(incident_dsn):
    """先复现旧症状:INNER JOIN node 静默过滤 4 张历史卡 → week=4、review 输入=14。"""
    with psycopg.connect(incident_dsn) as conn, conn.cursor() as cur:
        cur.execute(OLD_WEEK_SQL, ("20260712", "20260712"))
        old = cur.fetchall()
        assert len(old) == 4  # 病灶形态:8 → 4
        assert {r[0] for r in old} == set(LIVE_NODES.values())  # 1/5/6/8 被吞
        old_wrong = sum(1 for r in old if r[-1] == "错")
        swk = _week_stock_rows(cur, "20260712")
        assert old_wrong + sum(1 for r in swk if r[-1] == "错") == 14  # 病灶 review 输入


def test_week_rows_fixed_keeps_history(incident_dsn):
    """修复后:8 行全保留,card_id 首列,历史卡 fallback 标签非空,review 输入=18。"""
    with psycopg.connect(incident_dsn) as conn, conn.cursor() as cur:
        wk = _week_rows(cur, "20260712")
        assert len(wk) == 8
        assert sorted(r[0] for r in wk) == list(range(1, 9))
        assert all(len(r) == 13 and r[-1] in ("对", "错", "平") for r in wk)
        hist = {r[0]: r for r in wk if r[0] in HIST_NODES}
        assert len(hist) == 4
        for cid, r in hist.items():
            assert r[2] == "历史节点" and r[3] == HIST_NODES[cid]  # chain/node fallback 非空
        live = [r for r in wk if r[0] in LIVE_NODES]
        assert all(r[2] and r[2] != "历史节点" for r in live)  # 在维表的卡标签不受影响
        swk = _week_stock_rows(cur, "20260712")
        assert len(swk) == 12 and all(len(r) == 12 for r in swk)
        assert sorted(r[0] for r in swk) == list(range(1, 13))
        # 消费方解包(weekly() 同款推导式):wrong block 输入 7+11=18
        blocks = [_wrong_block(f"【节点】{chain}/{node}", nid, d, cf, th, ev, mx, ex, nr, pr)
                  for _cid, nid, chain, node, d, cf, th, ev, mx, ex, nr, pr, v in wk if v == "错"]
        blocks += [_wrong_block(f"【个股】{name}({code})", code, d, cf, th, ev, mx, ex, sr, pr)
                   for _cid, code, name, d, cf, th, ev, mx, ex, sr, pr, v in swk if v == "错"]
        assert len(blocks) == 18
        # week 统计仍取 r[-1](verdict 位置未破)
        assert _stats([(r[-1],) for r in wk])["n"] == 8


def test_reconcile_real_sql_closes(incident_dsn):
    """哨兵真 SQL:修复后两侧多重集合闭合,不抛异常。"""
    with psycopg.connect(incident_dsn) as conn, conn.cursor() as cur:
        wk = _week_rows(cur, "20260712")
        swk = _week_stock_rows(cur, "20260712")
        _reconcile_week_ids(cur, "20260712", "B6", "card_score", [r[0] for r in wk])
        _reconcile_week_ids(cur, "20260712", "B8", "decision_score", [r[0] for r in swk])


def test_healthy_0719_shape_no_false_alarm(full_dsn):
    """07-19 健康形状:B6 40/B8 60,多重集合一致,哨兵静默通过。"""
    with psycopg.connect(full_dsn) as conn, conn.cursor() as cur:
        wk = _week_rows(cur, "20260719")
        swk = _week_stock_rows(cur, "20260719")
        assert len(wk) == 40 and len(swk) == 60
        _reconcile_week_ids(cur, "20260719", "B6", "card_score", [r[0] for r in wk])
        _reconcile_week_ids(cur, "20260719", "B8", "decision_score", [r[0] for r in swk])


def test_dashboard_recent_keeps_history(incident_dsn, monkeypatch):
    """dashboard recent:node 维表缺失时历史卡仍在,fallback 非空,排序语义不变。"""
    _use_db(monkeypatch, incident_dsn)
    block = dashboard_block()
    recent = block["recent"]
    assert len(recent) == 8  # 库内仅 8 张,LIMIT 12 内全保留
    by_id = {r["card_id"]: r for r in recent}
    for cid, nid in HIST_NODES.items():
        assert by_id[cid]["chain"] == "历史节点" and by_id[cid]["node"] == nid
    assert all(r["chain"] and r["node"] for r in recent)
    # 排序:end_date DESC, abs(excess) DESC(同 end_date 下按 |excess| 降序)
    assert [r["card_id"] for r in recent] == sorted(
        by_id, key=lambda c: abs(by_id[c]["excess"]), reverse=True)


def test_dashboard_recent_limit_semantics(full_dsn, monkeypatch):
    """LIMIT 12 语义不变:48 张记分卡时 recent 恰 12 行,且全为最新 end_date 窗口。"""
    _use_db(monkeypatch, full_dsn)
    recent = dashboard_block()["recent"]
    assert len(recent) == 12
    assert all(r["end_date"] == "2026-07-17" for r in recent)  # end_date DESC 优先


# ---------- 2) 合成游标 fail-hard(不连接任何数据库) ----------

class _ExpCur:
    """_reconcile_week_ids 单元测试用:只应答 expected 侧查询。"""
    def __init__(self, ids):
        self._ids = ids

    def execute(self, sql, params=None):
        assert "SELECT card_id FROM" in sql

    def fetchall(self):
        return [(i,) for i in self._ids]


def test_reconcile_multiset_unit():
    ok = _ExpCur([1, 2, 3])
    _reconcile_week_ids(ok, "20260712", "B6", "card_score", [3, 2, 1])  # 序无关,闭合
    with pytest.raises(WeekReconcileError, match=r"missing_card_ids=\[3\]") as ei:
        _reconcile_week_ids(_ExpCur([1, 2, 3]), "20260712", "B6", "card_score", [1, 2])
    assert "B6" in str(ei.value) and "expected_n=3" in str(ei.value) \
        and "actual_n=2" in str(ei.value)
    with pytest.raises(WeekReconcileError, match=r"extra_card_ids=\[9\]"):
        _reconcile_week_ids(_ExpCur([1, 2]), "20260712", "B8", "decision_score", [1, 2, 9])
    # 数量相等但一丢一重:Counter 多重集合必须失败,且三类明细同时披露
    with pytest.raises(WeekReconcileError) as ei:
        _reconcile_week_ids(_ExpCur([1, 2]), "20260712", "B6", "card_score", [1, 1])
    msg = str(ei.value)
    assert "missing_card_ids=[2]" in msg and "extra_card_ids=[1]" in msg \
        and "duplicate_card_ids=[1]" in msg
    with pytest.raises(AssertionError):  # 表名白名单,禁注入
        _reconcile_week_ids(_ExpCur([]), "20260712", "B6", "pg_tables", [])


def _norm(sql: str) -> str:
    return " ".join(sql.split())


def _b6_row(cid, verdict="对"):
    return (cid, "n::x", "链", "节点", "偏多", "高", "论点", [], {}, -3.0, -2.0, 1.0, verdict)


def _b8_row(cid, verdict="对"):
    return (cid, "600000", "个股", "偏多", "中", "论点", [], {}, -2.0, -1.0, 1.0, verdict)


class SyntheticCursor:
    """按 SQL 形状分发的合成游标:週窗查询给 actual,card_id 裸查询给 expected,
    其余查询一律空集;记录 b7_weekly 写入次数。"""
    def __init__(self, week_rows, stock_rows, b6_expected, b8_expected):
        self.week_rows, self.stock_rows = week_rows, stock_rows
        self.b6_expected, self.b8_expected = b6_expected, b8_expected
        self.b7_writes = 0
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        s = _norm(sql)
        if s.startswith("INSERT INTO b7_weekly"):
            self.b7_writes += 1
            self._rows = []
        elif s.startswith("SELECT cs.card_id, jc.node_id"):
            self._rows = self.week_rows
        elif s.startswith("SELECT ds.card_id, dc.code"):
            self._rows = self.stock_rows
        elif s.startswith("SELECT card_id FROM card_score"):
            self._rows = [(c,) for c in self.b6_expected]
        elif s.startswith("SELECT card_id FROM decision_score"):
            self._rows = [(c,) for c in self.b8_expected]
        else:
            self._rows = []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _SynConn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur


def _wire(monkeypatch, cur):
    """weekly() 全依赖换合成件:db 连接 + LLM 计数 stub + _review_wrong 计数包装。"""
    @contextmanager
    def fake_conn():
        yield _SynConn(cur)
    monkeypatch.setattr(db, "rv_conn", fake_conn)
    calls = {"llm": 0, "review": 0}
    monkeypatch.setattr(llm, "chat_json",
                        lambda *a, **k: calls.__setitem__("llm", calls["llm"] + 1)
                        or {"review": [], "lessons": ["教训"]})
    real_review = scorecard._review_wrong

    def counting_review(week_end, blocks):
        calls["review"] += 1
        return real_review(week_end, blocks)
    monkeypatch.setattr(scorecard, "_review_wrong", counting_review)
    return calls


def test_weekly_fail_hard_b6(monkeypatch):
    """B6 侧不闭合:明确异常,_review_wrong=0 / LLM=0 / b7_weekly 写=0,无成功返回。"""
    cur = SyntheticCursor(week_rows=[_b6_row(1), _b6_row(2)], stock_rows=[],
                          b6_expected=[1, 2, 3], b8_expected=[])
    calls = _wire(monkeypatch, cur)
    with pytest.raises(WeekReconcileError, match="B6"):
        weekly("20260712")
    assert calls["review"] == 0 and calls["llm"] == 0 and cur.b7_writes == 0


def test_weekly_fail_hard_b8_side_independent(monkeypatch):
    """B8 侧不闭合(B6 闭合):一侧不能替另一侧抵消,同样整体失败。"""
    cur = SyntheticCursor(week_rows=[_b6_row(1)], stock_rows=[_b8_row(11), _b8_row(12)],
                          b6_expected=[1], b8_expected=[11, 12, 13])
    calls = _wire(monkeypatch, cur)
    with pytest.raises(WeekReconcileError, match="B8"):
        weekly("20260712")
    assert calls["review"] == 0 and calls["llm"] == 0 and cur.b7_writes == 0


def test_weekly_happy_path_synthetic(monkeypatch):
    """两侧闭合:正常走完 LLM(有错误卡)并写 b7_weekly 一次,成功返回。"""
    cur = SyntheticCursor(week_rows=[_b6_row(1, "错"), _b6_row(2)],
                          stock_rows=[_b8_row(11, "错")],
                          b6_expected=[1, 2], b8_expected=[11])
    calls = _wire(monkeypatch, cur)
    out = weekly("20260712")
    assert calls["review"] == 1 and calls["llm"] == 1 and cur.b7_writes == 1
    assert out["week_scored"] == 2 and out["stock_week_scored"] == 1 and out["wrong"] == 2


# ---------- 3) shell 静态验证(不跑真实脚本,不实发告警) ----------

def test_run_scorecard_shell_static():
    sh = ROOT / "scripts" / "run_scorecard.sh"
    assert subprocess.run(["bash", "-n", str(sh)]).returncode == 0
    text = sh.read_text()
    assert "set -euo pipefail" in text
    trap_lines = [ln for ln in text.splitlines()
                  if ln.strip().startswith("trap ") and ln.rstrip().endswith("ERR")]
    assert trap_lines and "alert_set scorecard" in trap_lines[0]


def test_err_trap_fires_on_nonzero(tmp_path):
    """隔离 stub:同构 set -euo pipefail + ERR trap 下,python 非零退出进 trap 且中止后续。"""
    out = tmp_path / "out.txt"
    snippet = tmp_path / "trap_stub.sh"
    snippet.write_text("#!/usr/bin/env bash\n"
                       "set -euo pipefail\n"
                       'alert_set(){ echo "STUB_TRAP:$1" >> "$OUT"; }\n'
                       "trap 'alert_set scorecard' ERR\n"
                       "python3 -c 'raise SystemExit(1)'\n"
                       'echo NEVER >> "$OUT"\n')
    r = subprocess.run(["bash", str(snippet)], env={**os.environ, "OUT": str(out)})
    assert r.returncode != 0
    assert out.read_text() == "STUB_TRAP:scorecard\n"
