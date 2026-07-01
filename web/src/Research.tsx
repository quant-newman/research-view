import type { Research } from "./types";
import { useOpenStock } from "./stockCtx";

// 评级色:偏多=红(A股涨色) 偏空=绿 中性=灰
const ratingColor = (r: string) => {
  if (/买入|增持|推荐|强烈|跑赢|优于/.test(r)) return "text-up bg-up/10";
  if (/减持|卖出|回避|跑输|弱于/.test(r)) return "text-down bg-down/10";
  return "text-muted bg-muted/10";
};

export function ResearchView({ r }: { r: Research | undefined }) {
  const open = useOpenStock();
  if (!r) return <div className="text-muted p-4">暂无研报</div>;
  return (
    <div className="grid grid-cols-[1.7fr_1fr] gap-4">
      <div className="border hairline rounded bg-surface">
        <div className="px-3 py-2 border-b hairline text-[13px] text-muted uppercase tracking-wide">
          近30日卖方研报 · {r.reports.length} 篇(池内)
        </div>
        <div className="divide-y divide-[#232B36]">
          {r.reports.map((rp, i) => (
            <div key={i} className="px-3 py-2 hover:bg-elevated/40">
              <div className="flex items-center gap-2 text-[14px]">
                <span className="mono text-dim">{rp.date}</span>
                <button onClick={() => open({ code: rp.code, name: rp.name })} className="text-primary font-medium hover:text-accent">{rp.name}</button>
                {rp.scope === "核心池"
                  ? <span className="px-1 rounded text-[12px] text-accent bg-accent/10">核心</span>
                  : <span className="px-1 rounded text-[12px] text-muted bg-muted/10">泛科技{rp.industry ? `·${rp.industry}` : ""}</span>}
                <span className={`px-1.5 py-0.5 rounded text-[13px] ${ratingColor(rp.rating || "")}`}>
                  {rp.rating || "—"}
                </span>
                {rp.tp != null && <span className="mono text-accent text-[13px]">目标 {rp.tp}</span>}
                <span className="text-dim text-[13px] ml-auto">{rp.org}</span>
              </div>
              <div className="text-muted text-[14px] mt-0.5 truncate">{rp.title}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="border hairline rounded bg-surface h-fit">
        <div className="px-3 py-2 border-b hairline text-[13px] text-muted uppercase tracking-wide">
          覆盖热度 · 研报最多的票
        </div>
        <div className="p-3 space-y-1.5">
          {r.coverage.map((c, i) => (
            <div key={i} className="flex items-center gap-2 text-[14px]">
              <span className="text-primary flex-1">{c.name}</span>
              <span className="mono text-accent">{c.n}篇</span>
              <span className="mono text-dim text-[13px]">{c.latest}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function LettersView({ r }: { r: Research | undefined }) {
  const letters = r?.letters || [];
  if (letters.length === 0) {
    return (
      <div className="max-w-2xl border hairline rounded bg-surface p-6 text-center">
        <div className="text-primary mb-2">基金信函 · 信源待接入</div>
        <p className="text-muted text-[14px] leading-relaxed">
          规划:接海外对冲基金季度信聚合圈(不自建信源清单),AWS 台北定时抓 →
          DeepSeek 中文摘要(3条核心观点 + 立场 + 策略 + 对AI科技链相关度评分)。
          处理不过来标「待分类」占位。
        </p>
        <p className="text-dim text-[13px] mt-3">表结构与 B5 摘要已就位,待你指定信源(Dropbox季度归档 / fiscal.ai 类)后接入。</p>
      </div>
    );
  }
  const relColor = (v: number | null) =>
    v == null ? "text-dim" : v >= 7 ? "text-up" : v >= 4 ? "text-accent" : "text-dim";
  return (
    <div className="grid grid-cols-2 gap-3">
      {letters.map((l, i) => (
        <div key={i} className="border hairline rounded bg-surface p-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-primary font-medium">{l.fund_name}</span>
            <span className="text-dim text-[13px] mono shrink-0">{l.period}</span>
          </div>
          {l.title && (
            <div className="text-muted text-[14px] mt-0.5">
              {l.url ? <a href={l.url} target="_blank" rel="noreferrer" className="hover:text-primary hover:underline">{l.title} ↗</a> : l.title}
            </div>
          )}
          <div className="flex flex-wrap gap-2 mt-1 text-[13px]">
            {l.stance && <span className="text-muted">{l.stance}</span>}
            {l.strategy && <span className="text-dim">{l.strategy}</span>}
            {l.relevance != null && <span className={relColor(l.relevance)}>AI科技链相关 {l.relevance}/10</span>}
          </div>
          {Array.isArray(l.core_views) && l.core_views.length > 0 && (
            <ul className="mt-2 space-y-1">
              {l.core_views.slice(0, 3).map((v: string, j: number) => (
                <li key={j} className="text-primary text-[14px] leading-snug flex gap-1.5">
                  <span className="text-accent shrink-0">·</span><span>{v}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </div>
  );
}
