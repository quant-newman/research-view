import { useEffect, useMemo, useState } from "react";
import type { Dashboard, NewsNode } from "./types";
import HeatmapView from "./Heatmap";
import SystemView from "./System";
import { ResearchView, LettersView } from "./Research";
import { NewsView } from "./News";
import { UsBoardView } from "./UsBoard";
import { UsResearchView } from "./UsResearch";
import { TechWireX } from "./TechWire";
import { HotspotView } from "./Hotspot";
import { MoneyflowView } from "./Moneyflow";
import { StockDetail } from "./StockDetail";
import { StockCtx, type StockSel } from "./stockCtx";
import { StatusBar, type Market } from "./StatusBar";
import { ReportPageView } from "./Report";

const NAV = [
  { key: "report", label: "报告" },
  { key: "hotspot", label: "热点" },
  { key: "flow", label: "资金" },
  { key: "heatmap", label: "热力" },
  { key: "news", label: "新闻" },
  { key: "research", label: "研究" },
  { key: "letters", label: "信函" },
  { key: "system", label: "系统" },
];

export default function App() {
  const [d, setD] = useState<Dashboard | null>(null);
  const [err, setErr] = useState("");
  const [view, setView] = useState("report");
  const [market, setMarket] = useState<Market>("A");
  const [stock, setStock] = useState<StockSel | null>(null);
  const [alert, setAlert] = useState<{ job?: string; at?: string; msg?: string } | null>(null);
  useEffect(() => {
    // 核心键缺失时补默认值:后端某天少发一个键不该让整页白屏
    fetch("/data/dashboard.json").then((r) => r.json()).then((raw) => setD({
      ...raw,
      meta: raw?.meta || { date: "", generated_at: "", tz: "UTC+8" },
      temperature: raw?.temperature ?? null,
      news_by_node: raw?.news_by_node || [],
      stock_events: raw?.stock_events || [],
    } as Dashboard)).catch((e) => setErr(String(e)));
    // 管道失败旗标(run_*.sh 失败时写入,成功清除)→ 红横幅
    fetch("/data/alert.json").then((r) => (r.ok ? r.json() : null)).then(setAlert).catch(() => setAlert(null));
  }, []);

  // 美股新闻(扁平)→ 复用 A股 的按节点分组结构(按板块分组);报告页与新闻页共用
  const usNewsNodes: NewsNode[] = useMemo(() => {
    const m: Record<string, NewsNode> = {};
    for (const n of d?.us?.news || []) {
      (m[n.sector] ||= { node_id: n.sector, chain: "美股", node: n.sector, scope: "美股", items: [] });
      m[n.sector].items.push({
        title: n.title, one_line: n.one_line, summary: n.summary, sentiment: n.sentiment, event_type: "",
        src: n.src, url: n.url, time: n.time || "", codes: [n.ticker], holding: false, watching: false,
      });
    }
    return Object.values(m).sort((a, b) => b.items.length - a.items.length);
  }, [d]);

  // 美股热点:优先用 build_us 的 DeepSeek 归因版(us.hotspot);老 blob 回退客户端统计版
  const usHotspot = useMemo(() => {
    const us = d?.us;
    if (us?.hotspot?.items?.length) return us.hotspot;
    if (!us?.news?.length) return null;
    const bySec: Record<string, { news: string[]; count: number; latest: string }> = {};
    for (const n of us.news) {
      (bySec[n.sector] ||= { news: [], count: 0, latest: "" });
      bySec[n.sector].count++;
      if ((n.time || "") > bySec[n.sector].latest) bySec[n.sector].latest = n.time || "";
      if (bySec[n.sector].news.length < 3) bySec[n.sector].news.push(n.one_line);
    }
    const ret1d: Record<string, number | null> = {};
    for (const nd of us.heatmap?.nodes || []) ret1d[nd.node] = nd.ret_1d ?? null;
    const items = Object.entries(bySec).map(([sec, v]) => ({
      node_id: sec, chain: "美股", node: sec, heat: v.count, trend: "持平",
      reason: `${v.count} 条相关新闻`, news_today: v.count, ret_1d: ret1d[sec] ?? null,
      lhb: 0, stocks: [] as string[], news: v.news, latest_time: v.latest,
    })).sort((a, b) => b.heat - a.heat).slice(0, 10);
    return { headline: "美股科技新闻热度(按板块新闻量)", items };
  }, [d]);

  if (err) return <div className="p-6 text-down">加载失败：{err}</div>;
  if (!d) return <div className="p-6 text-muted">加载中…</div>;

  const isUS = market === "US";
  const enabled = new Set(["report", "hotspot", "flow", "heatmap", "news", "research", "letters", "system"]);

  return (
    <StockCtx.Provider value={setStock}>
    <div className="min-h-screen flex">
      {stock && <StockDetail sel={stock} market={market} d={d} onClose={() => setStock(null)} />}
      {/* 左侧窄导航(桌面);手机换底部 tab 栏 */}
      <nav className="w-16 shrink-0 border-r hairline bg-surface hidden md:flex flex-col items-center py-4 gap-4 text-[12px] text-dim">
        <div className="text-accent font-bold text-[15px]">RV</div>
        {NAV.map((n) => {
          const on = view === n.key;
          const ok = enabled.has(n.key);
          return (
            <button key={n.key} disabled={!ok} onClick={() => ok && setView(n.key)}
              className={`flex flex-col items-center gap-0.5 ${on ? "text-primary" : ok ? "text-muted hover:text-primary" : "text-dim/50 cursor-not-allowed"}`}>
              <div className={`w-8 h-8 rounded flex items-center justify-center ${on ? "bg-elevated" : ""}`}>●</div>
              <span>{n.label}</span>
            </button>
          );
        })}
      </nav>

      {/* 手机底部 tab 栏(md 起隐藏,桌面无此 DOM 影响) */}
      <nav className="md:hidden fixed bottom-0 inset-x-0 z-40 bg-surface border-t hairline flex justify-around py-1.5 text-[11px]">
        {NAV.map((n) => {
          const on = view === n.key;
          return (
            <button key={n.key} onClick={() => setView(n.key)}
              className={`flex flex-col items-center gap-0.5 px-1 ${on ? "text-accent" : "text-muted"}`}>
              <span className="text-[13px] leading-none">●</span>
              <span>{n.label}</span>
            </button>
          );
        })}
      </nav>

      <div className="flex-1 flex flex-col min-w-0 pb-12 md:pb-0">
        {alert?.msg && (
          <div className="px-4 py-2 bg-down/15 text-down text-[13px] border-b hairline">
            ⚠ {alert.msg}{alert.at ? ` · ${alert.at}` : ""}
          </div>
        )}
        <StatusBar d={d} market={market} onMarket={setMarket} onHealth={() => setView("system")} />
        {view === "report" && <ReportPageView d={d} isUS={isUS} usNewsNodes={usNewsNodes} />}
        {view === "hotspot" && (
          <div className="flex-1 flex flex-col md:flex-row gap-5 p-3 md:p-5 overflow-auto">
            <div className="flex-1 min-w-0"><HotspotView hotspot={isUS ? usHotspot : d.hotspot} /></div>
            {isUS && (d.us?.wire?.some((w) => w.group === "推特X")) && (
              <div className="w-full md:w-[52%] shrink-0 min-w-0 border-t md:border-t-0 md:border-l hairline pt-4 md:pt-0 md:pl-5">
                <TechWireX wire={d.us?.wire || []} />
              </div>
            )}
          </div>
        )}
        {view === "flow" && (
          <div className="flex-1 p-3 md:p-5 overflow-auto"><MoneyflowView mf={d.moneyflow} isUS={isUS} /></div>
        )}
        {view === "heatmap" && (
          <div className="flex-1 p-3 md:p-5 overflow-auto space-y-4">
            <HeatmapView h={isUS ? d.us?.heatmap : d.heatmap} />
            {isUS && d.us && (
              <div className="border hairline rounded bg-surface p-3">
                <div className="text-[14px] text-muted mb-2">美股个股行情(收盘/涨跌/6M/52W位/市值/PE)</div>
                <UsBoardView b={{ us_session_date: d.us.us_session_date, items: d.us.board.items, n_ok: d.us.board.n_ok }} />
              </div>
            )}
          </div>
        )}
        {view === "news" && (
          <div className="flex-1 p-3 md:p-5 overflow-auto"><NewsView nodes={isUS ? usNewsNodes : d.news_by_node} /></div>
        )}
        {view === "research" && (
          <div className="flex-1 p-3 md:p-5 overflow-auto">
            {isUS ? <UsResearchView items={d.us?.research} /> : <ResearchView r={d.research} />}
          </div>
        )}
        {view === "letters" && (
          <div className="flex-1 p-3 md:p-5 overflow-auto"><LettersView r={d.research} /></div>
        )}
        {view === "system" && (
          <div className="flex-1 p-3 md:p-5 overflow-auto"><SystemView h={d.health} sources={d.sources?.taipei} /></div>
        )}
      </div>
    </div>
    </StockCtx.Provider>
  );
}
