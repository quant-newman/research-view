-- 筹码成本(Tushare cyq_perf,东财式估算口径,交易日盘后 17-18 点更新)。
-- 个股详情弹层「筹码/持仓成本」展示专用:不进 B6/B8 证据矩阵(#22 冻结,要作信号先过台架)。
-- 公共可重拉数据(宪法梯队4):upsert 非 append-only,只滚动保留近 30 日。
CREATE TABLE IF NOT EXISTS chip_cost (
  code        text    NOT NULL,           -- 6位代码(同 heatmap_stock.code)
  trade_date  date    NOT NULL,
  weight_avg  numeric,                    -- 加权平均成本(元)
  winner_rate numeric,                    -- 获利盘比例(%)
  cost_5pct   numeric,                    -- 90%筹码区间下沿(元)
  cost_95pct  numeric,                    -- 90%筹码区间上沿(元)
  fetched_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (code, trade_date)
);
