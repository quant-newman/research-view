#!/usr/bin/env bash
# 盘后流程(台北侧编排):ssh 阿里云跑完整 pipeline(采集→漏斗→B1→个股事件→热力→
#   研报→盘后报告 B3→质量校验→导出 dashboard)→ rsync dashboard.json 回本机 webdata/。
# 需在 ~22:30 UTC+8 后跑:moneyflow/龙虎榜 上游约 22:00 才落地,早跑会漏当日龙虎榜。
# 用法: bash scripts/run_afterhours.sh [YYYYMMDD]
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
DATE="${1:-$(TZ=Asia/Shanghai date +%Y%m%d)}"
SSH_BASE="-o StrictHostKeyChecking=no -o ConnectTimeout=20 -o UserKnownHostsFile=/dev/null"
SSH="sshpass -p $ALIYUN_DC_PASS ssh $SSH_BASE $ALIYUN_DC_USER@$ALIYUN_DC_HOST"
export RSYNC_RSH="sshpass -p $ALIYUN_DC_PASS ssh $SSH_BASE"
REMOTE=/opt/research_view

echo "[afterhours $(TZ=Asia/Shanghai date '+%F %T') UTC+8] 阿里云跑完整 pipeline $DATE ..."
$SSH "cd $REMOTE && ./.venv/bin/python scripts/run_pipeline.py $DATE" 2>&1 | grep -v "Warning: Permanently"

echo "[afterhours] 拉回 dashboard.json → webdata/ ..."
mkdir -p webdata
rsync -az "$ALIYUN_DC_USER@$ALIYUN_DC_HOST:$REMOTE/exports/dashboard.json" webdata/ 2>&1 | grep -v "Warning: Permanently" || true
echo "[afterhours] 完成。前端 8092 已更新。"
