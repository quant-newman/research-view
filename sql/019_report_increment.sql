-- 盘中增量条目:当日报告的"演进时间线"(B3 演进式改造)。
-- 设计:事实层每个时点从客观数据重算 delta(新增新闻/资金位移),防链式传递的
-- 误差累积;叙事层只写"较上一时点变了什么",基线报告仅作对照避免重复,不作事实源。
-- 无实质增量的时点不产生条目(节奏自动慢下来,token 只花在真变化上)。
CREATE TABLE IF NOT EXISTS report_increment (
    trade_date  date        NOT NULL,
    hhmm        text        NOT NULL,            -- 生成时点 HH:MM (UTC+8)
    entry       text        NOT NULL,            -- 增量叙述(50-150字,只引用delta事实)
    tags        jsonb,                           -- 涉及节点/票(可选)
    n_news      int,                             -- 溯源:本时点新增相关新闻数
    mf_shift    text,                            -- 溯源:资金位移摘要
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (trade_date, hhmm)
);
CREATE INDEX IF NOT EXISTS idx_report_increment_date ON report_increment(trade_date, created_at);
