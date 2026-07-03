import { useMemo, useState } from "react";
import type { UsBoard, UsBoardItem } from "./types";
import { useOpenStock } from "./stockCtx";
import { pctCls as pctColor } from "./ui";

const fmtPct = (v: number | null) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v}%`);
const fmtMc = (v: number | null) => (v == null ? "—" : v >= 1000 ? `${(v / 1000).toFixed(2)}T` : `${Math.round(v)}B`);

function Bar52({ p }: { p: number | null }) {
  if (p == null) return <span className="text-dim text-[13px]">—</span>;
  return (
    <div className="flex items-center gap-1 justify-end">
      <div className="w-14 h-1.5 bg-elevated rounded relative">
        <div className="absolute top-0 h-1.5 w-1 bg-accent rounded" style={{ left: `calc(${p}% - 2px)` }} />
      </div>
      <span className="text-dim text-[12px] w-6 text-right">{p}</span>
    </div>
  );
}

const HEAD = (
  <thead>
    <tr className="text-muted text-left text-[13px]">
      <th className="font-normal py-1">名称</th>
      <th className="font-normal">代码</th>
      <th className="font-normal text-right">收盘</th>
      <th className="font-normal text-right">涨跌</th>
      <th className="font-normal text-right">6M</th>
      <th className="font-normal text-right pr-1">52W位</th>
      <th className="font-normal text-right">市值</th>
      <th className="font-normal text-right">PE</th>
    </tr>
  </thead>
);

function Row({ it }: { it: UsBoardItem }) {
  const open = useOpenStock();
  return (
    <tr onClick={() => open({ code: it.ticker, name: it.name })} className="border-t hairline cursor-pointer hover:bg-elevated/40">
      <td className="py-1 text-primary">{it.name}</td>
      <td className="mono text-dim text-[13px]">{it.ticker}</td>
      <td className="text-right mono text-muted">{it.close ?? "—"}</td>
      <td className={`text-right mono ${pctColor(it.pct)}`}>{fmtPct(it.pct)}</td>
      <td className={`text-right mono ${pctColor(it.ret_6m)}`}>{fmtPct(it.ret_6m)}</td>
      <td className="text-right"><Bar52 p={it.pos_52w} /></td>
      <td className="text-right mono text-muted">{fmtMc(it.market_cap)}</td>
      <td className="text-right mono text-dim">{it.pe ?? "—"}</td>
    </tr>
  );
}

export function UsBoardView({ b }: { b: UsBoard | null | undefined }) {
  const [sort, setSort] = useState<"sector" | "pct" | "ret_6m">("sector");
  const items = b?.items || [];
  const stocks = useMemo(() => items.filter((i) => !i.ticker.startsWith("^")), [items]);
  const groups = useMemo(() => {
    const m: Record<string, UsBoardItem[]> = {};
    for (const it of stocks) (m[it.sector] ||= []).push(it);
    return Object.entries(m);
  }, [stocks]);
  const flat = useMemo(
    () => [...stocks].sort((a, c) => ((c as any)[sort] ?? -1e9) - ((a as any)[sort] ?? -1e9)),
    [stocks, sort],
  );

  if (!b || !items.length) {
    return (
      <div className="text-muted p-4 text-[15px]">
        美股板块暂无数据。<span className="text-dim">台北侧 fetch_us_board 未跑或未同步(盘前 08:30 自动刷新)。</span>
      </div>
    );
  }
  const idx = items.filter((i) => i.ticker.startsWith("^"));

  return (
    <div className="space-y-3 max-w-4xl">
      <div className="flex flex-wrap items-center gap-3 text-[14px]">
        <span className="text-muted">美东 {b.us_session_date} 收盘</span>
        <span className="text-dim text-[13px]">领先指标外盘 · 红涨绿跌</span>
        <div className="ml-auto flex gap-3">
          {idx.map((i) => (
            <span key={i.ticker} className="flex items-center gap-1">
              <span className="text-muted">{i.name}</span>
              <span className={`mono ${pctColor(i.pct)}`}>{fmtPct(i.pct)}</span>
            </span>
          ))}
        </div>
      </div>

      <div className="flex gap-1 text-[13px]">
        {([["sector", "按板块"], ["pct", "按涨跌"], ["ret_6m", "按6M动量"]] as const).map(([k, l]) => (
          <button key={k} onClick={() => setSort(k)}
            className={`px-2 py-0.5 rounded border ${sort === k ? "border-accent text-accent bg-accent/10" : "border-hairline text-muted hover:text-primary"}`}>
            {l}
          </button>
        ))}
      </div>

      {sort === "sector" ? (
        <div className="space-y-4">
          {groups.map(([sector, its]) => (
            <div key={sector}>
              <div className="flex items-center gap-2 mb-1 text-[14px]">
                <span className="w-0.5 h-3.5 bg-accent" />
                <span className="text-primary font-semibold">{sector}</span>
                <span className="text-dim">({its.length})</span>
              </div>
              <table className="w-full text-[14px]">{HEAD}<tbody>{its.map((it) => <Row key={it.ticker} it={it} />)}</tbody></table>
            </div>
          ))}
        </div>
      ) : (
        <table className="w-full text-[14px]">{HEAD}<tbody>{flat.map((it) => <Row key={it.ticker} it={it} />)}</tbody></table>
      )}
    </div>
  );
}
