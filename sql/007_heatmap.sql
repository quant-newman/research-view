-- AI热力图:四象限(叙事强度×财报兑现×估值)。数据只读自 marketdata,聚合存此。
CREATE TABLE IF NOT EXISTS heatmap_stock (
    code text PRIMARY KEY,
    ts_code text,
    name text,
    total_mv numeric,        -- 总市值(万元)
    pe numeric,
    ps numeric,
    ret_1m numeric,          -- 近1月涨幅%
    ret_6m numeric,          -- 近6月涨幅%(叙事强度)
    or_yoy numeric,          -- 营收同比%(财报兑现)
    gross_margin numeric,    -- 毛利率%
    netprofit_yoy numeric,
    pe_pct numeric,          -- PE 在池内分位 0-100(越高越贵)
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS heatmap_node (
    node_id text PRIMARY KEY,
    chain text,
    node text,
    n_stocks int,
    total_mv numeric,
    ret_1m numeric,          -- 节点中位
    ret_6m numeric,
    or_yoy numeric,
    gross_margin numeric,
    pe numeric,
    ps numeric,
    quadrant text,           -- 核心主线|等待验证|潜在补涨|风险区
    updated_at timestamptz NOT NULL DEFAULT now()
);
