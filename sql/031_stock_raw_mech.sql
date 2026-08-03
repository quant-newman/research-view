-- P0 机械基线修复(P0_MECH_FIX_DESIGN 2026-07-14 裁决+勘误E1;08-03 实施批):
-- 病灶=个股机械基线以 sign(alignment) 记 mech_verdict,而 alignment 入池门槛恒 ≥1.0,
-- 结构性 mech ≡ always_long。修复=新卡发卡时固化内存全精度方向加权和
-- raw_directional_score(= 1.0·price_z + 1.0·mf_z + 0.8·news_z + 0.6·lhb_z,attn 不参与)
-- 与 weight_version('w1');matrix 两位小数存储行为零改动。
-- 两列 nullable:存量行永为 NULL——decision_card append-only(trg_dcard_no_mod),禁止回填;
-- 存量(E0)走派生层纯函数重算(w1_recalc2dp,±0.017 误差带,|raw|≤0.017 记 indeterminate
-- 禁强判),不落卡表。E1 纪元起点 = 本迁移+代码部署 commit(记 DEPLOY_STATE)。
ALTER TABLE decision_card ADD COLUMN IF NOT EXISTS raw_directional_score numeric;
ALTER TABLE decision_card ADD COLUMN IF NOT EXISTS weight_version text;
