import { useEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts";
import type { Heatmap, HeatNode } from "./types";

const QUAD_COLOR: Record<string, string> = {
  核心主线: "#F6465D", 潜在补涨: "#F0B90B", 等待验证: "#4A9EFF", 风险区: "#5A6474", 数据不足: "#232B36",
};

const nz = (v: any): number | null => (v == null || v === "" ? null : Number(v));

function median(xs: (number | null)[]) {
  const a = xs.filter((v): v is number => v != null && !Number.isNaN(v)).sort((x, y) => x - y);
  return a.length ? a[Math.floor(a.length / 2)] : 0;
}

function Scatter({ nodes }: { nodes: HeatNode[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: "canvas" });
    const pts = nodes
      .map((n) => ({ ...n, ret_6m: nz(n.ret_6m), or_yoy: nz(n.or_yoy), total_mv: nz(n.total_mv) }))
      .filter((n) => n.ret_6m != null && n.or_yoy != null);
    const xSplit = median(pts.map((n) => n.ret_6m));
    const ySplit = median(pts.map((n) => n.or_yoy));
    const maxMv = Math.max(...pts.map((n) => n.total_mv || 0), 1);
    chart.setOption({
      backgroundColor: "transparent",
      grid: { left: 52, right: 20, top: 24, bottom: 44 },
      tooltip: {
        backgroundColor: "#1C2430", borderColor: "#232B36", textStyle: { color: "#E4E9F0", fontSize: 12 },
        formatter: (p: any) => {
          const n = p.data.n as HeatNode;
          return `<b>${n.chain}/${n.node}</b> · ${n.n_stocks}只<br/>叙事(6M): ${n.ret_6m}%<br/>兑现(营收): ${n.or_yoy}%<br/>PE中位: ${n.pe} · 毛利: ${n.gross_margin}%<br/>象限: ${n.quadrant}`;
        },
      },
      xAxis: {
        name: "叙事强度 · 6M涨幅%", nameLocation: "middle", nameGap: 28,
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
        // symbolSize 回调签名是 (value, params);自定义字段要从 params.data.n 取
        symbolSize: (_val: any, params: any) => 8 + 34 * Math.sqrt((params?.data?.n?.total_mv || 0) / maxMv),
        itemStyle: { color: (p: any) => QUAD_COLOR[p.data?.n?.quadrant] || "#5A6474", opacity: 0.82 },
        data: pts.map((n) => ({ value: [n.ret_6m, n.or_yoy], n })),
        markLine: {
          silent: true, symbol: "none", lineStyle: { color: "#3A4452", type: "dashed" },
          data: [{ xAxis: xSplit }, { yAxis: ySplit }],
        },
      }],
    });
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => { ro.disconnect(); chart.dispose(); };
  }, [nodes]);
  return <div ref={ref} className="w-full h-[380px]" />;
}

type SortKey = keyof HeatNode;
function NodeTable({ nodes }: { nodes: HeatNode[] }) {
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
    ["node", "节点"], ["chain", "链"], ["n_stocks", "公司数"], ["total_mv", "市值(万)"],
    ["ret_1m", "1M%"], ["ret_6m", "6M%"], ["or_yoy", "营收%"], ["gross_margin", "毛利%"],
    ["pe", "PE"], ["ps", "PS"], ["quadrant", "象限"],
  ];
  const click = (k: SortKey) => { if (k === sort) setAsc(!asc); else { setSort(k); setAsc(false); } };
  const num = (v: any) => (typeof v === "number" ? (Number.isInteger(v) ? v : v.toFixed(1)) : v ?? "—");
  const pctCls = (v: any) => (typeof v === "number" ? (v > 0 ? "text-up" : v < 0 ? "text-down" : "text-muted") : "");
  return (
    <div className="overflow-auto">
      <table className="w-full text-[12px] mono">
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
            <tr key={n.node_id} className="border-t hairline hover:bg-elevated/40">
              <td className="px-2 py-1.5 text-primary whitespace-nowrap">{n.node}</td>
              <td className="px-2 py-1.5 text-muted">{n.chain}</td>
              <td className="px-2 py-1.5 text-right">{n.n_stocks}</td>
              <td className="px-2 py-1.5 text-right text-muted">{n.total_mv ? Math.round(n.total_mv).toLocaleString() : "—"}</td>
              <td className={`px-2 py-1.5 text-right ${pctCls(n.ret_1m)}`}>{num(n.ret_1m)}</td>
              <td className={`px-2 py-1.5 text-right ${pctCls(n.ret_6m)}`}>{num(n.ret_6m)}</td>
              <td className={`px-2 py-1.5 text-right ${pctCls(n.or_yoy)}`}>{num(n.or_yoy)}</td>
              <td className="px-2 py-1.5 text-right text-muted">{num(n.gross_margin)}</td>
              <td className="px-2 py-1.5 text-right text-muted">{num(n.pe)}</td>
              <td className="px-2 py-1.5 text-right text-muted">{num(n.ps)}</td>
              <td className="px-2 py-1.5">
                <span className="px-1.5 py-0.5 rounded text-[11px]"
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

export default function HeatmapView({ h }: { h: Heatmap | undefined }) {
  if (!h) return <div className="text-muted p-4">暂无热力图数据</div>;
  const legend = [["核心主线", "叙事强+兑现好"], ["潜在补涨", "叙事强+兑现弱"],
                  ["等待验证", "叙事弱+兑现好"], ["风险区", "叙事弱+兑现弱"]];
  return (
    <div className="space-y-4">
      <div className="border hairline rounded bg-surface">
        <div className="flex items-center justify-between px-3 py-2 border-b hairline">
          <span className="text-[11px] text-muted uppercase tracking-wide">四象限 · 叙事强度 × 财报兑现(气泡=市值)</span>
          <div className="flex gap-3 text-[11px]">
            {legend.map(([q, d]) => (
              <span key={q} className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full inline-block" style={{ background: QUAD_COLOR[q] }} />
                <span className="text-muted">{q}</span><span className="text-dim">{d}</span>
              </span>
            ))}
          </div>
        </div>
        <div className="p-2"><Scatter nodes={h.nodes} /></div>
      </div>
      <div className="border hairline rounded bg-surface">
        <div className="px-3 py-2 border-b hairline text-[11px] text-muted uppercase tracking-wide">
          节点监控表 · {h.nodes.length} 节点(点表头排序)
        </div>
        <NodeTable nodes={h.nodes} />
      </div>
    </div>
  );
}
