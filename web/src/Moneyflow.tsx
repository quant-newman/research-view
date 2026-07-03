import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import type { Moneyflow, MfMultiNode, MfStock } from "./types";
import { useOpenStock } from "./stockCtx";
import { MoreList, pctCls } from "./ui";

// A股习惯:流入暖(红) / 流出冷(绿)
const UP = "#F6465D", DOWN = "#2EBD85";

// 当日节点累计主力净额多线图:零轴居中,终值前8高亮+右端标签(名称+累计值),其余细灰线。
// 点击任意线 → 下钻该节点成分股。x 轴=实际采集时点(午休/未采样区间自然收拢)。
function FlowChart({ intraday, onPick }: {
  intraday: NonNullable<Moneyflow["intraday"]>; onPick: (nid: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: "canvas" });
    const narrow = ref.current.clientWidth < 640;  // 手机:右端标签收窄、高亮少给几条
    const sers = intraday.series.filter((s) => Math.abs(s.last) >= 0.05);
    const ranked = [...sers].sort((a, b) => Math.abs(b.last) - Math.abs(a.last));
    const hot = new Set(ranked.slice(0, narrow ? 5 : 8).map((s) => s.node_id));
    const topAbs = Math.abs(ranked[0]?.last ?? 0);
    const maxAbs = Math.max(...sers.map((s) => Math.abs(s.last)), 1);
    chart.setOption({
      grid: { left: narrow ? 40 : 52, right: narrow ? 88 : 140, top: 18, bottom: 30 },
      xAxis: {
        type: "category", data: intraday.times, boundaryGap: false,
        axisLabel: { color: "#8A93A6", fontSize: 11 }, axisLine: { lineStyle: { color: "#2A3040" } },
      },
      yAxis: {
        type: "value", max: Math.ceil(maxAbs * 1.1), min: -Math.ceil(maxAbs * 1.1),
        axisLabel: { color: "#8A93A6", fontSize: 11, formatter: "{value}亿" },
        splitLine: { lineStyle: { color: "#1E2430" } },
      },
      tooltip: {
        trigger: "item", backgroundColor: "#161B26", borderColor: "#2A3040",
        textStyle: { color: "#E8ECF4", fontSize: 12 },
        formatter: (p: { seriesName: string; dataIndex: number; value: number }) =>
          `${p.seriesName}<br/>${intraday.times[p.dataIndex]} 累计 <b>${p.value > 0 ? "+" : ""}${p.value}亿</b>`,
      },
      series: sers.map((s) => {
        const isHot = hot.has(s.node_id);
        const color = s.last >= 0 ? UP : DOWN;
        return {
          name: `${s.chain}/${s.node}`, type: "line", data: s.values, connectNulls: true,
          symbol: "none", triggerLineEvent: true,
          lineStyle: {
            width: isHot ? (Math.abs(s.last) === topAbs ? 3 : 1.8) : 0.8,
            color: isHot ? color : "#3A4254", opacity: isHot ? 0.95 : 0.55,
          },
          emphasis: { focus: "series", lineStyle: { width: 3 } },
          endLabel: isHot ? {
            show: true, color, fontSize: narrow ? 9 : 11, distance: 4,
            formatter: () => `${s.node} ${s.last > 0 ? "+" : ""}${s.last}`,
          } : undefined,
        };
      }),
    });
    chart.on("click", (p) => {
      const s = sers[(p as { seriesIndex: number }).seriesIndex];
      if (s) onPick(s.node_id);
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("resize", onResize); chart.dispose(); };
  }, [intraday, onPick]);
  return <div ref={ref} className="w-full h-[300px] md:h-[430px]" />;
}

