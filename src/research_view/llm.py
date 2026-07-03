"""DeepSeek 调用层。铁律:只呈现事实/做分类,不下投资判断;严格 JSON;temperature=0。

健壮性:网络抖动或返回非纯 JSON(带 ```json 围栏/前后废话)不该让整条管道崩——
去围栏容错解析 + 失败指数退避重试(限流/服务端抖动连续立即重试只会再撞墙)。
"""
from __future__ import annotations

import json
import time
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


def chat_json(system: str, user: str, timeout: int = 120, retries: int = 2) -> dict:
    """调 DeepSeek chat,强制 JSON 输出,返回解析后的 dict。失败(网络/坏JSON)退避重试(5s/15s)。
    模型见 config.deepseek_model()(默认 v4-pro 旗舰,带思考故默认超时放宽到 120s)。"""
    key, base = config.deepseek()
    body = json.dumps({
        "model": config.deepseek_model(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "stream": False,
    }).encode("utf-8")

    last_err: Exception | None = None
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(5 * 3 ** (attempt - 1))  # 5s, 15s, 45s...
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
