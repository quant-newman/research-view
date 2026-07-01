import type { Health } from "./types";

const LEVEL_COLOR: Record<string, string> = { green: "#2EBD85", yellow: "#F0B90B", red: "#F6465D" };
const LEVEL_TEXT: Record<string, string> = { green: "全部正常", yellow: "有告警", red: "有失败" };

export function HealthDot({ level, onClick }: { level: string; onClick: () => void }) {
  return (
    <button onClick={onClick} className="flex items-center gap-1.5 text-[11px] hover:opacity-80" title="系统状态">
      <span className="w-2 h-2 rounded-full inline-block" style={{ background: LEVEL_COLOR[level] || "#5A6474" }} />
      <span className="text-dim">系统 {LEVEL_TEXT[level] || "—"}</span>
    </button>
  );
}

function Sec({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border hairline rounded bg-surface">
      <div className="px-3 py-2 border-b hairline text-[11px] text-muted uppercase tracking-wide">{title}</div>
      <div className="p-3">{children}</div>
    </div>
  );
}

export default function SystemView({ h }: { h: Health | undefined }) {
  if (!h) return <div className="text-muted p-4">暂无系统状态</div>;
  return (
    <div className="space-y-4 max-w-3xl">
      <div className="flex items-center gap-2">
        <span className="w-3 h-3 rounded-full inline-block" style={{ background: LEVEL_COLOR[h.level] }} />
        <span className="font-semibold">系统健康:{LEVEL_TEXT[h.level] || h.level}</span>
      </div>

      <Sec title="今日采集/生成任务">
        <table className="w-full text-[12px] mono">
          <thead><tr className="text-muted text-left">
            <th className="py-1 font-normal">任务</th><th className="font-normal">状态</th>
            <th className="font-normal text-right">记录</th><th className="font-normal text-right">耗时</th>
          </tr></thead>
          <tbody>
            {h.tasks.length === 0 && <tr><td colSpan={4} className="text-dim py-1">今日暂无任务记录</td></tr>}
            {h.tasks.map((t, i) => (
              <tr key={i} className="border-t hairline">
                <td className="py-1 text-primary">{t.task}</td>
                <td className={t.status === "失败" ? "text-up" : t.status === "部分成功" ? "text-accent" : "text-down"}>{t.status}</td>
                <td className="text-right text-muted">{t.count ?? "—"}</td>
                <td className="text-right text-dim">{t.duration_ms != null ? `${t.duration_ms}ms` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Sec>

      <Sec title="数据源新鲜度">
        <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-[12px] mono">
          {h.sources.map((s, i) => (
            <div key={i} className="flex items-center justify-between">
              <span className="text-muted">{s.name}</span>
              {s.pending ? (
                <span className="text-dim">◌ {s.latest}<span className="text-[10px] ml-1">待接入</span></span>
              ) : (
                <span className={s.stale ? "text-accent" : "text-dim"}>
                  {s.stale ? "⚠ " : ""}{s.latest}
                </span>
              )}
            </div>
          ))}
        </div>
      </Sec>

      <Sec title="数据质量存疑(标记而非丢弃)">
        {h.flags.length === 0
          ? <div className="text-dim text-[12px]">今日无存疑数据</div>
          : <div className="flex gap-3 text-[12px]">
              {h.flags.map((f, i) => (
                <span key={i} className="text-accent">{f.kind} <span className="mono">{f.count}</span></span>
              ))}
            </div>}
      </Sec>
    </div>
  );
}
