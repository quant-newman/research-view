import { useMemo, useState } from "react";
import type { UsResearchItem } from "./types";

const recColor = (r: string | null) => {
  if (!r) return "text-muted bg-muted/10";
  if (/strong_buy|buy/.test(r)) return "text-up bg-up/10";
  if (/sell|underperform/.test(r)) return "text-down bg-down/10";
  return "text-muted bg-muted/10";
};
const recLabel: Record<string, string> = {
  strong_buy: "强烈买入", buy: "买入", hold: "持有", underperform: "跑输", sell: "卖出",
};

export function UsResearchView({ items }: { items: UsResearchItem[] | undefined }) {
  const [sort, setSort] = useState<"upside" | "n_analysts">("upside");
  const rows = useMemo(
    () => [...(items || [])].sort((a, b) => ((b[sort] ?? -1e9) as number) - ((a[sort] ?? -1e9) as number)),
    [items, sort],
  );
  if (!items || !items.length) return <div className="text-muted p-4">美股分析师数据暂无。</div>;
  return (
    <div className="max-w-4xl space-y-3">
      <div className="flex items-center gap-2 text-[12px]">
        <span className="text-muted">分析师一致预期 · {items.length} 只</span>
        <span className="text-dim text-[11px]">目标价共识 / 评级 / 覆盖分析师数(客观事实,非本系统判断)</span>
        <div className="ml-auto flex gap-1 text-[11px]">
          {([["upside", "按上行空间"], ["n_analysts", "按覆盖数"]] as const).map(([k, l]) => (
            <button key={k} onClick={() => setSort(k)}
              className={`px-2 py-0.5 rounded border ${sort === k ? "border-accent text-accent bg-accent/10" : "border-hairline text-muted hover:text-primary"}`}>{l}</button>
          ))}
        </div>
      </div>
      <table className="w-full text-[12px]">
        <thead>
          <tr className="text-muted text-left text-[11px]">
            <th className="py-1 font-normal">名称</th><th className="font-normal">代码</th>
            <th className="font-normal">板块</th><th className="font-normal text-right">目标均价</th>
            <th className="font-normal text-right">上行空间</th><th className="font-normal">评级</th>
            <th className="font-normal text-right">分析师</th><th className="font-normal text-right">PE</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.code} className="border-t hairline">
              <td className="py-1 text-primary">{r.name}</td>
              <td className="mono text-dim text-[11px]">{r.code}</td>
              <td className="text-muted text-[11px]">{r.sector}</td>
              <td className="text-right mono text-muted">{r.target_mean ?? "—"}</td>
              <td className={`text-right mono ${r.upside == null ? "text-dim" : r.upside > 0 ? "text-up" : "text-down"}`}>
                {r.upside == null ? "—" : `${r.upside > 0 ? "+" : ""}${r.upside}%`}
              </td>
              <td>
                {r.rec_key && <span className={`px-1.5 py-0.5 rounded text-[11px] ${recColor(r.rec_key)}`}>{recLabel[r.rec_key] || r.rec_key}</span>}
              </td>
              <td className="text-right mono text-dim">{r.n_analysts ?? "—"}</td>
              <td className="text-right mono text-dim">{r.pe ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