// 多日资金表行:按|5日|排序前N,背离行加 ⚠ 琥珀标;点节点名下钻成分股
function MultiRows({ nodes, onPick }: { nodes: MfMultiNode[]; onPick: (nid: string) => void }) {
  const [open, setOpen] = useState(false);
  const ranked = [...nodes].sort((a, b) => Math.abs(b.d5) - Math.abs(a.d5))
    .filter((g) => Math.abs(g.d5) >= 0.1 || Math.abs(g.d20) >= 0.5);
  const shown = open ? ranked : ranked.slice(0, 10);
  const v = (x: number) => `${x > 0 ? "+" : ""}${x}`;
  return (
    <>
      {shown.map((g) => (
        <tr key={g.node_id} className="border-t hairline">
          <td className="py-1">
            <button onClick={() => onPick(g.node_id)} className="text-primary hover:text-accent text-left">
              {g.chain}/{g.node}{g.divergence && <span className="text-accent ml-1">⚠背离</span>}
            </button>
          </td>
          <td className={`text-right ${pctCls(g.d5)}`}>{v(g.d5)}亿</td>
          <td className={`text-right ${pctCls(g.d20)}`}>{v(g.d20)}亿</td>
          <td className={`text-right ${g.streak > 0 ? "text-up" : g.streak < 0 ? "text-down" : "text-dim"}`}>
            {Math.abs(g.streak) >= 2 ? `${Math.abs(g.streak)}日${g.streak > 0 ? "流入" : "流出"}` : "—"}
          </td>
          <td className={`text-right ${pctCls(g.ret_1w)}`}>{g.ret_1w != null ? `${v(g.ret_1w)}%` : "—"}</td>
        </tr>
      ))}
      {ranked.length > 10 && (
        <tr><td colSpan={5}>
          <button onClick={() => setOpen(!open)} className="text-info text-[13px] py-1 hover:underline">
            {open ? "收起 ▴" : `展开剩余 ${ranked.length - 10} 个节点 ▾`}
          </button>
        </td></tr>
      )}
    </>
  );
}

function StockRow({ s, onOpen }: { s: MfStock; onOpen: () => void }) {
  return (
    <button onClick={onOpen} className="flex items-center gap-2 w-full text-left py-1 border-t hairline hover:bg-elevated/40 text-[14px]">
      <span className="text-primary w-28 truncate">{s.name}</span>
      <span className="mono text-dim text-[12px]">{s.code}</span>
      <span className={`mono ml-auto ${pctCls(s.main)}`}>{s.main > 0 ? "+" : ""}{s.main}亿</span>
    </button>
  );
}

