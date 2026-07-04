-- 参照层每日成分快照(数据金矿规划,DECISIONS #30):
-- 参照层(stock_node)是"当前状态",历史修订会丢时点信息——回测已为此付学费(幸存者免责第2条)。
-- 每日盘后 pipeline 落一份成分快照(约200行/日),B7 记分按发卡日快照取成分,
-- 参照层此后任意改版(如 v2 机器人链)都不会追溯污染在途卡的分数。
-- ts_code NULL = 仅映射票(港股),快照保留,记分侧过滤。
CREATE TABLE IF NOT EXISTS ref_membership_snap (
    snap_date date NOT NULL,
    node_id   text NOT NULL,
    code      text NOT NULL,
    ts_code   text,
    tier      text,
    PRIMARY KEY (snap_date, node_id, code)
);
