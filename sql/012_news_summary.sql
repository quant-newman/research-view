-- 新闻 B1 从正文提炼的"核心观点总结"(比 one_line 标题级更实在,挑重点)。
ALTER TABLE raw_news ADD COLUMN IF NOT EXISTS summary text;
