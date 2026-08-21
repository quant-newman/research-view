-- 叙述层指纹(2026-08-21 降本批):hotspots/research_digest 原本每 15min 全量重烧 DeepSeek,
-- 而盘中输入(新闻集合/研报标题集合)通常一整档都没变 → 同一份叙述反复生成,约 130 次/日纯冗余。
-- 存下"生成这份叙述所依据的输入指纹",下一档指纹一致就复用已落库的叙述,不再调 LLM。
-- nullable:存量行 NULL=无指纹,首次运行必然重算一次并补上,不需要回填。
ALTER TABLE hotspot_daily    ADD COLUMN IF NOT EXISTS sig text;
ALTER TABLE research_digest  ADD COLUMN IF NOT EXISTS views_sig text;
