import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { clampPage, pageSlice, totalPages, PER_PAGE } from "./reflectionsPaging";

// 使用者周度复盘(公开面):进入本页才 fetch reflections.json,不进 App 首屏。
// 只展示后端已按 visibility=public + 当前叶子过滤后的数据,前端零可见性判断。
type Reflection = {
  reflection_id: number;
  week_end: string;
  title: string;
  content_md: string;
  content_sha256: string;
  source_filename: string | null;
  authored_at: string;
  recorded_at: string;
  version_no: number;
};

// Markdown 安全边界:react-markdown 默认不渲染 raw HTML(无 rehype-raw,原始标签
// 一律不进 DOM),无脚本执行面;外链统一补安全属性。
const mdComponents = {
  a: (props: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props} target="_blank" rel="noopener noreferrer nofollow" className="text-accent underline" />
  ),
};

function ReflectionItem({ r }: { r: Reflection }) {
  const [open, setOpen] = useState(false); // 默认折叠;展开=完整正文,不做 slice 截断
  return (
    <div className="border hairline rounded bg-surface">
      <button onClick={() => setOpen(!open)}
        className="w-full text-left px-4 py-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[15px] text-primary font-medium">{r.title}</div>
          <div className="text-[12px] text-muted mt-0.5">
            周截止 {r.week_end} · 写于 {r.authored_at} · 录入 {r.recorded_at} · v{r.version_no}
          </div>
        </div>
        <span className="text-[12px] text-dim shrink-0 mt-1">{open ? "收起 ▲" : "展开 ▼"}</span>
      </button>
      {open && (
        <div className="px-4 pb-4 border-t hairline pt-3 md-body text-[14px] leading-relaxed">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
            {r.content_md}
          </ReactMarkdown>
        </div>
      )}
    </div>
  );
}

export function ReflectionsView() {
  const [items, setItems] = useState<Reflection[] | null>(null); // null=加载中
  const [err, setErr] = useState("");
  const [page, setPage] = useState(1);

  const load = useCallback(() => {
    setErr("");
    setItems(null);
    fetch("/data/reflections.json", { cache: "no-store" })
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((j) => setItems(Array.isArray(j?.reflections) ? j.reflections : []))
      .catch((e) => setErr(String(e))); // 失败只影响本页,不碰全站
  }, []);
  useEffect(() => { load(); }, [load]);

  if (err) {
    return (
      <div className="flex-1 p-3 md:p-5 overflow-auto">
        <div className="text-down text-[14px]">复盘数据加载失败：{err}</div>
        <button onClick={load} className="mt-3 px-3 py-1.5 border hairline rounded text-[13px] text-primary hover:bg-elevated">重试</button>
      </div>
    );
  }
  if (items === null) return <div className="flex-1 p-6 text-muted">加载中…</div>;
  if (items.length === 0) return <div className="flex-1 p-6 text-muted">暂无公开复盘</div>;

  const total = items.length;
  const tp = totalPages(total);
  const cur = clampPage(page, total); // 数据缩减致越界 → 自动回合法页
  const { start, end } = pageSlice(cur, total);

  return (
    <div className="flex-1 p-3 md:p-5 overflow-auto space-y-3">
      <div className="text-[13px] text-muted">
        使用者周度复盘 · 共 {total} 篇 · 第 {cur}/{tp} 页(每页 {PER_PAGE} 篇,最新在前)
      </div>
      {items.slice(start, end).map((r) => <ReflectionItem key={r.reflection_id} r={r} />)}
      {tp > 1 && (
        <div className="flex items-center gap-3 pt-2 text-[13px]">
          <button disabled={cur <= 1} onClick={() => setPage(cur - 1)}
            className="px-3 py-1 border hairline rounded disabled:opacity-40 text-primary hover:bg-elevated">上一页</button>
          <span className="text-muted">{cur} / {tp}</span>
          <button disabled={cur >= tp} onClick={() => setPage(cur + 1)}
            className="px-3 py-1 border hairline rounded disabled:opacity-40 text-primary hover:bg-elevated">下一页</button>
        </div>
      )}
    </div>
  );
}
