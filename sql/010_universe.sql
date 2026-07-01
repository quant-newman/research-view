-- 科技行业域(比 180 核心池更大):申万一级 电子/计算机/通信/传媒 ∪ 核心池。
-- 核心池(180)= 高亮子集,带节点映射;泛科技票按申万行业标注。
CREATE TABLE IF NOT EXISTS tech_stock (
    code    text PRIMARY KEY,
    ts_code text,
    name    text,
    sw_l1   text,
    sw_l2   text,
    in_pool boolean NOT NULL DEFAULT false   -- 是否在 180 核心池
);
CREATE INDEX IF NOT EXISTS idx_tech_stock_l1 ON tech_stock(sw_l1);

-- 研报/新闻加范围标注
ALTER TABLE research_report ADD COLUMN IF NOT EXISTS scope text;      -- 核心池|泛科技
ALTER TABLE research_report ADD COLUMN IF NOT EXISTS industry text;   -- 泛科技票的申万L2
ALTER TABLE raw_news ADD COLUMN IF NOT EXISTS matched_tech_codes text[] DEFAULT '{}';
ALTER TABLE raw_news ADD COLUMN IF NOT EXISTS tech_industries text[] DEFAULT '{}';
