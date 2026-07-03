#!/usr/bin/env bash
# 盘中轻量刷新(台北侧编排):ssh 阿里云跑 run_light(采集→漏斗→B1→研报→导出)→
#   rsync dashboard.json 回本机 webdata/。cron 每 30 分钟跑,只刷新闻/研报,行情不动。
# 用法: bash scripts/run_intraday.sh [YYYYMMDD]
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

# 全局串行锁:盘前/盘中/盘后/美股 四编排都会重建 dashboard.json 并 rsync 回 webdata,
# 并发会写坏文件 → flock 排队(最多等 300s,超时报错走各自告警路径)。
exec 9>/tmp/rv_orchestrate.lock
flock -w 300 9
DATE="${1:-$(TZ=Asia/Shanghai date +%Y%m%d)}"
SSH_BASE="-i $HOME/.ssh/aliyun_dc_ed25519 -o IdentitiesOnly=yes -o ConnectTimeout=20"
SSH="ssh $SSH_BASE $ALIYUN_DC_USER@$ALIYUN_DC_HOST"
export RSYNC_RSH="ssh $SSH_BASE"
REMOTE=/opt/research_view

# 失败告警旗标:失败写 webdata/alert.json(前端红横幅),成功清除。
mkdir -p webdata
trap 'echo "{\"job\":\"盘中\",\"at\":\"$(TZ=Asia/Shanghai date "+%F %T")\",\"msg\":\"盘中刷新失败,数据可能陈旧(logs/intraday-*.log)\"}" > webdata/alert.json' ERR

$SSH "cd $REMOTE && ./.venv/bin/python scripts/run_light.py $DATE" 2>&1 | grep -v "Warning: Permanently"
rsync -az "$ALIYUN_DC_USER@$ALIYUN_DC_HOST:$REMOTE/exports/"{dashboard,trends}.json webdata/ 2>&1 | grep -v "Warning: Permanently" || true
rm -f webdata/alert.json
