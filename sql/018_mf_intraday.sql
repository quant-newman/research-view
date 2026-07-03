-- 盘中资金流·节点级累计快照:run_light 每 15min 把"当日截至此刻"的各节点主力净额
-- (来自 md.moneyflow_rt ∪ moneyflow_rt_extra 聚合)追加一个时点,积累成当日累计曲线
-- (资金页多线图)。同一 last_min 时点幂等跳过(午休/收盘后 stamp 不变即不重复落点)。
-- node_id='POOL' 行 = 核心池按个股去重的合计(节点求和会重复计入多节点票)。
CREATE TABLE IF NOT EXISTS mf_intraday_node (
    trade_date  date        NOT NULL,
    hhmm        text        NOT NULL,
    node_id     text        NOT NULL,
    main        numeric     NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (trade_date, hhmm, node_id)
);
