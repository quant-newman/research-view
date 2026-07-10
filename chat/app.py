"""chat 问答服务:POST /api/chat,SSE 流式。

两段式:①小模型按目录选片(失败降级到默认核心块,服务不断);②旗舰带切片流式回答。
铁律在 system prompt:只依据切片、没有就明说、标数据日期、不自创买卖建议。
严格只读——本服务只读 webdata,不触达任何管道/写操作。
"""
from __future__ import annotations

import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

import alert
import data
import guard
import llm
import push as pushmod

app = FastAPI(title="research-view-chat", docs_url=None, redoc_url=None)

MAX_Q = 1200          # 单问长度上限
MAX_TURNS = 8         # 带给模型的历史条数
FALLBACK_SECTIONS = ["report", "market", "temperature", "hotspot", "judgment", "moneyflow"]

ROUTER_SYS = (
    "你是投研看板的查询路由器。根据用户问题从目录中选出回答所需的数据块,只输出 JSON:"
    '{"sections":["..."],"node_ids":["..."],"codes":["..."]}。'
    "规则:sections 只能用目录里的键,按相关度排序,最多6个;"
    "涉及具体产业链节点/美股板块时,node_ids 用目录中的完整名称;"
    "涉及个股时 codes 填代码(A股6位数字,美股ticker),按名称在目录索引里找;"
    "问历史走势/近N天怎么走 → 加 trends 且必须给 codes;问消息面/新闻/为什么涨跌 → 加 news_by_node;"
    "问资金流向 → moneyflow;比较估值/涨幅 → heatmap;涉及美股 → us;"
    "问平台怎么看/研判/建议 → judgment 和 decision;问命中率/成绩 → scorecard。"
)

ANSWER_SYS = (
    "你是A股AI科技投研看板「研判视图」的问答助手。用户的问题要基于下面给出的看板数据切片回答。铁律:"
    "①只依据切片数据,切片里没有的信息明确说「看板数据里没有」,严禁用你自己的知识补数字或编造;"
    "②结论要带数据日期(meta.date 或各块自带的 date);"
    "③可以转述看板已有的研判卡/决策卡/报告观点,但要注明「平台研判认为」,你自己不新增买卖建议;"
    "④简体中文,先给结论再给依据,简洁,可用短列表,不用 markdown 表格;不要向用户提内部字段名或切片结构,直接说人话;"
    "⑤单位:资金流字段为亿元,涨幅类字段已是百分数,市值单位为万元(A股)/亿美元(美股)。\n"
    "【看板数据切片】\n{slices}"
)


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _client_ip(req: Request) -> str:
    return req.headers.get("x-real-ip") or (req.client.host if req.client else "?")


@app.get("/api/chat/health")
def health():
    meta = data.dashboard().get("meta", {})
    return {"ok": True, "data_date": meta.get("date"), "generated_at": meta.get("generated_at")}


# ---------- Web Push 订阅(PWA;异动推送发送在台北宿主 scripts/push_alerts.py) ----------

@app.get("/api/push/vapid-key")
def push_vapid_key():
    return {"key": pushmod.vapid_public_key()}


@app.post("/api/push/subscribe")
async def push_subscribe(req: Request):
    try:
        n = pushmod.subscribe(await req.json(), req.headers.get("user-agent", ""))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True, "subscriptions": n}


@app.post("/api/push/unsubscribe")
async def push_unsubscribe(req: Request):
    body = await req.json()
    n = pushmod.unsubscribe((body.get("endpoint") or "").strip())
    return {"ok": True, "subscriptions": n}


@app.post("/api/chat")
async def chat(req: Request):
    body = await req.json()
    msgs = [m for m in (body.get("messages") or [])
            if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content")]
    if not msgs or msgs[-1]["role"] != "user":
        return JSONResponse({"error": "最后一条须是用户提问"}, status_code=400)
    msgs = [{"role": m["role"], "content": str(m["content"])[:MAX_Q * 4]} for m in msgs[-MAX_TURNS:]]
    question = msgs[-1]["content"][:MAX_Q]

    deny = guard.check(_client_ip(req))
    if deny:
        return JSONResponse({"error": deny}, status_code=429)

    async def gen():
        try:
            # ① 选片(带最近几轮对话,让追问也能路由对)
            yield _sse({"type": "status", "t": "正在定位相关数据…"})
            convo = "\n".join(f"{'问' if m['role'] == 'user' else '答'}: {m['content'][:300]}" for m in msgs[-5:])
            try:
                sel, tk = await llm.route_json(ROUTER_SYS, f"{data.catalog()}\n\n【对话】\n{convo}")
                guard.add_tokens(tk)
            except Exception as e:  # noqa: BLE001 选片失败降级到默认块,服务不断,但要知道
                alert.notify("route", f"选片降级(用默认数据块兜底):{type(e).__name__}: {e}")
                sel = {"sections": FALLBACK_SECTIONS, "node_ids": [], "codes": []}
            sections = [s for s in (sel.get("sections") or []) if s in data.SECTION_DESC][:6] or FALLBACK_SECTIONS
            slices = data.build_slices(sections, sel.get("node_ids") or [], sel.get("codes") or [])
            yield _sse({"type": "status", "t": "已取数:" + "、".join(sections)})

            # ② 带切片流式回答
            payload = json.dumps(slices, ensure_ascii=False)
            chat_msgs = [{"role": "system", "content": ANSWER_SYS.replace("{slices}", payload)}, *msgs]
            async for ev in llm.answer_stream(chat_msgs):
                if ev["type"] == "usage":
                    guard.add_tokens(ev["total_tokens"])
                elif ev["type"] == "thinking":
                    yield _sse({"type": "status", "t": "思考中…"})
                else:
                    yield _sse(ev)
            yield _sse({"type": "done"})
        except Exception as e:  # noqa: BLE001 出错也走 SSE 告知前端,别让流悬着
            alert.notify(f"err:{type(e).__name__}", f"回答服务异常:{type(e).__name__}: {e}")
            yield _sse({"type": "error", "t": f"服务出错:{type(e).__name__}"})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
