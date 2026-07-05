# 总架构(现状,截至 2026-07-03)

> 本文描述**已落地的系统现状**,与开工前规划 4 份(PLAN_CONTEXT/BUILD_SPEC/ASSETS_AND_SPECS/SUPPLEMENT_2)冲突处以本文为准。演进路线见 [ROADMAP.md](ROADMAP.md),关键决策见 [DECISIONS.md](DECISIONS.md)。

## 1. 定位与铁律

个人版「A股 AI 科技产业链投研决策雷达」,终极目标 = 可执行的"买什么"。
**铁律:判断必须可追责**——LLM 可以输出方向/候选/条件,但每条必须:带证据链(可溯源到输入)、带证伪条件+时间窗、进成绩单被记分;事实层零幻觉标准不变。
**分工原则:产出要被记分或复核的,代码算;产出要被人读或需跨源理解的,LLM 写**(可审计性是分界线,不是成本)。

## 2. 双节点架构

```
┌─ 数据节点(境内网络) ─────────────────┐   ┌─ 编排节点(境外网络) ──────────────────┐
│ 采集: Tushare major_news / 东财补采    │   │ 海外源: yfinance 美股 / RSS 舆情       │
│ PostgreSQL:                           │   │        / X(twikit) / 基金信函          │
│  · research_view (rv_rw 读写,业务库)  │◄──┤ 编排 cron 全部在此(ssh 驱动数据节点)   │
│  · marketdata   (只读,数据中心行情库) │──►│ blob scp 过去 / dashboard 拉回来        │
│ run_pipeline / run_light 在此执行     │   │ 前端: React 静态 + nginx Docker :8092  │
└───────────────────────────────────────┘   └────────────────────────────────────────┘
        两节点 SSH 密钥互通(rsync/scp),文档与代码不出现具体云商/城市字样(脱敏红线)
```

- 硬约束:数据节点连不了海外网(yfinance/RSS/X 必须编排节点抓);Tushare 需境内网络;
  PG 仅本地监听(编排节点无法直写库,写操作走 ssh)。
- 前端**静态只读**:读挂载卷里的 `dashboard.json`/`trends.json`,无后端 API、无认证(个人用,已拍板)。

## 3. 数据层(research_view 库,sql/ 按序号迁移)

| 域 | 表 | 说明 |
|---|---|---|
| 参照层 | node(49) / stock / stock_node / theme_node / tech_stock | 产业链节点×票池映射,**人工拍板维护**(改法见 PROCESS §迁移) |
| 新闻 | raw_news | major_news 采集+funnel 规则匹配+B1 结构化(one_line/summary/情绪/票/节点) |
| 事件 | stock_event | 公告(预告/快报/增减持/解禁)+龙虎榜,零 LLM,稳定自然键 |
| 报告 | daily_report / report_increment | B3 盘前/盘后 + 盘中增量时间线(演进式) |
| 判断 | **judgment_card**(B6) / **decision_card**(B8) | **append-only**(触发器焊死),带矩阵快照/证据链/证伪/model |
| 记分 | **card_score / decision_score**(B7) | 分数=行情的确定性函数,upsert 幂等可重算 |
| 成绩单 | b7_weekly | 周度命中率/分源归因/错误归纳/lessons(回灌发卡 prompt) |
| 账本 | ledger | 证伪判断人工钉死,append-only |
| 研究 | research_report / research_digest / fund_letter | 卖方研报+变动榜+机构观点 / 基金信函(B5) |
| 资金 | moneyflow_rt_extra / mf_intraday_node | 盘中自采补充 + 15min 节点累计曲线 |
| 热点/热力 | hotspot_daily / heatmap_node / heatmap_stock | 热度榜(brief 利好利空) / 四象限多窗口 |
| 监控 | task_log / data_flag | 每步计时落账 + 数据质量旗标 |

marketdata(只读):bar_daily_raw / moneyflow / margin_detail / top_list / hot_rank / trade_calendar / index_daily / report_rc / 预告快报增减持解禁等。**rv_rw 在 DB 层无写权限。**

## 4. 判断链路(B1→B8 全景,核心资产)

```
事实层(零幻觉):
  B1 新闻结构化(one_line/summary/情绪/票/节点)   B5 信函结构化(core_views/立场/相关度)
  个股事件 / 研报 / 资金聚合 / 大盘仪表 / 热力    ← 全部代码采集,LLM 只做提炼翻译
呈现层:
  B3 演进式报告(盘前锚点→盘中增量→盘后收口)     热点榜(统计热度+中性归因)
判断层(可追责):
  B6 节点研判卡: 六源截面z矩阵+共振/背离(代码) + DeepSeek 方向/置信/证据链/情景
      ↓ 方向卡成分共振(对齐分,代码)
  B8 个股决策卡: 方向/信心/入场/退出/证伪(价位锚=发卡日收盘),node_card_id 追责链
记分层(闭环):
  B7: 到期(5开市日)按相对全池超额记分(对/错/平) → 周度成绩单+分源归因
      → DeepSeek 错误归纳(信息错/逻辑错/纯运气) → lessons 回灌次日发卡 prompt(校准期冻结只落库,DECISIONS #28)
人工闭环: 证伪草稿 → manage_ledger.py pin 钉死 → falsify 归因(append-only)
```

