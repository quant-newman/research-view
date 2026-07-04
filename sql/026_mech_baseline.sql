-- 0b 基准对照记分(ROADMAP 0b,外部评判"证据>新功能"):
-- mech_verdict = 机械基线的记分——方向取 sign(resonance)(节点卡)/sign(alignment)(个股卡),
-- 零 LLM,同一套 verdict 规则同一个 excess。三列对照:LLM方向 vs 机械基线 vs 恒多基线(从 excess
-- 分布统计,无需列)。若 LLM 方向层长期不优于机械基线,结论就是砍掉它(可审计的自我检验)。
-- 分数表可重算(非 append-only),ALTER + 重算合法。
ALTER TABLE card_score     ADD COLUMN IF NOT EXISTS mech_verdict text;
ALTER TABLE decision_score ADD COLUMN IF NOT EXISTS mech_verdict text;
