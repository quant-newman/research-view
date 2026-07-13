# 07-13 22:30 收口交回:哨兵第9项两层核对 + 07-06到期批对账 + health🟡触发源

> 执行:2026-07-13 23:49-23:58 UTC+8,cron 记分(22:31 afterhours 档)之后。
> 全程只读 SELECT + 纯函数 REPL,零写入,不触碰 weekly()(CALIBRATION_FREEZE=1 期间未跑)。
> 查询脚本原文见本目录 `sentinel9_check.py`(scp 至数据节点 /tmp,以 /opt/research_view/.venv 执行)。
> 口径基准:SENTINEL_SPEC.md 2026-07-13 追加节(选卡规则 14:48:02+0800 锁定版)。

## 一、哨兵第9项两层核对

### 选卡(锁定规则照抄执行,无回退)

主核字段 node×direction(card_score JOIN judgment_card,direction≠中性),
verdict∈{对,错} 候选共 6 张(card_id 19/20/21/22/25/26;23/24 为"平"不入候选),
**card_id 最小者 = 19**(optical::光纤光缆,偏空,subjective_prob=0.85,verdict=对)。
主核字段 n=6 > 0,未触发个股侧回退。

### (a) 单卡贡献(card_id=19)

- 手算:outcome=对=1;0.85 − 1 = −0.15;(−0.15)² = 0.0225;round 4 位 → **0.0225**
- 系统值(brier_stats 纯函数,单行传入,数据节点现跑):
  `brier_stats([(0.85,'对')])` → brier = **0.0225**
- **比对:0.0225 vs 0.0225,逐位一致 ✅**

### (b) 全样本重算(主核字段 node×direction)

**样本域**:scorecard.py:456-458 SQL 原文照抄(不限 trade_date,只滤 prob 非空),
取回 8 行(全部为 07-06 批 B6,是库内仅有的 prob 非空已记分节点卡);
其中 direction≠中性 8 行,verdict=平 2 行剔除(必报:n_flat=2,flat_rate=2/8=0.25),
**入样 n=6**。

```sql
SELECT jc.prompt_hash, jc.direction, jc.subjective_prob, cs.verdict
    FROM card_score cs JOIN judgment_card jc USING(card_id)
    WHERE jc.subjective_prob IS NOT NULL
```

人工逐卡重算 squared_error(outcome 对=1/错=0):

| prob | verdict | squared_error |
|------|---------|---------------|
| 0.85 | 对 | 0.0225 |
| 0.80 | 对 | 0.0400 |
| 0.80 | 对 | 0.0400 |
| 0.65 | 错 | 0.4225 |
| 0.60 | 错 | 0.3600 |
| 0.55 | 错 | 0.3025 |
| 0.65 | 平 | 剔除(n_flat) |
| 0.85 | 平 | 剔除(n_flat) |

和 = 0.0225+0.04+0.04+0.4225+0.36+0.3025 = 1.1875;
均值 = 1.1875 / 6 = 0.1979166…;round 4 位 → **0.1979**

- 系统值:取回 8 行手工传入 calibration_block() 纯函数(scorecard.py:340,
  REPL 路线,不触碰 weekly 本体),输出 direction 键:
  `{'n': 6, 'n_flat': 2, 'flat_rate': 0.25, 'brier': 0.1979, ...}`
- **比对:手算 0.1979 vs 系统 0.1979,逐位一致 ✅**(n/n_flat/flat_rate 亦全同)
- 交叉佐证:by_version['8528ca795ca4c6b8'].brier = 0.1979 同值。

**附:个股侧同法补核(非主核,仅留档)**:scorecard.py:460-462 SQL 取回 12 行
(B8 07-06 批),direction≠中性 11 行、无平,人工重算和 = 2.4850,
均值 = 2.4850/11 = 0.2259090… → **0.2259**;系统 stock_calibration.direction.brier
= **0.2259**,逐位一致 ✅(中性 1 行走 neutral 桶,brier=0.25,禁混桶不并入)。

