import { useEffect, useMemo, useState } from "react";
import type { Dashboard, NewsItem, NewsNode, Report, StockEvent } from "./types";
import HeatmapView from "./Heatmap";
import SystemView, { HealthDot } from "./System";
import { ResearchView, LettersView } from "./Research";
import { NewsView } from "./News";
import { UsBoardView } from "./UsBoard";
import { UsResearchView } from "./UsResearch";
import { TechWire, TechWireX } from "./TechWire";
import { HotspotView } from "./Hotspot";
import { StockDetail } from "./StockDetail";
import { StockCtx, useOpenStock, type StockSel } from "./stockCtx";
import { timeHour } from "./ui";

type Market = "A" | "US";

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

// A股红涨绿跌:正=红(up) 负=绿(down)
const pctColor = (v: number) => (v > 0 ? "text-up" : v < 0 ? "text-down" : "text-muted");
const sentColor: Record<string, string> = {
  利好: "text-up bg-up/10", 利空: "text-down bg-down/10",
  中性: "text-muted bg-muted/10", 澄清: "text-info bg-info/10",
};
const sentDot: Record<string, string> = { 利好: "bg-up", 利空: "bg-down", 中性: "bg-muted", 澄清: "bg-info" };
const sentTx: Record<string, string> = { 利好: "text-up", 利空: "text-down", 中性: "text-muted", 澄清: "text-info" };
const confDot: Record<string, string> = { 高: "bg-up", 中: "bg-accent", 低: "bg-muted" };

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

function Badge({ text, cls }: { text: string; cls: string }) {
  return <span className={`px-1.5 py-0.5 rounded text-[13px] ${cls}`}>{text}</span>;
}

