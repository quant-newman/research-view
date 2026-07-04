# 告警旗标共享库(被各编排脚本 source,不直接执行)。
# 按 job 分文件 webdata/alerts/<key>.json,合并最新一条到 webdata/alert.json(前端
# StatusBar 读单对象红横幅)。任何 job 成功只清自己的旗标——修复旧版单文件互清:
# 盘前失败的告警曾被 15 分钟后一次成功的盘中刷新 rm 掉,故障被掩盖。
# 用法: source scripts/lib_alert.sh
#       trap 'alert_set <key> <job名> "<msg>"' ERR   (装在 flock 之前,锁超时也告警)
#       ... 成功路径末尾 alert_clear <key>
ALERT_DIR="webdata/alerts"

_alert_merge() {
  local latest=""
  latest=$(ls -t "$ALERT_DIR"/*.json 2>/dev/null | head -1) || true
  if [ -n "$latest" ]; then
    cp "$latest" webdata/alert.json
  else
    rm -f webdata/alert.json
  fi
}

alert_set() {
  mkdir -p "$ALERT_DIR"
  # 飞书即时告警(DECISIONS #32):同 key 同 msg 不重复推(盘中每15min重试同错只推第一次)
  local old_msg=""
  old_msg=$(grep -o '"msg":"[^"]*"' "$ALERT_DIR/$1.json" 2>/dev/null || true)
  printf '{"job":"%s","at":"%s","msg":"%s"}\n' \
    "$2" "$(TZ=Asia/Shanghai date '+%F %T')" "$3" > "$ALERT_DIR/$1.json"
  _alert_merge
  if [ "$old_msg" != "\"msg\":\"$3\"" ]; then
    python3 "$(dirname "${BASH_SOURCE[0]}")/notify_feishu.py" alert "$2" "$3" >/dev/null 2>&1 || true
  fi
}

alert_clear() {
  rm -f "$ALERT_DIR/${1}.json"
  _alert_merge
}
