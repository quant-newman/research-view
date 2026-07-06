# 取证4 · 哈希真值 + _PROMPT_LABELS/测试 diff + 双绿输出

最终 prompt_hash 真值(sql/024 口径,sha256(SYSTEM+模板+lessons段)前16位,lessons段=空/冻结):
- 编排节点实算: B6 `8528ca795ca4c6b8` / B8 `780916554dc9be8b`
- 数据节点部署版实算: **一致**(B6 8528ca795ca4c6b8 / B8 780916554dc9be8b)

## _PROMPT_LABELS diff
```diff
 _PROMPT_LABELS = {
-    "ffb0a6cccf2c61b7": "B6 v2模板(07-04起;参照层v2/v3同哈希,07-05起z分母57→76)",
-    "fe67e54832acdb4f": "B8 v1模板(07-04起;参照层v2/v3同哈希,同上)",
-    "a778927f2c31ef56": "B6 v3模板(07-06起,+subjective_prob;DECISIONS #40)",
-    "cd3655bba4858708": "B8 v2模板(07-06起,+subjective_prob;DECISIONS #40)",
+    # 07-06 重登(#41 取证核查):库内真值=存量20卡(07-03)全NULL,07-04/05周末与07-06(截至质检修正)
+    # 零发卡——旧预登记 ffb0a6cc/fe67e548(v2模板)与 a778927f/cd3655bb(prob初版,当日质检修正前)
+    # 均为库内永不出现的死键,已删。07-06=复合版本硬边界:prob自报+参照层v3 合并为单一版本纪元,
+    # 效应归因整体隔离,禁止事后声称拆出单项贡献(#41)。
+    "8528ca795ca4c6b8": "B6 v3·07-06起:prob自报+参照层v3(76节点)",
+    "780916554dc9be8b": "B8 v2·07-06起:prob自报+参照层v3(76节点)",
     "unversioned": "07-04 加列前存量卡(参照层v1口径)",
 }
 
@@ -306,38 +308,55 @@ def version_stats(rows) -> dict:
     return {h: {"label": _PROMPT_LABELS.get(h, h), **_stats(rs)} for h, rs in grp.items()}
 
 
-# ---------- 校准(Brier,DECISIONS #40):subjective_prob 卡的概率校准,增量不替换 ----------
+# ---------- 校准(Brier,#40/#41):口径预注册于 docs/BRIER_SPEC.md,改代码就文档,不许反向 ----------
 
-def brier_stats(rows, nbins: int = 5) -> dict:
-    """rows: [(subjective_prob, verdict)] → Brier 均分 + 校准曲线数据点(等宽5桶)。
-    事件E=「verdict=对」,outcome: 对=1,错/平=0——平不剔除:模型报的是"兑现"概率,
-    兑现门槛(方向卡超额×方向≥+1pp)在发卡 prompt 里明示,带内=未兑现;剔平等于把概率
-    条件化在"分出对错"上,与模型面对的事件不一致,校准曲线会系统性偏高。
-    (与 hit_rate 只算 对/(对+错) 是两个指标两个口径。)无带 prob 样本返回 n=0。"""
-    pts = [(float(p), 1.0 if v == "对" else 0.0) for p, v in rows if p is not None]
+_BIN_EDGES = (0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)  # SPEC第4条:固定边界,落档日起写死,禁分位桶/事后改桶
+
```

## 测试 diff 摘要(tests/test_scorecard_stats.py)
- test_version_group: 旧键 ffb0a6cc→新真值 8528ca79,标签前缀 "B6 v2模板"→"B6 v3·07-06起";新增四死键不在 _PROMPT_LABELS 的断言;兜底用例(未登记哈希原样显示)保留。
- test_brier: 重写为 BRIER_SPEC 口径(平剔除+flat_rate 必报+固定边界桶+calibration_block 分层)。

## 双绿输出
```
[编排节点] PYTHONPATH=src python3 tests/test_scorecard_stats.py → OK
[数据节点] tests/test_scorecard_stats.py → OK
[数据节点] tests/test_z_equivalence.py → z 口径等价:4/4 通过(容差 1e-9)
```
