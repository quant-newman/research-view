"""DeepSeek 调用:路由用小模型(快/便宜),回答用旗舰流式。

与管道 src/research_view/llm.py 的同步实现分开——chat 要 async + SSE 流式,依赖 httpx。
"""
from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator

import httpx

KEY = os.environ["DEEPSEEK_API_KEY"]
BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
ROUTER_MODEL = os.environ.get("CHAT_ROUTER_MODEL", "deepseek-chat")  # v4-flash 小模型,选片够用
ANSWER_MODEL = os.environ.get("CHAT_ANSWER_MODEL", os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro"))

_HEADERS = {"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"}


def _loads_lenient(content: str) -> dict:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        i, j = content.find("{"), content.rfind("}")
        if i != -1 and j > i:
            return json.loads(content[i:j + 1])
        raise


async def route_json(system: str, user: str, timeout: float = 40) -> tuple[dict, int]:
    """选片调用:强制 JSON,返回 (解析结果, 总token)。"""
    body = {
        "model": ROUTER_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=timeout) as cli:
        r = await cli.post(f"{BASE}/chat/completions", headers=_HEADERS, json=body)
        r.raise_for_status()
        data = r.json()
    tokens = (data.get("usage") or {}).get("total_tokens", 0)
    return _loads_lenient(data["choices"][0]["message"]["content"]), tokens


async def answer_stream(messages: list[dict], timeout: float = 300) -> AsyncIterator[dict]:
    """回答调用:SSE 流式。产出 {"type":"delta","t":...} / {"type":"thinking"}(推理开始,只发一次)
    / {"type":"usage","total_tokens":...}(结束)。"""
    body = {"model": ANSWER_MODEL, "messages": messages, "temperature": 0.3, "stream": True,
            "stream_options": {"include_usage": True}}
    thinking_sent = False
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=15)) as cli:
        async with cli.stream("POST", f"{BASE}/chat/completions", headers=_HEADERS, json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                usage = chunk.get("usage")
                if usage:
                    yield {"type": "usage", "total_tokens": usage.get("total_tokens", 0)}
                for ch in chunk.get("choices") or []:
                    delta = ch.get("delta") or {}
                    if delta.get("reasoning_content") and not thinking_sent:
                        thinking_sent = True
                        yield {"type": "thinking"}
                    if delta.get("content"):
                        yield {"type": "delta", "t": delta["content"]}
