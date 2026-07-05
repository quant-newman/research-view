import type { Dashboard, DecisionBlock, DecisionCard, JudgmentBlock, JudgmentCard, Scorecard } from "./types";
import { useOpenStock } from "./stockCtx";
import { Badge, MoreList, StaleBadge, pctCls } from "./ui";

// —— 研判页:B6 节点研判 + B8 个股决策 + B7 成绩单(从报告页拆出,报告页回归纯事实层) ——

const dirBadge: Record<string, string> = {
  偏多: "bg-up/10 text-up", 偏空: "bg-down/10 text-down", 中性: "bg-elevated text-dim",
};
const zCls = (z: number) =>
  Math.abs(z) < 1 ? "text-dim" : z > 0 ? "text-up" : "text-down";

// —— B6 节点研判卡(六源共振,方向判断可追责,5日窗口进 B7 记分) ——
function CardRow({ c }: { c: JudgmentCard }) {
  const m = c.matrix || {};
  const zs: [string, number | undefined][] = [
    ["新闻", m.news?.z], ["资金", m.mf?.z], ["行情", m.price?.z],
    ["龙虎榜", m.lhb?.z], ["研报", m.research?.z],
  ];
  return (
    <div className="border hairline rounded bg-surface px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`px-1.5 py-0.5 rounded text-[12px] font-medium ${dirBadge[c.direction] || dirBadge.中性}`}>
          {c.direction}
        </span>
        <span className="text-primary text-[14px] font-semibold">{c.chain}/{c.node}</span>
        {c.confidence && <span className="text-dim text-[12px]">置信{c.confidence}</span>}
        <span className={`mono text-[12px] ${zCls(c.resonance ?? 0)}`}>共振{(c.resonance ?? 0) > 0 ? "+" : ""}{c.resonance}</span>
        <span className="text-dim text-[12px]">同向{c.n_agree}/激活{c.n_active}源</span>
        {c.divergence.length > 0 && (
          <Badge text={`⚠背离 ${c.divergence.map((d) => d.pair).join("、")}`} cls="bg-accent/10 text-accent" />
        )}
      </div>
      <p className="text-primary text-[14px] leading-relaxed mt-1.5">{c.thesis}</p>
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1.5 text-[12px] mono">
        {zs.map(([name, z]) => z != null && (
          <span key={name} className={zCls(z)}>{name}{z > 0 ? "+" : ""}{z.toFixed(1)}</span>
        ))}
        {m.letter?.hit && <span className="text-info">信函命中</span>}
      </div>
      {c.evidence.length > 0 && (
        <ul className="mt-1.5 space-y-0.5">
          {c.evidence.map((e, i) => (
            <li key={i} className="text-[13px] text-muted leading-snug">
              <span className="text-dim">[{e.src}]</span> {e.fact}
            </li>
          ))}
        </ul>
      )}
      {c.scenarios.map((s, i) => (
        <p key={i} className="text-[13px] text-muted mt-1 leading-snug">
          {s.cond && <span>{s.cond}{s.expect ? `,${s.expect}` : ""} </span>}
          {s.falsify && <span className="text-down">证伪:{s.falsify}</span>}
        </p>
      ))}
    </div>
  );
}

function JudgmentCards({ jb }: { jb: JudgmentBlock | null | undefined }) {
  if (!jb || jb.cards.length === 0) return null;
  return (
    <section>
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <div className="w-0.5 h-4 bg-accent" />
        <h2 className="font-semibold">节点研判 · 六源共振</h2>
        <span className="text-dim text-[12px]">方向=未来5交易日相对全池 · 判断留痕记分</span>
        {jb.fallback && <StaleBadge date={jb.date} label="今日研判未生成 · 显示" />}
      </div>
      <div className="space-y-2">
        <MoreList items={jb.cards} initial={5}>
          {(c) => <CardRow key={c.card_id} c={c} />}
        </MoreList>
      </div>
    </section>
  );
}

