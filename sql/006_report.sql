-- 每日报告 + 判断复盘账本。
-- daily_report:可重生/可更新(同日同段覆盖)。
-- ledger:判断复盘账本,append-only,插入后不可 UPDATE/DELETE(系统强制,非靠意志力)。

CREATE TABLE IF NOT EXISTS daily_report (
    report_id   text PRIMARY KEY,           -- {date}:{session}
    report_date date NOT NULL,
    session     text NOT NULL,              -- premarket|afterhours
    data_cutoff text NOT NULL,              -- UTC+8 时点
    headline    jsonb NOT NULL,             -- {fact, user_judgment:<待填>, confidence}
    top3        jsonb NOT NULL,
    sectors     jsonb,
    falsification jsonb,                     -- 草稿态证伪条件(待使用者审定钉死)
    holdings_moves jsonb,                    -- "我的持仓动态"(持仓票今日异动)
    generated_at timestamptz NOT NULL DEFAULT now()
);

-- 账本:一条判断被使用者"钉死"后落此,不可改。验证锚点=证伪条件是否触发。
CREATE TABLE IF NOT EXISTS ledger (
    ledger_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    report_id   text REFERENCES daily_report(report_id),
    claim       text NOT NULL,              -- 判断内容
    evidence    text,                       -- 证据
    condition   text NOT NULL,              -- 证伪条件(使用者审定后钉死的最终版)
    kind        text NOT NULL DEFAULT 'judgment',  -- judgment | attribution(证伪归因)
    error_type  text,                       -- 信息错|逻辑错|纯运气(kind=attribution 时)
    ref_ledger  bigint,                     -- attribution 指向被证伪的 judgment
    created_at_utc8 timestamptz NOT NULL DEFAULT now()  -- 钉死时间戳
);

-- append-only 焊死:禁止 UPDATE / DELETE
CREATE OR REPLACE FUNCTION ledger_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'ledger 是只读账本,不允许 % (append-only)', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_ledger_no_mod ON ledger;
CREATE TRIGGER trg_ledger_no_mod
    BEFORE UPDATE OR DELETE ON ledger
    FOR EACH ROW EXECUTE FUNCTION ledger_append_only();

-- 同时堵住 TRUNCATE(语句级),否则 append-only 形同虚设
DROP TRIGGER IF EXISTS trg_ledger_no_trunc ON ledger;
CREATE TRIGGER trg_ledger_no_trunc
    BEFORE TRUNCATE ON ledger
    FOR EACH STATEMENT EXECUTE FUNCTION ledger_append_only();
