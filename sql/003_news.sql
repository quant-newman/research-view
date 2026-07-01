-- 新闻层:原始新闻 + 规则漏斗匹配结果。
-- 主源 = Tushare major_news(标题级)。规则漏斗把命中 180 票/79 题材词的留下。
-- 翻译层结果(节点/票)直接落在同表列,便于按节点分组出事件流。

CREATE TABLE IF NOT EXISTS raw_news (
    news_id       text PRIMARY KEY,          -- 稳定去重键(url 优先,退化用 hash)
    src           text NOT NULL,             -- 同花顺/新浪/财联社/华尔街见闻/...
    title         text NOT NULL,
    pub_time      timestamptz NOT NULL,      -- UTC+8
    url           text,
    content       text,                      -- major_news 标题级,正文暂空
    content_hash  text NOT NULL,
    -- 规则漏斗 + 翻译层结果
    relevant        boolean,                 -- NULL=未过滤; true/false=漏斗判定
    matched_themes  text[] DEFAULT '{}',     -- 命中的题材词
    matched_node_ids text[] DEFAULT '{}',    -- 翻译到的节点
    matched_codes   text[] DEFAULT '{}',     -- 命中/关联的票(6位)
    fetched_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_raw_news_pub ON raw_news(pub_time DESC);
CREATE INDEX IF NOT EXISTS idx_raw_news_relevant ON raw_news(relevant) WHERE relevant;
CREATE INDEX IF NOT EXISTS idx_raw_news_nodes ON raw_news USING gin(matched_node_ids);
