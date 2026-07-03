"""台北侧信源状态汇报:各抓取脚本逐源上报 → exports/source_status.json(按 key 合并)。

配合 data/sources.json 注册表(enabled 开关 / threshold_hours 停更阈值);
编排脚本把状态文件随数据 blob 一起 scp 到阿里云,export.build_dashboard 合并注册表
挂 dash.sources,前端系统页信源面板可视化,monitor.health 计入黄红。
并发:四编排脚本有 flock 全局串行锁,合并写无竞态。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = ROOT / "exports" / "source_status.json"
REGISTRY_PATH = ROOT / "data" / "sources.json"


def registry() -> dict[str, dict]:
    try:
        reg = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        return {s["key"]: s for s in reg["sources"]}
    except Exception:  # noqa: BLE001 注册表缺失/损坏时全部视为启用,不阻塞抓取
        return {}


def enabled(key: str) -> bool:
    return registry().get(key, {}).get("enabled", True)


def report(entries: list[dict]) -> None:
    """entries: [{key, ok, n, err?}]。按 key 合并进状态文件(别的脚本的键不动),附 fetched_at。"""
    now = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")
    cur: dict = {}
    if STATUS_PATH.exists():
        try:
            cur = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 损坏则重建
            cur = {}
    for e in entries:
        cur[e["key"]] = {"ok": bool(e.get("ok")), "n": int(e.get("n") or 0),
                         "err": (e.get("err") or "")[:120], "fetched_at": now}
    STATUS_PATH.parent.mkdir(exist_ok=True)
    STATUS_PATH.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
