# research-view · A股 AI 科技投研决策雷达看板

A股 AI 科技产业链投研**决策雷达**(公众版):捕捉变化/增量,不陈列状态/存量。
目标"每天 5 分钟,比不看它多知道一件对决策有用的事"。

**主目标·三层漏斗**:大盘状态(环境)→ 板块/产业链轮动(方向,48 节点参照层)→ 重点个股(信号共振浮出)。

**判断权铁律**:LLM(DeepSeek)只呈现变化 + 提取事实 + 做分类(选择题),**绝不下投资判断**。
主线结论留白给使用者填。牛市视角(叙事+资金为主维度),唯一纪律是证伪条件。时间口径全系统 **UTC+8**。

> 规划文档见 `docs/`(CONTEXT 设计意图 / BUILD_SPEC 工程 / ASSETS_AND_SPECS 细节 / SUPPLEMENT_2 补充)。

## 架构(双节点)

- **数据节点(境内网络)**:采集(Tushare/东财)+ PostgreSQL 库 `research_view`;
  只读共享数据中心 `marketdata`(行情/财务/资金/龙虎榜,每日更新,DB 层物理只读)。
- **编排节点(境外网络)**:海外源抓取(yfinance 美股/RSS 舆情/基金信函/X)+ 编排 cron
  + React 前端(Docker/nginx)。两节点间 SSH 密钥同步(rsync/scp)。

## 产品形态

导航 8 页:报告 / 热点 / 资金 / 热力 / 新闻 / 研究 / 信函 / 系统,顶部 A股|美股 切换,手机自适应。

- **报告(B3,演进式)**:盘前锚点 → 盘中增量时间线(有实质变化才追加,事实层重算防误差累积)
  → 盘后收口(全量事实+当日节奏+跨日对照,top3 标「延续第N天/新出现/反转」)。
- **热点**:统计热度(新闻量/龙虎榜/涨跌)+ DeepSeek 中性归因,升温/降温对比。
- **资金**:48 节点主力净额聚合,当日盘口曲线 + 多日趋势(5/20日+连续天数+资金×涨幅背离)。
- **判断闭环**:报告证伪草稿 → 人工 CLI 审定钉死(append-only 账本)→ 证伪归因。

## 数据库

- `research_view`(owner `rv_rw`):参照层 `node/stock/stock_node/theme_node` + 新闻/事件/报告/
  研报/信函/资金/监控等业务表(见 `sql/` 按序号应用)。
- `marketdata`(只读):`rv_rw` 无写权限(DB 层焊死)。

## 目录

```
data/     参照数据资产(nodes/stock_node_map/theme_node_map + 母表 xlsx)
docs/     规划文档 4 份
sql/      schema 迁移(按序号应用,幂等)
src/research_view/  config/db/llm/funnel/structure/report/export/hotspots/heatmap/moneyflow/...
scripts/  编排脚本(盘前/盘中/盘后/美股/信函)+ 采集器 + 运维(备份/账本/信源状态)
web/      React+TS+Vite+Tailwind+ECharts 前端(静态只读,读 dashboard.json)
```

## 初始化

```bash
cp .env.example .env   # 填 DEEPSEEK/TUSHARE/DSN 等(占位符见文件内注释)
pip install -r requirements.txt
python3 scripts/init_db.py      # 建表 + 载参照数据(在数据节点跑)
```

## 运行节奏(cron,UTC+8)

盘前 08:30 / 盘中每 15min(08:00-23:45,新闻按滚动 24h 配额台账节流)/ 盘后 22:30 /
美股时段每小时 / 信函每周三晨;数据库每日备份并异地留存。
