import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import type { Dashboard, NewsItem } from "./types";
import type { StockSel } from "./stockCtx";
import { fmtMc, pctCls, sentColor } from "./ui";

// 走势小图数据(6M日线)单列 trends.json,首次打开个股详情时懒加载一次,模块级缓存。
type TrendPoint = [string, number];
type TrendMap = { a?: Record<string, TrendPoint[]>; us?: Record<string, TrendPoint[]> };
let _trendsCache: TrendMap | null = null;
let _trendsPromise: Promise<TrendMap> | null = null;
function loadTrends(): Promise<TrendMap> {
  if (_trendsCache) return Promise.resolve(_trendsCache);
  if (!_trendsPromise) {
    _trendsPromise = fetch("/data/trends.json")
      .then((r) => r.json())
      .then((j: TrendMap) => (_trendsCache = j))
      .catch(() => ({ a: {}, us: {} }) as TrendMap);
  }
  return _trendsPromise;
}

function TrendChart({ series }: { series: TrendPoint[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: "canvas" });
    const dates = series.map((p) => p[0]);
    const closes = series.map((p) => p[1]);
    const up = closes[closes.length - 1] >= closes[0]; // A股/美股统一红涨绿跌
    const color = up ? "#F6465D" : "#2EBD85";
    const fmt = (s: string) => `${s.slice(4, 6)}/${s.slice(6, 8)}`;
    chart.setOption({
      grid: { left: 46, right: 12, top: 10, bottom: 20 },
      tooltip: { trigger: "axis", formatter: (p: any) => `${dates[p[0].dataIndex]}<br/>${p[0].data}` },
      xAxis: { type: "category", data: dates.map(fmt), boundaryGap: false,
        axisLabel: { color: "#5A6474", fontSize: 10, interval: Math.max(1, Math.floor(dates.length / 6)) },
        axisLine: { lineStyle: { color: "#232B36" } }, axisTick: { show: false } },
      yAxis: { type: "value", scale: true, axisLabel: { color: "#5A6474", fontSize: 10 },
        splitLine: { lineStyle: { color: "#1A2029" } } },
      series: [{ type: "line", data: closes, smooth: true, symbol: "none",
        lineStyle: { color, width: 1.5 },
        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: up ? "rgba(246,70,93,0.22)" : "rgba(46,189,133,0.22)" },
          { offset: 1, color: "rgba(0,0,0,0)" }]) } }],
    });
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => { ro.disconnect(); chart.dispose(); };
  }, [series]);
  return <div ref={ref} className="w-full h-40" />;
}

const recLabel: Record<string, string> = { strong_buy: "强烈买入", buy: "买入", hold: "持有", underperform: "跑输", sell: "卖出" };
const num = (v: number | null | undefined, s = "") => (v == null ? "—" : `${v}${s}`);

function Field({ k, v, cls = "text-muted" }: { k: string; v: React.ReactNode; cls?: string }) {
  return <div className="flex flex-col"><span className="text-dim text-[12px]">{k}</span><span className={`mono ${cls}`}>{v}</span></div>;
}
function Sec({ title, n, children }: { title: string; n?: number; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[13px] text-muted mb-1.5 flex items-center gap-2">
        <span className="w-0.5 h-3.5 bg-accent" />{title}{n != null && <span className="text-dim">({n})</span>}
      </div>
      {children}
    </div>
  );
}

