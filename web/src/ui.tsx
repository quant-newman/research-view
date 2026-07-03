import { useState } from "react";

// ── 全站共享色映射(单点,勿在各页复制)────────────────────────────
// 涨跌色(A股红涨绿跌硬约束):null/undefined → text-dim
export const pctCls = (v: number | null | undefined) =>
  v == null ? "text-dim" : v > 0 ? "text-up" : v < 0 ? "text-down" : "text-muted";
export const sentColor: Record<string, string> = {
  利好: "text-up bg-up/10", 利空: "text-down bg-down/10",
  中性: "text-muted bg-muted/10", 澄清: "text-info bg-info/10",
};
export const sentDot: Record<string, string> = { 利好: "bg-up", 利空: "bg-down", 中性: "bg-muted", 澄清: "bg-info" };
export const sentTx: Record<string, string> = { 利好: "text-up", 利空: "text-down", 中性: "text-muted", 澄清: "text-info" };

export function Badge({ text, cls }: { text: string; cls: string }) {
  return <span className={`px-1.5 py-0.5 rounded text-[13px] ${cls}`}>{text}</span>;
}

// 时间统一显示到小时:"YYYY-MM-DD HH:MM" → "MM-DD HH时"。解析失败/空则不显示。
export function timeHour(t?: string): string {
  if (!t) return "";
  const m = t.match(/\d{4}-(\d{2})-(\d{2})[ T](\d{2}):\d{2}/);
  return m ? `${m[1]}-${m[2]} ${m[3]}时` : "";
}

// 陈旧数据角标:回退显示旧数据时提示"数据截至 X"(琥珀色,与"待审定"同色系)
export function StaleBadge({ date, label = "数据截至" }: { date?: string; label?: string }) {
  if (!date) return null;
  return (
    <span className="px-1.5 py-0.5 rounded text-[12px] bg-accent/10 text-accent whitespace-nowrap">
      ⏳ {label} {date}
    </span>
  );
}

// 可折叠区块:标题(带条数)点击展开/收起
export function Section({ title, count, defaultOpen = true, right, children }:
  { title: string; count?: number; defaultOpen?: boolean; right?: React.ReactNode; children: React.ReactNode }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border hairline rounded-md bg-surface">
      <div className="flex items-center gap-2 px-4 py-2.5">
        <button type="button" onClick={() => setOpen(!open)} className="flex items-center gap-2 text-[13px] text-muted hover:text-primary">
          <span className={`text-dim transition-transform ${open ? "rotate-90" : ""}`}>▸</span>
          <span className="w-1 h-1 rounded-full bg-accent/70" />
          <span className="font-medium">{title}</span>
          {count != null && <span className="text-dim mono">{count}</span>}
        </button>
        {right && <div className="ml-auto">{right}</div>}
      </div>
      {open && <div className="px-4 pb-4 border-t hairline pt-3">{children}</div>}
    </div>
  );
}

// 长列表折叠:先显 initial 条 + "展开剩余 N 条"
export function MoreList<T,>({ items, initial = 6, children }:
  { items: T[]; initial?: number; children: (item: T, i: number) => React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const shown = open ? items : items.slice(0, initial);
  return (
    <>
      {shown.map((it, i) => children(it, i))}
      {items.length > initial && (
        <button onClick={() => setOpen(!open)} className="text-info text-[13px] mt-2 hover:underline">
          {open ? "收起 ▴" : `展开剩余 ${items.length - initial} 条 ▾`}
        </button>
      )}
    </>
  );
}
