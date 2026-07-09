import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import type { Moneyflow, MfMultiNode, MfStock } from "./types";
import { useOpenStock } from "./stockCtx";
import { MoreList, pctCls } from "./ui";

// A股习惯:流入暖(红) / 流出冷(绿)
const UP = "#F6465D", DOWN = "#2EBD85";

// 推送订阅铃铛:盘中资金异动 Web Push 开关(订阅存 chat 容器 /api/push,发送在台北宿主)。
// iOS Safari 直开没有 PushManager,必须「添加到主屏幕」后从主屏幕打开——点击时给出指引。
function b64ToU8(s: string): Uint8Array<ArrayBuffer> {
  const pad = "=".repeat((4 - (s.length % 4)) % 4);
  const raw = atob((s + pad).replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}
function PushBell() {
  const [on, setOn] = useState<boolean | null>(null);  // null=未知/不支持
  const [busy, setBusy] = useState(false);
  const supported = "serviceWorker" in navigator && "PushManager" in window;
  useEffect(() => {
    if (!supported) return;
    navigator.serviceWorker.getRegistration()
      .then((reg) => reg?.pushManager.getSubscription())
      .then((sub) => setOn(!!sub)).catch(() => setOn(false));
  }, [supported]);
  const toggle = async () => {
    if (!supported) {
      alert("此浏览器不支持推送。iPhone 请先「分享 → 添加到主屏幕」,再从主屏幕图标打开后订阅(需 HTTPS)。");
      return;
    }
    setBusy(true);
    try {
      const reg = await navigator.serviceWorker.ready;
      const cur = await reg.pushManager.getSubscription();
      if (cur) {
        await cur.unsubscribe();
        await fetch("/api/push/unsubscribe", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ endpoint: cur.endpoint }) });
        setOn(false);
      } else {
        if ((await Notification.requestPermission()) !== "granted") { alert("通知权限被拒绝,请在浏览器设置里放行后重试。"); return; }
        const { key } = await (await fetch("/api/push/vapid-key")).json();
        const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToU8(key) });
        const r = await fetch("/api/push/subscribe", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(sub.toJSON()) });
        if (!r.ok) throw new Error(`subscribe ${r.status}`);
        setOn(true);
      }
    } catch (e) {
      alert(`推送订阅失败:${e}`);
    } finally { setBusy(false); }
  };
  return (
    <button onClick={toggle} disabled={busy}
      className={`px-2 py-0.5 rounded border hairline text-[13px] ${busy ? "text-dim" : on ? "text-accent" : "text-muted hover:text-primary"}`}
      title={on ? "已订阅盘中资金异动推送,点击退订" : "订阅盘中资金异动推送(15分钟主力净额异动,交易时段,日上限30条)"}>
      {on ? "🔔 推送已开" : "🔕 开启推送"}
    </button>
  );
}

// 流入(暖)/流出(冷)各一组色阶,同向多条线也能区分。色只编码方向(极性),
// 线的身份靠右端标注——各11阶已实测对暗底对比度全过(≥3:1),超出后循环可接受。
const WARM = ["#F6465D", "#FA8C16", "#F0B90B", "#E85D75", "#D4380D", "#FF7A45", "#C41D7F", "#AD6800",
              "#FFA39E", "#FFC53D", "#FF85C0"];
const COOL = ["#2EBD85", "#13C2C2", "#52C41A", "#36CFC9", "#389E0D", "#5CDBD3", "#1677FF", "#08979C",
              "#95DE64", "#69B1FF", "#A0D911"];

