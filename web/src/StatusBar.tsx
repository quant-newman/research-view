import { useEffect, useState } from "react";
import type { Dashboard } from "./types";
import { HealthDot } from "./System";
import { StaleBadge, pctCls, timeHour } from "./ui";

export type Market = "A" | "US";

function MarketToggle({ market, onMarket }: { market: Market; onMarket: (m: Market) => void }) {
  return (
    <div className="flex rounded overflow-hidden border hairline text-[13px] shrink-0">
      {(["A", "US"] as const).map((m) => (
        <button key={m} onClick={() => onMarket(m)}
          className={`px-2.5 py-0.5 ${market === m ? "bg-accent text-black font-semibold" : "text-muted hover:text-primary"}`}>
          {m === "A" ? "A股" : "美股"}
        </button>
      ))}
    </div>
  );
}

function Clock() {
  const [t, setT] = useState("");
  useEffect(() => {
    const f = () => {
      const d = new Date(Date.now() + (8 * 60 + new Date().getTimezoneOffset()) * 60000);
      setT(d.toTimeString().slice(0, 8));
    };
    f(); const id = setInterval(f, 1000); return () => clearInterval(id);
  }, []);
  return <span className="mono text-dim">{t} UTC+8</span>;
}

// "YYYY-MM-DD HH:MM"/ISO(都是 UTC+8 字面值)→ 分钟数,只用于两者相减,时区一致差值正确
const mins = (s?: string) => {
  const m = (s || "").match(/(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  return m ? Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) / 60000 : null;
};

export function StatusBar({ d, market, onMarket, onHealth }: { d: Dashboard; market: Market; onMarket: (m: Market) => void; onHealth: () => void }) {
  const us = d.us;
  const isUS = market === "US";
  const ut = us?.temperature;
  const at = d.temperature;
  const sessionLabel = d.report?.session === "premarket" ? "盘前" : d.report?.session === "intraday" ? "盘中" : "盘后";
  // 新闻停更检测:最新新闻比 dashboard 生成时点落后 >3h 即标(对比生成时点而非墙钟,周末/夜间不误报)
  let newsLatest = "";
  for (const g of d.news_by_node) for (const it of g.items) if (it.time && it.time > newsLatest) newsLatest = it.time;
  const nl = mins(newsLatest), gen = mins(d.meta?.generated_at);
  const newsStale = nl != null && gen != null && gen - nl > 180;
  return (
    <div className="flex items-center gap-4 px-4 h-11 border-b hairline bg-surface text-[14px]">
      <MarketToggle market={market} onMarket={onMarket} />
      <div className="flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full inline-block ${isUS ? "bg-info" : "bg-accent"}`} />
        <span className="font-semibold">{isUS ? "美股" : sessionLabel}</span>
        <span className="text-dim">·</span>
        <span className="text-muted">{isUS ? `美东 ${us?.us_session_date || "—"} ${us?.session_status || "收盘"}` : (d.report?.data_cutoff || d.meta?.date || "—")}</span>
      </div>
      {isUS && us?.fallback && <StaleBadge date={us.data_date} label="美股数据截至" />}
      {!isUS && newsStale && <StaleBadge date={timeHour(newsLatest)} label="新闻停更 · 最新" />}
      {isUS ? (
        ut && (
          <div className="mono text-muted flex gap-3">
            <span>覆盖 <span className="text-primary">{ut.counted}</span></span>
            <span className="text-up">涨 {ut.up}</span>
            <span className="text-down">跌 {ut.down}</span>
            <span className={pctCls(ut.avg_pct)}>均 {ut.avg_pct}%</span>
          </div>
        )
      ) : (
        at && (
          <div className="mono text-muted flex gap-3">
            <span>池 <span className="text-primary">{at.pool_counted}</span></span>
            <span className="text-up">涨 {at.up}</span>
            <span className="text-down">跌 {at.down}</span>
            <span className="text-up">涨停 {at.limit_up}</span>
            <span className={pctCls(at.avg_pct)}>均 {at.avg_pct}%</span>
          </div>
        )
      )}
      <div className="ml-auto flex items-center gap-4">
        {d.health && <HealthDot level={d.health.level} onClick={onHealth} />}
        <Clock />
      </div>
    </div>
  );
}
