import { useState } from "react";
import type { Dashboard, NewsItem, Report, StockEvent } from "./types";
import { TechWire } from "./TechWire";
import { useOpenStock } from "./stockCtx";
import { Badge, MoreList, StaleBadge, pctCls, sentDot, sentTx, timeHour } from "./ui";

const confDot: Record<string, string> = { 高: "bg-up", 中: "bg-accent", 低: "bg-muted" };

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
          {r.fallback && <StaleBadge date={r.report_date} label="今日报告未生成 · 显示" />}
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
          <span className={`mono w-16 shrink-0 text-right ${pctCls(it.pct ?? 0)}`}>
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

// 报告页整页(左报告+右侧栏,A股/美股 两套侧栏)。usNewsNodes 由 App 传入(新闻页也用)。
export function ReportPageView({ d, isUS, usNewsNodes }: { d: Dashboard; isUS: boolean; usNewsNodes: Dashboard["news_by_node"] }) {
  // 报告页舆情面板:只留媒体+Reddit(推特X 已挪到热点视图右栏)
  const usWireMedia = (d.us?.wire || []).filter((w) => w.group !== "推特X");
  return (
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
                    <span className={`mono ${pctCls(i.pct ?? 0)}`}>{i.pct == null ? "—" : `${i.pct > 0 ? "+" : ""}${i.pct}%`}</span>
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
  );
}
