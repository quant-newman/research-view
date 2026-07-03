-- B8 个股决策卡(四期,影子运行):三层漏斗收口——候选只从当日 B6 方向节点卡的成分股出。
-- append-only 同 judgment_card(判断不可改);decision_score 是行情的确定性函数(upsert 幂等)。
-- node_card_id = 追责链:这张个股卡基于哪张节点卡发出,B7 归因可穿透到上游板块判断。
CREATE TABLE IF NOT EXISTS decision_card (
    card_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trade_date   date NOT NULL,
    code         text NOT NULL,
    name         text,
    ts_code      text,
    node_id      text,
    node_card_id bigint,          -- 上游节点卡(追责链)
    direction    text NOT NULL,   -- 偏多|偏空|中性(中性=放弃候选,同样记分——漏杀好票也要被看见)
    confidence   text,
    horizon_days int NOT NULL DEFAULT 5,
    thesis       text,
    entry_cond   text,            -- 入场条件(具体可观察,以发卡日收盘为价位锚)
    exit_cond    text,            -- 退出/止损条件
    evidence     jsonb,           -- [{src,fact}] 可溯源证据链
    falsify      text,            -- 5交易日内可验证的证伪条件
    matrix       jsonb,           -- 个股六源z快照(新闻/资金/行情/龙虎榜/研报/人气榜)
    alignment    numeric,         -- 与节点方向的对齐分(代码算)
    close        numeric,         -- 发卡日收盘价(entry/exit 的锚)
    model        text,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_decision_card_date ON decision_card(trade_date, code, card_id DESC);

DROP TRIGGER IF EXISTS trg_dcard_no_mod ON decision_card;
CREATE TRIGGER trg_dcard_no_mod
    BEFORE UPDATE OR DELETE ON decision_card
    FOR EACH ROW EXECUTE FUNCTION ledger_append_only();
DROP TRIGGER IF EXISTS trg_dcard_no_trunc ON decision_card;
CREATE TRIGGER trg_dcard_no_trunc
    BEFORE TRUNCATE ON decision_card
    FOR EACH STATEMENT EXECUTE FUNCTION ledger_append_only();

-- 个股卡记分(与节点卡同口径:5开市日 个股 vs 全池等权超额)
CREATE TABLE IF NOT EXISTS decision_score (
    card_id    bigint PRIMARY KEY,
    trade_date date NOT NULL,
    code       text NOT NULL,
    end_date   date NOT NULL,
    stock_ret  numeric,
    pool_ret   numeric,
    excess     numeric,
    verdict    text NOT NULL,     -- 对|错|平
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_decision_score_end ON decision_score(end_date DESC);
