#!/usr/bin/env bash
# 月度备份还原演练(台北侧,cron 每月2号 16:10 UTC+8):没演练过的备份等于没有。
# 把最新一份异地备份(正是灾难时要用的台北副本)真还原进一次性 postgres:18 容器,
# 校验核心资产表行数(daily_report/judgment_card/ref_membership_snap/raw_news),
# 全程不碰阿里云共享实例与本机常驻服务,容器用后即弃。
# 用法: bash scripts/restore_drill.sh(手动可随时跑)
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/lib_alert.sh
trap 'alert_set drill 还原演练 "备份还原演练失败,备份可能不可还原(logs/drill-*.log)"; docker rm -f rv-restore-drill >/dev/null 2>&1 || true' ERR

LATEST=$(ls -t backups/research_view_*.dump 2>/dev/null | head -1)
if [ -z "$LATEST" ]; then
  echo "[drill] 无 .dump 备份可演练(新格式自 2026-07-06 起,等首份拉回)"
  false
fi
echo "[drill] 演练对象: $LATEST ($(du -h "$LATEST" | cut -f1))"

docker rm -f rv-restore-drill >/dev/null 2>&1 || true
docker run -d --name rv-restore-drill -e POSTGRES_PASSWORD=drill postgres:18 >/dev/null
for i in $(seq 1 30); do
  docker exec rv-restore-drill pg_isready -U postgres >/dev/null 2>&1 && break
  sleep 2
done

# --no-owner/--no-privileges:容器里没有生产角色;还原告警级错误会使退出码非零走 trap
docker exec rv-restore-drill createdb -U postgres rv_drill
docker exec -i rv-restore-drill pg_restore -U postgres -d rv_drill --no-owner --no-privileges < "$LATEST"

# 核心资产表行数校验:任何一张为0都算演练失败(备份了个寂寞)
for t in daily_report judgment_card ref_membership_snap raw_news; do
  n=$(docker exec rv-restore-drill psql -U postgres -d rv_drill -tAc "SELECT count(*) FROM $t")
  echo "[drill] $t: $n 行"
  [ "$n" -gt 0 ] || { echo "[drill] ✗ $t 为空"; false; }
done

docker rm -f rv-restore-drill >/dev/null
alert_clear drill
echo "[drill] ✓ 还原演练通过: $LATEST"
