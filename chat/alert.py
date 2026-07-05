"""飞书告警:复用平台值班机器人(FEISHU_WEBHOOK/FEISHU_SECRET,与 scripts/notify_feishu.py 同一套)。

原则:①未配置=静默跳过;②后台线程发送,绝不阻塞问答;③按 key 限流去重,防告警风暴。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import threading
import time
import urllib.request

WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "")
SECRET = os.environ.get("FEISHU_SECRET", "")

_lock = threading.Lock()
_last: dict[str, float] = {}  # 限流key -> 上次发送时间


def _post(text: str) -> None:
    body: dict = {"msg_type": "text", "content": {"text": text}}
    if SECRET:
        ts = str(int(time.time()))
        key = f"{ts}\n{SECRET}".encode()
        body["timestamp"] = ts
        body["sign"] = base64.b64encode(hmac.new(key, b"", hashlib.sha256).digest()).decode()
    try:
        req = urllib.request.Request(WEBHOOK, json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=8)
    except Exception:  # noqa: BLE001 告警失败不影响服务
        pass


def notify(key: str, text: str, min_gap: float = 3600) -> None:
    """限流告警:同 key 间隔 min_gap 秒内只发一次。后台线程,立即返回。"""
    if not WEBHOOK:
        return
    now = time.time()
    with _lock:
        if now - _last.get(key, 0) < min_gap:
            return
        _last[key] = now
    threading.Thread(target=_post, args=(f"[chat问答] {text}",), daemon=True).start()
