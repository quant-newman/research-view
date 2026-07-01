-- 热力图气泡 X 轴多时间窗口(1天/1周/1月/3月/6月),前端可切。
ALTER TABLE heatmap_node ADD COLUMN IF NOT EXISTS ret_1d numeric;
ALTER TABLE heatmap_node ADD COLUMN IF NOT EXISTS ret_1w numeric;
ALTER TABLE heatmap_node ADD COLUMN IF NOT EXISTS ret_3m numeric;
ALTER TABLE heatmap_stock ADD COLUMN IF NOT EXISTS ret_1d numeric;
ALTER TABLE heatmap_stock ADD COLUMN IF NOT EXISTS ret_1w numeric;
ALTER TABLE heatmap_stock ADD COLUMN IF NOT EXISTS ret_3m numeric;
