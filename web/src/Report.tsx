import { useState } from "react";
import type { Dashboard, JudgmentBlock, JudgmentCard, MarketGauge, Moneyflow, NewsItem, Report, StockEvent } from "./types";
import { TechWire } from "./TechWire";
import { useOpenStock } from "./stockCtx";
import { Badge, DIM_HEX, DOWN_HEX, MoreList, StaleBadge, UP_HEX, pctCls, sentDot, sentTx, timeHour } from "./ui";

const confDot: Record<string, string> = { 高: "bg-up", 中: "bg-accent", 低: "bg-muted" };

// 20日迷你走势线:色随区间方向(末值≥首值红/否则绿,A股约定);无轴无网格,细线
function Spark({ vals, color }: { vals?: number[]; color?: string }) {
  if (!vals || vals.length < 2) return null;
  const w = 56, h = 16, min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
  const pts = vals.map((v, i) =>
    `${(i / (vals.length - 1)) * w},${h - 1.5 - ((v - min) / span) * (h - 3)}`).join(" ");
  const c = color ?? (vals[vals.length - 1] >= vals[0] ? UP_HEX : DOWN_HEX);
  return (
    <svg width={w} height={h} className="inline-block align-middle" aria-hidden>
      <polyline points={pts} fill="none" stroke={c} strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

// 20日小柱图:signed=零轴居中正红负绿(净宽度/主力),否则单色幅度柱(成交额)
function MiniBars({ vals, signed }: { vals?: number[]; signed?: boolean }) {
  if (!vals || vals.length < 2) return null;
  const w = 56, h = 16, n = vals.length, bw = Math.max(1, Math.floor(w / n) - 1);
  const amax = Math.max(...vals.map((v) => Math.abs(v))) || 1;
  const min = Math.min(...vals), span = (Math.max(...vals) - min) || 1;
  return (
    <svg width={w} height={h} className="inline-block align-middle" aria-hidden>
      {vals.map((v, i) => {
        const x = i * (bw + 1);
        if (signed) {
          const mid = h / 2, bh = Math.max(1, (Math.abs(v) / amax) * (mid - 1));
          return <rect key={i} x={x} y={v >= 0 ? mid - bh : mid} width={bw} height={bh}
                       fill={v >= 0 ? UP_HEX : DOWN_HEX} />;
        }
        const bh = Math.max(1, ((v - min) / span) * (h - 2));
        return <rect key={i} x={x} y={h - bh} width={bw} height={bh} fill={DIM_HEX} />;
      })}
    </svg>
  );
}

// 大盘仪表(三层漏斗第一层·环境读数,EOD口径带日期标注;20日走势小图看趋势方向)
function GaugeBar({ g }: { g: MarketGauge | null | undefined }) {
  if (!g) return null;
  const b = g.breadth;
  const hist = g.history;
  const fmtWan = (v: number) => (v >= 10000 ? `${(v / 10000).toFixed(2)}万亿` : `${v.toFixed(0)}亿`);
  return (
    <section className="border hairline rounded bg-surface px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <span className="text-dim text-[12px]">大盘 · {g.trade_date} 收盘</span>
        {g.indexes.map((i) => (
          <span key={i.code} className="text-[13px] whitespace-nowrap inline-flex items-center gap-1.5">
            <span className="text-muted">{i.name}</span>
            <span className={`mono ${pctCls(i.pct)}`}>{i.pct > 0 ? "+" : ""}{i.pct.toFixed(2)}%</span>
            <Spark vals={i.spark} />
          </span>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 mt-1.5 text-[13px]">
        <span className="whitespace-nowrap inline-flex items-center gap-1.5">
          <span className="text-dim">宽度</span>
          <span><span className="text-up mono">{b.up}涨</span><span className="text-dim">/</span>
          <span className="text-down mono">{b.down}跌</span></span>
          <MiniBars vals={hist?.net} signed />
          <span className="text-dim text-[12px]">涨停{b.limit_up} 跌停{b.limit_down}</span>
        </span>
        <span className="whitespace-nowrap inline-flex items-center gap-1.5">
          <span className="text-dim">成交</span>
          <span className="mono text-muted">{fmtWan(g.turnover)}</span>
          {g.turnover_chg != null && (
            <span className={`mono text-[12px] ${pctCls(g.turnover_chg)}`}>
              {g.turnover_chg > 0 ? "+" : ""}{g.turnover_chg.toFixed(0)}亿
            </span>
          )}
          <MiniBars vals={hist?.turnover} />
        </span>
        {g.margin && (
          <span className="whitespace-nowrap inline-flex items-center gap-1.5">
            <span className="text-dim">两融</span>
            <span className="mono text-muted">{fmtWan(g.margin.balance)}</span>
            {g.margin.chg != null && (
              <span className={`mono text-[12px] ${pctCls(g.margin.chg)}`}>
                {g.margin.chg > 0 ? "+" : ""}{g.margin.chg.toFixed(0)}亿
              </span>
            )}
            <Spark vals={hist?.margin} color={DIM_HEX} />
          </span>
        )}
        {g.moneyflow && (
          <span className="whitespace-nowrap inline-flex items-center gap-1.5">
            <span className="text-dim">全A主力</span>
            <span className={`mono ${pctCls(g.moneyflow.main)}`}>
              {g.moneyflow.main > 0 ? "+" : ""}{g.moneyflow.main.toFixed(0)}亿
            </span>
            <MiniBars vals={hist?.main} signed />
          </span>
        )}
      </div>
    </section>
  );
}

// 头版化(倒金字塔):第1屏=主线hero+今日三件事;第2屏=证伪+盘中节奏(最新在前,收合);
// 第3屏起=综述正文+分板块(折叠)。结论先行,证据按需展开。
// 美股指数横条(对标A股大盘仪表位:环境读数第一眼可见,手机不再沉底)
function UsIndexBar({ us }: { us: Dashboard["us"] }) {
  if (!us?.indices?.length) return null;
  return (
    <section className="border hairline rounded bg-surface px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <span className="text-dim text-[12px]">美股 · {us.us_session_date}{us.session_status ? ` ${us.session_status}` : ""}</span>
        {us.indices.map((i) => (
          <span key={i.ticker} className="text-[13px] whitespace-nowrap inline-flex items-center gap-1.5">
            <span className="text-muted">{i.name}</span>
            <span className={`mono ${pctCls(i.pct ?? 0)}`}>{i.pct == null ? "—" : `${i.pct > 0 ? "+" : ""}${i.pct}%`}</span>
          </span>
        ))}
      </div>
    </section>
  );
}

// —— B6 节点研判卡(第2屏:六源共振,方向判断可追责,5日窗口进 B7 记分) ——
const dirBadge: Record<string, string> = {
  偏多: "bg-up/10 text-up", 偏空: "bg-down/10 text-down", 中性: "bg-elevated text-dim",
};
const zCls = (z: number) =>
  Math.abs(z) < 1 ? "text-dim" : z > 0 ? "text-up" : "text-down";

function CardRow({ c }: { c: JudgmentCard }) {
  const m = c.matrix || {};
  const zs: [string, number | undefined][] = [
    ["新闻", m.news?.z], ["资金", m.mf?.z], ["行情", m.price?.z],
    ["龙虎榜", m.lhb?.z], ["研报", m.research?.z],
  ];
  return (
    <div className="border hairline rounded bg-surface px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`px-1.5 py-0.5 rounded text-[12px] font-medium ${dirBadge[c.direction] || dirBadge.中性}`}>
          {c.direction}
        </span>
        <span className="text-primary text-[14px] font-semibold">{c.chain}/{c.node}</span>
        {c.confidence && <span className="text-dim text-[12px]">置信{c.confidence}</span>}
        <span className={`mono text-[12px] ${zCls(c.resonance ?? 0)}`}>共振{(c.resonance ?? 0) > 0 ? "+" : ""}{c.resonance}</span>
        <span className="text-dim text-[12px]">同向{c.n_agree}/激活{c.n_active}源</span>
        {c.divergence.length > 0 && (
          <Badge text={`⚠背离 ${c.divergence.map((d) => d.pair).join("、")}`} cls="bg-accent/10 text-accent" />
        )}
      </div>
      <p className="text-primary text-[14px] leading-relaxed mt-1.5">{c.thesis}</p>
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1.5 text-[12px] mono">
        {zs.map(([name, z]) => z != null && (
          <span key={name} className={zCls(z)}>{name}{z > 0 ? "+" : ""}{z.toFixed(1)}</span>
        ))}
        {m.letter?.hit && <span className="text-info">信函命中</span>}
      </div>
      {c.evidence.length > 0 && (
        <ul className="mt-1.5 space-y-0.5">
          {c.evidence.map((e, i) => (
            <li key={i} className="text-[13px] text-muted leading-snug">
              <span className="text-dim">[{e.src}]</span> {e.fact}
            </li>
          ))}
        </ul>
      )}
      {c.scenarios.map((s, i) => (
        <p key={i} className="text-[13px] text-muted mt-1 leading-snug">
          {s.cond && <span>{s.cond}{s.expect ? `,${s.expect}` : ""} </span>}
          {s.falsify && <span className="text-down">证伪:{s.falsify}</span>}
        </p>
      ))}
    </div>
  );
}

function JudgmentCards({ jb }: { jb: JudgmentBlock | null | undefined }) {
  if (!jb || jb.cards.length === 0) return null;
  return (
    <section className="border-t hairline pt-4">
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <div className="w-0.5 h-4 bg-accent" />
        <h2 className="font-semibold">节点研判 · 六源共振</h2>
        <span className="text-dim text-[12px]">方向=未来5交易日相对全池 · 判断留痕记分</span>
        {jb.fallback && <StaleBadge date={jb.date} label="今日研判未生成 · 显示" />}
      </div>
      <div className="space-y-2">
        <MoreList items={jb.cards} initial={3}>
          {(c) => <CardRow key={c.card_id} c={c} />}
        </MoreList>
      </div>
    </section>
  );
}

function DailyReport({ report, cards }: { report: Report | null | undefined; cards?: JudgmentBlock | null }) {
  const r = report;
  if (!r) return <div className="text-muted p-4">今日暂无报告</div>;
  return (
    <div className="space-y-5">
      {/* 今日主线(hero:整页第一眼要读到的一句话) */}
      <section>
        <div className="flex items-center gap-2 mb-2">
          <div className="w-0.5 h-4 bg-accent" />
          <h2 className="font-semibold">今日主线</h2>
          <span className={`w-2 h-2 rounded-full ${confDot[r.headline.confidence] || "bg-muted"}`} />
          <span className="text-dim text-[13px]">置信度 {r.headline.confidence}</span>
          {r.fallback && <StaleBadge date={r.report_date} label="今日报告未生成 · 显示" />}
        </div>
        <p className="text-[17px] leading-relaxed text-primary font-medium">{r.headline.fact}</p>
      </section>

      {/* 今天只看这3件事(紧跟主线,不被长文压到屏外) */}
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
                  <p className="text-primary">
                    {it.delta && (
                      <span className={`mr-1.5 px-1.5 py-0.5 rounded text-[12px] align-middle ${
                        it.delta === "新出现" ? "bg-accent/10 text-accent"
                        : it.delta === "反转" ? "bg-down/10 text-down" : "bg-info/10 text-info"}`}>
                        {it.delta === "延续" && it.streak_days ? `延续·第${it.streak_days}天` : it.delta}
                      </span>
                    )}
                    {it.change}
                  </p>
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

      {/* 节点研判卡(B6·第2屏:六源共振,带方向的可追责判断,紧跟三件事) */}
      <JudgmentCards jb={cards} />

      {/* 证伪与风险(纪律锚,提到第2屏:结论旁边就是"什么情况下它错了") */}
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

      {/* 盘中节奏(演进式增量,最新在前;先看最近3条,全程按需展开) */}
      {(r.increments?.length ?? 0) > 0 && (
        <section className="border-t hairline pt-4">
          <div className="flex items-center gap-2 mb-2">
            <div className="w-0.5 h-4 bg-accent" />
            <h2 className="font-semibold">盘中节奏</h2>
            <span className="text-dim text-[12px]">最新在前 · 只有实质变化才产生条目</span>
            <span className="text-dim text-[12px] mono ml-auto">{r.increments!.length}</span>
          </div>
          <ol className="space-y-1.5 border-l border-hairline ml-1.5 pl-3">
            <MoreList items={[...r.increments!].reverse()} initial={3}>
              {(inc) => (
                <li key={inc.hhmm} className="text-[14px]">
                  <span className="mono text-accent mr-2">{inc.hhmm}</span>
                  <span className="text-muted leading-relaxed">{inc.entry}</span>
                </li>
              )}
            </MoreList>
          </ol>
        </section>
      )}

      {/* 今日综述(正文层:结论都在上面了,这里是愿意细读的人的展开阅读) */}
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

      {/* 分板块扫描(状态陈列,默认折叠) */}
      {r.sectors.length > 0 && (
        <Panel title="分板块扫描" count={r.sectors.length} collapsible defaultOpen={false}>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
            {r.sectors.map((s, i) => (
              <div key={i} className="flex gap-2 text-[14px] border-l-2 border-hairline pl-2 py-0.5">
                <span className="text-accent shrink-0 font-medium">{s.chain}</span>
                <span className="text-dim">{s.status}</span>
              </div>
            ))}
          </div>
        </Panel>
      )}
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

// A股资金面:节点主力净额 top 流入/流出(客观统计,判断留给人)。个股名可点开详情。
function MoneyflowPanel({ mf }: { mf: Moneyflow }) {
  const openStock = useOpenStock();
  const flows = mf.nodes.filter((n) => Math.abs(n.main) >= 0.1);
  const tin = flows.slice(0, 5);
  const tout = flows.slice(-5).filter((n) => n.main < 0).reverse();
  const maxAbs = Math.max(...flows.map((n) => Math.abs(n.main)), 0.1);
  const Row = ({ n }: { n: typeof flows[0] }) => (
    <div className="flex items-center gap-2 text-[13px]">
      <span className="text-primary w-[38%] truncate shrink-0">{n.chain}/{n.node}</span>
      <div className="flex-1 h-2 rounded bg-elevated/60 overflow-hidden">
        <div className={`h-full ${n.main >= 0 ? "bg-up/70" : "bg-down/70"}`}
          style={{ width: `${Math.min(100, (Math.abs(n.main) / maxAbs) * 100)}%` }} />
      </div>
      <span className={`mono w-16 text-right shrink-0 ${pctCls(n.main)}`}>{n.main > 0 ? "+" : ""}{n.main}亿</span>
    </div>
  );
  const Tops = ({ ss }: { ss: { code: string; name: string; main: number }[] }) => (
    <>{ss.map((s) => (
      <button key={s.code} onClick={() => openStock({ code: s.code, name: s.name })}
        className="text-[12px] text-muted bg-elevated/60 px-1.5 py-0.5 rounded hover:text-accent mono">
        {s.name} <span className={pctCls(s.main)}>{s.main > 0 ? "+" : ""}{s.main}</span>
      </button>
    ))}</>
  );
  return (
    <div className="space-y-2">
      <div className="text-dim text-[12px]">
        主力=大单+超大单净额 · {mf.kind === "eod" ? `${mf.date} 收盘` : `${mf.date} 盘中截至${mf.stamp || ""}`}
        · 核心池合计 <span className={`mono ${pctCls(mf.pool_main)}`}>{mf.pool_main > 0 ? "+" : ""}{mf.pool_main}亿</span>
      </div>
      {tin.map((n) => <Row key={n.node_id} n={n} />)}
      {tout.length > 0 && <div className="border-t hairline my-1" />}
      {tout.map((n) => <Row key={n.node_id} n={n} />)}
      <div className="flex flex-wrap gap-1.5 pt-1">
        <Tops ss={tin.flatMap((n) => n.top_in).slice(0, 4)} />
        <Tops ss={tout.flatMap((n) => n.top_out).slice(0, 3)} />
      </div>
    </div>
  );
}

// 报告页整页(左报告+右侧栏,A股/美股 两套侧栏)。usNewsNodes 由 App 传入(新闻页也用)。
export function ReportPageView({ d, isUS, usNewsNodes }: { d: Dashboard; isUS: boolean; usNewsNodes: Dashboard["news_by_node"] }) {
  // 报告页舆情面板:只留媒体+Reddit(推特X 已挪到热点视图右栏)
  const usWireMedia = (d.us?.wire || []).filter((w) => w.group !== "推特X");
  return (
    <div className="flex-1 grid grid-cols-1 md:grid-cols-[1.6fr_1fr] gap-4 md:gap-6 p-3 md:p-6 overflow-auto">
      <div className="space-y-6">
        {isUS ? <UsIndexBar us={d.us} /> : <GaugeBar g={d.market} />}
        <DailyReport report={isUS ? d.us?.report : d.report} cards={isUS ? null : d.judgment} />
        {/* 推特X观点综述:左栏主阅读流(原在右栏,手机沉底刷不到) */}
        {isUS && (d.us?.report?.x_takes?.us_global || d.us?.report?.x_takes?.a_share) && (
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
        {!isUS && d.stock_events.length > 0 && (
          <Panel title="个股事件 · 公告 / 龙虎榜" count={d.stock_events.length} collapsible defaultOpen={false}>
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
            <Panel title="全球科技舆情 · WSJ/路透/科技媒体/Reddit" count={usWireMedia.length} collapsible defaultOpen={false}>
              <TechWire wire={usWireMedia} />
            </Panel>
          </>
        ) : (
          <>
            {d.moneyflow && d.moneyflow.nodes?.length > 0 && (
              <Panel title="资金面 · 节点主力净额" collapsible>
                <MoneyflowPanel mf={d.moneyflow} />
              </Panel>
            )}
            {d.report?.us_overnight && (
              <Panel title="隔夜美股科技链" collapsible>
                <UsOvernightBoard us={d.report.us_overnight} />
              </Panel>
            )}
            <Panel title="判断复盘账本 · 近30日" collapsible defaultOpen={false}>
              <LedgerPanel ledger={d.ledger} />
            </Panel>
            {/* 事件流与热点页新闻流同源,右栏默认收起当索引用;持仓空面板已删(四期持仓层复活时重建) */}
            <Panel title="事件流 · 按节点" count={d.news_by_node.length} collapsible defaultOpen={false}>
              <EventStream nodes={d.news_by_node} />
            </Panel>
          </>
        )}
      </div>
    </div>
  );
}
