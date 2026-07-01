-- 新闻 B1 结构化结果(DeepSeek 只做分类/提取,不下判断)。
ALTER TABLE raw_news ADD COLUMN IF NOT EXISTS sentiment text;          -- 利好|利空|中性|澄清
ALTER TABLE raw_news ADD COLUMN IF NOT EXISTS event_type text;         -- 公告|政策|涨跌异动|研报|外盘|其他
ALTER TABLE raw_news ADD COLUMN IF NOT EXISTS one_line text;           -- 原话概括≤40字,不加解读
ALTER TABLE raw_news ADD COLUMN IF NOT EXISTS is_chain_relevant boolean; -- 是否真属AI科技产业链(砍消费噪音)
ALTER TABLE raw_news ADD COLUMN IF NOT EXISTS llm_tickers text[] DEFAULT '{}'; -- LLM 提到的股票名(可能补规则漏的)
ALTER TABLE raw_news ADD COLUMN IF NOT EXISTS llm_done boolean NOT NULL DEFAULT false;
