"""weekly_reflection 最小闭环回归(07-21 第二批施工令 六.1-13/16)。

覆盖:
- 真 SQL 层(postgres:18 一次性容器,应用**真实迁移文件** sql/030 两遍验幂等):
  append-only 三禁/版本链(根=1/自增/禁分叉/禁跨周/伪造版本号被覆盖)/单周单根/
  叶子查询/导出可见性(private 不出、public 叶子出、public 旧版被 private 新版顶掉后消失)。
- CLI 层(import scripts/manage_weekly_reflection.py,rv_conn/EXPORT_DIR 打到容器与 tmp):
  中文 Markdown 逐字回读+三侧 SHA(原文件/库内正文重编码/导出 JSON)一致、
  preview 零写入、confirm-sha 不一致/空文件/非法 UTF-8/无时区 authored_at 全拒且零新增、
  source_filename 只落纯文件名。
- 空导出=合法 JSON 结构;八个改动过的 shell 脚本 bash -n。
只连本地一次性容器,禁连生产。运行:PYTHONPATH=src python3 -m pytest tests/test_weekly_reflection.py -v
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import psycopg  # noqa: E402
import pytest  # noqa: E402
from psycopg import errors  # noqa: E402

from research_view import db as rv_db  # noqa: E402
from research_view import export as rv_export  # noqa: E402

MIGRATION = (ROOT / "sql" / "030_weekly_reflection.sql").read_text(encoding="utf-8")
# sql/006 已在生产建好该函数;容器内逐字复刻其定义(文案含 TG_OP,与生产同款)
LEDGER_FN = """CREATE OR REPLACE FUNCTION ledger_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'ledger 是只读账本,不允许 % (append-only)', TG_OP;
END;
$$ LANGUAGE plpgsql;"""

MD_CN = """# 第29周复盘

本周**核心教训**:测量链先于研判链。

## 对的地方
- 光纤光缆偏空判断兑现,z矩阵 news+2.1 与资金流出相互印证;
- 没有为了"补样本"降低发卡门槛。

## 错的地方
1. 存储方向连续两周被"涨价传闻"带偏——信源单一;
2. 对 robotics 参照层重组的下游影响推演不足。

> 纪律:样本不足时,只看方向感,不下结论。

| 维度 | 本周 | 累计 |
|---|---|---|
| 节点卡 | 1/8 | 4/16 |

