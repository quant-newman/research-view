#!/usr/bin/env bash
# 盘中轻量刷新(台北侧编排):ssh 阿里云跑 run_light(采集→漏斗→B1→研报→导出)→
#   rsync dashboard.json 回本机 webdata/。cron 每 30 分钟跑,只刷新闻/研报,行情不动。
# 用法: bash scripts/run_intraday.sh [YYYYMMDD]
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
DATE="${1:-$(TZ=Asia/Shanghai date +%Y%m%d)}"
SSH_BASE="-o StrictHostKeyChecking=no -o ConnectTimeout=20 -o UserKnownHostsFile=/dev/null"
SSH="sshpass -p $ALIYUN_DC_PASS ssh $SSH_BASE $ALIYUN_DC_USER@$ALIYUN_DC_HOST"
export RSYNC_RSH="sshpass -p $ALIYUN_DC_PASS ssh $SSH_BASE"
REMOTE=/opt/research_view

$SSH "cd $REMOTE && ./.venv/bin/python scripts/run_light.py $DATE" 2>&1 | grep -v "Warning: Permanently"
mkdir -p webdata
rsync -az "$ALIYUN_DC_USER@$ALIYUN_DC_HOST:$REMOTE/exports/dashboard.json" webdata/ 2>&1 | grep -v "Warning: Permanently" || true
