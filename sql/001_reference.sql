-- research_view 参照数据表(本产品的股票宇宙定义,源自 data/ 的三份 JSON 资产)
-- 注:行情/财务/资金走 marketdata 只读,不在此复制;此处只存"我们的池子/节点/映射"。
-- 时间口径 UTC+8(服务器时区 Asia/Shanghai,now() 即 +08)。

CREATE TABLE IF NOT EXISTS node (
    node_id   text PRIMARY KEY,          -- {chain_en}::{子类}
    chain     text NOT NULL,             -- 中文链名(光通信/半导体/…)
    chain_en  text NOT NULL,
    node      text NOT NULL              -- 子类名
);

CREATE TABLE IF NOT EXISTS stock (
    code      text PRIMARY KEY,          -- 6 位代码(唯一,180 只)
    name      text NOT NULL,
    ts_code   text,                      -- 带交易所后缀,join marketdata 用(载入后回填)
    in_pool   boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- 一票可跨多节点(业务跨界,保留),故独立映射表
CREATE TABLE IF NOT EXISTS stock_node (
    code      text NOT NULL REFERENCES stock(code) ON DELETE CASCADE,
    node_id   text NOT NULL REFERENCES node(node_id) ON DELETE CASCADE,
    tier      text,                      -- 龙一/龙二/…
    purity    text,
    judgment  text,                      -- 使用者的产业判断(母表带来)
    PRIMARY KEY (code, node_id)
);

-- 新闻翻译层核心:题材关键词 → 节点
CREATE TABLE IF NOT EXISTS theme_node (
    theme     text NOT NULL,
    node_id   text NOT NULL REFERENCES node(node_id) ON DELETE CASCADE,
    PRIMARY KEY (theme, node_id)
);

CREATE INDEX IF NOT EXISTS idx_stock_node_node ON stock_node(node_id);
CREATE INDEX IF NOT EXISTS idx_theme_node_node ON theme_node(node_id);
