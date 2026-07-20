# 数据字典与断层日志(数据金矿规划,DECISIONS #30)

> 目的:两年后回头分析时,知道每列当时怎么算的、每段空洞为什么空。
> 维护义务(PROCESS§6 延伸):**新表/改口径随迁移更新本文;发现数据事故在"断层日志"记一行。**

## 资产分级

- **不可重算(真金,备份优先级最高)**:judgment_card / decision_card / b7_weekly / ledger /
  daily_report / report_increment / raw_news(LLM结构化) / research_report(打标) / fund_letter /
  hotspot_daily / mf_intraday_node(盘中曲线,东财只给当日) / ref_membership_snap / task_log /
  weekly_reflection(使用者亲笔周复盘,唯一不可再生)
- **可重算(丢了能重建)**:card_score / decision_score(行情的函数) / heatmap_*(每日 TRUNCATE,无历史,
  设计如此) / exports/*.json / trends.json
- **外部维护(md schema,dc 负责)**:bar_daily_raw / moneyflow / top_list / adj_factor 等,Tushare 可重拉

## 判断-结果语料库(头号资产)

| 表 | 口径要点 | 起始 |
|---|---|---|
| judgment_card | B6 节点卡,append-only(触发器焊死);matrix=发卡时六源z快照;resonance=方向源加权z(price1.0/mf1.0/news0.8/lhb0.6/letter0.5,z截断±3);horizon=5开市日;prompt_hash=sha256(SYSTEM+规则模板+lessons段)前16位,2026-07-04 起,NULL=之前口径;subjective_prob=LLM自报"兑现"概率(开区间0-1,兑现=超额×方向≥+1pp/中性≤2pp,sql/028),2026-07-06 起,NULL=之前卡或报废值 | 2026-07-03 |
| decision_card | B8 个股卡,候选=当日方向节点卡成分,对齐分门槛1.0/每节点Top3/日≤12;close=发卡日收盘价锚;node_card_id=追责链;subjective_prob 同节点卡(2026-07-06 起) | 2026-07-03 |
| card_score / decision_score | 到期(第5开市日,trade_calendar 必须 DISTINCT)记分;未复权 close→close 节点(成分等权)vs 全池等权超额pp;方向卡\|超额\|≥1pp 定对错,带内=平;中性卡≤2pp=对;**成分按发卡日 ref_membership_snap 锚定(2026-07-04 起,更早回退当前表)**;mech_verdict=机械基线(sign共振/对齐,同规则)——0b 三列对照:LLM vs 机械 vs 恒多(恒多从 excess 分布统计,无列) | 首批 2026-07-10 到期 |
| b7_weekly | 周日收口;stats 含 baseline/stock_baseline(0b)+calibration/stock_calibration(BRIER_SPEC 口径:样本域对/错+平剔除必报未判定率、固定边界桶、direction/neutral 分层、按prompt版本分组,#40/#41) | 2026-07-05 首跑(预期空单) |
| ref_membership_snap | 参照层每日成分快照(盘后 pipeline ref_snapshot 步,幂等);含仅映射票(ts_code NULL) | 2026-07-04 |
| weekly_reflection | 使用者手动整篇 Markdown 周复盘(**非** b7_weekly 自动周报,零 LLM,不进判断/记分链);append-only+版本链(根v1/修订=父+1/禁分叉/禁跨周/同周单根,触发器焊死);content_sha256=原文 UTF-8 字节 SHA;双时点 authored_at_utc8(须带时区)/recorded_at_utc8;visibility 默认 private,public 才出 reflections.json(只出当前叶子);唯一写入=数据节点 CLI manage_weekly_reflection.py(preview→confirm-sha)(sql/030,#46) | 2026-07-21(建表;首篇待使用者提供) |

## 信息层(rv 库)

| 表 | 口径要点 | 起始 |
|---|---|---|
| raw_news | major_news→funnel(域内判定,AMBIGUOUS_NAMES 防误命中)→B1 结构化(情绪/节点匹配);配额40次/天滚动窗,台账节流33次/天 | **2026-07-01** |
| research_report | Tushare 研报,近30日滚动采集+节点打标;变动榜=同机构内配对 | 2026-06-01 |
| fund_letter | 4源(BII/GS/MS/桥水汇总),周三cron;B5 relevance 评分 | 2026-07-01 |
| hotspot_daily | 节点热度榜+DeepSeek 归因+利好利空 brief(sql/020) | 2026-06 下旬 |
| daily_report / report_increment | B3 报告(盘前锚点/盘中增量/盘后收口);narrative 2026-07-02 起 | 2026-06 下旬 |
| mf_intraday_node | 盘中15min 节点主力累计(东财 push2delay,DC池∪自采);POOL=去重合计 | 2026-07-03 |
| chip_cost | 筹码成本(Tushare cyq_perf 东财式估算:加权平均成本/获利盘/90%区间),核心池每日盘后 upsert,滚动30日;**展示层专用(个股详情),不进 B6/B8 证据矩阵**(sql/027) | 2026-07-03(首采) |

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
| 2026-07-04 | **参照层 v2 切换(机器人链7→14节点,+6票,DECISIONS #31)**:截面z分母49→57;此前 raw_news.matched_node_ids/mf_intraday_node/hotspot_daily 里的旧机器人 node_id 不迁移,过渡窗内旧数据挂旧id属正常 |
| 2026-07-04 | B6 prompt_hash 变更 b2f7cf70df6678da→ffb0a6cccf2c61b7(模板"48节点"改"全部产业链节点",与参照层版本同界)——样本分组的两个版本轴切在同一天 |
| 2026-07-05 | **参照层 v3 扩容(+金融/创新医药/商业航天三链19节点60票,DECISIONS #37)**:截面z分母57→76;新链票07-05前无任何历史(研报/新闻域此前不含金融/医药/军工,盘中资金流07-06起走rt_extra自采生效)——新链节点的多日窗口指标在过渡周内基数不足属正常 |
| 2026-07-06 | **B6/B8 模板加 subjective_prob+当日质检修正(DECISIONS #40/#41)**:prompt_hash 最终真值 B6 8528ca795ca4c6b8、B8 780916554dc9be8b(当日中间版 a778927f/cd3655bb 与周末零发卡的 ffb0a6cc/fe67e548 均为库内零出现死键);**07-06=复合版本硬边界**(prob自报+参照层v3 单一纪元,禁拆单项贡献);旧卡 NULL 不回填,Brier/校准样本从 07-06 卡起算(07-13 首批到期,口径预注册 BRIER_SPEC.md) |
| 2026-07-05 前的周末 | **周末新闻从未自动采集**(cron 全周一~五+单日抓取窗口):pub_time 落在周六/周日的 major_news 缺失——07-04(周六)已于 07-05 手动补抓,更早周末(如 06-27/28)不补(#34 回填纪律);07-05 起周末低频档生效(DECISIONS #36) |
| 持续 | heatmap_stock/heatmap_node 每日 TRUNCATE,无历史(行情可重算,设计如此) |
| 持续 | 参照层 2026-07-04 前的修订无快照(如 07-03 执行器节点拆分),此前时点成分不可精确还原 |

## 备份纵深(轻量口径,使用者定)

日 pg_dump 21:00+23:30(同日覆盖,23:30含当日卡)→ 两地各14天 → 月度归档 archive/ 滚动12份 →
使用者侧云盘日快照(整机,阶梯保留)。恢复以 pg_dump 为权威,快照作保底。
2026-07-05 起 exports/ 观测层按日 blob(美股/X舆情/事件/信函,不进 PG,LLM 当时综合的 PIT 证据,
台架回测比对用)每日 tar 同链备份:exports_YYYYMMDD.tar.gz,同样两地14天+月度归档12份(DECISIONS #34)。
2026-07-06 起 us_overnight blob 增 macro 键(宏观锚:美债10Y/美元指数/USDCNY 在岸,yfinance,
展示层参照线不进 B6 矩阵;离岸 CNH=X Yahoo 历史仅回1行不可用,实测后以在岸替代)。
数据纪律总纲见 docs/DATA_CONSTITUTION.md(DECISIONS #35,含资产清单×备份覆盖对照表)。
恢复演练:2026-07-05 首演通过(20260705 dump→临时库零错误,13表行数对齐,触发器拒改);每半年一次挂季度审视。