calibration_block() 完整返回值原文与全部取回行,见 `sentinel9_check.output.txt`。

## 二、到期批对账(限定 trade_date=2026-07-06,"最新卡"= scorecard.py:115-127 DISTINCT ON 同款)

### B6:scored 8 + unresolved 0 = 8 ✅

| card_id | node_id | verdict |
|---|---|---|
| 19 | optical::光纤光缆 | 对 |
| 20 | robotics::工业机器人本体 | 错 |
| 21 | optical::光模块成品 | 错 |
| 22 | compute_infra::服务器整机 | 对 |
| 23 | optical::光器件/CPO封装 | 平 |
| 24 | finance::证券 | 平 |
| 25 | optical::通信设备 | 对 |
| 26 | pharma::生物药/ADC | 错 |

unresolved 明细:无(空集)。
汇总 3对/3错/2平(对=19/22/25,错=20/21/26,平=23/24),与累计口径(旧批 8 卡 1对7错 + 本批)= 4对/10错/2平、
飞书摘要"累计记分16(对4/错10)"完全对上。

### B8:scored 12 + unresolved 0 = 12 ✅

| card_id | code | verdict |
|---|---|---|
| 15 | 000938 | 对 |
| 16 | 301191 | 对 |
| 17 | 002747 | 错 |
| 18 | 600105 | 对 |
| 19 | 002491 | 对 |
| 20 | 000988 | 错 |
| 21 | 601211 | 错 |
| 22 | 301165 | 对 |
| 23 | 300394 | 错 |
| 24 | 600487 | 对 |
| 25 | 600030 | 对 |
| 26 | 000977 | 对 |

unresolved 明细:无(空集)。8对/4错。

佐证:22:31 afterhours 日志 `card_scores: {'scored': 8, 'pending': 40,
'stock_scored': 12, 'stock_pending': 60}`——本批 8+12 全部在该档记分;
飞书"待记分40"= 节点侧全库 pending(含 07-13 新卡等未到期批),与本项无冲突。

## 三、health🟡触发源

判定逻辑 monitor.py:177-179:红=当日 task_log 有失败;黄=无失败但
(任一非 pending 源 stale)或(data_flag 非空)。当日 task_log 失败行 0,
不是红;黄由**两条独立触发臂同时成立**,均非 md/rv 新鲜度阈值突破
(bar_daily_raw/moneyflow/raw_news 等九项新鲜度行全部不 stale):

1. **data_flag 臂:sanity_checks(afterhours pipeline 步,monitor.py:43)
   当日写入 PE极端 ×10**——22:31 日志原行 `sanity_checks: {'PE极端': 10}`。
   明细(data_flag 现查):600118 PE_TTM=6356.9 / 688037 1080.2 / 688048 2108.9 /
   688110 24954.2 / 688206 1108.3 / 688347 1232.7 / 688361 24165.6 /
   688409 1086.4 / 688507 1289.4 / 688716 2759.6。
   属数据质量"存疑标记"设计行为(标记不丢弃),非采集故障。
2. **台北信源臂:聚合行 stale=True(16/19 正常)**——job = 美股时段每小时
   run_us.sh → build_us 全球科技舆情步(fetch_tech_wire),3 个 Reddit RSS 源
   ok=False:wire_reddit_stocks(r/stocks)、wire_reddit_tech(r/technology)、
   wire_reddit_hw(r/hardware),err="取不到(超时/非200)",fetched_at 2026-07-13
   23:07(22:30 时点为前一小时档,us-20260713.log 三个整点档均现
   `! wire 源取失败,跳过: r/stocks|r/technology|r/hardware`,首档 r/hardware
   尚成功 11 条,后两档全失)。**不是 threshold_hours=60 新鲜度超时**
   (fetched_at 是新鲜的),是 ok=False 失败位拉黄(monitor.py:171
   `ok is False or stale` 计入 bad)。Reddit 限流为已知长期状况。

两臂任一单独成立即黄;当晚两臂同时成立。红臂(任务失败)为 0,黄色定性成立。
