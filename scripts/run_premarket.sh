#!/usr/bin/env bash
# 盘前流程(台北侧编排):
#   1) 台北拉隔夜美股(yfinance,阿里云连不了 Yahoo) → exports/us_overnight_DATE.json
#   2) scp 隔夜美股文件到阿里云 exports/
#   3) 阿里云合成盘前报告(persist_premarket)→ 落 daily_report(session=premarket)
#   4) 阿里云重建 dashboard.json(自动附隔夜美股)→ rsync 回本机 webdata/(前端即时生效)
# 用法: bash scripts/run_premarket.sh [YYYYMMDD]
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
DATE="${1:-$(TZ=Asia/Shanghai date +%Y%m%d)}"
SSH_BASE="-o StrictHostKeyChecking=no -o ConnectTimeout=20 -o UserKnownHostsFile=/dev/null"
SSH="sshpass -p $ALIYUN_DC_PASS ssh $SSH_BASE $ALIYUN_DC_USER@$ALIYUN_DC_HOST"
export RSYNC_RSH="sshpass -p $ALIYUN_DC_PASS ssh $SSH_BASE"
REMOTE=/opt/research_view

echo "[premarket] 1/4 台北拉隔夜美股 $DATE ..."
./.venv-taipei/bin/python scripts/fetch_us_overnight.py "$DATE"

echo "[premarket] 2/4 推隔夜美股文件到阿里云 ..."
rsync -az "exports/us_overnight_${DATE}.json" \
  "$ALIYUN_DC_USER@$ALIYUN_DC_HOST:$REMOTE/exports/" 2>&1 | grep -v "Warning: Permanently" || true

echo "[premarket] 3/4 阿里云合成盘前报告 ..."
$SSH "cd $REMOTE && ./.venv/bin/python -c \"import sys;sys.path.insert(0,'src');from research_view import report;print('premarket:',report.persist_premarket('$DATE'))\"" 2>&1 | grep -v "Warning: Permanently"

echo "[premarket] 4/4 阿里云重建 dashboard + 拉回 webdata/ ..."
$SSH "cd $REMOTE && ./.venv/bin/python -c \"import sys;sys.path.insert(0,'src');from research_view import export;print(export.build_dashboard('$DATE'))\"" 2>&1 | grep -v "Warning: Permanently"
mkdir -p webdata
rsync -az "$ALIYUN_DC_USER@$ALIYUN_DC_HOST:$REMOTE/exports/dashboard.json" webdata/ 2>&1 | grep -v "Warning: Permanently" || true
echo "[premarket] 完成。前端 8092 已读取盘前报告。"
