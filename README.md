# research-view · A股 AI 科技投研决策雷达看板

自用的 A股 AI 科技产业链投研**决策雷达**(独立产品):捕捉变化/增量,不陈列状态/存量。
目标"每天 5 分钟,比不看它多知道一件对决策有用的事"。

**判断权铁律**:LLM(DeepSeek)只呈现变化 + 提取事实 + 做分类(选择题),**绝不下投资判断**。
主线结论留白给使用者填。牛市视角(叙事+资金为主维度),唯一纪律是证伪条件。时间口径全系统 **UTC+8**。

> 规划文档见 `docs/`(CONTEXT 设计意图 / BUILD_SPEC 工程 / ASSETS_AND_SPECS 细节 / SUPPLEMENT_2 补充)。

## 架构(两地)

- **阿里云(国内数据侧)**:采集(Tushare/东财/互动易)+ PostgreSQL 库 `research_view`。
  只读共享数据中心 `marketdata`(行情/财务/资金/龙虎榜,已灌好,每日更新)。
- **台北 AWS(本机)**:汇总 + DeepSeek 生成 + yfinance 美股 + React 前端。

本项目**独立**,现阶段与已有 `radar` 项目无关(仅只读共享 marketdata)。

## 数据库

- `research_view`(owner `rv_rw`):本项目自有表。
- `marketdata`(只读):`rv_rw` 在 DB 层无写权限(物理只读)。
- 已建表:参照层 `node/stock/stock_node/theme_node`;持仓层 `holdings/watchlist`。

## 目录

```
data/     参照数据资产(nodes/stock_node_map/theme_node_map + 母表 xlsx)
docs/     规划文档 4 份
sql/      schema(按序号应用)
src/research_view/  config / db / (后续)collect / report / ...
scripts/  init_db / gen_reference_sql / manage_holdings
```

## 初始化

```bash
cp .env.example .env   # 填 DEEPSEEK/TUSHARE/DSN/RV_DB_PASS
pip install -r requirements.txt
python3 scripts/init_db.py      # 建表 + 载参照数据(在阿里云侧跑)
```

## 进度

见 GitHub 任务 / `docs/`。当前:第 0 步(数据底座+隔离建库)✅、第 0.5 步(持仓层)✅。
