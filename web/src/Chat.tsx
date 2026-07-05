import { useEffect, useRef, useState } from "react";

// 问答页:POST /api/chat SSE 流式。后端两段式(选片→DeepSeek带切片回答),严格只读。
// 事件协议:{type:"status"|"delta"|"done"|"error", t?:string}

type Msg = { role: "user" | "assistant"; content: string; status?: string; error?: boolean };

const EXAMPLES = [
  "机器人链今天为什么这么热?",
  "算力和创新医药最近资金面谁更强?",
  "绿的谐波最近走势和平台研判怎么样?",
  "美股AI算力芯片板块最新情况?",
  "今天的研判卡里信心最高的是哪个方向?",
];

// 极简行内渲染:只处理 **加粗**,其余按纯文本 pre-wrap(后端已要求不出表格)
function Rich({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return (
    <span className="whitespace-pre-wrap break-words">
      {parts.map((p, i) =>
        p.startsWith("**") && p.endsWith("**") ? <b key={i} className="text-primary">{p.slice(2, -2)}</b> : p)}
    </span>
  );
}

export function ChatView() {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);
  useEffect(() => () => abortRef.current?.abort(), []);

  const patchLast = (fn: (m: Msg) => Msg) =>
    setMsgs((cur) => cur.map((m, i) => (i === cur.length - 1 ? fn(m) : m)));

  async function send(q: string) {
    const question = q.trim();
    if (!question || busy) return;
    setInput("");
    setBusy(true);
    const history = [...msgs.filter((m) => !m.error), { role: "user" as const, content: question }];
    setMsgs([...history, { role: "assistant", content: "", status: "连接中…" }]);
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      const resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: history.map(({ role, content }) => ({ role, content })) }),
        signal: ac.signal,
      });
      if (!resp.ok || !resp.body) {
        const detail = await resp.json().catch(() => null);
        patchLast((m) => ({ ...m, status: undefined, error: true, content: detail?.error || `请求失败(${resp.status})` }));
        return;
      }
      const reader = resp.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const frames = buf.split("\n\n");
        buf = frames.pop() || "";
        for (const f of frames) {
          const line = f.split("\n").find((l) => l.startsWith("data:"));
          if (!line) continue;
          let ev: { type: string; t?: string };
          try { ev = JSON.parse(line.slice(5)); } catch { continue; }
          if (ev.type === "status") patchLast((m) => ({ ...m, status: ev.t }));
          else if (ev.type === "delta") patchLast((m) => ({ ...m, status: undefined, content: m.content + (ev.t || "") }));
          else if (ev.type === "error") patchLast((m) => ({ ...m, status: undefined, error: true, content: m.content || ev.t || "服务出错" }));
          else if (ev.type === "done") patchLast((m) => ({ ...m, status: undefined }));
        }
      }
      // 流断在中途(网络/超时):有内容就保留,空回答则提示
      patchLast((m) => (m.content || m.error ? { ...m, status: undefined } :
        { ...m, status: undefined, error: true, content: "没有收到回答,稍后再试" }));
    } catch {
      if (!ac.signal.aborted)
        patchLast((m) => ({ ...m, status: undefined, error: true, content: m.content || "网络错误,稍后再试" }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="flex-1 overflow-auto p-3 md:p-5">
        <div className="max-w-3xl mx-auto space-y-4">
          {msgs.length === 0 && (
            <div className="pt-8 space-y-4">
              <div className="text-center space-y-1">
                <div className="text-[16px] text-primary font-medium">问答 · 问看板数据</div>
                <div className="text-[13px] text-muted">基于当前看板数据回答(研判/资金/热点/行情/新闻/美股),数据之外不作答</div>
              </div>
              <div className="flex flex-wrap justify-center gap-2">
                {EXAMPLES.map((q) => (
                  <button key={q} onClick={() => send(q)}
                    className="px-3 py-1.5 rounded-full border hairline bg-surface text-[13px] text-muted hover:text-primary hover:border-accent/40">
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}
          {msgs.map((m, i) =>
            m.role === "user" ? (
              <div key={i} className="flex justify-end">
                <div className="max-w-[85%] px-3.5 py-2 rounded-lg bg-elevated text-[14px] text-primary">
                  <Rich text={m.content} />
                </div>
              </div>
            ) : (
              <div key={i} className="flex">
                <div className={`max-w-[95%] px-3.5 py-2 rounded-lg border hairline bg-surface text-[14px] leading-relaxed ${m.error ? "text-down" : "text-primary"}`}>
                  {m.content ? <Rich text={m.content} /> : null}
                  {m.status && <span className="text-[13px] text-dim animate-pulse">{m.content ? " " : ""}{m.status}</span>}
                </div>
              </div>
            ))}
          <div ref={bottomRef} />
        </div>
      </div>
      <div className="border-t hairline bg-surface p-3">
        <form className="max-w-3xl mx-auto flex gap-2"
          onSubmit={(e) => { e.preventDefault(); send(input); }}>
          <input value={input} onChange={(e) => setInput(e.target.value)} disabled={busy}
            placeholder={busy ? "回答中…" : "问看板数据,如:今天哪个链资金流入最多?"}
            className="flex-1 px-3.5 py-2.5 rounded-md bg-elevated text-[14px] text-primary placeholder:text-dim outline-none border hairline focus:border-accent/50 disabled:opacity-60" />
          <button type="submit" disabled={busy || !input.trim()}
            className="px-4 rounded-md bg-accent/15 text-accent text-[14px] disabled:opacity-40 hover:bg-accent/25">
            发送
          </button>
        </form>
        <div className="max-w-3xl mx-auto mt-1.5 text-[11px] text-dim">
          回答由 AI 基于看板数据生成,仅为数据解读,不构成投资建议
        </div>
      </div>
    </div>
  );
}
