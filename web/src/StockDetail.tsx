import type { Dashboard, NewsItem } from "./types";
import type { StockSel } from "./stockCtx";

const pctCls = (v: number | null | undefined) => (v == null ? "text-dim" : v > 0 ? "text-up" : v < 0 ? "text-down" : "text-muted");
const sentColor: Record<string, string> = {
  利好: "text-up bg-up/10", 利空: "text-down bg-down/10", 中性: "text-muted bg-muted/10", 澄清: "text-info bg-info/10",
};
const recLabel: Record<string, string> = { strong_buy: "强烈买入", buy: "买入", hold: "持有", underperform: "跑输", sell: "卖出" };
const num = (v: number | null | undefined, s = "") => (v == null ? "—" : `${v}${s}`);
const fmtMc = (v: number | null | undefined) => (v == null ? "—" : v >= 1000 ? `${(v / 1000).toFixed(2)}T` : `${Math.round(v)}B`);

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

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-4 overflow-auto" onClick={onClose}>
      <div className="bg-surface border hairline rounded-lg w-full max-w-2xl my-4" onClick={(e) => e.stopPropagation()}>
        {/* 头 */}
        <div className="flex items-center gap-2 px-4 py-3 border-b hairline">
          <span className="text-primary font-semibold text-[17px]">{name}</span>
          <span className="mono text-dim text-[13px]">{code}</span>
          {isUS && <span className="text-info text-[12px]">美股</span>}
          {pct != null && <span className={`mono ${pctCls(pct)}`}>{pct > 0 ? "+" : ""}{pct}%</span>}
          <button onClick={onClose} className="ml-auto text-muted hover:text-primary text-[14px]">✕</button>
        </div>

        <div className="p-4 space-y-4">
          {/* 行情/估值 */}
          <div className="grid grid-cols-4 gap-3 text-[14px]">
            <Field k="市值" v={fmtMc(mv)} />
            <Field k="PE" v={num(hs.pe ?? bd.pe)} />
            <Field k="6M涨幅" v={num(hs.ret_6m ?? bd.ret_6m, "%")} cls={pctCls(hs.ret_6m ?? bd.ret_6m)} />
            <Field k={isUS ? "营收增速" : "营收同比"} v={num(hs.or_yoy ?? bd.rev_growth, "%")} cls={pctCls(hs.or_yoy ?? bd.rev_growth)} />
            {!isUS && <Field k="毛利率" v={num(hs.gross_margin, "%")} />}
            {isUS && bd.target_mean != null && <Field k="目标均价" v={num(bd.target_mean)} cls="text-accent" />}
            {isUS && bd.rec_key && <Field k="评级" v={recLabel[bd.rec_key] || bd.rec_key} cls="text-up" />}
          </div>

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
