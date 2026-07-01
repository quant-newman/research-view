-- 基金信函补 title 列(B5 摘要带标题,便于前端展示与溯源)。
ALTER TABLE fund_letter ADD COLUMN IF NOT EXISTS title text;
