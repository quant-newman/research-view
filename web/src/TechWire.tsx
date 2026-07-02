import type { WireItem } from "./types";

const sentDot: Record<string, string> = { 利好: "bg-up", 利空: "bg-down", 中性: "bg-muted", 澄清: "bg-info" };
const sentTx: Record<string, string> = { 利好: "text-up", 利空: "text-down", 中性: "text-muted", 澄清: "text-info" };

// 分组展示顺序 + 中性标签色(权威媒体靠前,社交源靠后作情绪参考)
const GROUP_ORDER = ["华尔街日报", "路透社", "科技媒体", "Reddit", "推特X"];

export function TechWire({ wire }: { wire: WireItem[] }) {
  if (!wire?.length) {
    return <div className="text-dim text-[14px]">暂无舆情数据。<span className="text-dim">台北侧 build_us 抓 WSJ/路透/科技媒体/Reddit,盘后/盘前刷新。</span></div>;
  }
  const by: Record<string, WireItem[]> = {};
  for (const w of wire) (by[w.group] ||= []).push(w);
  const groups = Object.keys(by).sort((a, b) => {
    const ia = GROUP_ORDER.indexOf(a), ib = GROUP_ORDER.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
  return (
    <div className="space-y-4">
      {groups.map((g) => (
        <div key={g}>
          <div className="flex items-center gap-1.5 mb-1.5">
            <span className="w-0.5 h-3.5 bg-accent" />
            <span className="text-primary text-[13px] font-semibold">{g}</span>
            <span className="text-dim text-[12px] mono">{by[g].length}</span>
            {g === "Reddit" && <span className="text-dim text-[11px]">散户情绪·仅参考</span>}
          </div>
          <div className="border-l border-[#232B36] pl-3.5 ml-0.5 divide-y divide-[#232B36]">
            {by[g].map((w, i) => {
              const body = (
                <>
                  <div className="flex items-start gap-2">
                    <span className={`w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 ${sentDot[w.sentiment] || "bg-muted"}`} />
                    <p className="text-primary text-[14px] leading-snug font-medium flex-1">{w.one_line || w.title}</p>
                  </div>
                  {w.summary && <p className="text-muted text-[13px] leading-relaxed mt-1.5 ml-3.5">{w.summary}</p>}
                  <div className="flex items-center gap-2 mt-1.5 ml-3.5 text-[12px] text-dim">
                    <span className={sentTx[w.sentiment] || "text-muted"}>{w.sentiment}</span>
                    <span>·</span><span>{w.src}</span>
                    {w.url && <span className="text-accent/70">↗</span>}
                  </div>
                </>
              );
              return w.url ? (
                <a key={i} href={w.url} target="_blank" rel="noreferrer" className="block py-3 first:pt-0 hover:bg-elevated/40 -mx-1 px-1 rounded">{body}</a>
              ) : (
                <div key={i} className="py-3 first:pt-0">{body}</div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
