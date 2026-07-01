"""DeepSeek 调用层。铁律:只呈现事实/做分类,不下投资判断;严格 JSON;temperature=0。"""
from __future__ import annotations

import json
import urllib.request

from . import config


def chat_json(system: str, user: str, timeout: int = 60) -> dict:
    """调 DeepSeek chat,强制 JSON 输出,返回解析后的 dict。"""
    key, base = config.deepseek()
    body = json.dumps({
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    return json.loads(data["choices"][0]["message"]["content"])
