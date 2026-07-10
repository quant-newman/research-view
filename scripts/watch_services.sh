#!/usr/bin/env bash
# 服务级看门狗:常驻服务探活(web容器HTTP/chat健康接口/宿主nginx),cron 每5分钟。
# 与 lib_alert 体系互补:lib_alert 管编排 job 失败,本脚本管服务"假活"——容器 Up 但
#   5xx/超时、docker 守护死、宿主 nginx 挂,这些原来只能等人肉发现。
# 策略:探活失败→自动拉起→8s 后复探;恢复=发飞书留痕,仍失败=alert_set(飞书+红横幅,
#   同 key 同 msg 去重,持续故障只推第一次)。任何一路恢复即清自己的旗标。
set -uo pipefail
cd "$(dirname "$0")/.."
source scripts/lib_alert.sh

# 独立锁(不占编排锁 rv_orchestrate.lock:探活不该被数据管线排队,反之亦然)
exec 9>/tmp/rv_svcwatch.lock
flock -n 9 || exit 0

UA="Mozilla/5.0 (svcwatch)"  # 容器 nginx 对空/bot UA 一律 403
probe_web()  { [ "$(curl -m 8 -sA "$UA" -o /dev/null -w '%{http_code}' http://127.0.0.1:8092/)" = 200 ]; }
probe_chat() { curl -m 8 -sA "$UA" http://127.0.0.1:8092/api/chat/health 2>/dev/null | grep -q '"ok":true'; }
probe_ngx()  { systemctl is-active --quiet nginx; }

guard() {  # guard <key> <显示名> <probe函数> <拉起命令...>
  local key="$1" name="$2" probe="$3"; shift 3
  if "$probe"; then alert_clear "svc_$key"; return; fi
  echo "[$(TZ=Asia/Shanghai date '+%F %T')] $name 探活失败,尝试拉起: $*"
  "$@" >/dev/null 2>&1 || true
  sleep 8
  if "$probe"; then
    echo "  已自动拉起恢复"
    python3 scripts/notify_feishu.py alert "$name" "曾失联,看门狗已自动拉起恢复" >/dev/null 2>&1 || true
    alert_clear "svc_$key"
  else
    echo "  拉起无效,发告警"
    alert_set "svc_$key" "$name" "探活失败且自动拉起无效,需人工介入(logs/svcwatch-*.log)"
  fi
}

guard web  Web前端看板 probe_web  docker restart research-view-web
guard chat Chat问答后端 probe_chat docker restart research-view-chat
guard ngx  "宿主nginx(HTTPS入口)" probe_ngx sudo -n systemctl restart nginx
