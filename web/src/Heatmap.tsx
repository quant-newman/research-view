import { useEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts";
import type { Heatmap, HeatNode, HeatStock } from "./types";
import { useOpenStock } from "./stockCtx";
import { pctCls } from "./ui";

const QUAD_COLOR: Record<string, string> = {
  核心主线: "#F6465D", 潜在补涨: "#F0B90B", 等待验证: "#4A9EFF", 风险区: "#5A6474", 数据不足: "#232B36",
};

type WinKey = "ret_1d" | "ret_1w" | "ret_1m" | "ret_3m" | "ret_6m";
const WINS: [WinKey, string][] = [
  ["ret_1d", "1天"], ["ret_1w", "1周"], ["ret_1m", "1月"], ["ret_3m", "3月"], ["ret_6m", "6月"],
];
const WIN_LABEL: Record<WinKey, string> = Object.fromEntries(WINS) as Record<WinKey, string>;

const nz = (v: any): number | null => (v == null || v === "" ? null : Number(v));

// 象限按选中窗口涨幅(X)× 营收同比(Y)相对池内中位切分,前端动态重算
function quadOf(x: number | null, y: number | null, xm: number, ym: number): string {
  if (x == null || y == null) return "数据不足";
  const strong = x >= xm, deliver = y >= ym;
  return strong && deliver ? "核心主线" : !strong && deliver ? "等待验证" : strong ? "潜在补涨" : "风险区";
}

function median(xs: (number | null)[]) {
  const a = xs.filter((v): v is number => v != null && !Number.isNaN(v)).sort((x, y) => x - y);
  return a.length ? a[Math.floor(a.length / 2)] : 0;
}

function Scatter({ nodes, win, onSelect }: { nodes: HeatNode[]; win: WinKey; onSelect: (id: string) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const selRef = useRef(onSelect);
  selRef.current = onSelect;
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: "canvas" });
    const pts = nodes
      .map((n) => ({ ...n, x: nz((n as any)[win]), y: nz(n.or_yoy), total_mv: nz(n.total_mv) }))
      .filter((n) => n.x != null && n.y != null);
    const xSplit = median(pts.map((n) => n.x));
    const ySplit = median(pts.map((n) => n.y));
    const maxMv = Math.max(...pts.map((n) => n.total_mv || 0), 1);
    const label = WIN_LABEL[win];
    chart.setOption({
      backgroundColor: "transparent",
      grid: { left: 52, right: 20, top: 24, bottom: 44 },
      tooltip: {
        backgroundColor: "#1C2430", borderColor: "#232B36", textStyle: { color: "#E4E9F0", fontSize: 12 },
        formatter: (p: any) => {
          const n = p.data.n as HeatNode;
          return `<b>${n.chain}/${n.node}</b> · ${n.n_stocks}只<br/>叙事(${label}): ${p.data.value[0]}%<br/>兑现(营收): ${n.or_yoy}%<br/>PE中位: ${n.pe} · 毛利: ${n.gross_margin}%<br/>象限: ${p.data.q}<br/><span style="color:#8B95A5">点击看成分股</span>`;
        },
      },
      xAxis: {
        name: `叙事强度 · ${label}涨幅%`, nameLocation: "middle", nameGap: 28,
        nameTextStyle: { color: "#8B95A5" }, axisLine: { lineStyle: { color: "#232B36" } },
        axisLabel: { color: "#5A6474" }, splitLine: { lineStyle: { color: "#161C24" } },
      },
      yAxis: {
        name: "财报兑现 · 营收同比%", nameTextStyle: { color: "#8B95A5" },
        axisLine: { lineStyle: { color: "#232B36" } }, axisLabel: { color: "#5A6474" },
        splitLine: { lineStyle: { color: "#161C24" } },
      },
      series: [{
        type: "scatter",
        symbolSize: (_val: any, params: any) => 8 + 34 * Math.sqrt((params?.data?.n?.total_mv || 0) / maxMv),
        itemStyle: { color: (p: any) => QUAD_COLOR[p.data?.q] || "#5A6474", opacity: 0.82 },
        emphasis: { itemStyle: { opacity: 1, borderColor: "#E4E9F0", borderWidth: 1 } },
        data: pts.map((n) => ({ value: [n.x, n.y], n, q: quadOf(n.x, n.y, xSplit, ySplit) })),
        markLine: {
          silent: true, symbol: "none", lineStyle: { color: "#3A4452", type: "dashed" },
          data: [{ xAxis: xSplit }, { yAxis: ySplit }],
        },
      }],
    });
    chart.getZr().on("mousemove", (e: any) => { chart.getZr().setCursorStyle(e.target ? "pointer" : "default"); });
    chart.on("click", (p: any) => { const n = p?.data?.n; if (n?.node_id) selRef.current(n.node_id); });
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => { ro.disconnect(); chart.dispose(); };
  }, [nodes, win]);
  return <div ref={ref} className="w-full h-[300px] md:h-[380px]" />;
}

