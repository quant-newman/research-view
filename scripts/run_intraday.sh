#!/usr/bin/env bash
# 盘中轻量刷新(台北侧编排):ssh 阿里云跑 run_light(采集→漏斗→B1→研报→导出)→
#   rsync dashboard.json 回本机 webdata/。cron 每 15 分钟跑,只刷新闻/研报,行情不动。
# 用法: bash scripts/run_intraday.sh [YYYYMMDD]
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

# 失败告警旗标(装在 flock 之前:锁等待超时也走告警,不再无声退出)
source scripts/lib_alert.sh
mkdir -p webdata
trap 'alert_set intraday 盘中 "盘中刷新失败,数据可能陈旧(logs/intraday-*.log)"' ERR

# 全局串行锁:盘前/盘中/盘后/美股/信函 编排都会重建 dashboard.json 并 rsync 回 webdata,
# 并发会写坏文件 → flock 排队。等 900s:美股时段(UTC+8 22:00/23:00)整点 run_us
# 全量构建约 10min,300s 不够会让盘中档每晚整点例行超时+误告警(2026-07-03 首撞实测)。
exec 9>/tmp/rv_orchestrate.lock
flock -w 900 9
DATE="${1:-$(TZ=Asia/Shanghai date +%Y%m%d)}"
# LogLevel=ERROR 压掉 known-hosts Warning——不再需要 grep -v 过滤,rsync/ssh 退出码
# 原样生效(旧版 "| grep -v ... || true" 会吞掉拉回失败,前端静默用旧数据)。
SSH_BASE="-i $HOME/.ssh/aliyun_dc_ed25519 -o IdentitiesOnly=yes -o ConnectTimeout=20 -o LogLevel=ERROR"
SSH="ssh $SSH_BASE $ALIYUN_DC_USER@$ALIYUN_DC_HOST"
export RSYNC_RSH="ssh $SSH_BASE"
REMOTE=/opt/research_view

$SSH "cd $REMOTE && ./.venv/bin/python scripts/run_light.py $DATE"
rsync -az "$ALIYUN_DC_USER@$ALIYUN_DC_HOST:$REMOTE/exports/"{dashboard,trends,news}.json webdata/
alert_check_fresh 30  # export 在 run_light 内失败不影响退出码,以拉回文件新鲜度兜底
alert_clear intraday
# 盘中资金异动 Web Push(读刚拉回的 dashboard.json;无订阅/无新异动秒退,失败不阻塞编排)
.venv-taipei/bin/python scripts/push_alerts.py || true
