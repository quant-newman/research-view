-- 今日热点/主题热度榜:统计信号选候选 + DeepSeek 综合叙述。每日可覆盖重生。
CREATE TABLE IF NOT EXISTS hotspot_daily (
    report_date  date PRIMARY KEY,
    headline     text,                    -- 今日主题总览一句话(中性)
    items        jsonb NOT NULL,          -- [{theme,chain,node,reason,trend,heat,signals,stocks,news}]
    generated_at timestamptz NOT NULL DEFAULT now()
);
