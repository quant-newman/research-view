#!/usr/bin/env bash
# 盘后流程(台北侧编排):ssh 阿里云跑完整 pipeline(采集→漏斗→B1→个股事件→热力→
#   研报→盘后报告 B3→质量校验→导出 dashboard)→ rsync dashboard.json 回本机 webdata/。
# 需在 ~22:30 UTC+8 后跑:moneyflow/龙虎榜 上游约 22:00 才落地,早跑会漏当日龙虎榜。
# 用法: bash scripts/run_afterhours.sh [YYYYMMDD]
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

# 全局串行锁:盘前/盘中/盘后/美股 四编排都会重建 dashboard.json 并 rsync 回 webdata,
# 并发会写坏文件 → flock 排队(最多等 300s,超时报错走各自告警路径)。
exec 9>/tmp/rv_orchestrate.lock
flock -w 300 9
DATE="${1:-$(TZ=Asia/Shanghai date +%Y%m%d)}"
SSH_BASE="-i $HOME/.ssh/aliyun_dc_ed25519 -o IdentitiesOnly=yes -o ConnectTimeout=20"
SSH="ssh $SSH_BASE $ALIYUN_DC_USER@$ALIYUN_DC_HOST"
export RSYNC_RSH="ssh $SSH_BASE"
REMOTE=/opt/research_view

# 失败告警旗标:任何一步失败 → 写 webdata/alert.json,前端 StatusBar 显红横幅;成功跑完清除。
mkdir -p webdata
trap 'echo "{\"job\":\"盘后\",\"at\":\"$(TZ=Asia/Shanghai date "+%F %T")\",\"msg\":\"盘后流程失败,数据可能陈旧(logs/afterhours-*.log)\"}" > webdata/alert.json' ERR

echo "[afterhours $(TZ=Asia/Shanghai date '+%F %T') UTC+8] 阿里云跑完整 pipeline $DATE ..."
$SSH "cd $REMOTE && ./.venv/bin/python scripts/run_pipeline.py $DATE" 2>&1 | grep -v "Warning: Permanently"

echo "[afterhours] 拉回 dashboard.json → webdata/ ..."
rsync -az "$ALIYUN_DC_USER@$ALIYUN_DC_HOST:$REMOTE/exports/"{dashboard,trends}.json webdata/ 2>&1 | grep -v "Warning: Permanently" || true

echo "[afterhours] 拉回最新数据库备份(异地留存,两地各保14天)..."
mkdir -p backups
rsync -az "$ALIYUN_DC_USER@$ALIYUN_DC_HOST:$REMOTE/backups/" backups/ 2>&1 | grep -v "Warning: Permanently" || true
find backups -name 'research_view_*.sql.gz' -mtime +14 -delete 2>/dev/null || true

rm -f webdata/alert.json
echo "[afterhours] 完成。前端 8092 已更新。"
