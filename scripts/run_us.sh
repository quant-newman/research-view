#!/usr/bin/env bash
# 美股独立刷新(台北侧编排):台北 build_us(行情+基本面+新闻B1+研究+报告B3)→
#   scp us_DATE.json 到阿里云 → 重建 dashboard(挂 us blob)→ 拉回 webdata/。
# 美股一等公民,数据全在台北算(连 Yahoo)。可手动、与盘前一起、或美股时段 cron 每小时跑。
# 用法: bash scripts/run_us.sh [YYYYMMDD]
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

# 全局串行锁:盘前/盘中/盘后/美股 四编排都会重建 dashboard.json 并 rsync 回 webdata,
# 并发会写坏文件 → flock 排队(最多等 300s,超时报错走各自告警路径)。
exec 9>/tmp/rv_orchestrate.lock
flock -w 300 9
# 日期口径:UTC+8 减 6 小时归属交易日——美股收盘=UTC+8 凌晨 4-5 点,跨午夜的盘中刷新
# 仍写前一天的 us_DATE.json 并按前一天重建 dashboard(A股各栏不被翻到空的新一天)。
DATE="${1:-$(TZ=Asia/Shanghai date -d '-6 hours' +%Y%m%d)}"

# 失败告警旗标:失败写 webdata/alert.json(前端红横幅),成功清除。
mkdir -p webdata
trap 'echo "{\"job\":\"美股刷新\",\"at\":\"$(TZ=Asia/Shanghai date "+%F %T")\",\"msg\":\"美股刷新失败,美股页可能陈旧(logs/us-*.log)\"}" > webdata/alert.json' ERR
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
rsync -az "$ALIYUN_DC_USER@$ALIYUN_DC_HOST:$REMOTE/exports/"{dashboard,trends}.json webdata/ 2>&1 | grep -v "Warning: Permanently" || true
rm -f webdata/alert.json
echo "[us] 完成。前端顶部切"美股"即见。"
