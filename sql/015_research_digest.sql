-- 研报深化:评级/目标价变动榜(统计) + 机构观点提炼(DeepSeek 综述)。每日覆盖重生。
CREATE TABLE IF NOT EXISTS research_digest (
    report_date  date PRIMARY KEY,
    changes      jsonb NOT NULL,   -- [{code,name,rating_dir,latest_rating,prior_rating,tp_chg,...}]
    views        jsonb NOT NULL,   -- [{code,name,view,n,latest_rating}]
    generated_at timestamptz NOT NULL DEFAULT now()
);