// —— B8 个股决策卡(影子运行=校准期:每张卡进 B7 记分,首份引擎成绩单前仅供观察) ——
function DecisionRow({ c }: { c: DecisionCard }) {
  const open = useOpenStock();
  return (
    <div className="border hairline rounded bg-surface px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`px-1.5 py-0.5 rounded text-[12px] font-medium ${dirBadge[c.direction] || dirBadge.中性}`}>
          {c.direction === "中性" ? "放弃" : c.direction}
        </span>
        <button onClick={() => open({ code: c.code, name: c.name })}
          className="text-primary text-[14px] font-semibold hover:text-accent">
          {c.name} <span className="mono text-muted text-[12px]">{c.code}</span>
        </button>
        {c.confidence && <span className="text-dim text-[12px]">置信{c.confidence}</span>}
        <span className={`mono text-[12px] ${zCls(c.alignment ?? 0)}`}>对齐{(c.alignment ?? 0) > 0 ? "+" : ""}{c.alignment}</span>
        {c.chain && <span className="text-dim text-[12px]">▸{c.chain}/{c.node}</span>}
        {c.close != null && <span className="mono text-dim text-[12px] ml-auto">现价{c.close}</span>}
      </div>
      <p className="text-primary text-[14px] leading-relaxed mt-1.5">{c.thesis}</p>
      {(c.entry || c.exit) && (
        <div className="mt-1.5 space-y-0.5 text-[13px]">
          {c.entry && <p className="text-muted"><span className="text-up">入场：</span>{c.entry}</p>}
          {c.exit && <p className="text-muted"><span className="text-accent">退出/止损：</span>{c.exit}</p>}
        </div>
      )}
      {c.falsify && (
        <p className="text-[13px] text-muted mt-1"><span className="text-down">证伪：</span>{c.falsify}</p>
      )}
      {c.evidence.length > 0 && (
        <ul className="mt-1.5 space-y-0.5">
          {c.evidence.map((e, i) => (
            <li key={i} className="text-[13px] text-muted leading-snug">
              <span className="text-dim">[{e.src}]</span> {e.fact}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function DecisionCards({ db }: { db: DecisionBlock | null | undefined }) {
  if (!db || db.cards.length === 0) return null;
  return (
    <section className="border-t hairline pt-4">
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <div className="w-0.5 h-4 bg-accent" />
        <h2 className="font-semibold">个股决策 · B8</h2>
        <span className="text-dim text-[12px]">板块方向卡→成分共振 · 每张卡进 B7 记分</span>
        {db.fallback && <StaleBadge date={db.date} label="今日决策卡未生成 · 显示" />}
      </div>
      <div className="border border-accent/40 bg-accent/5 rounded px-3 py-2 mb-2 text-[13px] text-accent">
        ⚠ 校准期(影子运行)：引擎命中率尚无战绩验证——首份 B7 成绩单出炉前，以下输出仅供观察，不构成操作依据。
      </div>
      <div className="space-y-2">
        <MoreList items={db.cards} initial={5}>
          {(c) => <DecisionRow key={c.card_id} c={c} />}
        </MoreList>
      </div>
    </section>
  );
}

// B7 成绩单:研判卡到期按"5交易日相对全池超额"自动记分,命中率/分源归因/教训对错都晒
const SRC_CN: Record<string, string> = { news: "新闻", mf: "资金", price: "行情", lhb: "龙虎榜", letter: "信函" };
const vBadge: Record<string, string> = { 对: "text-up bg-up/10", 错: "text-down bg-down/10", 平: "text-dim bg-elevated" };

function ScorecardPanel({ sc }: { sc: Scorecard }) {
  const srcRows = Object.entries(sc.by_source || {}).filter(([, v]) => v.n > 0);
  return (
    <div className="space-y-2.5 text-[14px]">
      <div className="flex items-center gap-3 flex-wrap">
        {sc.cum.hit_rate != null ? (
          <span className="text-primary font-semibold">命中率 {sc.cum.hit_rate}%</span>
        ) : (
          <span className="text-dim">暂无到期记分</span>
        )}
        <span className="text-up">对 {sc.cum.right}</span>
        <span className="text-down">错 {sc.cum.wrong}</span>
        <span className="text-dim">平 {sc.cum.flat}</span>
        {sc.pending > 0 && (
          <span className="text-dim text-[12px]">待记分 {sc.pending} 张 · 发卡后第5个交易日到期</span>
        )}
      </div>
      {sc.baseline && sc.baseline.mech.n > 0 && (
        <div className="text-[12px] text-dim">
          基线对照：机械(sign共振) {sc.baseline.mech.hit_rate != null ? `${sc.baseline.mech.hit_rate}%` : "—"}
          {" · "}恒偏多 {sc.baseline.always_long.hit_rate != null ? `${sc.baseline.always_long.hit_rate}%` : "—"}
          {" —— LLM 方向层不优于基线即应被砍掉，对照公开"}
        </div>
      )}
      {sc.stock && (
        <div className="flex items-center gap-3 flex-wrap text-[13px]">
          <span className="text-dim">个股卡(B8)</span>
          {sc.stock.cum.hit_rate != null ? (
            <span className="text-primary">命中率 {sc.stock.cum.hit_rate}%</span>
          ) : (
            <span className="text-dim">暂无到期</span>
          )}
          <span className="text-up">对 {sc.stock.cum.right}</span>
          <span className="text-down">错 {sc.stock.cum.wrong}</span>
          <span className="text-dim">平 {sc.stock.cum.flat}</span>
          {sc.stock.pending > 0 && <span className="text-dim text-[12px]">待记分 {sc.stock.pending}</span>}
        </div>
      )}
      {sc.curve.length > 0 && (
        <div className="flex flex-wrap gap-1.5 text-[12px] mono">
          {sc.curve.map((w) => (
            <span key={w.week} className="bg-elevated/60 px-1.5 py-0.5 rounded text-muted">
              {w.week.slice(5)} {w.hit_rate != null ? `${w.hit_rate}%` : "—"}({w.right}/{w.n})
            </span>
          ))}
        </div>
      )}
      {srcRows.length > 0 && (
        <div className="text-[13px] space-y-0.5">
          <div className="text-dim text-[12px]">分源归因 · 跟随该源方向的判断命中</div>
          {srcRows.map(([k, v]) => (
            <div key={k} className="flex items-center gap-2">
              <span className="text-muted w-12">{SRC_CN[k] || k}</span>
              <span className="mono text-muted">{v.right}/{v.n}</span>
              <span className={`mono text-[12px] ${v.n && v.right / v.n >= 0.5 ? "text-up" : "text-down"}`}>
                {v.n ? Math.round((v.right / v.n) * 100) : 0}%
              </span>
            </div>
          ))}
        </div>
      )}
      {sc.recent.length > 0 && (
        <div className="space-y-1">
          <MoreList items={sc.recent} initial={5}>
            {(c) => (
              <div key={c.card_id} className="flex items-center gap-2 text-[13px]">
                <span className={`px-1.5 py-0.5 rounded text-[12px] shrink-0 ${vBadge[c.verdict] || vBadge.平}`}>{c.verdict}</span>
                <span className="text-primary truncate">{c.chain}/{c.node}</span>
                <span className="text-dim shrink-0">{c.direction}</span>
                <span className={`mono shrink-0 ${pctCls(c.excess)}`}>超额{c.excess > 0 ? "+" : ""}{c.excess}pp</span>
                <span className="mono text-dim text-[12px] ml-auto shrink-0">{c.end_date.slice(5)}</span>
              </div>
            )}
          </MoreList>
        </div>
      )}
      {sc.weekly && sc.weekly.lessons.length > 0 && (
        <div className="border-t hairline pt-2">
          <div className="text-dim text-[12px] mb-1">本周教训(回灌下周研判)· 截至 {sc.weekly.week_end}</div>
          <ul className="space-y-0.5 text-[13px] text-muted">
            {sc.weekly.lessons.map((l, i) => (
              <li key={i}>· {l}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// 研判页整页:左=B6节点研判+B8个股决策(判断层),右=B7成绩单(追责层)。仅A股链路。
export function JudgmentPageView({ d, isUS }: { d: Dashboard; isUS: boolean }) {
  if (isUS) {
    return (
      <div className="flex-1 p-6 text-muted text-[14px]">
        研判链路(B6/B7/B8)仅覆盖 A 股——顶部切回「A股」查看。
      </div>
    );
  }
  const hasCards = (d.judgment?.cards?.length ?? 0) > 0 || (d.decision?.cards?.length ?? 0) > 0;
  return (
    <div className="flex-1 grid grid-cols-1 md:grid-cols-[1.6fr_1fr] gap-4 md:gap-6 p-3 md:p-6 overflow-auto">
      <div className="space-y-6">
        {!hasCards && <div className="text-muted text-[14px]">今日暂无研判/决策卡(非交易日或盘后未生成)。</div>}
        <JudgmentCards jb={d.judgment} />
        <DecisionCards db={d.decision} />
      </div>
      <div className="space-y-5">
        <div className="border hairline rounded-md bg-surface">
          <div className="px-4 py-2.5 text-[12px] text-muted tracking-wide flex items-center gap-2 border-b hairline">
            <span className="w-1 h-1 rounded-full bg-accent/70" />研判成绩单 · B7 判断追责
          </div>
          <div className="p-4">
            {d.scorecard ? <ScorecardPanel sc={d.scorecard} /> : (
              <div className="text-dim text-[14px]">暂无成绩单数据。</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
