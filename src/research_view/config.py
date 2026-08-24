"""集中配置:从 .env 读密钥/DSN/路径。时间口径 UTC+8(Asia/Shanghai)。"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# 项目根 = 本文件上溯三级(src/research_view/config.py -> 项目根)
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"          # 参照数据资产(nodes / stock_node_map / theme_node_map)
SQL_DIR = ROOT / "sql"

TZ = "Asia/Shanghai"              # 全系统 UTC+8


def _load_dotenv() -> None:
    """极简 .env 加载(不依赖第三方,已存在的环境变量优先)。"""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        os.environ.setdefault(key, val)


_load_dotenv()


def require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"缺少环境变量 {name}(检查 .env)")
    return val


# 常用配置(惰性读取,缺失时在使用点报错)
def research_view_dsn() -> str:
    return require("RESEARCH_VIEW_DSN")


def marketdata_ro_dsn() -> str:
    return require("MARKETDATA_RO_DSN")


def deepseek() -> tuple[str, str]:
    return require("DEEPSEEK_API_KEY"), os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")


def deepseek_model() -> str:
    """默认用平台最新最强旗舰(2026-07 实测 /models 只有 v4-flash/v4-pro;
    旧别名 deepseek-chat 现指向 v4-flash 小模型,别再用)。可用 .env DEEPSEEK_MODEL 覆盖。"""
    return os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")


def tushare_token() -> str:
    return require("TUSHARE_TOKEN")


# ---- DeepSeek 夜间调用窗口(2026-08-24 降本批#2,使用者拍板)----
# 只在 UTC+8 18:00–08:00 烧 LLM。白天默认静默(新闻照抓照落库,只是不做叙述层),
# 留两档补做点让盘中不至于半天没摘要;补做点对齐 cron 火点 :00/:15/:30/:45——
# 09:45 早盘新闻已出、15:15 收盘后尾盘异动已定。可用 .env LLM_DAY_SLOTS 覆盖。
LLM_NIGHT_FROM, LLM_NIGHT_TO = 18, 8
_DAY_SLOTS_DEFAULT = "0945,1515"


def _slot_hit(now: datetime, slots: list[str]) -> str | None:
    """命中判定给 15 分钟宽限:cron 火点到真正执行之间隔着 flock 排队(最长 900s)与 ssh,
    卡死 HHMM 精确相等会让补做点在编排拥堵时凭空丢失。宽限 <15min 保证一个火点只命中一次。"""
    cur = now.hour * 60 + now.minute
    for s in slots:
        if 0 <= cur - (int(s[:2]) * 60 + int(s[2:])) < 15:
            return s
    return None


def llm_allowed(now: datetime | None = None) -> tuple[bool, str]:
    """这一档该不该调 DeepSeek。返回 (允许, 中文原因)——原因直接进日志,便于事后对账。

    RV_LLM_FORCE=1 全局豁免(手动补跑/取证)。窗口跨零点,故判据是 or 不是 and。
    """
    if os.environ.get("RV_LLM_FORCE") == "1":
        return True, "RV_LLM_FORCE=1 强制"
    now = now or datetime.now(ZoneInfo(TZ))
    if now.hour >= LLM_NIGHT_FROM or now.hour < LLM_NIGHT_TO:
        return True, f"夜间窗口{LLM_NIGHT_FROM}:00–0{LLM_NIGHT_TO}:00"
    slots = [x.strip() for x in os.environ.get("LLM_DAY_SLOTS", _DAY_SLOTS_DEFAULT).split(",") if x.strip()]
    hit = _slot_hit(now, slots)
    if hit:
        return True, f"白天补做点{hit}"
    return False, f"白天静默档{now:%H%M}(窗口18:00–08:00,补做点{'/'.join(slots)})"


def calibration_freeze() -> bool:
    """校准期冻结(DECISIONS #22/#28):冻结时 B7 lessons 只落库不注入发卡 prompt,
    防首批校准样本口径漂移。默认冻结;解冻=显式设 CALIBRATION_FREEZE=0(须记 DECISIONS)。"""
    return os.environ.get("CALIBRATION_FREEZE", "1") != "0"
