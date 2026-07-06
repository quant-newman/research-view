#!/usr/bin/env bash
# 盘后流程(台北侧编排):ssh 阿里云跑完整 pipeline(采集→漏斗→B1→个股事件→热力→
#   研报→盘后报告 B3→质量校验→导出 dashboard)→ rsync dashboard.json 回本机 webdata/。
# 需在 ~22:30 UTC+8 后跑:moneyflow/龙虎榜 上游约 22:00 才落地,早跑会漏当日龙虎榜。
# 用法: bash scripts/run_afterhours.sh [YYYYMMDD]
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

# 失败告警旗标(装在 flock 之前:锁等待超时也走告警,不再无声退出)
source scripts/lib_alert.sh
mkdir -p webdata
trap 'alert_set afterhours 盘后 "盘后流程失败,数据可能陈旧(logs/afterhours-*.log)"' ERR

# 全局串行锁:盘前/盘中/盘后/美股/信函 编排都会重建 dashboard.json 并 rsync 回 webdata,
# 并发会写坏文件 → flock 排队(最多等 300s)。
exec 9>/tmp/rv_orchestrate.lock
flock -w 300 9
DATE="${1:-$(TZ=Asia/Shanghai date +%Y%m%d)}"
# LogLevel=ERROR 压掉 known-hosts Warning,rsync/ssh 退出码原样生效(不再 grep/|| true 吞错)
SSH_BASE="-i $HOME/.ssh/aliyun_dc_ed25519 -o IdentitiesOnly=yes -o ConnectTimeout=20 -o LogLevel=ERROR"
SSH="ssh $SSH_BASE $ALIYUN_DC_USER@$ALIYUN_DC_HOST"
export RSYNC_RSH="ssh $SSH_BASE"
REMOTE=/opt/research_view

echo "[afterhours $(TZ=Asia/Shanghai date '+%F %T') UTC+8] 阿里云跑完整 pipeline $DATE ..."
$SSH "cd $REMOTE && ./.venv/bin/python scripts/run_pipeline.py $DATE"

echo "[afterhours] 拉回 dashboard.json → webdata/ ..."
rsync -az "$ALIYUN_DC_USER@$ALIYUN_DC_HOST:$REMOTE/exports/"{dashboard,trends}.json webdata/

echo "[afterhours] 拉回最新数据库备份(异地留存,两地各保14天)..."
mkdir -p backups
# 台北 .env(凭证单点)推到阿里云备份目录做交叉异地,随拉回同步回来(chmod 600)
rsync -az --chmod=F600 .env "$ALIYUN_DC_USER@$ALIYUN_DC_HOST:$REMOTE/backups/env_taipei_${DATE}" || true
rsync -az "$ALIYUN_DC_USER@$ALIYUN_DC_HOST:$REMOTE/backups/" backups/
# -maxdepth 1 保护 backups/archive/ 月度归档(旧版无此限定,台北侧归档14天即被误删)
find backups -maxdepth 1 -name 'research_view_*' -mtime +14 -delete 2>/dev/null || true
find backups -maxdepth 1 -name 'exports_*.tar.gz' -mtime +14 -delete 2>/dev/null || true
find backups -maxdepth 1 -name 'env_taipei_*' -mtime +14 -delete 2>/dev/null || true
# 备份新鲜度哨兵:最新备份老于 ~2 天=阿里云 21:00 备份 cron 已断或校验连败,告警不阻塞
if ! find backups -name 'research_view_*' -mtime -2 | grep -q .; then
  alert_set backup 备份 "数据库备份超过2天未更新,查阿里云 logs/backup.log"
  echo "[afterhours] ⚠ 备份陈旧告警已写(不阻塞)"
else
  alert_clear backup
fi

alert_clear afterhours
# 飞书盘后收口摘要(DECISIONS #32):发卡/记分/health 一眼确认机器干完活
python3 scripts/notify_feishu.py summary || true
echo "[afterhours] 完成。前端 8092 已更新。"
