#!/usr/bin/env bash
# 每日数据刷新(台北侧运行):阿里云生成 dashboard.json → 拉到本地 webdata/。
# 容器挂载 webdata,数据即时生效,无需重建镜像。
# 用法: bash scripts/sync_dashboard.sh [YYYYMMDD]
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
DATE="${1:-$(TZ=Asia/Shanghai date +%Y%m%d)}"
# LogLevel=ERROR 压掉 known-hosts Warning,ssh/rsync 退出码原样生效(07-21 审查阻塞项2:
# 原 "| grep -v … || true" 会吞同步失败——reflections 含公开/私密切换,同步失败禁静默)
SSH_BASE="-i $HOME/.ssh/aliyun_dc_ed25519 -o IdentitiesOnly=yes -o ConnectTimeout=20 -o LogLevel=ERROR"
SSH="ssh $SSH_BASE $ALIYUN_DC_USER@$ALIYUN_DC_HOST"

echo "[sync] 阿里云生成 dashboard $DATE ..."
$SSH "cd /opt/research_view && ./.venv/bin/python -c \"import sys;sys.path.insert(0,'src');from research_view import export;print(export.build_dashboard('$DATE'))\""

echo "[sync] 拉回 webdata/ ..."
export RSYNC_RSH="ssh $SSH_BASE"
mkdir -p webdata
rsync -az "$ALIYUN_DC_USER@$ALIYUN_DC_HOST:/opt/research_view/exports/"{dashboard,trends,news,reflections}.json webdata/
echo "[sync] 完成。容器已自动读取新数据(8092)。"
