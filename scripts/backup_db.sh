#!/usr/bin/env bash
# research_view 库每日备份(阿里云侧跑,cron 21:00 UTC+8)。
# ledger/daily_report/fund_letter 是不可重算的历史资产,丢盘即全灭 → pg_dump 每日快照。
# 台北 run_afterhours.sh 会把 backups/ 拉回台北异地留存(两地各保 14 天)。
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
mkdir -p backups
DATE=$(date +%Y%m%d)
OUT="backups/research_view_${DATE}.sql.gz"
pg_dump "$RESEARCH_VIEW_DSN" | gzip > "$OUT"
find backups -name 'research_view_*.sql.gz' -mtime +14 -delete
echo "backup ok: $OUT ($(du -h "$OUT" | cut -f1))"
