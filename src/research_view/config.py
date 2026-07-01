"""集中配置:从 .env 读密钥/DSN/路径。时间口径 UTC+8(Asia/Shanghai)。"""
from __future__ import annotations

import os
from pathlib import Path

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


def tushare_token() -> str:
    return require("TUSHARE_TOKEN")
