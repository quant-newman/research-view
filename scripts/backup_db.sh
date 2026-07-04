#!/usr/bin/env bash
# research_view 库每日备份(数据节点跑,cron 21:00+23:30 UTC+8;同日文件覆盖,23:30 档含当日判断卡/记分)。
# ledger/daily_report/fund_letter 是不可重算的历史资产,丢盘即全灭 → pg_dump 每日快照。
# exports/ 观测层按日 blob(美股/X舆情/事件/信函)不进 PG,是 LLM 当时综合的 PIT 证据,事后不可重建,
# 台架回测比对要用(DECISIONS #34)→ 每日 tar 走同一条备份链。
# 台北 run_afterhours.sh 会把 backups/ 拉回台北异地留存(两地各保 14 天)。
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
mkdir -p backups
DATE=$(date +%Y%m%d)
OUT="backups/research_view_${DATE}.sql.gz"
pg_dump "$RESEARCH_VIEW_DSN" | gzip > "$OUT"
find backups -maxdepth 1 -name 'research_view_*.sql.gz' -mtime +14 -delete
EXP_OUT="backups/exports_${DATE}.tar.gz"
tar -czf "$EXP_OUT" exports
find backups -maxdepth 1 -name 'exports_*.tar.gz' -mtime +14 -delete
# 月度归档(轻量,使用者定"备份不要太重"):每月1号快照存 archive/,只滚动保留12份
if [ "$(date +%d)" = "01" ]; then
  mkdir -p backups/archive
  cp "$OUT" "backups/archive/research_view_$(date +%Y%m).sql.gz"
  cp "$EXP_OUT" "backups/archive/exports_$(date +%Y%m).tar.gz"
  ls -1t backups/archive/research_view_*.sql.gz 2>/dev/null | tail -n +13 | xargs -r rm --
  ls -1t backups/archive/exports_*.tar.gz 2>/dev/null | tail -n +13 | xargs -r rm --
fi
echo "backup ok: $OUT ($(du -h "$OUT" | cut -f1)) + $EXP_OUT ($(du -h "$EXP_OUT" | cut -f1))"
