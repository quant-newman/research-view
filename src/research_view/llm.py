"""DeepSeek 调用层。铁律:只呈现事实/做分类,不下投资判断;严格 JSON;temperature=0。

健壮性:网络抖动或返回非纯 JSON(带 ```json 围栏/前后废话)不该让整条管道崩——
去围栏容错解析 + 失败自动重试一次。
"""
from __future__ import annotations

import json
import urllib.request

from . import config


def _loads_lenient(content: str) -> dict:
    """先直解;失败则切出首个 { 到末个 }(去掉 ```json 围栏或前后解释文字)再解。"""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        i, j = content.find("{"), content.rfind("}")
        if i != -1 and j > i:
            return json.loads(content[i:j + 1])
        raise


def chat_json(system: str, user: str, timeout: int = 60, retries: int = 1) -> dict:
    """调 DeepSeek chat,强制 JSON 输出,返回解析后的 dict。失败(网络/坏JSON)自动重试。"""
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

    last_err: Exception | None = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(
                f"{base}/chat/completions", data=body,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.load(resp)
            return _loads_lenient(data["choices"][0]["message"]["content"])
        except Exception as e:  # noqa: BLE001 网络/解析都重试一次再抛
            last_err = e
    raise last_err  # type: ignore[misc]
