# 取证6 · 原提案C验收清单实证

| # | 验收项 | 状态 | 实证 |
|---|---|---|---|
| 1 | **DDL 后 append-only 触发器仍活着(旧卡 UPDATE 被拒)** | ✅ 实测 | 见下方完整输出 |
| 2 | 新卡带 prob 落库 | ✅ 实测(2026-07-10 核验 07-06 晚批) | B6 8/8、B8 12/12 prob 非 NULL 且落 (0,1)(CHECK 之外逐值复核);prompt_hash 逐张完整 16 位=预期真值(B6 `8528ca795ca4c6b8`/B8 `780916554dc9be8b`,与 BRIER_SPEC 版本纪元一致);取值有变化(B6 5 个 distinct∈{0.55..0.85}/B8 6 个 distinct∈{0.5..0.75},非常量输出)。逐卡明细见下方第2项完整输出 |
| 3 | 到期卡 Brier 人工复算一致 | ✅ 口径已锁+机制实测 | 单测 (0.09+0.49)/2=0.29 与 brier_stats 一致;数据节点事务内假卡实测 (0.62−1)²=0.1444 一致(ROLLBACK 零污染);真卡待 07-13 首批到期复核 |
| 4 | 旧卡 NULL 不受影响 | ✅ 实测 | 两表 `WHERE subjective_prob IS NOT NULL` 计数=0;主记分路径不读该列 |
| 5 | CHECK 开区间拦截 | ✅ 实测 | 事务内 INSERT prob=1.2 → psycopg.errors.CheckViolation(已ROLLBACK) |

## 第1项完整输出(2026-07-06,sql/028 应用之后,数据节点生产库)

```
目标旧卡: card_id=1 trade_date=2026-07-03 node_id=robotics::减速器
UPDATE judgment_card SET subjective_prob=0.5 WHERE card_id=1
→ UPDATE 被拒: psycopg.errors.RaiseException
  完整错误: ledger 是只读账本,不允许 UPDATE (append-only)
  CONTEXT:  PL/pgSQL function ledger_append_only() line 3 at RAISE

UPDATE decision_card SET subjective_prob=0.5 WHERE card_id=1
→ UPDATE 被拒: ledger 是只读账本,不允许 UPDATE (append-only)
  CONTEXT:  PL/pgSQL function ledger_append_only() line 3 at RAISE
```
(两处均在事务内执行后 ROLLBACK;触发器 BEFORE UPDATE 在 ALTER ADD COLUMN 后对含新列的
UPDATE 同样拦截——加列不削触发器。)

## 第2项完整输出(2026-07-10 只读核验,数据节点生产库,trade_date=2026-07-06)

```
=== judgment_card (card_id, node_id, direction, subjective_prob, prompt_hash, length)
(19, 'optical::光纤光缆',            '偏空', 0.85, '8528ca795ca4c6b8', 16)
(20, 'robotics::工业机器人本体',      '偏多', 0.65, '8528ca795ca4c6b8', 16)
(21, 'optical::光模块成品',          '偏空', 0.55, '8528ca795ca4c6b8', 16)
(22, 'compute_infra::服务器整机',    '偏多', 0.80, '8528ca795ca4c6b8', 16)
(23, 'optical::光器件/CPO封装',      '偏空', 0.85, '8528ca795ca4c6b8', 16)
(24, 'finance::证券',               '偏多', 0.65, '8528ca795ca4c6b8', 16)
(25, 'optical::通信设备',            '偏多', 0.80, '8528ca795ca4c6b8', 16)
(26, 'pharma::生物药/ADC',          '偏多', 0.60, '8528ca795ca4c6b8', 16)
total/nonnull/in(0,1)/distinct_prob/distinct_hash: (8, 8, 8, 5, 1)

=== decision_card (card_id, code, direction, subjective_prob, prompt_hash, length)
(15, '000938', '偏多', 0.65, '780916554dc9be8b', 16)
(16, '301191', '偏多', 0.70, '780916554dc9be8b', 16)
(17, '002747', '偏多', 0.60, '780916554dc9be8b', 16)
(18, '600105', '偏空', 0.75, '780916554dc9be8b', 16)
(19, '002491', '偏空', 0.70, '780916554dc9be8b', 16)
(20, '000988', '偏空', 0.55, '780916554dc9be8b', 16)
(21, '601211', '偏多', 0.70, '780916554dc9be8b', 16)
(22, '301165', '偏多', 0.60, '780916554dc9be8b', 16)
(23, '300394', '偏空', 0.75, '780916554dc9be8b', 16)
(24, '600487', '偏空', 0.65, '780916554dc9be8b', 16)
(25, '600030', '中性', 0.50, '780916554dc9be8b', 16)
(26, '000977', '偏多', 0.65, '780916554dc9be8b', 16)
total/nonnull/in(0,1)/distinct_prob/distinct_hash: (12, 12, 12, 6, 1)
```
(只读 SELECT,零写入;07-07/08/09 后续批次同哈希同机制,本项验收以首个自动批 07-06 为锚。)
