-- DECISIONS #40:主观概率进卡——出卡时自报"判断兑现"的主观概率,B7 在现有记分外累积
-- Brier 分数与校准曲线数据点(ROADMAP 0c 的概率化实现;越早上线校准数据越厚)。
-- 兑现事件与记分判定同口径(scorecard._verdict):方向卡=超额×方向≥+1pp;中性卡=|超额|≤2pp。
-- Brier outcome:对=1,错/平=0——平不剔除(剔除=条件化在"分出对错"上,校准曲线系统性偏高;
-- 与 hit_rate 只算对/(对+错)是两个指标两个口径,见 docs/B7_SCORECARD.md)。
-- nullable + ALTER ADD COLUMN 不违反 append-only(同 sql/024 先例);旧卡 NULL 不回填——事后补=污染。
-- 开区间 CHECK:0/1 的"确定性"报数无信息且为将来 log score 留路。
ALTER TABLE judgment_card ADD COLUMN IF NOT EXISTS subjective_prob numeric
    CHECK (subjective_prob > 0 AND subjective_prob < 1);
ALTER TABLE decision_card ADD COLUMN IF NOT EXISTS subjective_prob numeric
    CHECK (subjective_prob > 0 AND subjective_prob < 1);
