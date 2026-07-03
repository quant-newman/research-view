-- 报告加 narrative(约500字今日综述,digest 一天新闻/事件/舆情)。幂等,可重复执行。
ALTER TABLE daily_report ADD COLUMN IF NOT EXISTS narrative text;
