# 数据字典与断层日志(数据金矿规划,DECISIONS #30)

> 目的:两年后回头分析时,知道每列当时怎么算的、每段空洞为什么空。
> 维护义务(PROCESS§6 延伸):**新表/改口径随迁移更新本文;发现数据事故在"断层日志"记一行。**

## 资产分级

- **不可重算(真金,备份优先级最高)**:judgment_card / decision_card / b7_weekly / ledger /
  daily_report / report_increment / raw_news(LLM结构化) / research_report(打标) / fund_letter /
  hotspot_daily / mf_intraday_node(盘中曲线,东财只给当日) / ref_membership_snap / task_log
- **可重算(丢了能重建)**:card_score / decision_score(行情的函数) / heatmap_*(每日 TRUNCATE,无历史,
  设计如此) / exports/*.json / trends.json
- **外部维护(md schema,dc 负责)**:bar_daily_raw / moneyflow / top_list / adj_factor 等,Tushare 可重拉

## 判断-结果语料库(头号资产)

| 表 | 口径要点 | 起始 |
|---|---|---|
| judgment_card | B6 节点卡,append-only(触发器焊死);matrix=发卡时六源z快照;resonance=方向源加权z(price1.0/mf1.0/news0.8/lhb0.6/letter0.5,z截断±3);horizon=5开市日;prompt_hash=sha256(SYSTEM+规则模板+lessons段)前16位,2026-07-04 起,NULL=之前口径 | 2026-07-03 |
| decision_card | B8 个股卡,候选=当日方向节点卡成分,对齐分门槛1.0/每节点Top3/日≤12;close=发卡日收盘价锚;node_card_id=追责链 | 2026-07-03 |
| card_score / decision_score | 到期(第5开市日,trade_calendar 必须 DISTINCT)记分;未复权 close→close 节点(成分等权)vs 全池等权超额pp;方向卡\|超额\|≥1pp 定对错,带内=平;中性卡≤2pp=对;**成分按发卡日 ref_membership_snap 锚定(2026-07-04 起,更早回退当前表)**;mech_verdict=机械基线(sign共振/对齐,同规则)——0b 三列对照:LLM vs 机械 vs 恒多(恒多从 excess 分布统计,无列) | 首批 2026-07-10 到期 |
| b7_weekly | 周日收口;stats 含 baseline/stock_baseline(0b);lessons 校准期只落库不注入(CALIBRATION_FREEZE,DECISIONS #28) | 2026-07-05 首跑(预期空单) |
| ref_membership_snap | 参照层每日成分快照(盘后 pipeline ref_snapshot 步,幂等);含仅映射票(ts_code NULL) | 2026-07-04 |

## 信息层(rv 库)

| 表 | 口径要点 | 起始 |
|---|---|---|
| raw_news | major_news→funnel(域内判定,AMBIGUOUS_NAMES 防误命中)→B1 结构化(情绪/节点匹配);配额40次/天滚动窗,台账节流33次/天 | **2026-07-01** |
| research_report | Tushare 研报,近30日滚动采集+节点打标;变动榜=同机构内配对 | 2026-06-01 |
| fund_letter | 4源(BII/GS/MS/桥水汇总),周三cron;B5 relevance 评分 | 2026-07-01 |
| hotspot_daily | 节点热度榜+DeepSeek 归因+利好利空 brief(sql/020) | 2026-06 下旬 |
| daily_report / report_increment | B3 报告(盘前锚点/盘中增量/盘后收口);narrative 2026-07-02 起 | 2026-06 下旬 |
| mf_intraday_node | 盘中15min 节点主力累计(东财 push2delay,DC池∪自采);POOL=去重合计 | 2026-07-03 |

## 常用 md 表(只读)

bar_daily_raw(1990起,未复权,复权乘 adj_factor) / moneyflow(2010起,主力=大单+超大单,万元,T日22:15落地,结构性偏净流出——读相对强弱) / top_list(2005起,net_amount 元) / hot_rank(2026-06-11起,ths 每日100名) / trade_calendar(沪深各一行,**用时必须 DISTINCT**) / margin_detail(T-1) / index_daily(pct_chg 已是%)。
全A成交额用 bar_daily_raw 合计(amount 千元),别用成指 amount(成分股口径)。

## 断层日志(已知空洞,分析时勿读成信号)

| 日期/区间 | 事件 |
|---|---|
| 2026-07-01 前 | raw_news 无数据(新闻层 07-01 上线)——回测新闻源仅3个交易日,统计无效 |
| 2026-07-02 下午-07-03 | major_news 配额死亡螺旋(失败重试也计数),新闻断续;07-03 14:10-20:00 超限,20:30 恢复一次(800条),22:30 台账拦截 |
| 2026-06-11 前 | hot_rank 无数据 |
| 2026-07-03 22:30 | 盘后 cron 跑的旧 pipeline(B6-B8 当晚更深夜才部署),judgment/decision/card_scores 三步缺席——首个全链自动跑=2026-07-07 |
| 持续 | heatmap_stock/heatmap_node 每日 TRUNCATE,无历史(行情可重算,设计如此) |
| 持续 | 参照层 2026-07-04 前的修订无快照(如 07-03 执行器节点拆分),此前时点成分不可精确还原 |

## 备份纵深(轻量口径,使用者定)

日 pg_dump 21:00+23:30(同日覆盖,23:30含当日卡)→ 两地各14天 → 月度归档 archive/ 滚动12份 →
使用者侧云盘日快照(整机,阶梯保留)。恢复以 pg_dump 为权威,快照作保底。
