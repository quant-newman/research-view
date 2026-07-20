-- 030: weekly_reflection —— 使用者手动周度复盘(07-21 第二批施工令)。
-- 边界:整篇 Markdown 原文,零 LLM,不进 B6/B8/scorecard/lessons/prompt 链;
--       默认 private,显式 public 才进公开导出;修订走版本链新增行,原行永不改。
-- append-only 焊死(复用 sql/006 ledger_append_only()),版本链由触发器自动维护,
-- 调用方不得自行伪造 version_no。幂等、纯新增、向后兼容(旧版代码不感知本表)。

CREATE TABLE IF NOT EXISTS weekly_reflection (
    reflection_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    week_end         date NOT NULL,
    title            text NOT NULL,
    content_md       text NOT NULL,
    content_sha256   text NOT NULL,
    source_filename  text,
    authored_at_utc8 timestamptz NOT NULL,
    recorded_at_utc8 timestamptz NOT NULL DEFAULT now(),
    supersedes_id    bigint REFERENCES weekly_reflection(reflection_id),
    version_no       int NOT NULL,
    visibility       text NOT NULL DEFAULT 'private'
        CHECK (visibility IN ('private', 'public')),
    -- 标题与正文去首尾空白后不得为空(~'\S'=至少一个非空白字符;
    -- 不用 btrim:它默认只裁空格,纯 \n\t 会绕过)
    CONSTRAINT wr_title_not_blank   CHECK (title ~ '\S'),
    CONSTRAINT wr_content_not_blank CHECK (content_md ~ '\S'),
    -- SHA-256 必须 64 位小写十六进制
    CONSTRAINT wr_sha256_format CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    -- source_filename 只存纯文件名:禁目录分隔符(路径/用户名零泄漏),禁纯空白
    CONSTRAINT wr_filename_pure CHECK (
        source_filename IS NULL
        OR (source_filename !~ '[/\\]' AND source_filename ~ '\S')),
    -- 同一旧版最多一个直接后继,版本链不得分叉(多 NULL 不冲突=各周根记录共存)
    CONSTRAINT wr_no_fork UNIQUE (supersedes_id)
);

-- 同一周只能有一条根记录(修订版不受限,root 唯一性只看 supersedes_id IS NULL)
CREATE UNIQUE INDEX IF NOT EXISTS wr_one_root_per_week
    ON weekly_reflection (week_end) WHERE supersedes_id IS NULL;

-- 导出/list 按周检索
CREATE INDEX IF NOT EXISTS wr_week_end_idx ON weekly_reflection (week_end);

-- 版本链自动维护:根=1;修订版必须引用存在的父版本、week_end 与父一致、
-- version_no=父+1。无论调用方传什么 version_no 一律覆盖(不得伪造)。
CREATE OR REPLACE FUNCTION weekly_reflection_version_chain() RETURNS trigger AS $$
DECLARE
    parent weekly_reflection%ROWTYPE;
BEGIN
    IF NEW.supersedes_id IS NULL THEN
        NEW.version_no := 1;
        RETURN NEW;
    END IF;
    SELECT * INTO parent FROM weekly_reflection WHERE reflection_id = NEW.supersedes_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'weekly_reflection: supersedes_id=% 不存在,修订版必须引用已存在父版本',
            NEW.supersedes_id;
    END IF;
    IF NEW.week_end IS DISTINCT FROM parent.week_end THEN
        RAISE EXCEPTION 'weekly_reflection: 禁止跨 week_end 修订(父=% 新=%)',
            parent.week_end, NEW.week_end;
    END IF;
    NEW.version_no := parent.version_no + 1;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_wr_version_chain ON weekly_reflection;
CREATE TRIGGER trg_wr_version_chain
    BEFORE INSERT ON weekly_reflection
    FOR EACH ROW EXECUTE FUNCTION weekly_reflection_version_chain();

-- append-only:复用 sql/006 的 ledger_append_only()(RAISE 文案含 TG_OP,通用)。
-- visibility 变化同样走新增修订版,不允许 UPDATE 旧行。
DROP TRIGGER IF EXISTS trg_wr_no_mod ON weekly_reflection;
CREATE TRIGGER trg_wr_no_mod
    BEFORE UPDATE OR DELETE ON weekly_reflection
    FOR EACH ROW EXECUTE FUNCTION ledger_append_only();
DROP TRIGGER IF EXISTS trg_wr_no_trunc ON weekly_reflection;
CREATE TRIGGER trg_wr_no_trunc
    BEFORE TRUNCATE ON weekly_reflection
    FOR EACH STATEMENT EXECUTE FUNCTION ledger_append_only();
