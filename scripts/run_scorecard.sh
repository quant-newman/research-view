#!/usr/bin/env bash
# B7 周度成绩单(台北侧编排,周日跑):ssh 阿里云 补记分(容错周内盘后漏跑)→ 周度收口
#   (汇总+DeepSeek错误归纳+lessons 回灌下周 B6)→ 重建 dashboard → rsync 回 webdata/。
# 用法: bash scripts/run_scorecard.sh [YYYYMMDD]
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

source scripts/lib_alert.sh
mkdir -p webdata
trap 'alert_set scorecard 成绩单 "B7周度成绩单失败(logs/scorecard-*.log)"' ERR

# 全局串行锁(与盘前/盘中/盘后/美股/信函共用);周日无美股整点重建,900s 足够
exec 9>/tmp/rv_orchestrate.lock
flock -w 900 9
DATE="${1:-$(TZ=Asia/Shanghai date +%Y%m%d)}"
SSH_BASE="-i $HOME/.ssh/aliyun_dc_ed25519 -o IdentitiesOnly=yes -o ConnectTimeout=20 -o LogLevel=ERROR"
SSH="ssh $SSH_BASE $ALIYUN_DC_USER@$ALIYUN_DC_HOST"
export RSYNC_RSH="ssh $SSH_BASE"
REMOTE=/opt/research_view

echo "[scorecard $(TZ=Asia/Shanghai date '+%F %T') UTC+8] 阿里云 B7 周度收口 $DATE ..."
$SSH "cd $REMOTE && ./.venv/bin/python -c \"
import sys; sys.path.insert(0, 'src')
from research_view import export, scorecard
print('  score_mature:', scorecard.score_mature())
print('  weekly:', scorecard.weekly('$DATE'))
print('  dashboard:', export.build_dashboard('$DATE'))
\""

echo "[scorecard] 拉回 dashboard.json → webdata/ ..."
rsync -az "$ALIYUN_DC_USER@$ALIYUN_DC_HOST:$REMOTE/exports/"{dashboard,trends,news,reflections}.json webdata/

alert_clear scorecard
# 飞书周报出炉通知(DECISIONS #32)
python3 scripts/notify_feishu.py weekly || true
echo "[scorecard] 完成。"
