-- 热点利好/利空要点总结(LLM 汇总,{pos:[],neg:[]}):headline 一句话不够读,合并页后新闻流太长,总结加厚
ALTER TABLE hotspot_daily ADD COLUMN IF NOT EXISTS brief jsonb;