// 当日节点累计主力净额多线图:零轴居中,前N条全部右端标注"节点名+累计值"
// 且防重叠(labelLayout shiftY 自动错开);其余节点合并为一条灰虚线"其他合计"。
// chain 筛选后 y 轴自动缩放到该链量级,小链的线不再被大链压成地平线。
// 点击任意线 → 下钻该节点成分股。x 轴=实际采集时点(午休/未采样区间自然收拢)。
function FlowChart({ intraday, onPick, chain, topN }: {
  intraday: NonNullable<Moneyflow["intraday"]>; onPick: (nid: string) => void;
  chain: string | null; topN: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: "canvas" });
    const narrow = ref.current.clientWidth < 640;
    const TOP = topN;
    const pool = chain ? intraday.series.filter((s) => s.chain === chain) : intraday.series;
    const ranked = [...pool].filter((s) => Math.abs(s.last) >= 0.05)
      .sort((a, b) => Math.abs(b.last) - Math.abs(a.last));
    const shown = ranked.slice(0, TOP);
    const rest = ranked.slice(TOP);
    const dense = shown.length > 20;  // 前30/全部档:线变细字变小,靠图高自适应保标签不叠
    const restVals = intraday.times.map((_, i) =>
      Math.round(rest.reduce((acc, s) => acc + (s.values[i] ?? 0), 0) * 100) / 100);
    const restLast = restVals.length ? restVals[restVals.length - 1] : 0;
    const topAbs = Math.abs(ranked[0]?.last ?? 0);
    const maxAbs = Math.max(...shown.map((s) => Math.abs(s.last)), Math.abs(restLast), 1);
    let wi = 0, ci = 0;
    const series = shown.map((s) => {
      const color = s.last >= 0 ? WARM[wi++ % WARM.length] : COOL[ci++ % COOL.length];
      return {
        name: `${s.chain}/${s.node}`, type: "line" as const, data: s.values, connectNulls: true,
        symbol: "none", triggerLineEvent: true,
        lineStyle: { width: Math.abs(s.last) === topAbs ? 3 : dense ? 1.1 : 1.6, color, opacity: 0.95 },
        emphasis: { focus: "series" as const, lineStyle: { width: 3.2 } },
        labelLayout: { moveOverlap: "shiftY" as const },
        endLabel: {
          show: true, color, fontSize: narrow ? 9 : dense ? 10 : 11, distance: 5,
          formatter: () => `${s.node} ${s.last > 0 ? "+" : ""}${s.last}`,
        },
      };
    });
    if (rest.length) {
      series.push({
        name: `其他${rest.length}节点合计`, type: "line" as const, data: restVals, connectNulls: true,
        symbol: "none", triggerLineEvent: true,
        lineStyle: { width: 1, color: "#5A6474", opacity: 0.8, type: "dashed" } as never,
        emphasis: { focus: "series" as const, lineStyle: { width: 2 } },
        labelLayout: { moveOverlap: "shiftY" as const },
        endLabel: {
          show: true, color: "#5A6474", fontSize: narrow ? 9 : 11, distance: 5,
          formatter: () => `其他${rest.length}节点 ${restLast > 0 ? "+" : ""}${restLast}`,
        },
      });
    }
    chart.setOption({
      grid: { left: narrow ? 40 : 52, right: narrow ? 96 : 150, top: 18, bottom: 30 },
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
      series,
    });
    chart.on("click", (p) => {
      const s = shown[(p as { seriesIndex: number }).seriesIndex];
      if (s) onPick(s.node_id);  // "其他合计"线在 shown 之外,点击自然无操作
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("resize", onResize); chart.dispose(); };
  }, [intraday, onPick, chain, topN]);
  // 图高随线数自适应:前20以内维持原高(300/430)不变,更多线时每条留足端标签纵向空间
  // (10px标签+shiftY防叠需≥15px/线,全部75节点≈1335px,长图滚动是"全部"档的显式代价)
  const isNarrow = typeof window !== "undefined" && window.innerWidth < 640;
  const pool = chain ? intraday.series.filter((s) => s.chain === chain) : intraday.series;
  const nShown = Math.min(topN, pool.filter((s) => Math.abs(s.last) >= 0.05).length);
  const height = Math.min(1400, Math.max(isNarrow ? 300 : 430, nShown * (isNarrow ? 15 : 17) + 60));
  return <div ref={ref} style={{ height }} className="w-full" />;
}

