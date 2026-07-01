-- 研究库(卖方研报,来自 Tushare report_rc,本身结构化,零 LLM)+ 基金信函。
CREATE TABLE IF NOT EXISTS research_report (
    report_id  text PRIMARY KEY,          -- hash(ts_code|date|org|title)
    code       text,
    ts_code    text,
    name       text,
    report_date date,
    title      text,
    org_name   text,
    author_name text,
    rating     text,                      -- 买入/增持/中性/...
    classify   text,
    tp         numeric,                    -- 目标价
    eps        numeric,
    pe         numeric,
    roe        numeric,
    quarter    text,
    node_ids   text[] DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_research_code ON research_report(code, report_date DESC);
CREATE INDEX IF NOT EXISTS idx_research_date ON research_report(report_date DESC);
CREATE INDEX IF NOT EXISTS idx_research_nodes ON research_report USING gin(node_ids);

-- 基金信函(海外对冲基金季度信;信源待接入,先建表 + B5 摘要结构)
CREATE TABLE IF NOT EXISTS fund_letter (
    letter_id  text PRIMARY KEY,
    fund_name  text NOT NULL,
    period     text,                       -- 如 2026Q1
    url        text,
    core_views jsonb,                       -- 3条核心观点
    stance     text,                        -- 看多|看空|谨慎|混合
    strategy   text,                        -- 全球宏观|多空|价值|困境债|量化|多策略
    relevance  int,                         -- 对AI科技链启发 0-10
    relevant_points jsonb,
    status     text NOT NULL DEFAULT '待分类',
    created_at timestamptz NOT NULL DEFAULT now()
);
