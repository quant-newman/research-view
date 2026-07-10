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

# 导出新鲜度校验(rsync 拉回 dashboard 后调):run_pipeline/run_light 里 step() 吞错,
# export 步骤失败时 Python 仍 exit 0,拉回的是旧文件——health 红角标/飞书盘后摘要读的
# 都是旧 health,看门狗 20h 阈值当晚也不命中,可静默一天以上。这里核对 generated_at
# 距今分钟数兜底。共享 export 旗标:任一编排拉回新鲜文件即恢复;msg 固定,飞书同错不重推。
# 用法: alert_check_fresh <max_age_min>
alert_check_fresh() {
  local age
  age=$(python3 -c 'import json
from datetime import datetime, timezone
g = datetime.fromisoformat(json.load(open("webdata/dashboard.json"))["meta"]["generated_at"])
print(int((datetime.now(timezone.utc) - g).total_seconds() / 60))' 2>/dev/null) || age=9999
  if [ "${age:-9999}" -gt "$1" ]; then
    alert_set export 导出 "dashboard.json 未刷新(export 步骤疑似失败:管线降级续跑不报错,查阿里云 task_log/health)"
  else
    alert_clear export
  fi
}
