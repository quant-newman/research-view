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

# 失败告警旗标(装在 flock 之前:锁等待超时也走告警,不再无声退出)
source scripts/lib_alert.sh
mkdir -p webdata
trap 'alert_set premarket 盘前 "盘前流程失败,数据可能陈旧(logs/premarket-*.log)"' ERR

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

echo "[premarket] 1/4 台北拉隔夜美股 + 美股板块 $DATE ..."
if ! ./.venv-taipei/bin/python scripts/fetch_us_overnight.py "$DATE"; then
  echo "[premarket] ⚠ 隔夜美股拉取失败(Yahoo 抖动?),降级:盘前仅出国内部分"
fi
if ! ./.venv-taipei/bin/python scripts/build_us.py "$DATE"; then
  echo "[premarket] ⚠ 美股板块构建失败,美股页沿用上次数据"
fi

echo "[premarket] 2/4 推美股文件到阿里云 ..."
# 推送失败=阿里云拿旧文件建 dashboard,必须告警(旧版 || true 会静默陈旧一天)
for f in "us_overnight_${DATE}.json" "us_${DATE}.json" "source_status.json"; do
  if [ -f "exports/$f" ]; then
    rsync -az "exports/$f" "$ALIYUN_DC_USER@$ALIYUN_DC_HOST:$REMOTE/exports/"
  fi
done

echo "[premarket] 3/4 阿里云合成盘前报告 ..."
$SSH "cd $REMOTE && ./.venv/bin/python -c \"import sys;sys.path.insert(0,'src');from research_view import report;print('premarket:',report.persist_premarket('$DATE'))\""

echo "[premarket] 4/4 阿里云重建 dashboard + 拉回 webdata/ ..."
$SSH "cd $REMOTE && ./.venv/bin/python -c \"import sys;sys.path.insert(0,'src');from research_view import export;print(export.build_dashboard('$DATE'))\""
rsync -az "$ALIYUN_DC_USER@$ALIYUN_DC_HOST:$REMOTE/exports/"{dashboard,trends,news,reflections}.json webdata/
alert_clear premarket
echo "[premarket] 完成。前端 8092 已读取盘前报告。"
