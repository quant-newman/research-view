# research-view · A股 AI 科技投研决策雷达看板

A股 AI 科技产业链投研**决策雷达**(个人版):捕捉变化/增量,不陈列状态/存量,终极目标=可执行、可追责的"买什么"。
北极星体验:"每天 5 分钟,比不看它多知道一件对决策有用的事"。

**主目标·三层漏斗**:大盘状态(环境)→ 板块/产业链轮动(方向,49 节点参照层)→ 重点个股(收口)。

**铁律:判断必须可追责**——LLM(DeepSeek)可以输出方向/候选/条件,但每条必须带证据链(可溯源到输入)、
证伪条件+时间窗,并进成绩单被自动记分归因;事实层零幻觉标准不变(输入之外的数字/来源一律不写)。
牛市视角(叙事+资金为主维度),时间口径全系统 **UTC+8**。

> 文档体系(`docs/`):**[ARCHITECTURE](docs/ARCHITECTURE.md) 总架构现状 · [ROADMAP](docs/ROADMAP.md) 路线图与队列 ·
> [PROCESS](docs/PROCESS.md) 开发流程规范 · [DECISIONS](docs/DECISIONS.md) 决策记录** ·
> 判断链路设计 [B6 研判卡](docs/B6_JUDGMENT_CARD.md) / [B7 成绩单](docs/B7_SCORECARD.md) / [B8 决策层](docs/B8_DECISION.md) ·
> 开工前规划 4 份(PLAN_CONTEXT/BUILD_SPEC/ASSETS_AND_SPECS/SUPPLEMENT_2,历史文档,冲突处以 ARCHITECTURE 为准)。

## 架构(双节点)

- **数据节点(境内网络)**:采集(Tushare/东财)+ PostgreSQL 库 `research_view`;
  只读共享数据中心 `marketdata`(行情/财务/资金/龙虎榜,每日更新,DB 层物理只读)。
- **编排节点(境外网络)**:海外源抓取(yfinance 美股/RSS 舆情/基金信函/X)+ 编排 cron
  + React 前端(Docker/nginx)。两节点间 SSH 密钥同步(rsync/scp)。

## 产品形态

导航 7 页:报告 / 热点(含新闻流) / 资金 / 热力 / 研究 / 信函 / 系统,顶部 A股|美股 切换,手机自适应。

- **报告(头版化)**:大盘仪表 → 主线 → 今日三件事 → **B6 节点研判卡** → **B8 个股决策卡** → 证伪
  → 盘中节奏 → 综述;B3 演进式(盘前锚点→盘中增量→盘后收口,top3 标「延续第N天/新出现/反转」)。
- **判断链路(可追责闭环)**:B6 六源证据矩阵(z截面/共振/背离,代码算)+ DeepSeek 研判卡 →
  B8 方向节点成分共振出个股决策卡(入场/退出/证伪,价位锚)→ **B7 到期按相对全池超额自动记分**,
  周度成绩单分源归因,错误教训回灌次日发卡 prompt。判断表 append-only,对错都晒。
- **热点**:统计热度(新闻量/龙虎榜/涨跌/资金)+ DeepSeek 中性归因 + 利好/利空要点,卡片下钻直达节点新闻。
- **资金**:49 节点主力净额聚合,当日盘口曲线 + 多日趋势(5/20日+连续天数+资金×涨幅背离)。
- **人工闭环**:报告证伪草稿 → CLI 审定钉死(append-only 账本)→ 证伪归因。

## 数据库

- `research_view`(owner `rv_rw`):参照层 `node/stock/stock_node/theme_node` + 新闻/事件/报告/
  研报/信函/资金/监控等业务表(见 `sql/` 按序号应用)。
- `marketdata`(只读):`rv_rw` 无写权限(DB 层焊死)。

## 目录

```
data/     参照数据资产(nodes/stock_node_map/theme_node_map + 母表 xlsx + sources.json 信源注册表)
docs/     架构/路线图/流程/决策记录 + B6-B8 设计 + 开工前规划4份(历史)
sql/      schema 迁移(按序号应用,幂等;判断表 append-only)
src/research_view/  config/db/llm/funnel/structure/report/export/hotspots/heatmap/moneyflow/
                    market/evidence(B6)/decision(B8)/scorecard(B7)/...
scripts/  编排脚本(盘前/盘中/盘后/美股/信函/成绩单)+ 采集器 + 运维(备份/账本/信源状态)
web/      React+TS+Vite+Tailwind+ECharts 前端(静态只读,读 dashboard.json)
```

## 初始化

```bash
cp .env.example .env   # 填 DEEPSEEK/TUSHARE/DSN 等(占位符见文件内注释)
pip install -r requirements.txt
python3 scripts/init_db.py      # 建表 + 载参照数据(在数据节点跑)
```

## 运行节奏(cron,UTC+8)

盘前 08:30 / 盘中每 15min(08:00-23:45,新闻按滚动 24h 配额台账节流)/ 盘后 22:30(含 B6/B8 发卡+B7 记分)/
美股时段每小时 / 信函每周三晨 / **B7 周度成绩单每周日 20:00**;数据库每日备份并异地留存。
