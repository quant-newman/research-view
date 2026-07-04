# B7 周度成绩单(三期)设计说明

> 四期演进的第三期(一期头版化 ✅ → 二期 B6 研判卡 ✅ → **三期 B7 成绩单** → 四期 B8 个股决策层)。
> B6 让判断留痕,B7 让判断被记分——"判断必须可追责"铁律的闭环端。B8 须等 B7 首份真实成绩单后开工(避免无校准裸荐股)。

## 分工原则

**记分/归因归代码,归纳归 LLM。** 到期对账、命中率、分源归因全部由 `src/research_view/scorecard.py` 确定性计算;DeepSeek 只对"本周判错的卡"做错误归纳(信息错/逻辑错/纯运气)并提炼下周教训(lessons)。

## 记分口径(与 B6 发卡口径同一)

- 卡的 direction = 对"发卡日起 horizon_days(5) 个开市日内,节点**相对全池**超额"的判断。
- 到期日 = 发卡日后第 5 个开市日(md.trade_calendar,**须 DISTINCT——沪深两所各一行,不去重 horizon 被折半**,2026-07-03 实测踩过)。
- 节点收益 = 成分股等权区间收益(bar_daily_raw 未复权 close,同 heatmap 口径,除权票会失真、等权下影响有限);全池收益 = 全核心池等权(beta 基准);超额 = 两者之差(pp)。
- 判定:方向卡 |超额|≥1pp 才定对/错,带内=**平**(不给贴边判断白捡命中);中性卡 |超额|≤2pp=对。
- 每节点每日只记**最新 card_id**(append-only 重跑卡不记分);记分本身是行情的函数,card_score 可重算,PK upsert 幂等。

## 分源归因(代码算)

对每张已定对/错的方向卡:某源"显著且指向卡方向"(|z|≥1 同号;信函=命中且立场同号)即计入该源名下,统计"跟随该源方向的判断"命中率。错误卡的 z 矩阵快照随卡在库,逐卡可复核哪个源误导了方向。

## 校准回路(lessons 回灌)

周日收口:`weekly()` 汇总累计/本周命中 + 分方向/分源 → 本周错误卡喂 DeepSeek → `b7_weekly.lessons`(2-5条可操作教训)。`evidence.generate()` 每天发卡前读**最新一份非空 lessons** 注入 prompt(明示"经验校准,不是事实源,不得写进 evidence")。无错误卡不烧 LLM,lessons 空则不回灌。

**校准期冻结(DECISIONS #28,2026-07-04):`CALIBRATION_FREEZE`(默认冻结)拦住 B6/B8 两处注入点——lessons 只落库不注入,防首批校准样本 prompt 漂移;冻结状态每次 pipeline 落 task_log(`calibration_freeze` 步,1=冻结)。解冻=首份周报+样本≥40 后使用者拍板,显式置 0 并记 DECISIONS。判断卡带 `prompt_hash`(SYSTEM+规则模板+lessons段,排除每日数据块),B7 可按 prompt 版本分组样本。**

## 编排与消费

- **日常记分**:run_pipeline 盘后档 `card_scores` 步(judgment_cards 之后,零 LLM 幂等)——到期卡当晚即记分,不等周日。
- **周度收口**:`scripts/run_scorecard.sh`,台北 cron `0 12 * * 0`(周日 20:00 UTC+8):补记分→weekly→重建 dashboard→拉回。
- **导出**:`dash.scorecard = {pending, cum, by_direction, by_source, curve(周命中率), recent(最近12张), weekly{lessons,review}}`;从未发卡=None。
- **前端**:报告页右栏「研判成绩单 · B7 判断追责」——命中率/对错平计数/周曲线 chips/分源归因/最近记分卡(对=红 错=绿 平=灰徽章)/本周教训。**对错都晒**,空态如实显示"待记分 N 张"。

## 时间线(2026-07-03 上线时)

- 首批 8 张卡 07-03 发出 → 07-10(周五)到期,当晚盘后 cron 首次真实记分。
- 首个有内容的周报 = 07-12(周日);本周日 07-05 会跑出诚实空单。
- ~~lessons 首次回灌 ≈ 07-13(周一)盘后发卡~~(校准期冻结,DECISIONS #28:解冻前只落库不注入)。

## 已知边界

- 未复权收益的除权失真(同 heatmap,接受)。
- 分源归因只统计"源与卡方向一致"的情形,不区分该源是不是 thesis 实际依赖的源(matrix 快照在库,B8 阶段可细化到 evidence 级归因)。
- 平局卡不进命中率分母(hit_rate = 对/(对+错)),防止震荡市刷分。
