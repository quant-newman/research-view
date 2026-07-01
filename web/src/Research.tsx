import type { Research } from "./types";
import { useOpenStock } from "./stockCtx";
import { Section, MoreList } from "./ui";

// 评级色:偏多=红(A股涨色) 偏空=绿 中性=灰
const ratingColor = (r: string) => {
  if (/买入|增持|推荐|强烈|跑赢|优于/.test(r)) return "text-up bg-up/10";
  if (/减持|卖出|回避|跑输|弱于/.test(r)) return "text-down bg-down/10";
  return "text-muted bg-muted/10";
};

export function ResearchView({ r }: { r: Research | undefined }) {
  const open = useOpenStock();
  if (!r) return <div className="text-muted p-4">暂无研报</div>;
  const changes = r.digest?.changes || [];
  const views = r.digest?.views || [];
  return (
    <div className="space-y-4 max-w-5xl">
      {/* 评级/目标价变动榜 + 机构观点提炼 */}
      <div className="grid grid-cols-2 gap-4">
        <Section title="评级 / 目标价变动榜" count={changes.length}>
          {changes.length === 0 ? <div className="text-dim text-[13px]">近30日无评级/目标价变动。</div> : (
            <div className="space-y-2">
              <MoreList items={changes} initial={8}>
                {(c, i) => (
                  <div key={i} className="flex items-center gap-2 text-[13px]">
                    <span className={`px-1.5 py-0.5 rounded text-[12px] shrink-0 ${c.rating_dir === "上调" ? "text-up bg-up/10" : c.rating_dir === "下调" ? "text-down bg-down/10" : "text-muted bg-muted/10"}`}>
                      {c.rating_dir || (c.tp_chg && c.tp_chg > 0 ? "目标↑" : "目标↓")}
                    </span>
                    <button onClick={() => open({ code: c.code, name: c.name })} className="text-primary font-medium hover:text-accent shrink-0">{c.name}</button>
                    {c.rating_dir && <span className="text-muted">{c.prior_rating}→<span className="text-primary">{c.latest_rating}</span></span>}
                    {c.tp_chg != null && <span className={`mono ${c.tp_chg > 0 ? "text-up" : "text-down"}`}>目标{c.prior_tp}→{c.latest_tp}({c.tp_chg > 0 ? "+" : ""}{c.tp_chg}%)</span>}
                    <span className="text-dim text-[12px] ml-auto shrink-0">{c.latest_org}</span>
                  </div>
                )}
              </MoreList>
            </div>
          )}
        </Section>

        <Section title="机构观点提炼 · 覆盖最多" count={views.length}>
          {views.length === 0 ? <div className="text-dim text-[13px]">暂无。</div> : (
            <div className="space-y-2.5">
              <MoreList items={views} initial={6}>
                {(v, i) => (
                  <div key={i}>
                    <div className="flex items-center gap-2 text-[13px]">
                      <button onClick={() => open({ code: v.code, name: v.name })} className="text-primary font-medium hover:text-accent">{v.name}</button>
                      {v.latest_rating && <span className={`px-1 rounded text-[12px] ${ratingColor(v.latest_rating)}`}>{v.latest_rating}</span>}
                      <span className="text-dim text-[12px]">{v.n}篇</span>
                    </div>
                    {v.view && <p className="text-muted text-[13px] leading-relaxed mt-0.5">{v.view}</p>}
                  </div>
                )}
              </MoreList>
            </div>
          )}
        </Section>
      </div>

      {/* 研报流 + 覆盖热度 */}
      <div className="grid grid-cols-[1.7fr_1fr] gap-4">
        <Section title="近30日卖方研报" count={r.reports.length}>
          <div className="divide-y divide-[#232B36] -mt-1">
            <MoreList items={r.reports} initial={14}>
              {(rp, i) => (
                <div key={i} className="py-2">
                  <div className="flex items-center gap-2 text-[14px]">
                    <span className="mono text-dim">{rp.date}</span>
                    <button onClick={() => open({ code: rp.code, name: rp.name })} className="text-primary font-medium hover:text-accent">{rp.name}</button>
                    {rp.scope === "核心池"
                      ? <span className="px-1 rounded text-[12px] text-accent bg-accent/10">核心</span>
                      : <span className="px-1 rounded text-[12px] text-muted bg-muted/10">泛科技{rp.industry ? `·${rp.industry}` : ""}</span>}
                    <span className={`px-1.5 py-0.5 rounded text-[13px] ${ratingColor(rp.rating || "")}`}>{rp.rating || "—"}</span>
                    {rp.tp != null && <span className="mono text-accent text-[13px]">目标 {rp.tp}</span>}
                    <span className="text-dim text-[13px] ml-auto">{rp.org}</span>
                  </div>
                  <div className="text-muted text-[14px] mt-0.5 truncate">{rp.title}</div>
                </div>
              )}
            </MoreList>
          </div>
        </Section>

        <Section title="覆盖热度 · 研报最多的票" count={r.coverage.length}>
          <div className="space-y-1.5">
            <MoreList items={r.coverage} initial={15}>
              {(c, i) => (
                <div key={i} className="flex items-center gap-2 text-[14px]">
                  <button onClick={() => open({ name: c.name })} className="text-primary flex-1 text-left hover:text-accent">{c.name}</button>
                  <span className="mono text-accent">{c.n}篇</span>
                  <span className="mono text-dim text-[13px]">{c.latest}</span>
                </div>
              )}
            </MoreList>
          </div>
        </Section>
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
            <div className="mt-2.5 border-t hairline pt-2">
              <div className="text-accent text-[12px] mb-1.5">核心要点</div>
              <ul className="space-y-1.5">
                {l.core_views.map((v: string, j: number) => (
                  <li key={j} className="text-primary text-[14px] leading-relaxed flex gap-1.5">
                    <span className="text-accent shrink-0 mono">{j + 1}</span><span>{v}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
