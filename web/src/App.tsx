import { useEffect, useMemo, useState } from "react";
import type { Dashboard, NewsItem, NewsNode, Report, StockEvent } from "./types";
import HeatmapView from "./Heatmap";
import SystemView, { HealthDot } from "./System";
import { ResearchView, LettersView } from "./Research";
import { NewsView } from "./News";
import { UsBoardView } from "./UsBoard";
import { UsResearchView } from "./UsResearch";

type Market = "A" | "US";

function MarketToggle({ market, onMarket }: { market: Market; onMarket: (m: Market) => void }) {
  return (
    <div className="flex rounded overflow-hidden border hairline text-[11px] shrink-0">
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
  return <span className={`px-1.5 py-0.5 rounded text-[11px] ${cls}`}>{text}</span>;
}

function StatusBar({ d, market, onMarket, onHealth }: { d: Dashboard; market: Market; onMarket: (m: Market) => void; onHealth: () => void }) {
  const us = d.us;
  const isUS = market === "US";
  const ut = us?.temperature;
  const at = d.temperature;
  const sessionLabel = d.report?.session === "premarket" ? "盘前" : "盘后";
  return (
    <div className="flex items-center gap-4 px-4 h-11 border-b hairline bg-surface text-[12px]">
      <MarketToggle market={market} onMarket={onMarket} />
      <div className="flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full inline-block ${isUS ? "bg-info" : "bg-accent"}`} />
        <span className="font-semibold">{isUS ? "美股" : sessionLabel}</span>
        <span className="text-dim">·</span>
        <span className="text-muted">{isUS ? `美东 ${us?.us_session_date || "—"} 收盘` : (d.report?.data_cutoff || d.meta.date)}</span>
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
        <div className="mono text-muted flex gap-3">
          <span>池 <span className="text-primary">{at.pool_counted}</span></span>
          <span className="text-up">涨 {at.up}</span>
          <span className="text-down">跌 {at.down}</span>
          <span className="text-up">涨停 {at.limit_up}</span>
          <span className={pctColor(at.avg_pct)}>均 {at.avg_pct}%</span>
        </div>
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
          <span className="text-dim text-[11px]">置信度 {r.headline.confidence}</span>
        </div>
        <p className="text-[13px] leading-relaxed text-primary">{r.headline.fact}</p>
        <div className="mt-2 border border-accent/50 rounded bg-accent/5 px-3 py-2">
          <span className="text-accent text-[11px]">我的判断（人填 · 模型不越位）</span>
          <input
            className="w-full bg-transparent outline-none text-primary mt-1 placeholder:text-dim"
            placeholder="在此写下你的判断……（模型永远留白这一栏）"
          />
        </div>
      </section>

      {/* 今天只看这3件事 */}
      <section>
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
                  <div className="flex flex-wrap items-center gap-2 mt-1 text-[11px]">
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
      <section>
        <div className="flex items-center gap-2 mb-2">
          <div className="w-0.5 h-4 bg-dim" />
          <h2 className="font-semibold text-muted">分板块扫描</h2>
        </div>
        <div className="space-y-1">
          {r.sectors.map((s, i) => (
            <div key={i} className="flex gap-2 text-[12px]">
              <span className="text-muted w-16 shrink-0">{s.chain}</span>
              <span className="text-dim">{s.status}</span>
            </div>
          ))}
        </div>
      </section>

      {/* 证伪与风险 */}
      <section>
        <div className="flex items-center gap-2 mb-2">
          <div className="w-0.5 h-4 bg-up" />
          <h2 className="font-semibold">证伪与风险</h2>
        </div>
        <div className="space-y-2">
          {r.falsification.map((f, i) => (
            <div key={i} className="border hairline rounded px-3 py-2">
              <p className="text-primary text-[12px]">{f.claim}</p>
              <p className="text-muted text-[11px] mt-1">
                <span className="text-down">证伪条件：</span>{f.condition}
              </p>
              <div className="mt-1 flex gap-2">
                <Badge text="DeepSeek 起草" cls="bg-elevated text-dim" />
                <Badge text="待审定" cls="bg-accent/10 text-accent" />
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function EventStream({ nodes }: { nodes: Dashboard["news_by_node"] }) {
  return (
    <div className="space-y-3">
      {nodes.slice(0, 10).map((g) => (
        <div key={g.node_id}>
          <div className="flex items-center gap-2 text-[11px] text-muted mb-1">
            <span className="text-primary">{g.chain}/{g.node}</span>
            <span className="text-dim">({g.items.length})</span>
          </div>
          <div className="space-y-1">
            {g.items.slice(0, 4).map((n: NewsItem, i) => (
              <div key={i} className="flex items-start gap-2 text-[12px] leading-snug">
                <Badge text={n.sentiment} cls={sentColor[n.sentiment] || "text-muted"} />
                <span className="text-primary flex-1">{n.one_line || n.title}</span>
                <span className="text-dim text-[11px] shrink-0">{n.src}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function Events({ events }: { events: StockEvent[] }) {
  return (
    <div className="space-y-1">
      {events.map((e, i) => (
        <div key={i} className="flex items-center gap-2 text-[12px]">
          <Badge text={e.event_type} cls="bg-elevated text-muted" />
          <span className={e.direction === "利好" ? "text-up" : e.direction === "利空" ? "text-down" : "text-muted"}>
            {e.direction}
          </span>
          <span className="mono text-muted">{e.code}</span>
          <span className="text-dim flex-1 truncate">{e.summary}</span>
          <span className="mono text-dim text-[11px]">{e.date}</span>
        </div>
      ))}
    </div>
  );
}

function UsOvernightBoard({ us }: { us: NonNullable<Dashboard["report"]>["us_overnight"] }) {
  if (!us) return null;
  return (
    <div className="space-y-1">
      <div className="text-[11px] text-dim mb-1">美东 {us.us_session_date} 收盘 · 隔夜外盘参照(红涨绿跌)</div>
      {us.items.map((it) => (
        <div key={it.ticker} className="flex items-center gap-2 text-[12px]">
          <span className="text-primary w-24 shrink-0 truncate">{it.name}</span>
          <span className="mono text-dim text-[11px] w-12 shrink-0">{it.ticker}</span>
          <span className={`mono w-16 shrink-0 text-right ${pctColor(it.pct ?? 0)}`}>
            {it.pct === null ? "—" : `${it.pct > 0 ? "+" : ""}${it.pct}%`}
          </span>
          <span className="text-dim text-[11px] truncate">{it.mapping}</span>
        </div>
      ))}
    </div>
  );
}

function LedgerPanel({ ledger }: { ledger: Dashboard["ledger"] }) {
  if (!ledger || ledger.judgments.length === 0) {
    return (
      <div className="text-dim text-[12px] space-y-1">
        <div>存活 0 · 证伪 0 — 账本待积累。</div>
        <div className="text-[11px]">审定钉死判断:<span className="mono text-muted">manage_ledger.py pin &lt;report_id&gt; &lt;序号&gt;</span></div>
      </div>
    );
  }
  const ed = ledger.error_dist || {};
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3 text-[12px]">
        <span className="text-up">存活 {ledger.alive}</span>
        <span className="text-down">证伪 {ledger.falsified}</span>
        {Object.keys(ed).length > 0 && (
          <span className="text-dim text-[11px]">
            {Object.entries(ed).map(([k, v]) => `${k}${v}`).join(" · ")}
          </span>
        )}
      </div>
      <div className="space-y-1.5">
        {ledger.judgments.slice(0, 8).map((j) => (
          <div key={j.id} className="border hairline rounded px-2 py-1.5 text-[12px]">
            <div className="flex items-center gap-2">
              <span className={`px-1.5 py-0.5 rounded text-[10px] ${j.falsified ? "text-down bg-down/10" : "text-up bg-up/10"}`}>
                {j.falsified ? `✗证伪${j.error_type ? `·${j.error_type}` : ""}` : "存活"}
              </span>
              <span className="mono text-dim text-[11px]">#{j.id}</span>
              <span className="mono text-dim text-[11px] ml-auto">{j.date}</span>
            </div>
            <p className="text-primary mt-1 leading-snug">{j.claim}</p>
            <p className="text-muted text-[11px] mt-0.5"><span className="text-down">证伪:</span>{j.condition}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border hairline rounded bg-surface">
      <div className="px-3 py-2 border-b hairline text-[11px] text-muted uppercase tracking-wide">{title}</div>
      <div className="p-3">{children}</div>
    </div>
  );
}

const NAV = [
  { key: "report", label: "报告" },
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
  useEffect(() => {
    fetch("/data/dashboard.json").then((r) => r.json()).then(setD).catch((e) => setErr(String(e)));
  }, []);

  // 美股新闻(扁平)→ 复用 A股 的按节点分组结构(按板块分组)
  const usNewsNodes: NewsNode[] = useMemo(() => {
    const m: Record<string, NewsNode> = {};
    for (const n of d?.us?.news || []) {
      (m[n.sector] ||= { node_id: n.sector, chain: "美股", node: n.sector, scope: "美股", items: [] });
      m[n.sector].items.push({
        title: n.title, one_line: n.one_line, sentiment: n.sentiment, event_type: "",
        src: n.src, url: n.url, time: "", codes: [n.ticker], holding: false, watching: false,
      });
    }
    return Object.values(m).sort((a, b) => b.items.length - a.items.length);
  }, [d]);

  if (err) return <div className="p-6 text-down">加载失败：{err}</div>;
  if (!d) return <div className="p-6 text-muted">加载中…</div>;

  const isUS = market === "US";
  const enabled = new Set(["report", "heatmap", "news", "research", "letters", "system"]);

  return (
    <div className="min-h-screen flex">
      {/* 左侧窄导航 */}
      <nav className="w-14 shrink-0 border-r hairline bg-surface flex flex-col items-center py-3 gap-4 text-[10px] text-dim">
        <div className="text-accent font-bold text-[13px]">RV</div>
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
        <StatusBar d={d} market={market} onMarket={setMarket} onHealth={() => setView("system")} />
        {view === "report" && (
          <div className="flex-1 grid grid-cols-[1.6fr_1fr] gap-4 p-4 overflow-auto">
            <div><DailyReport report={isUS ? d.us?.report : d.report} /></div>
            <div className="space-y-4">
              {isUS ? (
                <>
                  <Panel title="美股新闻流 · 按板块">
                    <EventStream nodes={usNewsNodes} />
                  </Panel>
                  <Panel title="美股指数">
                    <div className="space-y-1">
                      {(d.us?.indices || []).map((i) => (
                        <div key={i.ticker} className="flex items-center gap-2 text-[13px]">
                          <span className="text-primary flex-1">{i.name}</span>
                          <span className="mono text-dim text-[11px]">{i.ticker}</span>
                          <span className={`mono ${pctColor(i.pct ?? 0)}`}>{i.pct == null ? "—" : `${i.pct > 0 ? "+" : ""}${i.pct}%`}</span>
                        </div>
                      ))}
                    </div>
                  </Panel>
                </>
              ) : (
                <>
                  {d.report?.us_overnight && (
                    <Panel title="隔夜美股科技链 · 盘前">
                      <UsOvernightBoard us={d.report.us_overnight} />
                    </Panel>
                  )}
                  <Panel title="判断复盘账本 · 近30日">
                    <LedgerPanel ledger={d.ledger} />
                  </Panel>
                  <Panel title="我的持仓 / 自选动态">
                    {d.report?.holdings_moves?.length
                      ? <div className="text-primary text-[13px]">{d.report.holdings_moves.length} 条异动</div>
                      : <div className="text-dim text-[13px]">未设持仓/自选。设置后,你的票有事永远第一时间最高优先级出现。</div>}
                  </Panel>
                  <Panel title="事件流 · 按节点">
                    <EventStream nodes={d.news_by_node} />
                  </Panel>
                  <Panel title="个股事件 · 公告/龙虎榜">
                    <Events events={d.stock_events} />
                  </Panel>
                </>
              )}
            </div>
          </div>
        )}
        {view === "heatmap" && (
          <div className="flex-1 p-4 overflow-auto space-y-4">
            <HeatmapView h={isUS ? d.us?.heatmap : d.heatmap} />
            {isUS && d.us && (
              <div className="border hairline rounded bg-surface p-3">
                <div className="text-[12px] text-muted mb-2">美股个股行情(收盘/涨跌/6M/52W位/市值/PE)</div>
                <UsBoardView b={{ us_session_date: d.us.us_session_date, items: d.us.board.items, n_ok: d.us.board.n_ok }} />
              </div>
            )}
          </div>
        )}
        {view === "news" && (
          <div className="flex-1 p-4 overflow-auto"><NewsView nodes={isUS ? usNewsNodes : d.news_by_node} /></div>
        )}
        {view === "research" && (
          <div className="flex-1 p-4 overflow-auto">
            {isUS ? <UsResearchView items={d.us?.research} /> : <ResearchView r={d.research} />}
          </div>
        )}
        {view === "letters" && (
          <div className="flex-1 p-4 overflow-auto"><LettersView r={d.research} /></div>
        )}
        {view === "system" && (
          <div className="flex-1 p-4 overflow-auto"><SystemView h={d.health} /></div>
        )}
      </div>
    </div>
  );
}
