-- 系统健康监控:每个定时任务(采集/生成/校验)记录一行。轻量,只留最近30天。
CREATE TABLE IF NOT EXISTS task_log (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task        text NOT NULL,               -- 任务名(fetch_news/structure/events/heatmap/report/...)
    status      text NOT NULL,               -- 成功|部分成功|失败
    records_count int,
    duration_ms int,
    error_msg   text,
    ts_utc8     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_task_log_ts ON task_log(ts_utc8 DESC);
CREATE INDEX IF NOT EXISTS idx_task_log_task ON task_log(task, ts_utc8 DESC);

-- 数据质量存疑标记(校验不通过标记而非丢弃,人工可见)
CREATE TABLE IF NOT EXISTS data_flag (
    id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind      text NOT NULL,                 -- 涨跌幅异常|PE极端|市值突变|停牌
    code      text,
    detail    text,
    ts_utc8   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_data_flag_ts ON data_flag(ts_utc8 DESC);
