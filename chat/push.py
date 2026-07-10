"""Web Push(PWA 站内推送),照 agu 先例:VAPID 签名。
订阅存 /state/push_subs.json——与台北宿主 scripts/push_alerts.py 共用同一文件
(容器只管订阅增删;推送发送一律在宿主脚本,容器无群发能力——公网端点零鉴权,
群发测试端点 2026-07-10 已删除,测试通知走宿主 pywebpush 直发)。
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

TZ8 = timezone(timedelta(hours=8))
SUBS = Path(os.environ.get("STATE_DIR", "/state")) / "push_subs.json"
VAPID_PEM = os.environ.get("VAPID_PRIVATE_KEY_PATH", "/app/vapid_private.pem")

_lock = threading.Lock()


def _load() -> dict:
    try:
        return json.loads(SUBS.read_text())
    except Exception:  # noqa: BLE001 文件不存在/损坏视为零订阅
        return {}


def _save(subs: dict) -> None:
    tmp = SUBS.with_suffix(".tmp")
    tmp.write_text(json.dumps(subs, ensure_ascii=False, indent=1))
    tmp.replace(SUBS)


@lru_cache
def vapid_public_key() -> str:
    """从私钥 PEM 推导浏览器订阅用的 applicationServerKey(base64url 未压缩点)。"""
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid02, b64urlencode

    v = Vapid02.from_file(VAPID_PEM)
    raw = v.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return b64urlencode(raw)


def subscribe(payload: dict, ua: str) -> int:
    ep = (payload.get("endpoint") or "").strip()
    keys = payload.get("keys") or {}
    if not ep or not keys.get("p256dh") or not keys.get("auth"):
        raise ValueError("订阅缺 endpoint/keys")
    with _lock:
        subs = _load()
        subs[ep] = {"p256dh": keys["p256dh"], "auth": keys["auth"], "ua": ua[:200],
                    "created": datetime.now(TZ8).isoformat(timespec="seconds")}
        _save(subs)
        return len(subs)


def unsubscribe(endpoint: str) -> int:
    with _lock:
        subs = _load()
        subs.pop(endpoint, None)
        _save(subs)
        return len(subs)


