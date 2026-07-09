#!/usr/bin/env python3
"""盘中资金异动 Web Push 推送(台北侧,run_mf/run_intraday 收尾调,失败不阻塞编排):
读 webdata/dashboard.json 的 moneyflow.alerts(只推当日),对未推过的条目向
logs/chat/push_subs.json 的订阅设备发 Web Push(订阅由 chat 容器 /api/push/subscribe 写入,
VAPID 私钥 vapid_private.pem 两侧共用)。已推状态 logs/push/sent.json 按日滚动;
日上限 30 条防刷屏(超出只进看板不推送)。无订阅/无新异动秒退,不产生任何开销。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TZ8 = timezone(timedelta(hours=8))
SUBS = ROOT / "logs/chat/push_subs.json"
STATE = ROOT / "logs/push/sent.json"
PEM = ROOT / "vapid_private.pem"
VAPID_SUB = os.environ.get("VAPID_SUB", "mailto:admin@example.com")
DAILY_CAP = 30


def main() -> None:
    today = datetime.now(TZ8).strftime("%Y-%m-%d")
    try:
        subs = json.loads(SUBS.read_text())
    except Exception:  # noqa: BLE001 无订阅文件=还没人订阅
        subs = {}
    if not subs:
        print("push_alerts: 无订阅设备,跳过")
        return
    try:
        dash = json.loads((ROOT / "webdata/dashboard.json").read_text())
    except Exception as e:  # noqa: BLE001
        print(f"push_alerts: dashboard 读取失败 {e}")
        return
    blk = (dash.get("moneyflow") or {}).get("alerts") or {}
    if blk.get("date") != today:
        print("push_alerts: 无当日异动")
        return
    state = {"date": today, "sent": [], "n": 0}
    try:
        old = json.loads(STATE.read_text())
        if old.get("date") == today:
            state = old
    except Exception:  # noqa: BLE001 状态文件不存在=今日首跑
        pass
    todo = [a for a in (blk.get("items") or []) if f"{a['hhmm']}-{a['code']}" not in state["sent"]]
    if not todo:
        print("push_alerts: 无新异动")
        return

    from pywebpush import WebPushException, webpush
    sent, dead = 0, set()
    for a in sorted(todo, key=lambda x: x["hhmm"]):
        if state["n"] >= DAILY_CAP:
            print(f"push_alerts: 触及日上限{DAILY_CAP},剩余{len(todo) - sent}条只进看板不推")
            break
        d = a["delta"]
        ratio = f",≈20日日均成交{round(a['ratio'] * 1000) / 10}%" if a.get("ratio") else ""
        cum = (f";今日累计{'+' if (a.get('cum') or 0) > 0 else ''}{a['cum']}亿"
               if a.get("cum") is not None else "")
        payload = json.dumps({
            "title": f"资金异动 · {a['name']}({a['code']})",
            "body": f"{a['hhmm']} 主力15分钟净{'流入 +' if d > 0 else '流出 '}{d}亿{ratio}{cum}",
            "url": f"/?stock={a['code']}",
            "tag": f"mf-{a['code']}",   # 同票通知合并替换,不叠一屏
        }, ensure_ascii=False)
        for ep, s in subs.items():
            if ep in dead:
                continue
            try:
                webpush(subscription_info={"endpoint": ep,
                                           "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}},
                        data=payload, vapid_private_key=str(PEM), vapid_claims={"sub": VAPID_SUB},
                        ttl=3600, headers={"Urgency": "high"}, timeout=10)
            except WebPushException as e:
                st = e.response.status_code if e.response is not None else None
                if st in (404, 410):
                    dead.add(ep)
                else:
                    print(f"push_alerts: 发送失败({st}) {str(e)[:80]}")
            except Exception as e:  # noqa: BLE001 单设备失败不阻塞
                print(f"push_alerts: 发送异常 {str(e)[:80]}")
        state["sent"].append(f"{a['hhmm']}-{a['code']}")
        state["n"] += 1
        sent += 1
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False))
    # 失效订阅就地清理(与 chat 容器同文件;订阅变更频率极低,读改写竞态可忽略)
    if dead:
        try:
            cur = json.loads(SUBS.read_text())
            for ep in dead:
                cur.pop(ep, None)
            SUBS.write_text(json.dumps(cur, ensure_ascii=False, indent=1))
        except Exception:  # noqa: BLE001
            pass
    print(f"push_alerts: 推送{sent}条 → {len(subs) - len(dead)}台设备")


if __name__ == "__main__":
    main()
