import { useMemo, useState } from "react";
import type { NewsNode, NewsItem } from "./types";
import { useOpenStock } from "./stockCtx";

const sentColor: Record<string, string> = {
  利好: "text-up bg-up/10", 利空: "text-down bg-down/10",
  中性: "text-muted bg-muted/10", 澄清: "text-info bg-info/10",
};
const SENTS = ["利好", "利空", "中性", "澄清"];

type Flat = NewsItem & { chain: string; node: string; scope: string; gid: string };

function timeShort(t?: string) {
  if (!t) return "";
  const m = t.match(/\d{4}-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  return m ? `${m[1]}-${m[2]} ${m[3]}:${m[4]}` : t.slice(5, 16);
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick}
      className={`px-2 py-0.5 rounded text-[13px] border ${on ? "border-accent text-accent bg-accent/10" : "border-hairline text-muted hover:text-primary"}`}>
      {children}
    </button>
  );
}

function NewsRow({ n }: { n: Flat }) {
  const open = useOpenStock();
  const mine = n.holding || n.watching;
  return (
    <div className={`border rounded px-3 py-2 ${mine ? "border-accent/40 bg-accent/5" : "hairline bg-surface"}`}>
      <div className="flex items-start gap-2">
        <span className={`px-1.5 py-0.5 rounded text-[13px] shrink-0 ${sentColor[n.sentiment] || "text-muted"}`}>{n.sentiment}</span>
        <div className="flex-1 min-w-0">
          <p className="text-primary text-[15px] leading-snug font-medium">{n.one_line || n.title}</p>
          {n.summary && <p className="text-muted text-[14px] leading-relaxed mt-1">{n.summary}</p>}
          <div className="flex flex-wrap items-center gap-2 mt-1 text-[13px] text-dim">
            <span className="text-muted">{n.chain}/{n.node}</span>
            {n.codes?.slice(0, 4).map((c) => <button key={c} onClick={() => open({ code: c })} className="mono text-muted hover:text-accent">{c}</button>)}
            {n.holding && <span className="text-accent">持仓</span>}
            {n.watching && <span className="text-info">自选</span>}
            <span className="ml-auto text-muted">{n.src}</span>
            <span className="mono">{timeShort(n.time)}</span>
            {n.url && <a href={n.url} target="_blank" rel="noreferrer" className="text-info hover:underline">原文↗</a>}
          </div>
        </div>
      </div>
    </div>
  );
}

export function NewsView({ nodes }: { nodes: NewsNode[] }) {
  const [sent, setSent] = useState<Set<string>>(new Set());
  const [mineOnly, setMineOnly] = useState(false);
  const [scope, setScope] = useState<"all" | "核心链" | "泛科技">("all");
  const [mode, setMode] = useState<"chain" | "time">("chain");

  const flat: Flat[] = useMemo(() =>
    nodes.flatMap((g) => g.items.map((it) => ({
      ...it, chain: g.chain, node: g.node, scope: g.scope || "核心链", gid: g.node_id,
    }))), [nodes]);

  const toggleSent = (s: string) => {
    const next = new Set(sent);
    next.has(s) ? next.delete(s) : next.add(s);
    setSent(next);
  };
  const pass = (n: Flat) =>
    (sent.size === 0 || sent.has(n.sentiment)) &&
    (!mineOnly || n.holding || n.watching) &&
    (scope === "all" || n.scope === scope);

  // 去重后的扁平集合(同一条新闻可命中多个节点)
  const dedup = useMemo(() => {
    const seen = new Set<string>();
    const out: Flat[] = [];
    for (const n of flat) {
      const k = `${n.title}|${n.src}|${n.time}`;
      if (seen.has(k)) continue;
      seen.add(k); out.push(n);
    }
    return out;
  }, [flat]);

  const dedupPassed = dedup.filter(pass);
  const mineCount = dedup.filter((n) => n.holding || n.watching).length;
  const timeSorted = [...dedupPassed].sort((a, b) => (b.time || "").localeCompare(a.time || ""));

  return (
    <div className="space-y-3">
      {/* 过滤条 */}
      <div className="flex flex-wrap items-center gap-3 text-[14px]">
        <div className="flex items-center gap-1">
          {SENTS.map((s) => <Chip key={s} on={sent.has(s)} onClick={() => toggleSent(s)}>{s}</Chip>)}
        </div>
        <span className="text-dim">·</span>
        <Chip on={mineOnly} onClick={() => setMineOnly(!mineOnly)}>只看持仓/自选{mineCount ? ` (${mineCount})` : ""}</Chip>
        <span className="text-dim">·</span>
        <div className="flex items-center gap-1">
          {(["all", "核心链", "泛科技"] as const).map((s) =>
            <Chip key={s} on={scope === s} onClick={() => setScope(s)}>{s === "all" ? "全部范围" : s}</Chip>)}
        </div>
        <div className="ml-auto flex items-center gap-1">
          <Chip on={mode === "chain"} onClick={() => setMode("chain")}>按链</Chip>
          <Chip on={mode === "time"} onClick={() => setMode("time")}>最新</Chip>
        </div>
        <span className="text-dim mono">{dedupPassed.length} 条</span>
      </div>

      {mineCount === 0 && (
        <div className="text-dim text-[13px]">未设持仓/自选 — 设置后你的票有新闻会高亮置顶。</div>
      )}

      {/* 内容 */}
      {mode === "time" ? (
        <div className="space-y-1.5">
          {timeSorted.map((n, i) => <NewsRow key={i} n={n} />)}
        </div>
      ) : (
        <div className="space-y-4">
          {nodes.map((g) => {
            const items = g.items.filter((it) => pass({
              ...it, chain: g.chain, node: g.node, scope: g.scope || "核心链", gid: g.node_id,
            } as Flat));
            if (!items.length) return null;
            return (
              <div key={g.node_id}>
                <div className="flex items-center gap-2 mb-1.5 text-[14px]">
                  <span className="w-0.5 h-3.5 bg-accent" />
                  <span className="text-primary font-semibold">{g.chain}/{g.node}</span>
                  <span className={`px-1.5 py-0.5 rounded text-[12px] ${g.scope === "泛科技" ? "text-muted bg-muted/10" : "text-accent bg-accent/10"}`}>{g.scope || "核心链"}</span>
                  <span className="text-dim">({items.length})</span>
                </div>
                <div className="space-y-1.5">
                  {items.map((it, i) => <NewsRow key={i} n={{
                    ...it, chain: g.chain, node: g.node, scope: g.scope || "核心链", gid: g.node_id,
                  } as Flat} />)}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
