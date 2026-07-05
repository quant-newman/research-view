"""护栏:全网开放不设登录(使用者拍板),但两道保险防脚本烧穿 key——
① 按 IP 限速(每分钟/每日);② 全局每日请求数 + token 熔断(状态落盘,重启不清零)。
一切按 UTC+8 记日。
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import alert

TZ8 = timezone(timedelta(hours=8))
STATE = Path(os.environ.get("STATE_DIR", "/state")) / "usage.json"

PER_IP_MIN = int(os.environ.get("CHAT_PER_IP_MIN", "6"))
PER_IP_DAY = int(os.environ.get("CHAT_PER_IP_DAY", "80"))
GLOBAL_DAY = int(os.environ.get("CHAT_GLOBAL_DAY", "500"))
TOKEN_DAY = int(os.environ.get("CHAT_TOKEN_DAY", "8000000"))  # ~几块钱量级

_lock = threading.Lock()
_minute: dict[str, list[float]] = {}  # ip -> 近60s时间戳
_day = {"date": "", "reqs": 0, "tokens": 0, "per_ip": {}}


def _today() -> str:
    return datetime.now(TZ8).strftime("%Y-%m-%d")


def _roll() -> None:
    """跨日清零;进程启动时从盘上恢复当日计数。"""
    if _day["date"] != _today():
        if not _day["date"] and STATE.exists():
            try:
                saved = json.loads(STATE.read_text())
                if saved.get("date") == _today():
                    _day.update(saved)
                    return
            except Exception:
                pass
        _day.update({"date": _today(), "reqs": 0, "tokens": 0, "per_ip": {}})


def _save() -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(_day, ensure_ascii=False))
    except OSError:
        pass  # 落盘失败不影响服务,只是重启丢当日计数


def check(ip: str) -> str | None:
    """请求前检查,超限返回给用户看的中文原因,通过返回 None 并记账。"""
    now = time.time()
    with _lock:
        _roll()
        if _day["tokens"] >= TOKEN_DAY or _day["reqs"] >= GLOBAL_DAY:
            alert.notify("burn", f"每日熔断已触发:req={_day['reqs']} tokens={_day['tokens']},"
                                 f"来源IP数={len(_day['per_ip'])},请查 usage.json 是否被刷", min_gap=6 * 3600)
            return "今日问答额度已用完,明天再来(每日有全局熔断,防滥用)"
        win = [t for t in _minute.get(ip, []) if now - t < 60]
        if len(win) >= PER_IP_MIN:
            return "问得太快了,歇几秒再问"
        if _day["per_ip"].get(ip, 0) >= PER_IP_DAY:
            alert.notify(f"ip:{ip}", f"单IP触顶:{ip} 已达每日{PER_IP_DAY}问上限(疑似滥用)", min_gap=24 * 3600)
            return "你今天问得够多了,明天再来"
        win.append(now)
        _minute[ip] = win
        _day["reqs"] += 1
        _day["per_ip"][ip] = _day["per_ip"].get(ip, 0) + 1
        _save()
    return None


def add_tokens(n: int) -> None:
    with _lock:
        _roll()
        _day["tokens"] += n
        _save()