function StatusBar({ d, market, onMarket, onHealth }: { d: Dashboard; market: Market; onMarket: (m: Market) => void; onHealth: () => void }) {
  const us = d.us;
  const isUS = market === "US";
  const ut = us?.temperature;
  const at = d.temperature;
  const sessionLabel = d.report?.session === "premarket" ? "盘前" : d.report?.session === "intraday" ? "盘中" : "盘后";
  return (
    <div className="flex items-center gap-4 px-4 h-11 border-b hairline bg-surface text-[14px]">
      <MarketToggle market={market} onMarket={onMarket} />
      <div className="flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full inline-block ${isUS ? "bg-info" : "bg-accent"}`} />
        <span className="font-semibold">{isUS ? "美股" : sessionLabel}</span>
        <span className="text-dim">·</span>
        <span className="text-muted">{isUS ? `美东 ${us?.us_session_date || "—"} ${us?.session_status || "收盘"}` : (d.report?.data_cutoff || d.meta?.date || "—")}</span>
      </div>
      {isUS ? (
        ut && (
          <div className="mono text-muted flex gap-3">
            <span>覆盖 <span className="text-primary">{ut.counted}</span></span>
            <span className="text-up">涨 {ut.up}</span>
            <span className="text-down">跌 {ut.down}</span>
            <span className={pctColor(ut.avg_pct)}>均 {ut.avg_pct}%</span>
          </div>
        )
      ) : (
        at && (
          <div className="mono text-muted flex gap-3">
            <span>池 <span className="text-primary">{at.pool_counted}</span></span>
            <span className="text-up">涨 {at.up}</span>
            <span className="text-down">跌 {at.down}</span>
            <span className="text-up">涨停 {at.limit_up}</span>
            <span className={pctColor(at.avg_pct)}>均 {at.avg_pct}%</span>
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

function DailyReport({ report }: { report: Report | null | undefined }) {
  const r = report;
  if (!r) return <div className="text-muted p-4">今日暂无报告</div>;
  return (
    <div className="space-y-5">
      {/* 今日主线 */}
      <section>
        <div className="flex items-center gap-2 mb-2">
          <div className="w-0.5 h-4 bg-accent" />
          <h2 className="font-semibold">今日主线</h2>
          <span className={`w-2 h-2 rounded-full ${confDot[r.headline.confidence] || "bg-muted"}`} />
          <span className="text-dim text-[13px]">置信度 {r.headline.confidence}</span>
        </div>
        <p className="text-[15px] leading-relaxed text-primary">{r.headline.fact}</p>
        <div className="mt-2 border border-accent/50 rounded bg-accent/5 px-3 py-2">
          <span className="text-accent text-[13px]">我的判断（人填 · 模型不越位）</span>
          <input
            className="w-full bg-transparent outline-none text-primary mt-1 placeholder:text-dim"
            placeholder="在此写下你的判断……（模型永远留白这一栏）"
          />
        </div>
      </section>

      {/* 今日综述 ~500字 */}
      {r.narrative && (
        <section className="border-t hairline pt-4">
          <div className="flex items-center gap-2 mb-2">
            <div className="w-0.5 h-4 bg-info" />
            <h2 className="font-semibold">今日综述</h2>
            <span className="text-dim text-[12px]">DeepSeek 综合 · 只述事实不判断</span>
          </div>
          <div className="border hairline rounded bg-surface px-4 py-3 text-[14px] leading-[1.85] text-muted whitespace-pre-line">
            {r.narrative}
          </div>
        </section>
      )}

      {/* 今天只看这3件事 */}
      <section className="border-t hairline pt-4">
        <div className="flex items-center gap-2 mb-2">
          <div className="w-0.5 h-4 bg-accent" />
          <h2 className="font-semibold">今天只看这 3 件事</h2>
        </div>
        <ol className="space-y-2">
          {r.top3.map((it, i) => (
            <li key={i} className="border hairline rounded bg-surface px-3 py-2">
              <div className="flex gap-2">
                <span className="mono text-accent">{i + 1}</span>
                <div className="flex-1">
                  <p className="text-primary">{it.change}</p>
                  <div className="flex flex-wrap items-center gap-2 mt-1 text-[13px]">
                    <span className="text-info">{it.evidence}</span>
                    {it.node_ids.map((n) => (
                      <span key={n} className="text-dim">▸{n}</span>
                    ))}
                    {it.related_stocks.map((s) => (
                      <span key={s} className="mono text-muted">{s}</span>
                    ))}
                  </div>
                </div>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {/* 分板块扫描 */}
      <section className="border-t hairline pt-4">
        <div className="flex items-center gap-2 mb-2">
          <div className="w-0.5 h-4 bg-dim" />
          <h2 className="font-semibold text-muted">分板块扫描</h2>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
          {r.sectors.map((s, i) => (
            <div key={i} className="flex gap-2 text-[14px] border-l-2 border-hairline pl-2 py-0.5">
              <span className="text-accent shrink-0 font-medium">{s.chain}</span>
              <span className="text-dim">{s.status}</span>
            </div>
          ))}
        </div>
      </section>

      {/* 证伪与风险 */}
      <section className="border-t hairline pt-4">
        <div className="flex items-center gap-2 mb-2">
          <div className="w-0.5 h-4 bg-up" />
          <h2 className="font-semibold">证伪与风险</h2>
        </div>
        <div className="space-y-2">
          {r.falsification.map((f, i) => (
            <div key={i} className="border hairline rounded px-3 py-2">
              <p className="text-primary text-[14px]">{f.claim}</p>
              <p className="text-muted text-[13px] mt-1">
                <span className="text-down">证伪条件：</span>{f.condition}
              </p>
              <div className="mt-1 flex gap-2">
                <Badge text="DeepSeek 起草" cls="bg-elevated text-dim" />
                {f.pinned_id == null ? (
                  <Badge text="待审定" cls="bg-accent/10 text-accent" />
                ) : f.pinned_falsified ? (
                  <Badge text={`✗已证伪 #${f.pinned_id}`} cls="bg-down/10 text-down" />
                ) : (
                  <Badge text={`✓已钉死 #${f.pinned_id}`} cls="bg-up/10 text-up" />
                )}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function EventStream({ nodes }: { nodes: Dashboard["news_by_node"] }) {
  const open = useOpenStock();
  return (
    <MoreList items={nodes.slice(0, 14)} initial={5}>
      {(g) => (
        <div key={g.node_id} className="mb-5 last:mb-0">
          <div className="flex items-center gap-2 mb-2.5">
            <span className="w-0.5 h-3.5 bg-accent" />
            <span className="text-primary text-[13px] font-semibold">{g.chain}/{g.node}</span>
            <span className="text-dim text-[12px] mono">{g.items.length}</span>
          </div>
          <div className="border-l border-[#232B36] pl-3.5 ml-0.5 divide-y divide-[#232B36]">
            <MoreList items={g.items} initial={3}>
              {(n: NewsItem, i) => (
                <div key={i} className="py-3 first:pt-0">
                  <div className="flex items-start gap-2">
                    <span className={`w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 ${sentDot[n.sentiment] || "bg-muted"}`} />
                    <p className="text-primary text-[14px] leading-snug font-medium flex-1">{n.one_line || n.title}</p>
                  </div>
                  {n.summary && <p className="text-muted text-[13px] leading-relaxed mt-1.5 ml-3.5">{n.summary}</p>}
                  <div className="flex items-center gap-2 mt-1.5 ml-3.5 text-[12px] text-dim">
                    <span className={sentTx[n.sentiment] || "text-muted"}>{n.sentiment}</span>
                    {timeHour(n.time) && <><span>·</span><span className="mono">{timeHour(n.time)}</span></>}
                    <span>·</span><span>{n.src}</span>
                    {(n.codes || []).slice(0, 3).map((c) => (
                      <button key={c} onClick={() => open({ code: c })} className="mono hover:text-accent">{c}</button>
                    ))}
                  </div>
                </div>
              )}
            </MoreList>
          </div>
        </div>
      )}
    </MoreList>
  );
}

const dirDot = (d: string) => (d === "利好" ? "bg-up" : d === "利空" ? "bg-down" : "bg-muted");
function Events({ events }: { events: StockEvent[] }) {
  const open = useOpenStock();
  return (
    <MoreList items={events} initial={7}>
      {(e: StockEvent, i) => (
        <div key={i} className="flex items-center gap-2.5 py-2.5 border-b border-[#232B36] last:border-0 text-[13px]">
          <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dirDot(e.direction)}`} />
          <span className="text-muted shrink-0 w-16">{e.event_type}</span>
          <button onClick={() => open({ code: e.code })} className="mono text-muted hover:text-accent shrink-0 w-14 text-left">{e.code}</button>
          <span className="text-dim flex-1 truncate">{e.summary}</span>
          <span className="mono text-dim text-[12px] shrink-0">{e.date}</span>
        </div>
      )}
    </MoreList>
  );
}

function UsOvernightBoard({ us }: { us: NonNullable<Dashboard["report"]>["us_overnight"] }) {
  if (!us) return null;
  return (
    <div className="space-y-1">
      <div className="text-[13px] text-dim mb-1">美东 {us.us_session_date} 收盘 · 隔夜外盘参照(红涨绿跌)</div>
      {us.items.map((it) => (
        <div key={it.ticker} className="flex items-center gap-2 text-[14px]">
          <span className="text-primary w-24 shrink-0 truncate">{it.name}</span>
          <span className="mono text-dim text-[13px] w-12 shrink-0">{it.ticker}</span>
          <span className={`mono w-16 shrink-0 text-right ${pctColor(it.pct ?? 0)}`}>
            {it.pct === null ? "—" : `${it.pct > 0 ? "+" : ""}${it.pct}%`}
          </span>
          <span className="text-dim text-[13px] truncate">{it.mapping}</span>
        </div>
      ))}
    </div>
  );
}

function LedgerPanel({ ledger }: { ledger: Dashboard["ledger"] }) {
  if (!ledger || ledger.judgments.length === 0) {
    return (
      <div className="text-dim text-[14px] space-y-1">
        <div>存活 0 · 证伪 0 — 账本待积累。</div>
        <div className="text-[13px]">审定钉死判断:<span className="mono text-muted">manage_ledger.py pin &lt;report_id&gt; &lt;序号&gt;</span></div>
      </div>
    );
  }
  const ed = ledger.error_dist || {};
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3 text-[14px]">
        <span className="text-up">存活 {ledger.alive}</span>
        <span className="text-down">证伪 {ledger.falsified}</span>
        {Object.keys(ed).length > 0 && (
          <span className="text-dim text-[13px]">
            {Object.entries(ed).map(([k, v]) => `${k}${v}`).join(" · ")}
          </span>
        )}
      </div>
      <div className="space-y-1.5">
        {ledger.judgments.slice(0, 8).map((j) => (
          <div key={j.id} className="border hairline rounded px-2 py-1.5 text-[14px]">
            <div className="flex items-center gap-2">
              <span className={`px-1.5 py-0.5 rounded text-[12px] ${j.falsified ? "text-down bg-down/10" : "text-up bg-up/10"}`}>
                {j.falsified ? `✗证伪${j.error_type ? `·${j.error_type}` : ""}` : "存活"}
              </span>
              <span className="mono text-dim text-[13px]">#{j.id}</span>
              <span className="mono text-dim text-[13px] ml-auto">{j.date}</span>
            </div>
            <p className="text-primary mt-1 leading-snug">{j.claim}</p>
            <p className="text-muted text-[13px] mt-0.5"><span className="text-down">证伪:</span>{j.condition}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function Panel({ title, children, count, collapsible = false, defaultOpen = true }:
  { title: string; children: React.ReactNode; count?: number; collapsible?: boolean; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border hairline rounded-md bg-surface">
      <button type="button" onClick={() => collapsible && setOpen(!open)}
        className={`w-full px-4 py-2.5 text-[12px] text-muted tracking-wide flex items-center gap-2 ${open ? "border-b hairline" : ""} ${collapsible ? "hover:text-primary cursor-pointer" : "cursor-default"}`}>
        <span className="w-1 h-1 rounded-full bg-accent/70" />{title}
        {count != null && <span className="text-dim mono">{count}</span>}
        {collapsible && <span className={`ml-auto text-dim transition-transform ${open ? "rotate-90" : ""}`}>▸</span>}
      </button>
      {open && <div className="p-4">{children}</div>}
    </div>
  );
}

// 长列表折叠:先显示 initial 条,余下"展开剩余 N 条"
function MoreList<T,>({ items, initial = 5, children }: { items: T[]; initial?: number; children: (item: T, i: number) => React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const shown = open ? items : items.slice(0, initial);
  return (
    <>
      {shown.map((it, i) => children(it, i))}
      {items.length > initial && (
        <button onClick={() => setOpen(!open)} className="text-info text-[13px] mt-2 hover:underline">
          {open ? "收起 ▴" : `展开剩余 ${items.length - initial} 条 ▾`}
        </button>
      )}
    </>
  );
}

const NAV = [
  { key: "report", label: "报告" },
  { key: "hotspot", label: "热点" },
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

  // 美股新闻(扁平)→ 复用 A股 的按节点分组结构(按板块分组)
  // 报告页舆情面板:只留媒体+Reddit(推特X 已挪到热点视图右栏)
  const usWireMedia = useMemo(() => (d?.us?.wire || []).filter((w) => w.group !== "推特X"), [d]);

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
  const enabled = new Set(["report", "hotspot", "heatmap", "news", "research", "letters", "system"]);

  return (
    <StockCtx.Provider value={setStock}>
    <div className="min-h-screen flex">
      {stock && <StockDetail sel={stock} market={market} d={d} onClose={() => setStock(null)} />}
      {/* 左侧窄导航 */}
      <nav className="w-16 shrink-0 border-r hairline bg-surface flex flex-col items-center py-4 gap-4 text-[12px] text-dim">
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

      <div className="flex-1 flex flex-col min-w-0">
        {alert?.msg && (
          <div className="px-4 py-2 bg-down/15 text-down text-[13px] border-b hairline">
            ⚠ {alert.msg}{alert.at ? ` · ${alert.at}` : ""}
          </div>
        )}
        <StatusBar d={d} market={market} onMarket={setMarket} onHealth={() => setView("system")} />
        {view === "report" && (
          <div className="flex-1 grid grid-cols-[1.6fr_1fr] gap-6 p-6 overflow-auto">
            <div className="space-y-6">
              <DailyReport report={isUS ? d.us?.report : d.report} />
              {!isUS && d.stock_events.length > 0 && (
                <Panel title="个股事件 · 公告 / 龙虎榜" count={d.stock_events.length} collapsible>
                  <Events events={d.stock_events} />
                </Panel>
              )}
            </div>
            <div className="space-y-5">
              {isUS ? (
                <>
                  <Panel title="美股新闻流 · 按板块" count={usNewsNodes.length} collapsible>
                    <EventStream nodes={usNewsNodes} />
                  </Panel>
                  <Panel title="全球科技舆情 · WSJ/路透/科技媒体/Reddit" count={usWireMedia.length} collapsible>
                    <TechWire wire={usWireMedia} />
                  </Panel>
                  {(d.us?.report?.x_takes?.us_global || d.us?.report?.x_takes?.a_share) && (
                    <Panel title="推特X 观点综述 · serenity等17号(完整流见「热点」页)" collapsible>
                      <div className="space-y-2.5 text-[14px] leading-relaxed">
                        {d.us?.report?.x_takes?.us_global && d.us.report.x_takes.us_global !== "(无)" && (
                          <div><span className="text-accent text-[12px]">美股/全球</span>
                            <p className="text-muted mt-0.5">{d.us.report.x_takes.us_global}</p></div>
                        )}
                        {d.us?.report?.x_takes?.a_share && d.us.report.x_takes.a_share !== "(无)" && (
                          <div><span className="text-accent text-[12px] bg-accent/10 px-1 rounded">A股</span>
                            <p className="text-muted mt-0.5">{d.us.report.x_takes.a_share}</p></div>
                        )}
                      </div>
                    </Panel>
                  )}
                  <Panel title="美股指数" collapsible>
                    <div className="space-y-1">
                      {(d.us?.indices || []).map((i) => (
                        <div key={i.ticker} className="flex items-center gap-2 text-[15px]">
                          <span className="text-primary flex-1">{i.name}</span>
                          <span className="mono text-dim text-[13px]">{i.ticker}</span>
                          <span className={`mono ${pctColor(i.pct ?? 0)}`}>{i.pct == null ? "—" : `${i.pct > 0 ? "+" : ""}${i.pct}%`}</span>
                        </div>
                      ))}
                    </div>
                  </Panel>
                </>
              ) : (
                <>
                  {d.report?.us_overnight && (
                    <Panel title="隔夜美股科技链">
                      <UsOvernightBoard us={d.report.us_overnight} />
                    </Panel>
                  )}
                  <Panel title="判断复盘账本 · 近30日" collapsible>
                    <LedgerPanel ledger={d.ledger} />
                  </Panel>
                  <Panel title="我的持仓 / 自选动态" collapsible>
                    {d.report?.holdings_moves?.length
                      ? <div className="text-primary text-[15px]">{d.report.holdings_moves.length} 条异动</div>
                      : <div className="text-dim text-[15px]">未设持仓/自选。设置后,你的票有事永远第一时间最高优先级出现。</div>}
                  </Panel>
                  <Panel title="事件流 · 按节点" count={d.news_by_node.length} collapsible>
                    <EventStream nodes={d.news_by_node} />
                  </Panel>
                </>
              )}
            </div>
          </div>
        )}
        {view === "hotspot" && (
          <div className="flex-1 flex gap-5 p-5 overflow-auto">
            <div className="flex-1 min-w-0"><HotspotView hotspot={isUS ? usHotspot : d.hotspot} /></div>
            {isUS && (d.us?.wire?.some((w) => w.group === "推特X")) && (
              <div className="w-[52%] shrink-0 min-w-0 border-l hairline pl-5">
                <TechWireX wire={d.us?.wire || []} />
              </div>
            )}
          </div>
        )}
        {view === "heatmap" && (
          <div className="flex-1 p-5 overflow-auto space-y-4">
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
          <div className="flex-1 p-5 overflow-auto"><NewsView nodes={isUS ? usNewsNodes : d.news_by_node} /></div>
        )}
        {view === "research" && (
          <div className="flex-1 p-5 overflow-auto">
            {isUS ? <UsResearchView items={d.us?.research} /> : <ResearchView r={d.research} />}
          </div>
        )}
        {view === "letters" && (
          <div className="flex-1 p-5 overflow-auto"><LettersView r={d.research} /></div>
        )}
        {view === "system" && (
          <div className="flex-1 p-5 overflow-auto"><SystemView h={d.health} /></div>
        )}
      </div>
    </div>
    </StockCtx.Provider>
  );
}
