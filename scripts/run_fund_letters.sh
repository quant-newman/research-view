#!/usr/bin/env bash
# 基金信函流程(台北侧编排):
#   1) 台北抓海外信函(国内连不了)+ DeepSeek B5 摘要 → exports/fund_letters_DATE.json
#   2) scp 到阿里云 → 入库 fund_letter → 重建 dashboard → 拉回 webdata/
# 低频跑(信函多为季度/周更),手动或每周 cron。
# 用法: bash scripts/run_fund_letters.sh [YYYYMMDD] [源key] [每源篇数]
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

# 失败告警旗标 + 全局串行锁(旧版此脚本漏了两者:它同样重建 dashboard 并 rsync 回 webdata)
source scripts/lib_alert.sh
mkdir -p webdata
trap 'alert_set letters 信函 "信函流程失败,信函页可能陈旧(logs/letters-*.log)"' ERR
exec 9>/tmp/rv_orchestrate.lock
flock -w 300 9

DATE="${1:-$(TZ=Asia/Shanghai date +%Y%m%d)}"
SRC="${2:-oaktree,blackrock,gs,ms}"
LIMIT="${3:-2}"
# LogLevel=ERROR 压掉 known-hosts Warning,rsync/ssh 退出码原样生效(不再 grep/|| true 吞错)
SSH_BASE="-i $HOME/.ssh/aliyun_dc_ed25519 -o IdentitiesOnly=yes -o ConnectTimeout=20 -o LogLevel=ERROR"
SSH="ssh $SSH_BASE $ALIYUN_DC_USER@$ALIYUN_DC_HOST"
export RSYNC_RSH="ssh $SSH_BASE"
REMOTE=/opt/research_view

echo "[letters] 1/3 台北抓信函 + B5 摘要 ($SRC, 每源$LIMIT篇) ..."
./.venv-taipei/bin/python scripts/fetch_fund_letters.py "$DATE" "$SRC" "$LIMIT"

echo "[letters] 2/3 推送 + 阿里云入库 ..."
rsync -az "exports/fund_letters_${DATE}.json" exports/source_status.json \
  "$ALIYUN_DC_USER@$ALIYUN_DC_HOST:$REMOTE/exports/"
$SSH "cd $REMOTE && ./.venv/bin/python -c \"import sys;sys.path.insert(0,'src');from research_view import fund_letters;print('入库:',fund_letters.ingest(date_utc8='$DATE'))\""

echo "[letters] 3/3 重建 dashboard + 拉回 ..."
$SSH "cd $REMOTE && ./.venv/bin/python -c \"import sys;sys.path.insert(0,'src');from research_view import export;print(export.build_dashboard('$DATE'))\""
rsync -az "$ALIYUN_DC_USER@$ALIYUN_DC_HOST:$REMOTE/exports/"{dashboard,news}.json webdata/
alert_clear letters
echo "[letters] 完成。信函页已更新。"