export function MoneyflowView({ mf, isUS }: { mf?: Moneyflow | null; isUS: boolean }) {
  const openStock = useOpenStock();
  const [nid, setNid] = useState<string | null>(null);
  if (isUS) return <div className="text-muted p-4">资金面为 A股口径(主力=大单+超大单净额),请切回「A股」查看。</div>;
  if (!mf || !mf.nodes?.length) return <div className="text-muted p-4">暂无资金数据(交易日盘中/盘后生成)。</div>;

  const intraday = mf.intraday;
  const label = mf.kind === "eod" ? `${mf.date} 收盘` : `${mf.date} 盘中截至${mf.stamp || ""}`;
  const sel = mf.nodes.find((n) => n.node_id === nid) || mf.nodes[0];
  // 全池个股(members 跨节点去重;多节点票取任一,net额相同)
  const seen = new Set<string>();
  const allStocks: MfStock[] = [];
  for (const n of mf.nodes) for (const s of n.members || []) {
    if (!seen.has(s.code)) { seen.add(s.code); allStocks.push(s); }
  }
  allStocks.sort((a, b) => b.main - a.main);

  return (
    <div className="space-y-5 max-w-6xl">
      <div className="flex flex-wrap items-center gap-3 text-[14px]">
        <span className="text-primary font-semibold text-[16px]">资金面 · 产业链节点主力净额</span>
        <span className="text-dim">{label}</span>
        <span className="text-dim">核心池合计 <span className={`mono ${pctCls(mf.pool_main)}`}>{mf.pool_main > 0 ? "+" : ""}{mf.pool_main}亿</span></span>
        <span className="text-dim text-[12px] ml-auto">主力=大单+超大单净额 · 口径=48产业链节点 · 只呈现事实不下判断</span>
      </div>

      {/* 当日累计曲线(15min 采集节奏;部署当日为小时桶种子,次一交易日起自然积累) */}
      {intraday && intraday.times.length > 1 ? (
        <div className="border hairline rounded bg-surface p-3">
          <div className="text-[13px] text-muted mb-1">当日累计净流入曲线 · {intraday.date} · 点击线条下钻成分股</div>
          <FlowChart intraday={intraday} onPick={setNid} />
        </div>
      ) : (
        <div className="border hairline rounded bg-surface p-4 text-dim text-[14px]">
          盘中累计曲线自下一交易日开始积累(每 15 分钟一个点,随盘中刷新生长)。
        </div>
      )}

      {/* 多日资金:5/20日累计 + 连续天数 + 资金×涨幅背离(EOD口径,与当日截面互补) */}
      {mf.multi && mf.multi.nodes.length > 0 && (
        <div className="border hairline rounded bg-surface p-3">
          <div className="text-[13px] text-muted mb-2">
            多日资金 · 截至 {mf.multi.asof}(EOD)· <span className="text-accent">⚠背离</span>=近一周涨跌与5日资金方向相反
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-[14px] mono">
              <thead><tr className="text-muted text-left text-[12px]">
                <th className="py-1 font-normal">节点</th>
                <th className="font-normal text-right">5日</th>
                <th className="font-normal text-right">20日</th>
                <th className="font-normal text-right">连续</th>
                <th className="font-normal text-right">周涨跌</th>
              </tr></thead>
              <tbody>
                <MultiRows nodes={mf.multi.nodes} onPick={setNid} />
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-[1.2fr_1fr] gap-5">
        {/* 节点排行 → 点击下钻 */}
        <div className="border hairline rounded bg-surface p-3">
          <div className="text-[13px] text-muted mb-2">节点排行(点击看成分股)</div>
          <MoreList items={mf.nodes.filter((n) => Math.abs(n.main) >= 0.05)} initial={16}>
            {(n) => (
              <button key={n.node_id} onClick={() => setNid(n.node_id)}
                className={`flex items-center gap-2 w-full text-left py-1 border-t hairline text-[14px] hover:bg-elevated/40 ${sel?.node_id === n.node_id ? "bg-elevated/50" : ""}`}>
                <span className="text-primary truncate">{n.chain}/{n.node}</span>
                <span className="text-dim text-[12px]">{n.n}只</span>
                <span className={`mono ml-auto ${pctCls(n.main)}`}>{n.main > 0 ? "+" : ""}{n.main}亿</span>
              </button>
            )}
          </MoreList>
        </div>

        {/* 选中节点成分股 + 全池个股 */}
        <div className="space-y-5">
          {sel && (
            <div className="border hairline rounded bg-surface p-3">
              <div className="text-[13px] text-muted mb-2">
                {sel.chain}/{sel.node} 成分资金 <span className={`mono ${pctCls(sel.main)}`}>{sel.main > 0 ? "+" : ""}{sel.main}亿</span>
              </div>
              {(sel.members || []).map((s) => (
                <StockRow key={s.code} s={s} onOpen={() => openStock({ code: s.code, name: s.name })} />
              ))}
            </div>
          )}
          <div className="border hairline rounded bg-surface p-3">
            <div className="text-[13px] text-muted mb-2">全池个股主力净额</div>
            <MoreList items={allStocks} initial={15}>
              {(s) => <StockRow key={s.code} s={s} onOpen={() => openStock({ code: s.code, name: s.name })} />}
            </MoreList>
          </div>
        </div>
      </div>
    </div>
  );
}
