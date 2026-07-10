#!/usr/bin/env bash
# 纯资金档高频刷新(台北侧编排):ssh 阿里云跑 run_light --mf-only(补采→快照→导出,
#   约2s,无 DeepSeek/新闻配额)→ rsync dashboard/trends 回本机 webdata/。
# cron 每5min 火(:05/:10/:20/:25/:35/:40/:50/:55),:00/:15/:30/:45 归全量档 run_intraday,
#   两档合起来资金曲线=5分钟分辨率。快照按(日期,数据时点)幂等,午休/收盘自动跳过。
# 用法: bash scripts/run_mf.sh [YYYYMMDD]
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

source scripts/lib_alert.sh
mkdir -p webdata
trap 'alert_set mf 资金档 "资金5分钟档失败,盘中曲线可能陈旧(logs/mf-*.log)"' ERR

# 与其他编排共用全局串行锁,但高频档不排队:锁忙(全量档/美股构建在跑,它们本身就带
# 资金步骤或已出交易时段)直接跳过本火点,5分钟后下个火点自然补上。
exec 9>/tmp/rv_orchestrate.lock
if ! flock -n 9; then
  echo "[MF] 锁忙,本火点跳过"
  exit 0
fi
DATE="${1:-$(TZ=Asia/Shanghai date +%Y%m%d)}"
SSH_BASE="-i $HOME/.ssh/aliyun_dc_ed25519 -o IdentitiesOnly=yes -o ConnectTimeout=20 -o LogLevel=ERROR"
SSH="ssh $SSH_BASE $ALIYUN_DC_USER@$ALIYUN_DC_HOST"
export RSYNC_RSH="ssh $SSH_BASE"
REMOTE=/opt/research_view

$SSH "cd $REMOTE && ./.venv/bin/python scripts/run_light.py $DATE --mf-only"
rsync -az "$ALIYUN_DC_USER@$ALIYUN_DC_HOST:$REMOTE/exports/"{dashboard,trends,news}.json webdata/
alert_check_fresh 30  # export 在 run_light --mf-only 内失败不影响退出码,以拉回文件新鲜度兜底
alert_clear mf
# 盘中资金异动 Web Push(读刚拉回的 dashboard.json;无订阅/无新异动秒退,失败不阻塞编排)
.venv-taipei/bin/python scripts/push_alerts.py || true