type SortKey = keyof HeatNode;
function NodeTable({ nodes, onSelect, selected }: { nodes: HeatNode[]; onSelect: (id: string) => void; selected: string | null }) {
  const [sort, setSort] = useState<SortKey>("total_mv");
  const [asc, setAsc] = useState(false);
  const rows = useMemo(() => {
    const r = [...nodes];
    r.sort((a, b) => {
      const va = a[sort], vb = b[sort];
      if (va == null) return 1; if (vb == null) return -1;
      return (va < vb ? -1 : va > vb ? 1 : 0) * (asc ? 1 : -1);
    });
    return r;
  }, [nodes, sort, asc]);
  const cols: [SortKey, string][] = [
    ["node", "节点"], ["chain", "链"], ["n_stocks", "公司数"], ["total_mv", "市值(亿)"],
    ["ret_1m", "1M%"], ["ret_6m", "6M%"], ["or_yoy", "营收%"], ["gross_margin", "毛利%"],
    ["pe", "PE"], ["ps", "PS"], ["quadrant", "象限"],
  ];
  const click = (k: SortKey) => { if (k === sort) setAsc(!asc); else { setSort(k); setAsc(false); } };
  const num = (v: any) => (typeof v === "number" ? (Number.isInteger(v) ? v : v.toFixed(1)) : v ?? "—");
  return (
    <div className="overflow-auto">
      <table className="w-full text-[14px] mono">
        <thead className="sticky top-0 bg-surface">
          <tr className="text-muted text-left">
            {cols.map(([k, label]) => (
              <th key={k} className="px-2 py-1.5 cursor-pointer hover:text-primary font-normal whitespace-nowrap"
                  onClick={() => click(k)}>
                {label}{sort === k ? (asc ? " ▲" : " ▼") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((n) => (
            <tr key={n.node_id} onClick={() => onSelect(n.node_id)}
                className={`border-t hairline cursor-pointer hover:bg-elevated/40 ${selected === n.node_id ? "bg-elevated/60" : ""}`}>
              <td className="px-2 py-1.5 text-primary whitespace-nowrap">{n.node}</td>
              <td className="px-2 py-1.5 text-muted">{n.chain}</td>
              <td className="px-2 py-1.5 text-right">{n.n_stocks}</td>
              <td className="px-2 py-1.5 text-right text-muted">{n.total_mv ? Math.round(n.total_mv / 1e4).toLocaleString() : "—"}</td>
              <td className={`px-2 py-1.5 text-right ${pctCls(n.ret_1m)}`}>{num(n.ret_1m)}</td>
              <td className={`px-2 py-1.5 text-right ${pctCls(n.ret_6m)}`}>{num(n.ret_6m)}</td>
              <td className={`px-2 py-1.5 text-right ${pctCls(n.or_yoy)}`}>{num(n.or_yoy)}</td>
              <td className="px-2 py-1.5 text-right text-muted">{num(n.gross_margin)}</td>
              <td className="px-2 py-1.5 text-right text-muted">{num(n.pe)}</td>
              <td className="px-2 py-1.5 text-right text-muted">{num(n.ps)}</td>
              <td className="px-2 py-1.5">
                <span className="px-1.5 py-0.5 rounded text-[13px]"
                      style={{ color: QUAD_COLOR[n.quadrant], background: `${QUAD_COLOR[n.quadrant]}1a` }}>
                  {n.quadrant}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StockPanel({ node, stocks, onClose }: { node: HeatNode; stocks: HeatStock[]; onClose: () => void }) {
  const openStock = useOpenStock();
  const num = (v: number | null) => (v == null ? "—" : Number.isInteger(v) ? v : v.toFixed(1));
  const sorted = [...stocks].sort((a, b) => (b.ret_6m ?? -1e9) - (a.ret_6m ?? -1e9));
  return (
    <div className="border border-accent/40 rounded bg-surface">
      <div className="flex items-center gap-2 px-3 py-2 border-b hairline">
        <span className="text-primary font-semibold text-[14px]">{node.chain}/{node.node}</span>
        <span className="px-1.5 py-0.5 rounded text-[12px]" style={{ color: QUAD_COLOR[node.quadrant], background: `${QUAD_COLOR[node.quadrant]}1a` }}>{node.quadrant}</span>
        <span className="text-dim text-[13px]">{stocks.length} 只成分股</span>
        <button onClick={onClose} className="ml-auto text-muted hover:text-primary text-[13px]">✕ 收起</button>
      </div>
      <div className="p-3 overflow-auto">
        {stocks.length === 0 ? (
          <div className="text-dim text-[13px]">该节点无个股明细数据。</div>
        ) : (
          <table className="w-full text-[14px] mono">
            <thead><tr className="text-muted text-left text-[13px]">
              <th className="font-normal py-1">名称</th><th className="font-normal">代码</th>
              <th className="font-normal text-right">6M%</th><th className="font-normal text-right">营收%</th>
              <th className="font-normal text-right">毛利%</th><th className="font-normal text-right">PE</th>
              <th className="font-normal text-right">市值(亿)</th>
            </tr></thead>
            <tbody>
              {sorted.map((s) => (
                <tr key={s.code} onClick={() => openStock({ code: s.code, name: s.name })}
                    className="border-t hairline cursor-pointer hover:bg-elevated/40">
                  <td className="py-1 text-primary">{s.name}</td>
                  <td className="text-dim text-[13px]">{s.code}</td>
                  <td className={`text-right ${pctCls(s.ret_6m)}`}>{num(s.ret_6m)}</td>
                  <td className={`text-right ${pctCls(s.or_yoy)}`}>{num(s.or_yoy)}</td>
                  <td className="text-right text-muted">{num(s.gross_margin)}</td>
                  <td className="text-right text-muted">{num(s.pe)}</td>
                  <td className="text-right text-muted">{s.total_mv ? Math.round(s.total_mv / 1e4).toLocaleString() : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

export default function HeatmapView({ h }: { h: Heatmap | undefined }) {
  const [sel, setSel] = useState<string | null>(null);
  const [win, setWin] = useState<WinKey>("ret_6m");
  if (!h) return <div className="text-muted p-4">暂无热力图数据</div>;
  const legend = [["核心主线", "叙事强+兑现好"], ["潜在补涨", "叙事强+兑现弱"],
                  ["等待验证", "叙事弱+兑现好"], ["风险区", "叙事弱+兑现弱"]];
  const selNode = h.nodes.find((n) => n.node_id === sel) || null;
  const selStocks = sel ? (h.stocks || []).filter((s) => (s.node_ids || []).includes(sel)) : [];
  return (
    <div className="space-y-4">
      <div className="border hairline rounded bg-surface">
        <div className="flex flex-wrap items-center justify-between gap-y-1 px-3 py-2 border-b hairline">
          <span className="text-[13px] text-muted uppercase tracking-wide">四象限 · 叙事强度 × 财报兑现(气泡=市值 · 点气泡看成分股)</span>
          <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[13px]">
            {legend.map(([q, d]) => (
              <span key={q} className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full inline-block" style={{ background: QUAD_COLOR[q] }} />
                <span className="text-muted">{q}</span><span className="text-dim">{d}</span>
              </span>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 px-3 py-1.5 border-b hairline text-[13px]">
          <span className="text-dim">叙事窗口(X轴涨幅):</span>
          {WINS.map(([k, l]) => (
            <button key={k} onClick={() => setWin(k)}
              className={`px-2 py-0.5 rounded border ${win === k ? "border-accent text-accent bg-accent/10" : "border-hairline text-muted hover:text-primary"}`}>
              {l}
            </button>
          ))}
        </div>
        <div className="p-2"><Scatter nodes={h.nodes} win={win} onSelect={setSel} /></div>
      </div>
      {selNode && <StockPanel node={selNode} stocks={selStocks} onClose={() => setSel(null)} />}
      <div className="border hairline rounded bg-surface">
        <div className="px-3 py-2 border-b hairline text-[13px] text-muted uppercase tracking-wide">
          节点监控表 · {h.nodes.length} 节点(点表头排序 · 点行看成分股)
        </div>
        <NodeTable nodes={h.nodes} onSelect={setSel} selected={sel} />
      </div>
    </div>
  );
}