// 曲线过滤器:产业链 chips(v3 后 9 链 76 节点,全混一图看不清)+ 前N条切换
function ChartFilters({ chains, chain, onChain, topN, onTopN }: {
  chains: string[]; chain: string | null; onChain: (c: string | null) => void;
  topN: number; onTopN: (n: number) => void;
}) {
  const chip = (on: boolean) =>
    `px-2 py-0.5 rounded border hairline ${on ? "bg-accent text-black font-semibold" : "text-muted hover:text-primary"}`;
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-[12px] mb-2">
      <button onClick={() => onChain(null)} className={chip(chain === null)}>全部链</button>
      {chains.map((c) => (
        <button key={c} onClick={() => onChain(chain === c ? null : c)} className={chip(chain === c)}>{c}</button>
      ))}
      <span className="ml-auto flex items-center gap-1.5">
        <span className="text-dim">显示</span>
        {[6, 12, 20, 30].map((n) => (
          <button key={n} onClick={() => onTopN(n)} className={chip(topN === n)}>前{n}</button>
        ))}
        <button onClick={() => onTopN(999)} className={chip(topN === 999)}>全部</button>
      </span>
    </div>
  );
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

export function MoneyflowView({ mf, isUS, onReload }: {
  mf?: Moneyflow | null; isUS: boolean; onReload?: () => Promise<void>;
}) {
  const openStock = useOpenStock();
  const [nid, setNid] = useState<string | null>(null);
  const [tab, setTab] = useState<"today" | "multi">("today");
  const [busy, setBusy] = useState(false);
  const [chain, setChain] = useState<string | null>(null);
  const [topN, setTopN] = useState(typeof window !== "undefined" && window.innerWidth < 640 ? 6 : 12);
  if (isUS) return <div className="text-muted p-4">资金面为 A股口径(主力=大单+超大单净额),请切回「A股」查看。</div>;
  if (!mf || !mf.nodes?.length) return <div className="text-muted p-4">暂无资金数据(交易日盘中/盘后生成)。</div>;

  const intraday = mf.intraday;
  const label = mf.kind === "eod" ? `${mf.date} 收盘` : `${mf.date} 盘中截至${mf.stamp || ""}`;
  // 严格按 node_id 匹配:参照层改版后旧id(历史曲线)查不到成分,绝不能错位回退到别的节点
  const sel = nid ? mf.nodes.find((n) => n.node_id === nid) ?? null : mf.nodes[0];
  const staleNid = nid != null && !mf.nodes.some((n) => n.node_id === nid);
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
        {/* 子页签:当日盘口 / 多日趋势(两套口径与截止日不同,分开看不混排) */}
        <div className="flex rounded overflow-hidden border hairline text-[13px]">
          {([["today", "当日盘口"], ["multi", "多日趋势"]] as const).map(([k, l]) => (
            <button key={k} onClick={() => setTab(k)}
              className={`px-2.5 py-0.5 ${tab === k ? "bg-accent text-black font-semibold" : "text-muted hover:text-primary"}`}>
              {l}
            </button>
          ))}
        </div>
        {onReload && (
          <button disabled={busy}
            onClick={() => { setBusy(true); onReload().finally(() => setBusy(false)); }}
            className={`px-2 py-0.5 rounded border hairline text-[13px] ${busy ? "text-dim" : "text-muted hover:text-primary"}`}
            title="重新拉取看板数据(盘中资金曲线每5分钟更新)">
            {busy ? "刷新中…" : "↻ 刷新"}
          </button>
        )}
        <PushBell />
        {tab === "today" && <span className="text-dim">{label} · 核心池合计 <span className={`mono ${pctCls(mf.pool_main)}`}>{mf.pool_main > 0 ? "+" : ""}{mf.pool_main}亿</span></span>}
        {tab === "multi" && mf.multi && <span className="text-dim">EOD 截至 {mf.multi.asof}</span>}
        <span className="text-dim text-[12px] ml-auto hidden lg:inline">主力=大单+超大单净额 · 口径=全部产业链节点 · 只呈现事实不下判断</span>
      </div>

      {tab === "today" && (<>
      {/* 盘中个股资金异动:15分钟主力净额变动 ≥ max(0.3亿, 20日日均成交额×2%),点击开个股详情 */}
      {mf.alerts && mf.alerts.items.length > 0 && (
        <div className="border hairline rounded bg-surface p-3">
          <div className="text-[13px] text-muted mb-1.5">
            盘中资金异动 · {mf.alerts.date}
            <span className="text-dim ml-2 hidden sm:inline">15分钟主力净额变动超过该票日常体量(max(0.3亿, 20日日均成交2%)) · 同票同向1小时最多报一次</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {mf.alerts.items.slice(0, 40).map((a, i) => (
              <button key={i} onClick={() => openStock({ code: a.code })}
                className="flex items-center gap-1.5 border hairline rounded px-2 py-1 text-[13px] hover:bg-elevated">
                <span className="mono text-dim text-[12px]">{a.hhmm}</span>
                <span className="text-primary">{a.name}</span>
                <span className={`mono ${pctCls(a.delta)}`}>{a.delta > 0 ? "+" : ""}{a.delta}亿</span>
                {a.ratio != null && <span className="text-dim text-[12px]">≈日均{Math.round(a.ratio * 1000) / 10}%</span>}
              </button>
            ))}
          </div>
        </div>
      )}
      {/* 当日累计曲线(15min 采集节奏;部署当日为小时桶种子,次一交易日起自然积累) */}
      {intraday && intraday.times.length > 1 ? (
        <div className="border hairline rounded bg-surface p-3">
          <div className="text-[13px] text-muted mb-1">当日累计净流入曲线 · {intraday.date} · 点击线条下钻成分股</div>
          <ChartFilters
            chains={[...new Set(intraday.series.map((s) => s.chain))]}
            chain={chain} onChain={setChain} topN={topN} onTopN={setTopN} />
          <FlowChart intraday={intraday} onPick={setNid} chain={chain} topN={topN} />
        </div>
      ) : (
        <div className="border hairline rounded bg-surface p-4 text-dim text-[14px]">
          盘中累计曲线自下一交易日开始积累(每 15 分钟一个点,随盘中刷新生长)。
        </div>
      )}
      </>)}

      {tab === "multi" && (
        mf.multi && mf.multi.nodes.length > 0 ? (
        <div className="border hairline rounded bg-surface p-3">
          <div className="text-[13px] text-dim leading-relaxed mb-2 border-b hairline pb-2">
            <span className="text-muted">怎么读:</span>主力净额(大单+超大单)口径<span className="text-muted">结构性偏净流出</span>——主力卖出常用大单、买入常拆成中小单,全市场多数交易日为负
            {mf.multi.market && <>(基准:全市场5日 <span className={`mono ${pctCls(mf.multi.market.d5)}`}>{mf.multi.market.d5 > 0 ? "+" : ""}{mf.multi.market.d5}亿</span>)</>}。
            看<span className="text-muted">相对强弱与方向变化</span>,不是绝对买卖量。<span className="text-accent">⚠背离</span>=近一周涨跌与5日资金方向相反。
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
                <MultiRows nodes={mf.multi.nodes} onPick={(n) => { setNid(n); setTab("today"); }} />
              </tbody>
            </table>
          </div>
        </div>
        ) : <div className="border hairline rounded bg-surface p-4 text-dim text-[14px]">多日数据生成中(盘后落地)。</div>
      )}

      {tab === "today" && (
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
          {staleNid && (
            <div className="border hairline rounded bg-surface p-3 text-[13px] text-dim leading-relaxed">
              该曲线属参照层旧版本节点(已重组,如机器人链 07-04 起 7→14 细分)。历史曲线保留作事实记录,
              成分股请在左侧节点排行选择新节点;下一交易日起曲线按新结构生长。
            </div>
          )}
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
      )}
    </div>
  );
}
