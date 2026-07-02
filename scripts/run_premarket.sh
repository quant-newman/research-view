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
SSH_BASE="-i $HOME/.ssh/aliyun_dc_ed25519 -o IdentitiesOnly=yes -o ConnectTimeout=20"
SSH="ssh $SSH_BASE $ALIYUN_DC_USER@$ALIYUN_DC_HOST"
export RSYNC_RSH="ssh $SSH_BASE"
REMOTE=/opt/research_view

# 失败告警旗标:失败写 webdata/alert.json(前端红横幅),成功清除。
mkdir -p webdata
trap 'echo "{\"job\":\"盘前\",\"at\":\"$(TZ=Asia/Shanghai date "+%F %T")\",\"msg\":\"盘前流程失败,数据可能陈旧(logs/premarket-*.log)\"}" > webdata/alert.json' ERR

echo "[premarket] 1/4 台北拉隔夜美股 + 美股板块 $DATE ..."
if ! ./.venv-taipei/bin/python scripts/fetch_us_overnight.py "$DATE"; then
  echo "[premarket] ⚠ 隔夜美股拉取失败(Yahoo 抖动?),降级:盘前仅出国内部分"
fi
if ! ./.venv-taipei/bin/python scripts/build_us.py "$DATE"; then
  echo "[premarket] ⚠ 美股板块构建失败,美股页沿用上次数据"
fi

echo "[premarket] 2/4 推美股文件到阿里云 ..."
for f in "us_overnight_${DATE}.json" "us_${DATE}.json"; do
  if [ -f "exports/$f" ]; then
    rsync -az "exports/$f" "$ALIYUN_DC_USER@$ALIYUN_DC_HOST:$REMOTE/exports/" 2>&1 | grep -v "Warning: Permanently" || true
  fi
done

echo "[premarket] 3/4 阿里云合成盘前报告 ..."
$SSH "cd $REMOTE && ./.venv/bin/python -c \"import sys;sys.path.insert(0,'src');from research_view import report;print('premarket:',report.persist_premarket('$DATE'))\"" 2>&1 | grep -v "Warning: Permanently"

echo "[premarket] 4/4 阿里云重建 dashboard + 拉回 webdata/ ..."
$SSH "cd $REMOTE && ./.venv/bin/python -c \"import sys;sys.path.insert(0,'src');from research_view import export;print(export.build_dashboard('$DATE'))\"" 2>&1 | grep -v "Warning: Permanently"
rsync -az "$ALIYUN_DC_USER@$ALIYUN_DC_HOST:$REMOTE/exports/"{dashboard,trends}.json webdata/ 2>&1 | grep -v "Warning: Permanently" || true
rm -f webdata/alert.json
echo "[premarket] 完成。前端 8092 已读取盘前报告。"