## 5. 模块地图(src/research_view/)

| 模块 | 职责 |
|---|---|
| config / db / llm | 凭证与路径 / 双库连接(时区焊死UTC+8) / DeepSeek chat_json(容错+退避) |
| universe / funnel / structure | 科技域构建 / 规则漏斗+票名匹配(AMBIGUOUS_NAMES 防误命中) / B1 |
| collect/news · announcements · heatmap · research | major_news(**台账节流**) / 个股事件 / 热力多窗口 / 研报 |
| report / hotspots / research_digest | B3 三态报告+增量 / 热点榜+brief / 评级变动榜+观点 |
| moneyflow / market | 节点资金聚合(EOD/rt/多日/曲线) / 大盘仪表(指数/宽度/成交/两融/主力+20日history) |
| **evidence / decision / scorecard** | B6 六源矩阵+研判卡 / B8 候选+决策卡 / B7 记分+归因+周报+lessons |
| fund_letters / monitor / export | 信函入库 / health+task_run+台北信源状态 / dashboard.json 合成(**唯一出口**,_scrub 防 NaN) |

scripts/:`run_pipeline.py`(盘后主管道 16 步,含 calibration_freeze/ref_snapshot 留痕步) `run_light.py`(盘中轻量) + 6 个编排 sh(盘前/盘中/盘后/美股/信函/成绩单,**flock 全局串行锁+lib_alert 旗标**) + 台北侧采集 fetch_*(us_board/us_overnight/tech_wire/fund_letters/build_us) + 运维(backup_db/manage_ledger/manage_holdings/source_status/init_db)。

## 6. 编排节奏(cron 全景,UTC+8,周一~五除注明)

| 时点 | 任务 | 内容 |
|---|---|---|
| 08:30 | run_premarket | yfinance 隔夜→盘前报告(锚点)→dashboard |
| 08:00-23:30 每15min | run_intraday(run_light) | 新闻(整半点,配额台账)/研报/热点/**盘中增量**/资金快照+自采 |
| 周末 09:00-23:00 每2h | run_intraday(run_light) | **周末低频档(DECISIONS #36)**:周末新闻发酵补采(同走配额台账)+热点/看板保鲜;资金步非交易日自动零开销 |
| 22:30 | run_afterhours(run_pipeline) | 全量:采集→漏斗→B1→事件→热力→研报→**B3→热点→B6发卡→B8发卡→B7记分**→导出;顺带拉备份 |
| 21:30 + 22:00-05:00 整点 | run_us | build_us 全量美股 blob(约12min,锁等900s);21:30档=夏令时开盘(冬令时为开盘前预热) |
| 周三 07:00 | run_fund_letters | 信函 4 源 |
| 周日 20:00 | run_scorecard | B7 补记分+周报+lessons |
| 每日 21:00+23:30(数据节点) | backup_db | pg_dump(同日文件覆盖,23:30档含当日判断卡/记分),盘后 rsync 异地留存,两地各14天 |
| 每日 23:50(含周末) | watchdog | 独立看门狗:停摆(>20h)/交易日静默零/周一🟢心跳,只异常出声(飞书) |

## 7. 前端(web/,React+TS+Vite+Tailwind+ECharts,Bloomberg 暗色,A股红涨绿跌)

导航 8 页:**报告**(大盘仪表→主线hero→三件事→证伪→盘中节奏→综述;右栏:资金面/隔夜美股/账本/事件流) / **研判**(仅A股:**B6节点研判**+**B8个股决策[校准横幅]**;右栏**B7成绩单**——判断层独立成页,报告页回归事实层,2026-07-05 使用者要求拆出) / **热点**(排名+X舆情+全量新闻流下钻) / **资金**(当日曲线|多日趋势) / **热力**(四象限+时间窗+下钻) / **研究** / **信函** / **系统**(health+信源面板)。顶部 A股|美股切换;任意股票可点开详情弹层(6M走势);手机 md: 断点适配。

## 8. 监控与可靠性

- 每步 task_run 落 task_log → health(绿黄红,按源落地时点判新鲜);前端 StatusBar 红横幅(alert.json 按 job 分旗标)+StaleBadge 陈旧标注+新闻停更检测。
- 台北 18 外网源:注册表(data/sources.json,enabled 开关)×逐源上报→系统页面板(静默失效可见化)。
- 防御:LLM 指数退避 / SAVEPOINT 防整批丢 / 兜底导出(单步失败 dashboard 照刷) / ErrorBoundary / nginx 限流+bot 403(**curl 调试须 -A 浏览器UA**)。
- **独立看门狗**(`scripts/watchdog.py`,DECISIONS #33):不 import 管线代码、只读 dashboard.json——覆盖
  lib_alert 盲区(cron 整体没跑/flock 卡死时没有任何 job 会告警)。🔴 停摆>20h 或 .env 丢失(经备份副本
  `~/.config/mofang_watchdog.env` 发出,**轮换 webhook 须两处同步**);🟡 交易日收口后"成功但为空"
  (B6/B8 无当日卡、新闻 0 条、资金/热点/B3 回退,radar P0-3 模式);🟢 周一心跳(没收到=整机宕,人肉 dead-man)。
