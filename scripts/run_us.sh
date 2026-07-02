#!/usr/bin/env bash
# 美股独立刷新(台北侧编排):台北 build_us(行情+基本面+新闻B1+研究+报告B3)→
#   scp us_DATE.json 到阿里云 → 重建 dashboard(挂 us blob)→ 拉回 webdata/。
# 美股一等公民,数据全在台北算(连 Yahoo)。可手动或与盘前一起跑。
# 用法: bash scripts/run_us.sh [YYYYMMDD]
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
DATE="${1:-$(TZ=Asia/Shanghai date +%Y%m%d)}"  # 与 dashboard 的 UTC+8 日期口径一致
SSH_BASE="-i $HOME/.ssh/aliyun_dc_ed25519 -o IdentitiesOnly=yes -o ConnectTimeout=20"
SSH="ssh $SSH_BASE $ALIYUN_DC_USER@$ALIYUN_DC_HOST"
export RSYNC_RSH="ssh $SSH_BASE"
REMOTE=/opt/research_view

echo "[us] 1/3 台北构建美股全量数据 $DATE ..."
./.venv-taipei/bin/python scripts/build_us.py "$DATE"

echo "[us] 2/3 推送 us_${DATE}.json → 阿里云 ..."
rsync -az "exports/us_${DATE}.json" "$ALIYUN_DC_USER@$ALIYUN_DC_HOST:$REMOTE/exports/" 2>&1 | grep -v "Warning: Permanently" || true

echo "[us] 3/3 重建 dashboard + 拉回 ..."
$SSH "cd $REMOTE && ./.venv/bin/python -c \"import sys;sys.path.insert(0,'src');from research_view import export;print(export.build_dashboard('$DATE'))\"" 2>&1 | grep -v "Warning: Permanently"
mkdir -p webdata
rsync -az "$ALIYUN_DC_USER@$ALIYUN_DC_HOST:$REMOTE/exports/"{dashboard,trends}.json webdata/ 2>&1 | grep -v "Warning: Permanently" || true
echo "[us] 完成。前端顶部切"美股"即见。"
