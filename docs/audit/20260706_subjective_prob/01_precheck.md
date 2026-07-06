# 取证1 · 第0步前置核查输出(2026-07-06 19:0x UTC+8,数据节点实查)

## 0a 今日发卡情况(判定 DECISIONS 写法)
```
judgment_card WHERE trade_date='2026-07-06' OR created_at::date='2026-07-06' → (0, None, None)
decision_card 同查 → (0, None, None)
```
**结论:零卡 → 决策写法**(批准与 18:43 部署均早于首张新版卡;首卡=当晚 22:30 盘后档)。
prompt 质检修正亦发生在首卡之前 → **零孤儿样本,库内不存在缺陷版小版本**。

## 0b 周末(07-04/05)发卡情况(判定死键)
```
judgment_card WHERE trade_date IN ('2026-07-04','2026-07-05') → 0
decision_card 同查 → 0
```
辅证:库内 prompt_hash 真实分布(全表 GROUP BY):
```
judgment_card: [('NULL', 8)]
decision_card: [('NULL', 12)]
```
**结论:存量 20 卡(07-03)全 NULL;ffb0a6cccf2c61b7 / fe67e54832acdb4f(v2模板,周末零发卡)
与 a778927f2c31ef56 / cd3655bba4858708(prob初版,质检修正前零发卡)均为库内永不出现的
死键 → 已从 _PROMPT_LABELS 删除。**

## 0c 昨晚周报 cron 遗留验证(关上一补丁验收循环)
```
b7_weekly: week_end=2026-07-05, generated_at=2026-07-05 20:00:02.274551+08:00
```
stats JSON(全文见本目录 01a_b7weekly_20260705.json):cum/week/stock_cum/stock_week 全零、
baseline/override 四桶全零、by_version/by_direction 空对象——零记分卡诚实空单,与代码
确定性输出一致(零输入时 _stats/override_slices/version_stats 均为常量输出,无 LLM 调用)。
说明:07-05 手动调用的终端原文未在本会话留存,等价性由确定性论证成立(零输入→常量输出),
generated_at=20:00:02 证明周日 cron 实跑非手动补写。
