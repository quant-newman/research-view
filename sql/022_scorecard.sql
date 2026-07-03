-- B7 周度成绩单(三期):研判卡到期记分 + 周度收口(错误归纳回灌下周 B6 prompt)。
-- card_score 是代码对客观行情的确定性计算(可重算),用 PK upsert 保证幂等,
-- 不做 append-only——判断(judgment_card)不可改,分数是行情的函数、随时可复核。
CREATE TABLE IF NOT EXISTS card_score (
    card_id    bigint PRIMARY KEY,   -- 对应 judgment_card(每节点每日只记最新一张卡)
    trade_date date NOT NULL,        -- 卡发出日
    node_id    text NOT NULL,
    end_date   date NOT NULL,        -- horizon 到期交易日(发卡日后第 horizon_days 个开市日)
    node_ret   numeric,              -- 节点成分等权区间收益 %
    pool_ret   numeric,              -- 全池等权区间收益 %(beta 基准)
    excess     numeric,              -- 超额(百分点)= node_ret - pool_ret
    n_members  int,                  -- 参与计算的成分股数
    verdict    text NOT NULL,        -- 对|错|平(方向卡超额 ±1pp 外定对错,带内=平;中性卡 ±2pp 带内=对)
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_card_score_end ON card_score(end_date DESC);

-- 周度成绩单:累计/本周命中率 + 分方向/分源归因(代码算) + 错误归纳与教训(DeepSeek)。
-- lessons 由 evidence.generate() 读最新一份回灌下周研判 prompt(校准回路)。
CREATE TABLE IF NOT EXISTS b7_weekly (
    week_end     date PRIMARY KEY,
    stats        jsonb,  -- {cum, week, by_direction, by_source}
    review       jsonb,  -- 本周错误卡归纳 [{node_id, error_type(信息错|逻辑错|纯运气), why}]
    lessons      jsonb,  -- ["下周研判注意事项", ...] 回灌 B6
    generated_at timestamptz NOT NULL DEFAULT now()
);