export function StockDetail({ sel, market, d, onClose }: { sel: StockSel; market: "A" | "US"; d: Dashboard; onClose: () => void }) {
  const isUS = market === "US";
  // 解析 code / name
  const hStocks = (isUS ? d.us?.heatmap?.stocks : d.heatmap?.stocks) || [];
  const board = isUS ? (d.us?.board?.items || []) : [];
  const byCode = (c?: string) => c && (hStocks.find((s) => s.code === c) || board.find((s: any) => s.ticker === c));
  const byName = (n?: string) => n && (hStocks.find((s) => s.name === n) || board.find((s: any) => s.name === n));
  const hit: any = byCode(sel.code) || byName(sel.name) || {};
  const code = sel.code || hit.code || hit.ticker;
  const name = hit.name || sel.name || code;

  // 行情/估值
  const hs: any = hStocks.find((s) => s.code === code) || {};
  const bd: any = board.find((s: any) => s.ticker === code) || {};

  // 节点/象限
  const nodeIds: string[] = hs.node_ids || (bd.sector ? [bd.sector] : []);
  const nodes = (isUS ? d.us?.heatmap?.nodes : d.heatmap?.nodes) || [];
  const myNodes = nodes.filter((n) => nodeIds.includes(n.node_id));

  // 新闻
  let news: (NewsItem & { one_line?: string })[] = [];
  if (isUS) {
    news = (d.us?.news || []).filter((n) => n.ticker === code).map((n) => ({ ...n } as any));
  } else {
    const seen = new Set<string>();
    for (const g of d.news_by_node) for (const it of g.items) {
      if ((it.codes || []).includes(code) && !seen.has(it.title)) { seen.add(it.title); news.push(it); }
    }
  }
  // 事件(仅A股)
  const events = isUS ? [] : d.stock_events.filter((e) => e.code === code);
  // 研报
  const aReports = isUS ? [] : (d.research?.reports || []).filter((r) => r.code === code);
  const usRes: any = isUS ? (d.us?.research || []).find((r) => r.code === code) : null;

  const pct = bd.pct ?? hs.ret_1d;
  const mv = hs.total_mv ?? bd.market_cap;

  // 6个月走势(懒加载 trends.json,按 code/ticker 查)
  const [trend, setTrend] = useState<TrendPoint[] | null>(null);
  useEffect(() => {
    let alive = true;
    loadTrends().then((t) => {
      if (!alive) return;
      const s = (isUS ? t.us : t.a)?.[code as string];
      setTrend(s && s.length > 1 ? s : []);
    });
    return () => { alive = false; };
  }, [code, isUS]);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-0 sm:p-4 overflow-auto" onClick={onClose}>
      <div className="bg-surface border hairline rounded-none sm:rounded-lg w-full max-w-2xl my-0 sm:my-4 min-h-full sm:min-h-0" onClick={(e) => e.stopPropagation()}>
        {/* 头 */}
        <div className="flex items-center gap-2 px-4 py-3 border-b hairline">
          <span className="text-primary font-semibold text-[17px]">{name}</span>
          <span className="mono text-dim text-[13px]">{code}</span>
          {isUS && <span className="text-info text-[12px]">美股</span>}
          {pct != null && <span className={`mono ${pctCls(pct)}`}>{pct > 0 ? "+" : ""}{pct}%</span>}
          <button onClick={onClose} className="ml-auto text-muted hover:text-primary text-[14px]">✕</button>
        </div>

        <div className="p-4 space-y-4">
          {/* 行情/估值(1日涨幅在标题行;A股加周/月窗口与5日主力——个股维度信息归详情弹层) */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-[14px]">
            <Field k="市值" v={fmtMc(mv, isUS)} />
            <Field k="PE" v={num(hs.pe ?? bd.pe)} />
            {!isUS && <Field k="1周涨幅" v={num(hs.ret_1w, "%")} cls={pctCls(hs.ret_1w)} />}
            {!isUS && <Field k="1月涨幅" v={num(hs.ret_1m, "%")} cls={pctCls(hs.ret_1m)} />}
            <Field k="6M涨幅" v={num(hs.ret_6m ?? bd.ret_6m, "%")} cls={pctCls(hs.ret_6m ?? bd.ret_6m)} />
            <Field k={isUS ? "营收增速" : "营收同比"} v={num(hs.or_yoy ?? bd.rev_growth, "%")} cls={pctCls(hs.or_yoy ?? bd.rev_growth)} />
            {!isUS && <Field k="毛利率" v={num(hs.gross_margin, "%")} />}
            {!isUS && d.moneyflow?.stocks?.[code] != null && (
              <Field k={`主力净额(${d.moneyflow.kind === "eod" ? "收盘" : "盘中"})`}
                v={`${d.moneyflow.stocks[code] > 0 ? "+" : ""}${d.moneyflow.stocks[code]}亿`}
                cls={pctCls(d.moneyflow.stocks[code])} />
            )}
            {!isUS && d.moneyflow?.stocks5?.[code] != null && (
              <Field k="主力5日累计"
                v={`${d.moneyflow.stocks5[code] > 0 ? "+" : ""}${d.moneyflow.stocks5[code]}亿`}
                cls={pctCls(d.moneyflow.stocks5[code])} />
            )}
            {isUS && bd.target_mean != null && <Field k="目标均价" v={num(bd.target_mean)} cls="text-accent" />}
            {isUS && bd.rec_key && <Field k="评级" v={recLabel[bd.rec_key] || bd.rec_key} cls="text-up" />}
          </div>

          {/* 筹码/市场持仓成本(仅A股,东财式估算口径,盘后更新):现价偏离用6M走势末点(最新收盘) */}
          {!isUS && (() => {
            const chip = d.chips?.[code as string];
            if (!chip || chip.avg == null) return null;
            const last = trend && trend.length > 1 ? trend[trend.length - 1][1] : null;
            const dev = last != null && chip.avg ? Math.round((last / chip.avg - 1) * 1000) / 10 : null;
            return (
              <Sec title="筹码 · 市场持仓成本(估算)">
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-[14px]">
                  <Field k="平均成本" v={`${chip.avg}元`} cls="text-primary" />
                  <Field k="现价较成本" v={dev == null ? "—" : `${dev > 0 ? "+" : ""}${dev}%`} cls={pctCls(dev)} />
                  <Field k="获利盘" v={num(chip.win, "%")}
                    cls={chip.win != null && chip.win >= 50 ? "text-up" : "text-muted"} />
                  <Field k="90%筹码区间" v={chip.lo != null && chip.hi != null ? `${chip.lo}-${chip.hi}元` : "—"} />
                </div>
                <div className="text-dim text-[12px] mt-1.5">
                  筹码分布为历史成交推算的估算口径 · 截至 {chip.date} 收盘 · 只呈现事实不构成建议
                </div>
              </Sec>
            );
          })()}

          {/* 6个月走势小图 */}
          {trend && trend.length > 1 && (
            <Sec title="6个月走势">
              <TrendChart series={trend} />
            </Sec>
          )}

          {/* 所属节点/象限 */}
          {myNodes.length > 0 && (
            <Sec title="所属产业链节点 · 热力象限">
              <div className="flex flex-wrap gap-2">
                {myNodes.map((n) => (
                  <span key={n.node_id} className="text-[13px] bg-elevated/60 px-2 py-1 rounded flex items-center gap-1.5">
                    <span className="text-primary">{n.chain}/{n.node}</span>
                    <span className="text-accent text-[12px]">{n.quadrant}</span>
                  </span>
                ))}
              </div>
            </Sec>
          )}

          {/* 研报/分析师 */}
          {(aReports.length > 0 || usRes) && (
            <Sec title="研报 / 分析师" n={isUS ? undefined : aReports.length}>
              {isUS && usRes ? (
                <div className="text-[14px] text-muted">
                  目标均价 <span className="text-accent mono">{usRes.target_mean ?? "—"}</span>,
                  上行空间 <span className={`mono ${pctCls(usRes.upside)}`}>{usRes.upside == null ? "—" : `${usRes.upside}%`}</span>,
                  评级 <span className="text-up">{recLabel[usRes.rec_key] || usRes.rec_key || "—"}</span>,
                  {usRes.n_analysts ?? "—"} 家覆盖
                </div>
              ) : (
                <div className="space-y-1">
                  {aReports.slice(0, 6).map((r, i) => (
                    <div key={i} className="flex items-center gap-2 text-[13px]">
                      <span className="mono text-dim">{r.date}</span>
                      <span className="text-accent">{r.rating || "—"}</span>
                      {r.tp != null && <span className="mono text-accent text-[12px]">目标{r.tp}</span>}
                      <span className="text-muted truncate">{r.org}</span>
                    </div>
                  ))}
                </div>
              )}
            </Sec>
          )}

          {/* 个股事件 */}
          {events.length > 0 && (
            <Sec title="个股事件 · 公告/龙虎榜" n={events.length}>
              <div className="space-y-1">
                {events.map((e, i) => (
                  <div key={i} className="flex items-center gap-2 text-[13px]">
                    <span className="bg-elevated text-muted px-1.5 py-0.5 rounded text-[12px]">{e.event_type}</span>
                    <span className={e.direction === "利好" ? "text-up" : e.direction === "利空" ? "text-down" : "text-muted"}>{e.direction}</span>
                    <span className="text-dim flex-1 truncate">{e.summary}</span>
                    <span className="mono text-dim text-[12px]">{e.date}</span>
                  </div>
                ))}
              </div>
            </Sec>
          )}

          {/* 相关新闻(带核心观点) */}
          <Sec title="相关新闻" n={news.length}>
            {news.length === 0 ? <div className="text-dim text-[13px]">近期无匹配到该票的新闻。</div> : (
              <div className="space-y-2">
                {news.slice(0, 12).map((n, i) => (
                  <div key={i} className="border hairline rounded px-3 py-2">
                    <div className="flex items-start gap-2">
                      <span className={`px-1.5 py-0.5 rounded text-[12px] shrink-0 ${sentColor[n.sentiment] || "text-muted"}`}>{n.sentiment}</span>
                      <div className="flex-1 min-w-0">
                        <p className="text-primary text-[14px] leading-snug font-medium">{n.one_line || n.title}</p>
                        {n.summary && <p className="text-muted text-[13px] leading-relaxed mt-1">{n.summary}</p>}
                        <div className="flex items-center gap-2 mt-1 text-[12px] text-dim">
                          <span>{n.src}</span>
                          {n.url && <a href={n.url} target="_blank" rel="noreferrer" className="text-info hover:underline">原文↗</a>}
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Sec>
        </div>
      </div>
    </div>
  );
}
