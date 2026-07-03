-- B6 节点研判卡(二期):六源证据矩阵(代码算)+ DeepSeek 方向/置信/条件式情景。
-- 铁律「判断必须可追责」:每张卡带完整证据快照(matrix/evidence)+ 证伪条件+时间窗,
-- append-only 焊死(复用 ledger_append_only 触发器函数)——B7 周度成绩单按卡记分,
-- 卡不可改;重跑同日只会追加,消费方取每节点最新一张(card_id 最大)。
CREATE TABLE IF NOT EXISTS judgment_card (
    card_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trade_date   date NOT NULL,
    node_id      text NOT NULL,
    direction    text NOT NULL,           -- 偏多|偏空|中性(未来 horizon 内相对全池超额)
    confidence   text,                    -- 高|中|低
    horizon_days int NOT NULL DEFAULT 5,  -- 判断时间窗(交易日),B7 到期打分
    thesis       text,                    -- 一句话研判(带责任的判断,非中性陈列)
    evidence     jsonb,                   -- [{src,fact}] 证据链,每条可溯源到输入
    scenarios    jsonb,                   -- [{cond,expect,falsify}] 条件式情景+证伪条件
    matrix       jsonb,                   -- 六源 z-score 矩阵快照(代码算,B7 归因用)
    resonance    numeric,                 -- 共振分(方向源 z 加权和,代码算)
    n_agree      int,                     -- 与主方向一致的激活源数
    n_active     int,                     -- 激活源总数(|z|≥1 或信函命中)
    divergence   jsonb,                   -- 背离标注(代码算:源间反向/资金×价格)
    model        text,                    -- 生成模型(追责溯源)
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_judgment_card_date ON judgment_card(trade_date, node_id, card_id DESC);

-- append-only:复用 sql/006 的 ledger_append_only()(RAISE 文案含 TG_OP,通用)
DROP TRIGGER IF EXISTS trg_jcard_no_mod ON judgment_card;
CREATE TRIGGER trg_jcard_no_mod
    BEFORE UPDATE OR DELETE ON judgment_card
    FOR EACH ROW EXECUTE FUNCTION ledger_append_only();
DROP TRIGGER IF EXISTS trg_jcard_no_trunc ON judgment_card;
CREATE TRIGGER trg_jcard_no_trunc
    BEFORE TRUNCATE ON judgment_card
    FOR EACH STATEMENT EXECUTE FUNCTION ledger_append_only();
