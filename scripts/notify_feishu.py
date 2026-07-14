#!/usr/bin/env python3
"""飞书值班通知(DECISIONS #32):失败告警 + 盘后摘要 + 周报出炉。编排节点侧跑。

用法: notify_feishu.py alert <job> <msg>     # 任务失败(lib_alert.sh 钩子,同 msg 去重后调)
      notify_feishu.py summary               # 盘后收口摘要(读 webdata/dashboard.json)
      notify_feishu.py weekly                # 周日成绩单出炉
      notify_feishu.py test [文本]           # 接入测试

.env 需 FEISHU_WEBHOOK(+建议 FEISHU_SECRET 签名校验);未配置=静默跳过,永不阻塞编排。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _env() -> dict:
    out = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip()
    return out


def send(text: str) -> bool:
    env = _env()
    url = env.get("FEISHU_WEBHOOK")
    if not url:
        return False  # 未配置=静默跳过
    body: dict = {"msg_type": "text", "content": {"text": text}}
    secret = env.get("FEISHU_SECRET")
    if secret:
        ts = str(int(time.time()))
        key = f"{ts}\n{secret}".encode()
        body["timestamp"] = ts
        body["sign"] = base64.b64encode(hmac.new(key, b"", hashlib.sha256).digest()).decode()
    req = urllib.request.Request(url, json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            resp = json.loads(r.read().decode())
        ok = resp.get("code") == 0 or resp.get("StatusCode") == 0
        if not ok:
            print(f"feishu 拒收: {resp}", file=sys.stderr)
        return ok
    except Exception as e:  # noqa: BLE001 通知失败绝不阻塞编排
        print(f"feishu 发送失败: {e}", file=sys.stderr)
        return False


def _dash() -> dict:
    try:
        return json.loads((ROOT / "webdata" / "dashboard.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def summary() -> str:
    d = _dash()
    day = (d.get("meta") or {}).get("date") or ""
    jn = len((d.get("judgment") or {}).get("cards") or [])
    dn = len((d.get("decision") or {}).get("cards") or [])
    sc = d.get("scorecard") or {}
    cum = sc.get("cum") or {}
    health = (d.get("health") or {}).get("level") or "?"
    mark = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(health, "⚪")
    lines = [f"📋 盘后收口 {day}",
             f"B6节点卡 {jn} 张 · B8决策卡 {dn} 张 · 待记分 {sc.get('pending', 0)}",
             f"累计记分 {cum.get('n', 0)}(对{cum.get('right', 0)}/错{cum.get('wrong', 0)})"
             + (f" 命中率 {cum['hit_rate']}%" if cum.get("hit_rate") is not None else ""),
             f"health {mark} {health}"]
    try:
        alert = json.loads((ROOT / "webdata" / "alert.json").read_text(encoding="utf-8"))
        lines.append(f"⚠ 未清告警: {alert.get('job')} {alert.get('msg')}")
    except Exception:  # noqa: BLE001 无 alert.json=无未清告警
        pass
    return "\n".join(lines)


def weekly() -> str:
    d = _dash()
    sc = d.get("scorecard") or {}
    cum, wk = sc.get("cum") or {}, sc.get("weekly") or {}
    bl = (sc.get("baseline") or {}).get("mech") or {}
    lines = [f"📊 B7 周度成绩单出炉({wk.get('week_end', '')})",
             f"累计 {cum.get('n', 0)} 张:对{cum.get('right', 0)}/错{cum.get('wrong', 0)}/平{cum.get('flat', 0)}"
             + (f" 命中率 {cum['hit_rate']}%" if cum.get("hit_rate") is not None else "(暂无到期)")]
    if bl.get("hit_rate") is not None:
        lines.append(f"机械基线 {bl['hit_rate']}%(LLM 不优于它即应被砍,对照公开)")
    lessons = wk.get("lessons") or []
    if lessons:
        lines.append("本周教训: " + "；".join(lessons[:3]))
    lines.append("详情看板 → 报告页右栏")
    return "\n".join(lines)


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "test"
    if mode == "alert":
        job = sys.argv[2] if len(sys.argv) > 2 else "?"
        msg = sys.argv[3] if len(sys.argv) > 3 else ""
        # 服务器系统时区为 UTC,strftime 不带 tz 会把 UTC 时间标成 UTC+8(07-13 首撞:06:16 实为 14:16)
        stamp = time.strftime("%F %T", time.gmtime(time.time() + 8 * 3600))
        ok = send(f"🔴 任务失败: {job}\n{msg}\n{stamp} UTC+8 · 看板 StatusBar 有红横幅")
    elif mode == "summary":
        ok = send(summary())
    elif mode == "weekly":
        ok = send(weekly())
    else:
        ok = send(sys.argv[2] if len(sys.argv) > 2 else
                  "✅ 飞书值班通知接入成功(签名校验已启用)。此后:任务失败即时告警 / 每日22:30盘后摘要 / 周日成绩单出炉。")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
