# 08-25 #48 首个完整交易日观察 + 时段门放行留痕补丁

- 时间:2026-08-25 上午(UTC+8)
- 起因:ROADMAP 08-25 观察点核验;核验中发现观察口径①不可执行
- 变更:`scripts/run_light.py` 放行分支补一行 `LLM 时段门: 放行({why})`;ROADMAP 观察点口径修正 + 结果登记
- commit:`f39576e`(前序 `0dd5bb7`)
- 部署:rsync exit 0,DEPLOY_STATE `f39576e / dirty 0 / 2026-08-25 10:25:13`
- 测试:tests/test_llm_gate.py + tests/test_b1_batch.py 40 passed;两侧 py_compile ok
- 判断链触碰:零

## 上午核验读数(补丁前的生产行为)

| 观察点 | 结果 |
|---|---|
| ① 白天静默档 | 08:00–10:15 共 10 档静默行全在场;叙述层三处(研报提炼/report_increment/热点综述)同步静默,统计列仍最新 |
| ② 09:45 补做点 | 09:48 `structured=28 / chain_relevant=20 / pruned=8 / calls=4` = **7.0 条每次**(区间 6–8) |
| ② 积压闭合 | 08:00 档 relevant 26 + 09:00 档 2 = 28,与 09:48 补做数逐条对上 |
| ③ 告警串 | `⚠ 窗口外 LLM 调用` / `只对齐回` / `整批失败` 全天零命中;日志无 ⚠/ERROR/Traceback |
| ④ 07:40 盘前档 | 四步全绿;B1[news] 60 条缓存 45 送 15=1 批,B1[wire] 110 条缓存 102 送 8=1 批 |

库内复核(数据节点 research_view):
```
今日抓取入库(fetched_at>=08-25 00:00) = 53
  relevant=true            : 28
  relevant 且 llm_done     : 28
  relevant 且 summary 非空 : 28
  ★积压(relevant 未 llm_done): 0
  昨日残留积压              : 0
```

## 偏差与处置

ROADMAP 原写"09:45/15:15 两档应出现 `白天补做点`"——**不成立**。
`config.llm_allowed()` 返回的 why 只在各调用点的**拒绝分支**被打印,放行分支无痕。
后果:补做点是否命中只能靠"structure_b1 没打跳过"反证;补做点被 flock 挤出 15min
宽限而丢失时,日志里没有任何正面信号(与 07-14 告警载体自身失败属同族盲区)。
处置:run_light 放行分支补日志,15:15 档起生效;ROADMAP 口径同步改为新标记。

## 部署后首档(10:30,回归检查)

静默行照常在场、无放行行(10:30 本就在静默段,符合预期)、无 ⚠/ERROR,exit 0。
`push_alerts: 触及日上限30` 为常态(近三交易日每日 52–54 次),非本批引入。
原文见 09_0825_post_deploy_slot.txt。

## 未闭合

- 15:15 第二个补做点:验放行行 + structured:calls 比
- 18:00 首个夜间档:白天积压 summary/sentiment 补齐,不跨天
