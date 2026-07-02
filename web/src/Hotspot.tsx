import { useState } from "react";
import type { Hotspot, HotspotItem } from "./types";
import { useOpenStock } from "./stockCtx";
import { MoreList, timeHour } from "./ui";

const trendCls: Record<string, string> = {
  升温: "text-up bg-up/10", 降温: "text-down bg-down/10", 持平: "text-muted bg-muted/10",
};
const pctCls = (v: number | null | undefined) => (v == null ? "text-dim" : v > 0 ? "text-up" : v < 0 ? "text-down" : "text-muted");

function Card({ it, rank }: { it: HotspotItem; rank: number }) {
  const [open, setOpen] = useState(rank <= 2);
  const openStock = useOpenStock();
  return (
    <div className="border hairline rounded bg-surface">
      <div className="flex items-start gap-3 px-3 py-2.5">
        <span className="mono text-accent text-[16px] w-6 shrink-0">{rank}</span>
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-primary font-semibold text-[15px]">{it.chain}/{it.node}</span>
            <span className={`px-1.5 py-0.5 rounded text-[12px] ${trendCls[it.trend] || "text-muted"}`}>{it.trend}</span>
            <span className="text-dim text-[12px] mono">热度 {it.heat}</span>
            {timeHour(it.latest_time) && <span className="text-dim text-[12px] mono ml-auto">最新 {timeHour(it.latest_time)}</span>}
          </div>
          {it.reason && <p className="text-muted text-[14px] leading-relaxed mt-1">{it.reason}</p>}
          <div className="flex flex-wrap items-center gap-3 mt-1.5 text-[12px] text-dim mono">
            <span>新闻 <span className="text-primary">{it.news_today}</span>{it.news_prior != null ? `(昨${it.news_prior})` : ""}</span>
            {it.lhb ? <span>龙虎榜 <span className="text-accent">{it.lhb}</span></span> : null}
            {it.ret_1d != null && <span>今日 <span className={pctCls(it.ret_1d)}>{it.ret_1d > 0 ? "+" : ""}{it.ret_1d}%</span></span>}
            {(it.pos || it.neg) ? <span><span className="text-up">利好{it.pos || 0}</span>/<span className="text-down">利空{it.neg || 0}</span></span> : null}
          </div>
          {it.stocks?.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-1.5">
              {it.stocks.slice(0, 6).map((s) => <button key={s} onClick={() => openStock({ name: s })} className="text-[12px] text-muted bg-elevated/60 px-1.5 py-0.5 rounded hover:text-accent">{s}</button>)}
            </div>
          )}
          {it.news?.length > 0 && (
            <>
              <button onClick={() => setOpen(!open)} className="text-info text-[12px] mt-1.5 hover:underline">
                {open ? "收起" : `展开 ${it.news.length} 条驱动新闻`}
              </button>
              {open && (
                <ul className="mt-1 space-y-1">
                  {it.news.map((n, i) => (
                    <li key={i} className="text-[13px] text-muted leading-relaxed flex gap-1.5">
                      <span className="text-accent shrink-0">·</span><span>{n}</span>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export function HotspotView({ hotspot }: { hotspot: Hotspot | null | undefined }) {
  if (!hotspot || !hotspot.items?.length) {
    return <div className="text-muted p-4 text-[14px]">今日暂无热点数据(盘中/盘后自动刷新)。</div>;
  }
  return (
    <div className="max-w-3xl space-y-3">
      <div className="border border-accent/40 rounded bg-accent/5 px-4 py-3">
        <div className="text-accent text-[12px] mb-1">今日热点 · 市场在炒什么</div>
        <p className="text-primary text-[16px] leading-relaxed font-medium">{hotspot.headline}</p>
        <p className="text-dim text-[12px] mt-1">热度=统计(新闻量+龙虎榜+涨跌),归因由 DeepSeek 综合 · 只呈现事实不下判断</p>
      </div>
      <div className="space-y-2">
        <MoreList items={hotspot.items} initial={6}>
          {(it, i) => <Card key={it.node_id + i} it={it} rank={i + 1} />}
        </MoreList>
      </div>
    </div>
  );
}
