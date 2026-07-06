# 取证6 · 原提案C验收清单实证

| # | 验收项 | 状态 | 实证 |
|---|---|---|---|
| 1 | **DDL 后 append-only 触发器仍活着(旧卡 UPDATE 被拒)** | ✅ 实测 | 见下方完整输出 |
| 2 | 新卡带 prob 落库 | ⏳ 待 07-06 22:30 盘后档 | 观察点已登记 ROADMAP;两节点部署版模板/哈希已核对一致 |
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
