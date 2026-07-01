-- 持仓/自选层(贯穿维度)。使用者手动维护,不接券商 API。
-- 隐私:金额类字段(cost_price/position_pct)可空,且【绝不进静态导出的公开 JSON】,
-- 静态页只输出"是否持仓/自选"的布尔标记。池外持仓票 in_pool=false,前端标"⚠池外"。

CREATE TABLE IF NOT EXISTS holdings (
    code        text PRIMARY KEY,
    name        text NOT NULL,
    status      text NOT NULL DEFAULT '持有',
    in_pool     boolean NOT NULL DEFAULT false,   -- 是否在 180 池内
    cost_price   numeric,                          -- 敏感·可空·不导出
    position_pct numeric,                          -- 敏感·可空·不导出
    note        text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS watchlist (
    code        text PRIMARY KEY,
    name        text NOT NULL,
    status      text NOT NULL DEFAULT '关注',
    in_pool     boolean NOT NULL DEFAULT false,
    note        text,                              -- 如"等回调"/"跟踪扣非兑现"
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