下周只做一件事:把哨兵第9项跑成肌肉记忆。
"""


@pytest.fixture(scope="module")
def pg():
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        pytest.skip("docker 不可用(本批验收须实跑容器层)")
    name = f"rvwr-{uuid.uuid4().hex[:8]}"
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


@pytest.fixture()
def wr_db(pg):
    """每测试独立 database,真实迁移文件应用两遍(幂等即第二遍不抛)。"""
    dbname = f"wr_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(pg + " dbname=postgres", autocommit=True) as c:
        c.execute(f"CREATE DATABASE {dbname}")
    dsn = pg + f" dbname={dbname}"
    with psycopg.connect(dsn) as conn:
        conn.execute(LEDGER_FN)
        conn.execute(MIGRATION)
        conn.execute(MIGRATION)  # 幂等:第二遍必须原样通过
    return dsn


def _connect(dsn):
    return psycopg.connect(dsn)


SHA = lambda b: hashlib.sha256(b).hexdigest()  # noqa: E731


def _ins(conn, week_end, *, content="正文x", vis="private", sup=None,
         title="T", fname="a.md", forged_ver=None):
    cols = "week_end,title,content_md,content_sha256,source_filename,authored_at_utc8,supersedes_id,visibility"
    vals = [week_end, title, content, SHA(content.encode()), fname,
            "2026-07-19T21:30:00+08:00", sup, vis]
    if forged_ver is not None:
        cols += ",version_no"
        vals.append(forged_ver)
    ph = ",".join(["%s"] * len(vals))
    row = conn.execute(
        f"INSERT INTO weekly_reflection({cols}) VALUES({ph}) RETURNING reflection_id, version_no",
        vals).fetchone()
    return row


def _count(dsn):
    with _connect(dsn) as c:
        return c.execute("SELECT count(*) FROM weekly_reflection").fetchone()[0]


# ---------- 真 SQL 层 ----------

def test_append_only_update_delete_truncate(wr_db):
    with _connect(wr_db) as conn:
        _ins(conn, "2026-07-19")
        conn.commit()
        for stmt in ("UPDATE weekly_reflection SET title='改' WHERE version_no=1",
                     "DELETE FROM weekly_reflection",
                     "TRUNCATE weekly_reflection"):
            with pytest.raises(errors.RaiseException):
                conn.execute(stmt)
            conn.rollback()
    assert _count(wr_db) == 1


def test_version_chain_auto_and_forged_overwritten(wr_db):
    with _connect(wr_db) as conn:
        rid1, v1 = _ins(conn, "2026-07-19", forged_ver=99)  # 伪造版本号必须被触发器覆盖
        assert v1 == 1
        rid2, v2 = _ins(conn, "2026-07-19", sup=rid1, forged_ver=7)
        assert v2 == 2
        rid3, v3 = _ins(conn, "2026-07-19", sup=rid2)
        assert v3 == 3
        conn.commit()


def test_no_fork_second_supersede_rejected(wr_db):
    with _connect(wr_db) as conn:
        rid1, _ = _ins(conn, "2026-07-19")
        _ins(conn, "2026-07-19", sup=rid1)
        conn.commit()
        with pytest.raises(errors.UniqueViolation):
            _ins(conn, "2026-07-19", sup=rid1)  # 同一旧版第二个直接后继=分叉
        conn.rollback()
    assert _count(wr_db) == 2


def test_cross_week_revise_rejected(wr_db):
    with _connect(wr_db) as conn:
        rid1, _ = _ins(conn, "2026-07-19")
        conn.commit()
        with pytest.raises(errors.RaiseException):
            _ins(conn, "2026-07-26", sup=rid1)  # 跨 week_end 修订
        conn.rollback()
        with pytest.raises(errors.RaiseException):
            _ins(conn, "2026-07-26", sup=99999)  # 父版本不存在
        conn.rollback()
    assert _count(wr_db) == 1


def test_second_root_same_week_rejected(wr_db):
    with _connect(wr_db) as conn:
        _ins(conn, "2026-07-19")
        conn.commit()
        with pytest.raises(errors.UniqueViolation):
            _ins(conn, "2026-07-19")  # 同周第二条根记录
        conn.rollback()
        _ins(conn, "2026-07-26")  # 别的周不受影响
        conn.commit()


def test_field_constraints(wr_db):
    with _connect(wr_db) as conn:
        for kw in (dict(title="  "), dict(content="\n \t"),
                   dict(fname="/tmp/泄漏.md"), dict(fname="dir\\x.md"), dict(fname=" ")):
            with pytest.raises(errors.CheckViolation):
                _ins(conn, "2026-07-19", **kw)
            conn.rollback()
        with pytest.raises(errors.CheckViolation):  # SHA 必须 64 位小写 hex
            conn.execute("""INSERT INTO weekly_reflection(week_end,title,content_md,
                content_sha256,authored_at_utc8,visibility)
                VALUES('2026-07-19','T','x','ABCD','2026-07-19T21:30:00+08:00','private')""")
        conn.rollback()
        with pytest.raises(errors.CheckViolation):  # visibility 枚举
            _ins(conn, "2026-07-19", vis="unlisted")
        conn.rollback()
    assert _count(wr_db) == 0


def _leaves(conn):
    return conn.execute("""SELECT reflection_id, version_no FROM weekly_reflection r
        WHERE NOT EXISTS (SELECT 1 FROM weekly_reflection c
                          WHERE c.supersedes_id = r.reflection_id)
        ORDER BY r.week_end, r.reflection_id""").fetchall()


def test_leaf_query_old_version_never_current(wr_db):
    with _connect(wr_db) as conn:
        rid1, _ = _ins(conn, "2026-07-19")
        rid2, _ = _ins(conn, "2026-07-19", sup=rid1)
        rid3, _ = _ins(conn, "2026-07-26")
        conn.commit()
        leaves = _leaves(conn)
    assert leaves == [(rid2, 2), (rid3, 1)]  # 旧版 rid1 不得冒充当前版


# ---------- 导出可见性(直调生产 build_reflections,rv_conn/EXPORT_DIR 打到容器/tmp) ----------

@pytest.fixture()
def export_env(wr_db, tmp_path, monkeypatch):
    @contextmanager
    def fake_rv_conn():
        conn = psycopg.connect(wr_db)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    monkeypatch.setattr(rv_db, "rv_conn", fake_rv_conn)
    monkeypatch.setattr(rv_export, "EXPORT_DIR", tmp_path)
    return wr_db, tmp_path


def _export_json(tmp_path):
    p = rv_export.build_reflections()
    assert p == tmp_path / "reflections.json"
    return json.loads(p.read_text(encoding="utf-8"))


def test_export_empty_is_valid_json(export_env):
    _, tmp_path = export_env
    j = _export_json(tmp_path)
    assert j == {"meta": {"n": 0, "generated_at": j["meta"]["generated_at"]},
                 "reflections": []}
    assert isinstance(j["reflections"], list)


def test_export_visibility_and_replacement(export_env):
    dsn, tmp_path = export_env
    with _connect(dsn) as conn:
        pub, _ = _ins(conn, "2026-07-19", vis="public", content=MD_CN, title="公开周")
        _ins(conn, "2026-07-12", vis="private", content="私有正文", title="私有周")
        conn.commit()
    j = _export_json(tmp_path)
    assert j["meta"]["n"] == 1 and len(j["reflections"]) == 1
    r = j["reflections"][0]
    assert r["title"] == "公开周" and r["content_md"] == MD_CN and r["version_no"] == 1
    dumped = json.dumps(j, ensure_ascii=False)
    assert "私有" not in dumped  # private 标题/正文零旁路泄漏
    assert "/home" not in dumped and "/tmp" not in dumped  # 路径零泄漏
    # public 旧版被 private 新版取代 → 该周整体从公开 JSON 消失(旧版不得残留)
    with _connect(dsn) as conn:
        _ins(conn, "2026-07-19", vis="private", sup=pub, content="转私", title="公开周v2")
        conn.commit()
    j2 = _export_json(tmp_path)
    assert j2["meta"]["n"] == 0 and j2["reflections"] == []


def test_export_order_desc(export_env):
    dsn, tmp_path = export_env
    with _connect(dsn) as conn:
        for we in ("2026-07-05", "2026-07-19", "2026-07-12"):
            _ins(conn, we, vis="public", content=f"周{we}", title=f"T{we}")
        conn.commit()
    weeks = [r["week_end"] for r in _export_json(tmp_path)["reflections"]]
    assert weeks == ["2026-07-19", "2026-07-12", "2026-07-05"]  # week_end 倒序


# ---------- CLI 层 ----------

def _load_cli():
    spec = importlib.util.spec_from_file_location(
        "manage_weekly_reflection", ROOT / "scripts" / "manage_weekly_reflection.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def cli(export_env):
    dsn, tmp_path = export_env
    return _load_cli(), dsn, tmp_path


def _args(**kw):
    base = dict(public=False, private=False, title=None)
    base.update(kw)
    return SimpleNamespace(**base)


AUTH = "2026-07-19T21:30:00+08:00"


def test_cli_roundtrip_three_side_sha(cli, tmp_path):
    mod, dsn, exp_dir = cli
    f = tmp_path / "第29周复盘.md"
    f.write_text(MD_CN, encoding="utf-8")
    file_sha = SHA(f.read_bytes())
    mod.cmd_add(_args(file=str(f), week_end="2026-07-19", title="第29周复盘",
                      authored_at=AUTH, confirm_sha=file_sha, public=True))
    with _connect(dsn) as conn:
        content, db_sha, fname = conn.execute(
            "SELECT content_md, content_sha256, source_filename FROM weekly_reflection").fetchone()
    assert content == MD_CN                      # 逐字回读(换行/标点/表格原样)
    assert SHA(content.encode("utf-8")) == file_sha == db_sha  # 侧1=侧2
    assert fname == "第29周复盘.md" and "/" not in fname       # 纯文件名
    j = json.loads((exp_dir / "reflections.json").read_text(encoding="utf-8"))
    assert SHA(j["reflections"][0]["content_md"].encode("utf-8")) == file_sha  # 侧3
    assert j["reflections"][0]["content_sha256"] == file_sha


def test_cli_preview_zero_write(cli, tmp_path, capsys):
    mod, dsn, _ = cli
    f = tmp_path / "p.md"
    f.write_text(MD_CN, encoding="utf-8")
    mod.cmd_preview(_args(file=str(f), week_end="2026-07-19", title="预览",
                          authored_at=AUTH))
    out = capsys.readouterr().out
    assert SHA(f.read_bytes()) in out and "p.md" in out
    assert _count(dsn) == 0  # preview 零数据库写入


def test_cli_rejects_zero_insert(cli, tmp_path):
    mod, dsn, _ = cli
    good = tmp_path / "g.md"
    good.write_text(MD_CN, encoding="utf-8")
    sha = SHA(good.read_bytes())
    empty = tmp_path / "empty.md"
    empty.write_text("  \n", encoding="utf-8")
    bad_utf8 = tmp_path / "bad.md"
    bad_utf8.write_bytes(b"\xff\xfe\x00\x41")
    cases = [
        _args(file=str(good), week_end="2026-07-19", title="T", authored_at=AUTH,
              confirm_sha="0" * 64),                     # confirm-sha 不一致
        _args(file=str(empty), week_end="2026-07-19", title="T", authored_at=AUTH,
              confirm_sha=SHA(empty.read_bytes())),      # 空文件
        _args(file=str(bad_utf8), week_end="2026-07-19", title="T", authored_at=AUTH,
              confirm_sha=SHA(bad_utf8.read_bytes())),   # 非法 UTF-8
        _args(file=str(good), week_end="2026-07-19", title="T",
              authored_at="2026-07-19T21:30:00", confirm_sha=sha),  # 无时区
        _args(file=str(good), week_end="2026-07-19", title="T",
              authored_at="昨晚", confirm_sha=sha),       # 非 ISO
    ]
    for a in cases:
        with pytest.raises(SystemExit):
            mod.cmd_add(a)
    assert _count(dsn) == 0  # 全部拒绝且数据库零新增


def test_cli_revise_explicit_visibility_and_no_cross_week(cli, tmp_path):
    mod, dsn, exp_dir = cli
    f = tmp_path / "r.md"
    f.write_text(MD_CN, encoding="utf-8")
    sha = SHA(f.read_bytes())
    mod.cmd_add(_args(file=str(f), week_end="2026-07-19", title="根版",
                      authored_at=AUTH, confirm_sha=sha, public=True))
    f2 = tmp_path / "r2.md"
    f2.write_text(MD_CN + "\n补:v2。\n", encoding="utf-8")
    sha2 = SHA(f2.read_bytes())
    with pytest.raises(SystemExit):  # revise 不显式 --public/--private → 拒
        mod.cmd_revise(_args(file=str(f2), supersedes=1, authored_at=AUTH,
                             confirm_sha=sha2))
    mod.cmd_revise(_args(file=str(f2), supersedes=1, authored_at=AUTH,
                         confirm_sha=sha2, private=True))
    with _connect(dsn) as conn:
        rows = conn.execute("""SELECT version_no, visibility, week_end::text, title
                               FROM weekly_reflection ORDER BY reflection_id""").fetchall()
    assert rows[0][:2] == (1, "public") and rows[1][:2] == (2, "private")
    assert rows[1][2] == "2026-07-19"      # week_end 继承父版本,禁跨周
    assert rows[1][3] == "根版"             # title 未传=沿用父版本
    j = json.loads((exp_dir / "reflections.json").read_text(encoding="utf-8"))
    assert j["meta"]["n"] == 0             # public 根版被 private v2 顶掉 → 公开面消失
    with pytest.raises(SystemExit):        # 父版本不存在
        mod.cmd_revise(_args(file=str(f2), supersedes=999, authored_at=AUTH,
                             confirm_sha=sha2, private=True))


# ---------- 导出 fail-closed + 原子替换(07-21 审查阻塞项1回归) ----------

@contextmanager
def _broken_rv_conn():
    raise RuntimeError("模拟导出查询失败")
    yield  # pragma: no cover


def test_export_fail_closed_no_stale_public(export_env, monkeypatch):
    """旧 public 导出已存在 + 新 private 叶子已入库 + 导出异常:
    旧公开标题/正文/SHA 必须从正式 JSON 消失,落地=合法空结构,无半截临时文件。"""
    dsn, tmp_path = export_env
    with _connect(dsn) as conn:  # 库内状态:public 根已被 private v2 顶掉(当前叶子=private)
        pub, _ = _ins(conn, "2026-07-12", vis="public", content="旧公开正文UNIQ0721",
                      title="旧公开标题UNIQ0721")
        _ins(conn, "2026-07-12", vis="private", sup=pub, content="转私正文")
        conn.commit()
    old_sha = SHA("旧公开正文UNIQ0721".encode())
    (tmp_path / "reflections.json").write_text(json.dumps(
        {"meta": {"n": 1, "generated_at": "x"},
         "reflections": [{"reflection_id": pub, "week_end": "2026-07-12",
                          "title": "旧公开标题UNIQ0721", "content_md": "旧公开正文UNIQ0721",
                          "content_sha256": old_sha, "source_filename": "a.md",
                          "authored_at": "x", "recorded_at": "x", "version_no": 1}]},
        ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(rv_db, "rv_conn", _broken_rv_conn)  # 导出查询异常
    with pytest.raises(RuntimeError, match="模拟导出查询失败"):
        rv_export.build_reflections()  # fail-closed 后仍必须向上抛错
    txt = (tmp_path / "reflections.json").read_text(encoding="utf-8")
    j = json.loads(txt)  # 安全空结构=合法 JSON
    assert j["reflections"] == [] and j["meta"]["n"] == 0
    assert "UNIQ0721" not in txt and old_sha not in txt  # 旧公开内容零残留
    assert not list(tmp_path.glob(".reflections.json.tmp*"))  # 临时文件成败都清理


def test_export_atomic_tmp_cleanup_on_success(export_env):
    dsn, tmp_path = export_env
    with _connect(dsn) as conn:
        _ins(conn, "2026-07-19", vis="public", content=MD_CN, title="正常路径")
        conn.commit()
    p = rv_export.build_reflections()
    assert json.loads(p.read_text(encoding="utf-8"))["meta"]["n"] == 1
    assert not list(tmp_path.glob(".reflections.json.tmp*"))  # 走临时文件+原子替换,零残留


def test_export_empty_fallback_unwritable_raises(export_env, monkeypatch):
    """安全空文件也无法落地:异常必须继续向上抛(整条流水非零),不得报成功。"""
    _, tmp_path = export_env
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)  # 目录不可写:正式与临时文件都写不进
    try:
        monkeypatch.setattr(rv_export, "EXPORT_DIR", ro)
        monkeypatch.setattr(rv_db, "rv_conn", _broken_rv_conn)
        with pytest.raises(Exception):
            rv_export.build_reflections()
        assert not (ro / "reflections.json").exists()
    finally:
        ro.chmod(0o700)


# ---------- sync_dashboard.sh 失败传播(07-21 审查阻塞项2回归) ----------

def test_sync_dashboard_rsync_failure_propagates(tmp_path):
    src = (ROOT / "scripts" / "sync_dashboard.sh").read_text(encoding="utf-8")
    # 静态:吞错模式已从**代码行**删除(注释里保留"原模式为何被删"的审查留痕,只检非注释行)
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert "|| true" not in code and "grep -v" not in code
    assert "set -euo pipefail" in code and "LogLevel=ERROR" in code
    # 沙箱实跑(stub ssh/rsync,不出网不连生产):rsync 非零→脚本非零;rsync 零→脚本零
    sandbox = tmp_path / "sb"
    (sandbox / "scripts").mkdir(parents=True)
    (sandbox / "scripts" / "sync_dashboard.sh").write_text(src, encoding="utf-8")
    (sandbox / ".env").write_text("ALIYUN_DC_USER=stubu\nALIYUN_DC_HOST=stubh\n",
                                  encoding="utf-8")
    stubbin = tmp_path / "stubbin"
    stubbin.mkdir()
    (stubbin / "ssh").write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    (stubbin / "ssh").chmod(0o755)
    env = dict(os.environ, PATH=f"{stubbin}:{os.environ['PATH']}", HOME=str(tmp_path))
    for code, expect_fail in ((23, True), (0, False)):
        (stubbin / "rsync").write_text(f"#!/bin/bash\nexit {code}\n", encoding="utf-8")
        (stubbin / "rsync").chmod(0o755)
        r = subprocess.run(["bash", str(sandbox / "scripts" / "sync_dashboard.sh"), "20260721"],
                           env=env, capture_output=True, text=True)
        if expect_fail:
            assert r.returncode != 0, "rsync 失败必须传播为脚本失败,禁静默吞掉"
        else:
            assert r.returncode == 0, r.stderr


# ---------- shell 静态验证(六.16) ----------

def test_bash_n_modified_scripts():
    for name in ("run_afterhours.sh", "run_intraday.sh", "run_mf.sh", "run_premarket.sh",
                 "run_scorecard.sh", "run_us.sh", "run_fund_letters.sh", "sync_dashboard.sh"):
        r = subprocess.run(["bash", "-n", str(ROOT / "scripts" / name)],
                           capture_output=True, text=True)
        assert r.returncode == 0, f"{name}: {r.stderr}"
        assert "reflections" in (ROOT / "scripts" / name).read_text(encoding="utf-8")
