# vNext 3a/3b 分支·diff+单测+回滚方案(07-10 备好,不合并不部署)

- **分支**:`vnext-measurement-20260710`,单提交 `072dc83`(基于 main `0d8d046`)。
  diff 快照:`vnext_branch_072dc83.diff`(本目录);合并前须 rebase main 复验单测。
- **改动面**:仅 `src/research_view/scorecard.py` + `tests/test_scorecard_stats.py`。
  零 DDL、零 prompt、零编排脚本、零前端——不触发 prompt_hash 重登。
- **单测**:`test_brier_uncond`(人工复算锚 0.2967/桶内平 outcome=0/条件与无条件
  flat_rate 分母差异/透传/空态)+ `test_headline`(三件套+全中性+空态不除零);
  旧用例逐字未动且全绿=默认参数行为零变化的守护。本机 `python3 tests/test_scorecard_stats.py` OK。

## 回滚方案(三层,由浅入深)

1. **未合并(当前状态)**:什么都不用做;放弃=删分支 `git branch -D vnext-measurement-20260710`。
2. **已合并未部署**:`git revert <merge-commit>`(或 revert 072dc83),推送即完。
3. **已合并已部署**:
   - 代码:revert 后按 PROCESS §4 runbook 重新 rsync 数据节点+更新 DEPLOY_STATE;
   - 数据:**无脏数据风险**——本 diff 不含 DDL,不写新表;唯一落库面是 b7_weekly.stats
     JSON 追加 4 个新键(headline/stock_headline/calibration_uncond/stock_calibration_uncond),
     旧键逐字不动,旧代码读旧键天然兼容;回滚后对受影响周重跑
     `scorecard.weekly(week_end)`(upsert 幂等)即回到旧形态,或不重跑仅留冗余键(无消费方,无害);
   - 前端/展示:本分支不含展示层改动(b 的 headline 重排属 07-19 执行清单另一项),无需回滚。

## 合并门(勿提前)

按 docs/VNEXT_MEASUREMENT.md 密封条款:07-19 两份周报(07-12/07-19)落地后,
与解冻捆绑四件同批走 PROCESS 变更流程,DECISIONS 记录后方可合并部署。

## 外部审查放行记录(2026-07-11,使用者转达)

- **3a/3b 分支 diff(072dc83)外部审查逐行审毕:放行**;合并门维持 07-19 不提前。

**合并日注意(07-11 补,随放行同录):**

1. e 项换 prompt 哈希后 `_PROMPT_LABELS` 登新键,旧键作历史标签保留;
2. 同窗口多件(本分支/supersede/PIT护栏/哨兵首批)合并次序由 07-19 排序会
   统一定,不各自 rebase。
