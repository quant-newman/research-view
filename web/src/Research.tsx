import type { Research } from "./types";

// 评级色:偏多=红(A股涨色) 偏空=绿 中性=灰
const ratingColor = (r: string) => {
  if (/买入|增持|推荐|强烈|跑赢|优于/.test(r)) return "text-up bg-up/10";
  if (/减持|卖出|回避|跑输|弱于/.test(r)) return "text-down bg-down/10";
  return "text-muted bg-muted/10";
};

export function ResearchView({ r }: { r: Research | undefined }) {
  if (!r) return <div className="text-muted p-4">暂无研报</div>;
  return (
    <div className="grid grid-cols-[1.7fr_1fr] gap-4">
      <div className="border hairline rounded bg-surface">
        <div className="px-3 py-2 border-b hairline text-[11px] text-muted uppercase tracking-wide">
          近30日卖方研报 · {r.reports.length} 篇(池内)
        </div>
        <div className="divide-y divide-[#232B36]">
          {r.reports.map((rp, i) => (
            <div key={i} className="px-3 py-2 hover:bg-elevated/40">
              <div className="flex items-center gap-2 text-[12px]">
                <span className="mono text-dim">{rp.date}</span>
                <span className="text-primary font-medium">{rp.name}</span>
                <span className={`px-1.5 py-0.5 rounded text-[11px] ${ratingColor(rp.rating || "")}`}>
                  {rp.rating || "—"}
                </span>
                {rp.tp != null && <span className="mono text-accent text-[11px]">目标 {rp.tp}</span>}
                <span className="text-dim text-[11px] ml-auto">{rp.org}</span>
              </div>
              <div className="text-muted text-[12px] mt-0.5 truncate">{rp.title}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="border hairline rounded bg-surface h-fit">
        <div className="px-3 py-2 border-b hairline text-[11px] text-muted uppercase tracking-wide">
          覆盖热度 · 研报最多的票
        </div>
        <div className="p-3 space-y-1.5">
          {r.coverage.map((c, i) => (
            <div key={i} className="flex items-center gap-2 text-[12px]">
              <span className="text-primary flex-1">{c.name}</span>
              <span className="mono text-accent">{c.n}篇</span>
              <span className="mono text-dim text-[11px]">{c.latest}</span>
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
        <p className="text-muted text-[12px] leading-relaxed">
          规划:接海外对冲基金季度信聚合圈(不自建信源清单),AWS 台北定时抓 →
          DeepSeek 中文摘要(3条核心观点 + 立场 + 策略 + 对AI科技链相关度评分)。
          处理不过来标「待分类」占位。
        </p>
        <p className="text-dim text-[11px] mt-3">表结构与 B5 摘要已就位,待你指定信源(Dropbox季度归档 / fiscal.ai 类)后接入。</p>
      </div>
    );
  }
  return (
    <div className="grid grid-cols-2 gap-3">
      {letters.map((l, i) => (
        <div key={i} className="border hairline rounded bg-surface p-3">
          <div className="flex items-center justify-between">
            <span className="text-primary font-medium">{l.fund_name}</span>
            <span className="text-dim text-[11px] mono">{l.period}</span>
          </div>
          <div className="flex gap-2 mt-1 text-[11px]">
            {l.stance && <span className="text-muted">{l.stance}</span>}
            {l.strategy && <span className="text-dim">{l.strategy}</span>}
            {l.relevance != null && <span className="text-accent">相关 {l.relevance}/10</span>}
          </div>
        </div>
      ))}
    </div>
  );
}
