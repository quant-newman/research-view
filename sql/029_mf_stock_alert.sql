-- 盘中个股资金两表(展示/推送层,纯代码零 LLM,不进 B6/B8 判断链——同 chip_cost 先例,#22 冻结不破):
-- ① mf_intraday_stock:个股当日主力累计快照,随 snapshot_intraday 与节点同节奏落点(约5min),
--    个股详情「当日资金累计曲线」用;滚动保留60天(派生层,可由上游快照节奏重积累)。
-- ② mf_alert:资金异动记录——15分钟窗口主力净额变动 ≥ max(0.3亿, 20日日均成交额×2%),
--    同票同方向60分钟冷却;PK(日,时点,票)幂等。资金页异动条 + Web Push 推送消费。
CREATE TABLE IF NOT EXISTS mf_intraday_stock (
    trade_date  date        NOT NULL,
    hhmm        text        NOT NULL,
    code        text        NOT NULL,   -- 6位代码(与前端/heatmap 键一致)
    main        numeric     NOT NULL,   -- 当日累计主力净额(亿)
    PRIMARY KEY (trade_date, hhmm, code)
);

CREATE TABLE IF NOT EXISTS mf_alert (
    trade_date  date        NOT NULL,
    hhmm        text        NOT NULL,   -- 触发时点(=资金数据时点,非墙钟)
    code        text        NOT NULL,
    name        text        NOT NULL,
    delta       numeric     NOT NULL,   -- 窗口内主力净额变动(亿,正=流入)
    window_min  int         NOT NULL,   -- 实际窗口分钟数(快照分辨率决定,约13-25)
    avg_amount  numeric,                -- 20日日均成交额(亿,阈值基准)
    ratio       numeric,                -- delta/avg_amount(占日均成交比)
    cum         numeric,                -- 触发时当日累计主力净额(亿)
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (trade_date, hhmm, code)
);
