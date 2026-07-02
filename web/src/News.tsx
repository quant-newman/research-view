import { useMemo, useState } from "react";
import type { NewsNode, NewsItem } from "./types";
import { useOpenStock } from "./stockCtx";
import { Section, MoreList, timeHour } from "./ui";

const sentColor: Record<string, string> = {
  利好: "text-up bg-up/10", 利空: "text-down bg-down/10",
  中性: "text-muted bg-muted/10", 澄清: "text-info bg-info/10",
};
const SENTS = ["利好", "利空", "中性", "澄清"];

type Flat = NewsItem & { chain: string; node: string; scope: string; gid: string };

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
            <span className="mono">{timeHour(n.time)}</span>
            {n.url && <a href={n.url} target="_blank" rel="noreferrer" className="text-info hover:underline">原文↗</a>}
          </div>
        </div>
      </div>
    </div>
  );
}

const EVTS = ["公告", "政策", "涨跌异动", "研报", "外盘", "其他"];

export function NewsView({ nodes }: { nodes: NewsNode[] }) {
  const [sent, setSent] = useState<Set<string>>(new Set());
  const [evt, setEvt] = useState<Set<string>>(new Set());
  const [mineOnly, setMineOnly] = useState(false);
  const [scope, setScope] = useState<"all" | "核心链" | "泛科技">("all");
  const [mode, setMode] = useState<"chain" | "event" | "time">("chain");

  const flat: Flat[] = useMemo(() =>
    nodes.flatMap((g) => g.items.map((it) => ({
      ...it, chain: g.chain, node: g.node, scope: g.scope || "核心链", gid: g.node_id,
    }))), [nodes]);

  const toggle = (set: Set<string>, setter: (s: Set<string>) => void, v: string) => {
    const next = new Set(set); next.has(v) ? next.delete(v) : next.add(v); setter(next);
  };
  const pass = (n: Flat) =>
    (sent.size === 0 || sent.has(n.sentiment)) &&
    (evt.size === 0 || evt.has(n.event_type || "其他")) &&
    (!mineOnly || n.holding || n.watching) &&
    (scope === "all" || n.scope === scope);

  const dedup = useMemo(() => {
    const seen = new Set<string>(); const out: Flat[] = [];
    for (const n of flat) { const k = `${n.title}|${n.src}|${n.time}`; if (!seen.has(k)) { seen.add(k); out.push(n); } }
    return out;
  }, [flat]);

  const dedupPassed = dedup.filter(pass);
  const mineCount = dedup.filter((n) => n.holding || n.watching).length;
  const evtsPresent = EVTS.filter((e) => dedup.some((n) => (n.event_type || "其他") === e));

  // 分组:按链(用 nodes)/ 按事件(event_type)
  const groups = useMemo(() => {
    if (mode === "chain") {
      return nodes.map((g) => ({
        key: g.node_id, title: `${g.chain}/${g.node}`, scope: g.scope || "核心链",
        items: g.items.map((it) => ({ ...it, chain: g.chain, node: g.node, scope: g.scope || "核心链", gid: g.node_id } as Flat)).filter(pass),
      })).filter((g) => g.items.length);
    }
    const m: Record<string, Flat[]> = {};
    for (const n of dedupPassed) (m[n.event_type || "其他"] ||= []).push(n);
    return EVTS.filter((e) => m[e]?.length).map((e) => ({ key: e, title: e, scope: undefined as any, items: m[e] }));
  }, [mode, nodes, sent, evt, mineOnly, scope]);

  const timeSorted = [...dedupPassed].sort((a, b) => (b.time || "").localeCompare(a.time || ""));

  return (
    <div className="space-y-3">
      {/* 过滤条 */}
      <div className="flex flex-wrap items-center gap-2.5 text-[14px]">
        <div className="flex items-center gap-1">
          {SENTS.map((s) => <Chip key={s} on={sent.has(s)} onClick={() => toggle(sent, setSent, s)}>{s}</Chip>)}
        </div>
        <span className="text-dim">·</span>
        <div className="flex items-center gap-1">
          {evtsPresent.map((e) => <Chip key={e} on={evt.has(e)} onClick={() => toggle(evt, setEvt, e)}>{e}</Chip>)}
        </div>
        <span className="text-dim">·</span>
        <Chip on={mineOnly} onClick={() => setMineOnly(!mineOnly)}>持仓/自选{mineCount ? ` (${mineCount})` : ""}</Chip>
        <div className="flex items-center gap-1">
          {(["all", "核心链", "泛科技"] as const).map((s) =>
            <Chip key={s} on={scope === s} onClick={() => setScope(s)}>{s === "all" ? "全部" : s}</Chip>)}
        </div>
        <div className="ml-auto flex items-center gap-1">
          {(["chain", "event", "time"] as const).map((mo) =>
            <Chip key={mo} on={mode === mo} onClick={() => setMode(mo)}>{mo === "chain" ? "按链" : mo === "event" ? "按事件" : "最新"}</Chip>)}
        </div>
        <span className="text-dim mono">{dedupPassed.length} 条</span>
      </div>

      {/* 内容 */}
      {mode === "time" ? (
        <div className="space-y-1.5">
          <MoreList items={timeSorted} initial={20}>{(n, i) => <NewsRow key={i} n={n} />}</MoreList>
        </div>
      ) : (
        <div className="space-y-3">
          {groups.map((g, gi) => (
            <Section key={g.key} title={g.title} count={g.items.length} defaultOpen={gi < 4}
              right={g.scope ? <span className={`px-1.5 py-0.5 rounded text-[12px] ${g.scope === "泛科技" ? "text-muted bg-muted/10" : "text-accent bg-accent/10"}`}>{g.scope}</span> : undefined}>
              <div className="space-y-1.5">
                <MoreList items={g.items} initial={5}>{(it, i) => <NewsRow key={i} n={it} />}</MoreList>
              </div>
            </Section>
          ))}
        </div>
      )}
    </div>
  );
}
