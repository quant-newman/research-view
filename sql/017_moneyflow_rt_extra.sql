-- 盘中资金流·自采补充表:DC 数据中心 md.moneyflow_rt 的监控池(agu 产业表 168 只)
-- 未覆盖的核心池票,由 run_light 每 15min 从东财 push2delay 自采(同 DC 口径,单位元)。
-- 消费时与 md.moneyflow_rt UNION(见 src/research_view/moneyflow.py)。幂等可重跑。
CREATE TABLE IF NOT EXISTS moneyflow_rt_extra (
    trade_date  date        NOT NULL,
    ts_code     text        NOT NULL,
    last_min    text,
    main_net    numeric,
    elg_net     numeric,
    lg_net      numeric,
    mid_net     numeric,
    sm_net      numeric,
    hourly      jsonb,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (trade_date, ts_code)
);
