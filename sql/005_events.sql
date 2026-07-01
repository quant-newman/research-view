-- 个股事件(来自 marketdata 结构化公告 + 龙虎榜,零 LLM,直接映射票→节点)。
CREATE TABLE IF NOT EXISTS stock_event (
    event_id   text PRIMARY KEY,             -- hash(type|ts_code|date|key)
    code       text,
    ts_code    text,
    node_ids   text[] DEFAULT '{}',
    event_type text NOT NULL,                -- 业绩预告|业绩快报|增减持|解禁|龙虎榜
    direction  text,                         -- 利好|利空|中性(基于事实方向,非投资判断)
    event_date date,
    summary    text NOT NULL,                -- 客观陈述,不加解读
    detail     jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_stock_event_code ON stock_event(code);
CREATE INDEX IF NOT EXISTS idx_stock_event_date ON stock_event(event_date DESC);
CREATE INDEX IF NOT EXISTS idx_stock_event_nodes ON stock_event USING gin(node_ids);
