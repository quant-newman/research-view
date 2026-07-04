#!/usr/bin/env python3
"""独立看门狗(DECISIONS #33,定向吸收 radar 审视教训 P1-5/P0-3)。每日 23:50 UTC+8 cron。

独立性纪律:不 import src/ 与 notify_feishu.py——管线代码坏了不能陪葬告警链;
飞书 webhook 读项目 .env,.env 丢失时回退 ~/.config/mofang_watchdog.env 备份副本
(轮换 webhook 须两处同步,radar 同款残余)。

检查与出声("只异常出声"+周一心跳):
  🔴 项目 .env 丢失(根因级,经备份副本发出) / dashboard.json 不可读或超 20h 未更新
     ——覆盖 lib_alert 的盲区:cron 整体没跑/flock 卡死/机器半死时没有任何 job 会告警
  🟡 交易日收口后"成功但为空":B6/B8 无当日卡、新闻 0 条、资金/热点/B3 回退旧日
     ——radar P0-3 模式(上游静默退化成空结果,管线自己报 OK)
  🟢 周一心跳:证明看门狗+webhook 链路活着;周一没收到=整机宕,人肉 dead-man

用法: watchdog.py [--dry-run|--test]
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKUP_ENV = Path.home() / ".config" / "mofang_watchdog.env"
TZ8 = timezone(timedelta(hours=8))
STALE_HOURS = 20  # 昨晚23:30最后一刷→今晚23:50=24.3h 必命中;周六 vs 早晨美股档 18.8h 不误报


def _parse_env(path: Path) -> dict:
    out = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def send(text: str, dry: bool = False) -> bool:
    if dry:
        print(f"[dry-run] {text}")
        return True
    env = _parse_env(ROOT / ".env") or _parse_env(BACKUP_ENV)
    url = env.get("FEISHU_WEBHOOK")
    if not url:
        print("无可用 webhook(.env 与备份副本均缺),告警链断", file=sys.stderr)
        return False
    body: dict = {"msg_type": "text", "content": {"text": text}}
    secret = env.get("FEISHU_SECRET")
    if secret:
        ts = str(int(time.time()))
        key = f"{ts}\n{secret}".encode()
        body["timestamp"] = ts
        body["sign"] = base64.b64encode(hmac.new(key, b"", hashlib.sha256).digest()).decode()
    req = urllib.request.Request(url, json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    for attempt in range(3):  # radar P2-10 教训:告警单点须重试
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                resp = json.loads(r.read().decode())
            if resp.get("code") == 0 or resp.get("StatusCode") == 0:
                return True
            print(f"feishu 拒收: {resp}", file=sys.stderr)
            return False  # 拒收(签名/格式错)重试无益
        except Exception as e:  # noqa: BLE001
            print(f"feishu 第{attempt + 1}次失败: {e}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    return False


def _norm(d) -> str:
    return str(d or "").replace("-", "")


def check() -> tuple[list[str], list[str], str]:
    """返回 (red, yellow, 状态一行)。只读 webdata/dashboard.json,不连库不碰管线。"""
    red: list[str] = []
    yellow: list[str] = []
    now = datetime.now(TZ8)
    today = now.strftime("%Y%m%d")

    if not (ROOT / ".env").exists():
        red.append("项目 .env 丢失(编排全链将陆续断,本条经备份 webhook 发出)")

    dash_path = ROOT / "webdata" / "dashboard.json"
    try:
        d = json.loads(dash_path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        red.append(f"dashboard.json 不可读({e}),前端已黑屏级故障")
        return red, yellow, "dashboard 不可读"

    meta = d.get("meta") or {}
    age_h = None
    try:
        gen = datetime.fromisoformat(meta.get("generated_at"))
        age_h = (now - gen).total_seconds() / 3600
    except (TypeError, ValueError):
        red.append("meta.generated_at 缺失/不可解析")
    if age_h is not None and age_h > STALE_HOURS:
        red.append(f"dashboard 已 {age_h:.1f}h 未更新(阈值{STALE_HOURS}h)——编排链疑似整体停摆")

    market = d.get("market") or {}
    trade_date = _norm(market.get("trade_date") or (d.get("temperature") or {}).get("trade_date"))
    status = (f"dashboard {age_h:.1f}h 前更新" if age_h is not None else "更新时间未知") \
        + f" · 最近交易日 {trade_date or '?'}"

    # 交易日判据=行情最新交易日==今天(节假日自然跳过,无需交易日历)。
    # 只在收口后跑(23:50)才成立:盘后 22:30 全量已把 market 刷到当日。
    if trade_date == today and _norm(meta.get("date")) == today:
        if not meta.get("news_relevant"):
            yellow.append("当日相关新闻 0 条(采集成功但为空?)")
        jd = d.get("judgment") or {}
        if _norm(jd.get("date")) != today or not jd.get("cards"):
            yellow.append("B6 无当日节点卡(回退旧日)")
        dc = d.get("decision") or {}
        if _norm(dc.get("date")) != today or not dc.get("cards"):
            yellow.append("B8 无当日决策卡(回退旧日)")
        mf = d.get("moneyflow") or {}
        if _norm(mf.get("date")) != today or not mf.get("stocks"):
            yellow.append("资金面无当日数据")
        rp = d.get("report") or {}
        if not str(rp.get("report_id", "")).startswith(today) or rp.get("session") != "afterhours":
            yellow.append("B3 盘后报告未收口")
        hs = d.get("hotspot") or {}
        if _norm(hs.get("date")) != today:
            yellow.append("热点榜回退旧日")

    if not BACKUP_ENV.exists():
        yellow.append(f"webhook 备份副本缺失({BACKUP_ENV}),.env 一丢告警链全哑")
    return red, yellow, status


def main() -> None:
    dry = "--dry-run" in sys.argv
    if "--test" in sys.argv:
        ok = send("🐶 看门狗接入测试:独立于管线代码,每日 23:50 体检,只异常出声+周一心跳。", dry)
        sys.exit(0 if ok else 1)

    red, yellow, status = check()
    now = datetime.now(TZ8)
    stamp = now.strftime("%F %T")
    print(f"[watchdog {stamp} UTC+8] {status} · red={len(red)} yellow={len(yellow)}")

    msg = None
    if red:
        msg = "🔴 看门狗: " + "；".join(red)
        if yellow:
            msg += "\n附🟡: " + "；".join(yellow)
    elif yellow:
        msg = "🟡 看门狗(成功但为空/回退): " + "；".join(yellow)
    elif now.weekday() == 0:  # 周一心跳,证明这条链活着
        msg = f"🟢 看门狗周一心跳: 链路正常 · {status}"
    if msg:
        send(f"{msg}\n{stamp} UTC+8", dry)
    sys.exit(1 if red else 0)


if __name__ == "__main__":
    main()
