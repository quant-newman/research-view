#!/usr/bin/env python3
"""使用者周度复盘 CLI(weekly_reflection 唯一写入侧,07-21 第二批施工令)。

魂:复盘是使用者亲笔的整篇 Markdown——**原文不可篡改保存**(append-only+版本链),
零 LLM(不摘要/不润色/不改写),不进 B6/B8/记分/lessons/prompt 链。
默认 private;public 必须显式指定,且只有"当前叶子版本为 public"才进公开导出。
不提供 edit/delete/overwrite:改内容或改可见性一律走 revise 新增版本,旧行零触碰。

与 manage_ledger.py 同模式:前端静态只读、PG 仅本地监听,本 CLI 在数据节点侧跑。

用法(两步走,先 preview 拿 SHA 再写入,防错文件/错编码):
  # 1) 预览(零写入):校验 UTF-8/非空/时区,显示元数据与 content_sha256
  python3 scripts/manage_weekly_reflection.py preview 复盘.md \\
      --week-end 2026-07-19 --title "第29周复盘" --authored-at "2026-07-19T21:30:00+08:00"
  # 2) 新建某周根记录(--confirm-sha 必须与 preview 所得一致;公开须显式 --public)
  python3 scripts/manage_weekly_reflection.py add 复盘.md \\
      --week-end 2026-07-19 --title "第29周复盘" --authored-at "2026-07-19T21:30:00+08:00" \\
      --confirm-sha <preview所得64位sha>
  # 3) 修订(新插一行,旧行不动;week_end 继承父版本;可见性必须显式 --public/--private)
  python3 scripts/manage_weekly_reflection.py revise 复盘v2.md --supersedes 1 \\
      --authored-at "2026-07-20T09:00:00+08:00" --confirm-sha <sha> --private
  # 4) 列表(默认只列当前叶子;--week-end 筛选;--chain 显示完整版本链)
  python3 scripts/manage_weekly_reflection.py list
  # 5) 看指定版本全文(必须明确 reflection_id,不提供"看起来最新"的模糊对象)
  python3 scripts/manage_weekly_reflection.py show 1
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from research_view import db, export  # noqa: E402


def _die(msg: str) -> None:
    print(f"[错误] {msg}", file=sys.stderr)
    sys.exit(2)


def _read_md(path_str: str) -> tuple[str, str, bytes]:
    """读 Markdown 文件:严格 UTF-8,拒绝空文件。返回 (正文, 纯文件名, 原始字节)。
    正文=字节流 strict 解码,零改写(换行/标点/段落原样);纯文件名=Path.name 截断路径。"""
    p = Path(path_str)
    if not p.is_file():
        _die(f"文件不存在: {path_str}")
    raw = p.read_bytes()
    try:
        content = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as e:
        _die(f"非法 UTF-8: {e}")
    if not content.strip():
        _die("空文件(或只有空白),拒绝")
    return content, p.name, raw


def _parse_authored_at(s: str) -> datetime:
    """authored_at 必须是带明确时区偏移的 ISO-8601,禁止无时区值。"""
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        _die(f"authored-at 不是合法 ISO-8601: {s!r}")
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        _die(f"authored-at 缺时区偏移(如 +08:00),拒绝无时区值: {s!r}")
    return dt


def _parse_week_end(s: str) -> date:
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    _die(f"week-end 不是合法日期(YYYY-MM-DD 或 YYYYMMDD): {s!r}")
    raise AssertionError  # unreachable


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _print_meta(week_end, title, authored_at, visibility, fname, nbytes, sha) -> None:
    print(f"week_end       : {week_end}")
    print(f"title          : {title}")
    print(f"authored_at    : {authored_at}")
    print(f"visibility     : {visibility}")
    print(f"source_filename: {fname}")
    print(f"字节数          : {nbytes}")
    print(f"content_sha256 : {sha}")


def _visibility(args, *, required: bool) -> str:
    if getattr(args, "public", False) and getattr(args, "private", False):
        _die("--public 与 --private 只能二选一")
    if args.public:
        return "public"
    if getattr(args, "private", False):
        return "private"
    if required:
        _die("revise 必须显式指定 --public 或 --private(可见性不隐式继承)")
    return "private"  # add/preview 默认 private,公开必须显式 --public


def cmd_preview(args) -> None:
    content, fname, raw = _read_md(args.file)
    authored = _parse_authored_at(args.authored_at)
    week_end = _parse_week_end(args.week_end)
    vis = _visibility(args, required=False)
    _print_meta(week_end, args.title, authored.isoformat(), vis, fname, len(raw), _sha256(raw))
    print("(preview 零数据库写入;add 时带 --confirm-sha <上面这串>)")


def _insert(cur, *, week_end, title, content, sha, fname, authored, supersedes, vis):
    cur.execute(
        """INSERT INTO weekly_reflection
               (week_end, title, content_md, content_sha256, source_filename,
                authored_at_utc8, supersedes_id, visibility)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING reflection_id, version_no, recorded_at_utc8""",
        (week_end, title, content, sha, fname, authored, supersedes, vis))
    return cur.fetchone()


def _confirm_or_die(args, raw: bytes) -> str:
    sha = _sha256(raw)
    if args.confirm_sha.strip().lower() != sha:
        _die(f"confirm-sha 不一致,拒绝写入(零写入)。实际文件 SHA={sha}")
    return sha


def cmd_add(args) -> None:
    content, fname, raw = _read_md(args.file)
    authored = _parse_authored_at(args.authored_at)
    week_end = _parse_week_end(args.week_end)
    sha = _confirm_or_die(args, raw)
    vis = _visibility(args, required=False)
    # 单事务:任一校验失败(含 DB 约束)整体回滚——rv_conn 异常即 rollback
    with db.rv_conn() as conn, conn.cursor() as cur:
        rid, ver, recorded = _insert(cur, week_end=week_end, title=args.title,
                                     content=content, sha=sha, fname=fname,
                                     authored=authored, supersedes=None, vis=vis)
    print(f"已写入根记录 reflection_id={rid} version_no={ver} recorded_at={recorded}")
    _print_meta(week_end, args.title, authored.isoformat(), vis, fname, len(raw), sha)
    _regen_export()


def cmd_revise(args) -> None:
    content, fname, raw = _read_md(args.file)
    authored = _parse_authored_at(args.authored_at)
    sha = _confirm_or_die(args, raw)
    vis = _visibility(args, required=True)
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("""SELECT week_end, title, version_no FROM weekly_reflection
                       WHERE reflection_id=%s""", (args.supersedes,))
        parent = cur.fetchone()
        if parent is None:
            _die(f"supersedes_id={args.supersedes} 不存在")
        week_end, parent_title, _ = parent
        title = args.title if args.title is not None else parent_title
        rid, ver, recorded = _insert(cur, week_end=week_end, title=title,
                                     content=content, sha=sha, fname=fname,
                                     authored=authored, supersedes=args.supersedes, vis=vis)
    print(f"已写入修订版 reflection_id={rid} version_no={ver}"
          f"(supersedes {args.supersedes})recorded_at={recorded}")
    _print_meta(week_end, title, authored.isoformat(), vis, fname, len(raw), sha)
    _regen_export()


def _regen_export() -> None:
    """写入成功后当场重建 exports/reflections.json(下次编排 rsync 自动带走)。"""
    print(f"已重建导出: {export.build_reflections()}")


def cmd_list(args) -> None:
    where, params = "", []
    if args.week_end:
        where = "WHERE r.week_end=%s"
        params.append(_parse_week_end(args.week_end))
    if args.chain:
        sql = f"""SELECT r.reflection_id, r.week_end, r.version_no, r.visibility, r.title,
                         r.supersedes_id,
                         NOT EXISTS (SELECT 1 FROM weekly_reflection c
                                     WHERE c.supersedes_id=r.reflection_id) AS is_leaf
                  FROM weekly_reflection r {where}
                  ORDER BY r.week_end DESC, r.version_no"""
    else:
        sql = f"""SELECT r.reflection_id, r.week_end, r.version_no, r.visibility, r.title,
                         r.supersedes_id, true AS is_leaf
                  FROM weekly_reflection r {where}
                  {"AND" if where else "WHERE"} NOT EXISTS
                      (SELECT 1 FROM weekly_reflection c WHERE c.supersedes_id=r.reflection_id)
                  ORDER BY r.week_end DESC, r.reflection_id DESC"""
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    if not rows:
        print("(无记录)")
        return
    for rid, week_end, ver, vis, title, sup, leaf in rows:
        tag = "PUBLIC " if vis == "public" else "private"
        leafmark = "当前版" if leaf else f"旧版→{sup or '根'}"
        print(f"#{rid:<4} {week_end} v{ver} [{tag}] {leafmark:<8} {title}")


def cmd_show(args) -> None:
    with db.rv_conn() as conn, conn.cursor() as cur:
        cur.execute("""SELECT reflection_id, week_end, title, content_md, content_sha256,
                              source_filename, authored_at_utc8, recorded_at_utc8,
                              supersedes_id, version_no, visibility
                       FROM weekly_reflection WHERE reflection_id=%s""", (args.reflection_id,))
        row = cur.fetchone()
    if row is None:
        _die(f"reflection_id={args.reflection_id} 不存在")
    (rid, week_end, title, content, sha, fname, authored, recorded,
     sup, ver, vis) = row
    print(f"reflection_id  : {rid}(version_no={ver}, supersedes={sup or '—'})")
    print(f"recorded_at    : {recorded}")
    _print_meta(week_end, title, authored, vis, fname or "—",
                len(content.encode("utf-8")), sha)
    print("-" * 60)
    print(content)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def _md_args(p, *, confirm: bool):
        p.add_argument("file", help="UTF-8 Markdown 文件路径(只入库 Path.name 纯文件名)")
        p.add_argument("--authored-at", required=True,
                       help="写作时间,带时区偏移的 ISO-8601(如 2026-07-19T21:30:00+08:00)")
        p.add_argument("--public", action="store_true", help="显式公开(默认 private)")
        if confirm:
            p.add_argument("--confirm-sha", required=True,
                           help="preview 所得 content_sha256,不一致拒绝写入")

    p = sub.add_parser("preview", help="校验并显示元数据与 SHA,零数据库写入")
    _md_args(p, confirm=False)
    p.add_argument("--week-end", required=True)
    p.add_argument("--title", required=True)
    p.set_defaults(fn=cmd_preview)

    p = sub.add_parser("add", help="新建某周根记录(须 --confirm-sha)")
    _md_args(p, confirm=True)
    p.add_argument("--week-end", required=True)
    p.add_argument("--title", required=True)
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("revise", help="修订:新插一行,旧行零触碰;week_end 继承父版本")
    _md_args(p, confirm=True)
    p.add_argument("--supersedes", type=int, required=True, help="被修订版本的 reflection_id")
    p.add_argument("--title", default=None, help="不传=沿用父版本标题")
    p.add_argument("--private", action="store_true",
                   help="显式私有(revise 必须 --public/--private 二选一,不隐式继承)")
    p.set_defaults(fn=cmd_revise)

    p = sub.add_parser("list", help="默认只列当前叶子版本")
    p.add_argument("--week-end", default=None, help="按周筛选")
    p.add_argument("--chain", action="store_true", help="显示完整版本链")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("show", help="显示指定版本完整元数据、SHA 与原文")
    p.add_argument("reflection_id", type=int)
    p.set_defaults(fn=cmd_show)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
