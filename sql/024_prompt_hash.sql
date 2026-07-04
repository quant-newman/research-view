-- 任务#13/DECISIONS #28:校准期审计——判断卡记录发卡 prompt 版本。
-- prompt_hash = sha256(SYSTEM + user模板(规则文本) + lessons段) 前16位;
-- 每日数据块与日期不入哈希(否则天天变),lessons 回灌引起的 prompt 漂移由此可检测,
-- B7 校准样本可按 prompt 版本分组,避免口径混样。
-- nullable + ALTER ADD COLUMN 不违反 append-only(不改已有行;旧卡 NULL = 2026-07-04 前口径)。
ALTER TABLE judgment_card ADD COLUMN IF NOT EXISTS prompt_hash text;
ALTER TABLE decision_card ADD COLUMN IF NOT EXISTS prompt_hash text;
