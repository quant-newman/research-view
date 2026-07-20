# 数据资产宪法(research_view 适用版)

> 源:使用者 2026-06-22 立的全平台数据资产宪法。2026-07-05 经审读、带四处修订采纳,**适用范围仅本平台**
> (其他平台各自治理,DECISIONS #27 平台独立不变;宪法统一的是纪律,不碰数据互喂)。拍板记 DECISIONS #35。
> 核心信念:**自产数据是未来的黄金——买得到的都不值钱,买不到、只能用时间攒的才是壁垒。**
> 冲突原则:本文与既有 DECISIONS 冲突时,以 DECISIONS 为准并回改本文——宪法不推翻已拍板决策。

---

## 三条底线

**1. 只增不删,不覆盖。**
自产判断/信号/账本一律 append-only;修正=新增修正记录,不改旧行——错误记录本身也是数据。
落地手段=结构焊死(DB 触发器/只读权限),不靠自觉。
**豁免(修订,与 DECISIONS #16 对齐):确定性派生值(card_score / decision_score / heatmap 快照 / tech_stock)
可重算可重建,前提=生成规则版本化可审计——规则/口径变更必须记 DATA.md 断层日志(prompt_hash /
mech_verdict 规则同理)。判断本体绝不可改。**

**2. 带全时间戳落库。**
**新表一律双戳**:事件发生时间(valid,如 trade_date/pub_time/report_date)+系统记录时间
(observed,如 created_at/fetched_at)。**存量表不回改**(schema 永不破坏,DECISIONS #24),
已知缺陷记录在案(见 DATA.md 断层日志)。时区统一 UTC+8(使用者已拍板,无"或 UTC"口子)。

**3. 有备份,且演练过恢复。**
现状(2026-07-06 起,DECISIONS #39):日 pg_dump 自定义格式 .dump 21:00+23:30,**产出即
pg_restore --list 校验 TOC**(截断/损坏当场删残件退出非零→台北新鲜度哨兵2天内告警)→
两地各 14 天 → 月度归档滚 12 份;exports/ 观测层按日 blob 同链 tar(2026-07-05 起,
07-06 起含数据节点 .env);台北 .env 交叉推数据节点(env_taipei_*,同 14 天滚动);
使用者侧云盘日快照作保底。
**恢复演练升级为月度自动(scripts/restore_drill.sh,台北 cron 每月2号 16:10):**
最新异地 .dump 真还原进一次性 postgres 容器+核心资产表行数校验,失败走 lib_alert+飞书;
半年一次人工演练(DECISIONS #33,挂季度审视,首次 2026-10)继续保留作深检。
首次人工演练 2026-07-05 已通过:20260705 备份恢复临时库零错误,13 关键表行数逐一对齐,
append-only 触发器在恢复库实测拒改。

---

## 优先级判据(备份与保存资源先紧着谁)

**不可回填的先保。**

| 梯队 | 数据 | 本平台对应 | 为什么 |
|---|---|---|---|
| 1 | 执行数据(真实成交/滑点/盘口) | **不适用**——本平台不执行交易(判断放大器形态,DECISIONS #24),不新增采集义务 | 全行业皇冠,但属交易执行侧平台 |
| 2 | 判断记录(事前记、带证伪条件) | judgment_card / decision_card / ledger / b7_weekly(review+lessons) / daily_report 叙事 / fund_letter / weekly_reflection(使用者亲笔周复盘,#46) | 唯一记录"当时怎么想的、后来对不对";**严格不可回填**(DECISIONS #34) |
| 3 | 自建口径信号历史 + **公共但不可回填的观测层(修订新增)** | hotspot_daily / mf_intraday_node(dc 只留4天,全史仅我们有) / ref_membership_snap / report_increment / raw_news(wire 部分 feed 不可回拉) / exports 观测层 blob / md.hot_rank(无历史API) | 口径独特×历史长度=价值;**公共数据凡无历史接口、仅观测时可得者,按本梯队待遇** |
| 4 | 公共事实(行情/财务/公告) | marketdata 只读(dc 属地,非本平台备份责任);research_report(接口可重拉) | 可重拉,丢了能补,是入场费不是壁垒 |

推论:梯队 2-3 丢失即永久损失,备份等级最高;梯队 4 可降级。

**念头记录(原宪法空档,本平台对应):ledger 表(append-only)结构已备,按使用缺口启用——
不为宪法新增开发(值班模式,DECISIONS #30)。**

---

## 资产清单 × 备份覆盖对照(季度审视逐项打勾;新增梯队 2-3 表时必须同步更新本表)

| 资产 | 存储 | 备份覆盖 |
|---|---|---|
| judgment_card / decision_card / ledger / b7_weekly / daily_report / fund_letter / stock_event / weekly_reflection(2026-07-21 新增,梯队2;首份含表备份须 pg_restore --list 核对 TOC) | PG(触发器焊死) | pg_dump 两地14天+月档 ✓ |
| hotspot_daily / report_increment / mf_intraday_node / ref_membership_snap / raw_news / research_report / task_log / data_flag | PG | pg_dump 同上 ✓ |
| card_score / decision_score(可重算,规则版本留痕) | PG | pg_dump 同上 ✓(重算规则=代码在 git) |
| exports/ 观测层日 blob(us/events/信函/source_status/backtest 诊断) | 文件(数据节点为超集) | exports_*.tar.gz 同链 ✓(2026-07-05 起) |
| heatmap_stock/node / tech_stock(派生,TRUNCATE 重建) | PG | 不单独保(行情可重算,设计如此) |
| 参照层源文件 data/*.json / 全部代码与迁移 | git 仓库 | GitHub 远端 ✓ |

---

## 修改记录
- 2026-07-05:采纳(源宪法 2026-06-22 立)。四处修订:①派生值豁免(对齐 #16)②双戳向前适用(对齐 #24)
  ③时区收紧 UTC+8 ④"公共但不可回填"升梯队 3;梯队 1 标注不适用;首次恢复演练通过。
