# 观象·07-13 白天准备令(终稿)照录 + 选卡规则锁定时间戳

> 锁定时间戳:**2026-07-13 14:48:02 +0800**(第二节抽样规则自此刻锁死,
> 先于今晚 22:30 任何结果产生;git commit 时间为次级锚)。
> 版本沿革:初稿(同日上午)经现查评审提出四处缺口(两侧n=0穷尽/手算round4/
> calibration_block 取值路线/位数以代码 round 为准)+一处执行提示(累积域不加
> trade_date 过滤),终稿全部吸收;评审结论=与既有决策无冲突,唯一阻塞为四2
> 隐私审计边界文档缺失(见 03_privacy_audit_status.md)。
> 预检结果:七项全过,见 01_precheck.md。

## 终稿原文(照录,零删改)

【观象·07-13 白天准备令(终稿)】(锚:main=db9ad45,本地与 origin 零差异,现查确认)

一、哨兵第9项规格追加扩容
SENTINEL_SPEC.md 密封正文不改,在文末追加本节(与07-12第7项论据登记同惯例——
该文件本身即"纸面预注册2026-07-11密封",不得改写原九项文字)。
原"抽一张手算"为第一层要求,本次补齐第二层全样本均值核对,两层同时留档:
  (a) 单卡贡献:严格按第二节预先锁定的选卡规则取一张 verdict∈{对,错}的
      prob 卡,手算 (subjective_prob − outcome)²(outcome 对=1/错=0,
      与 brier_stats() 定义一致[scorecard.py:323]);手算结果先 round 到4位
      再与系统值比对,不得用全精度手算值对系统 round(...,4) 输出(否则必现假性不一致)
  (b) 全样本重算:选定字段(见二·抽样规则)全部入样卡人工重算 squared_error
      均值,与系统 calibration_block() 输出的对应 brier 值逐位核对。
      calibration_block() 只活在 weekly() 内部调用[scorecard.py:459,463],
      而 weekly() 今晚禁跑(五2)——取值方式:照抄 scorecard.py:456-458 的
      两段 SQL(card_score JOIN judgment_card / decision_score JOIN decision_card,
      均 WHERE subjective_prob IS NOT NULL)在只读连接里现查,取回的行手工传入
      calibration_block() 纯函数调用(REPL 或一次性脚本,不落任何生产代码改动,
      不触碰 weekly() 本体),调用过程本身入留档。
      该 SQL 不限 trade_date、只过滤 prob 非空——今晚这个域会恰好等于07-06批
      已记分子集:HORIZON_DAYS=5[decision.py:22/evidence.py:23],07-06(周一)+5
      交易日(07-07/08/09/10/13)到期日正是今晚,07-07/08/09批(即便带prob)
      到期都在07-14之后,今晚未到期不会混入——这是horizon结构决定的,不是巧合。
      留档 SQL 照抄原域即可,不要自行加 trade_date 过滤去"对齐"(那会破坏与
      系统值的可比性);trade_date=2026-07-06 限定是五7 对账的事,与一(b) 分开,不要混。
  禁止行为:单卡 squared_error 直接比多卡累计 brier 均值——打回项。
  留档须含:卡号、样本域、SQL 或等价查询、单卡贡献值、两个对比值(均已round到位)。

二、抽样规则锁定(先于看任何今晚结果,现在锁死;本条时间戳与本令一并留档)
  主核字段 = node × direction,即 calibration_block() 返回结构中的 "direction" 键
  (对应 card_score/judgment_card,取 direction≠中性 的行[scorecard.py:346]);
  个股侧为 stock_calibration.direction,对应 decision_score/decision_card
  [scorecard.py:463,475]。
  单卡选择规则:该字段下 verdict∈{对,错}、card_id 最小者。
  回退规则:若该字段 n=0,才回退用 stock_calibration.direction,并记录回退原因;
  若两侧均 n=0(如全部为"平"),记诚实空态,一(a)(b) 顺延至首个有样本日执行,
  不得当场另订选卡规则。
  今晚出结果后不得以任何理由更改本节选卡规则。

三、只读预检(今日白天执行,只查不改)
  1. 07-06 批数量核对:B6 应为 8 张、B8 应为 12 张
     (取证基准:docs/audit/20260706_subjective_prob/06_acceptance.md 第2项完整输出
     [judgment_card card_id 19-26/decision_card card_id 15-26,trade_date=2026-07-06]
     及 docs/audit/20260712_weekly_correction/evidence/ref_epoch_forensics.txt 第25行
     "首批prob卡8 B6+12 B8")
  2. 全部 prob 非空且落在开区间 (0,1)
  3. prompt_hash 一致(登记真值 B6=8528ca795ca4c6b8 / B8=780916554dc9be8b,
     #41 落档,与 _PROMPT_LABELS[scorecard.py:296-297] 一致)
  4. 07-06 批在今晚22:30正式cron前不得已有 card_score/decision_score;
     仅按 07-06 批 card_id(judgment_card 19-26 / decision_card 15-26)查询,
     不以全表是否存在 verdict 判断
  5. CALIBRATION_FREEZE=1(config.py:calibration_freeze() 读环境变量,
     默认冻结[config.py:65],现查确认)
  6. 无参照层变更(双冻结之一仍生效)
  7. 核对 07-12 23:20 扫描确有执行:以 crontab 触发记录、扫描自身日志或飞书送达
     记录证明"扫描任务执行";另附其读取的 task_log 扫描结果。
     除非扫描器设计上本就写 task_log,不得强求人造一条 task_log 记录。
  预检全部只读查询,发现任何一项不过,当场停止并向外部审查窗口报告,不自行处理。

四、白天可做的纸面/只读事项
  1. 金宏气体(688106,card_id 12)suppress 候选案例入档,措辞固定:
     "suppress 候选案例;B8 mechanical P0 未修,当前不得称 LLM 压掉正确机械信号"
  2. 隐私审计按 07-12 已批准的只读、脱敏边界执行并交回;
     当前状态=待执行/待验收,不得写"已验收通过"

五、今晚(07-13 22:30起)执行约束
  1. 只允许正常 22:30 UTC+8(=14:30 UTC)cron 触发的 run_afterhours.sh→
     ssh 阿里云→run_pipeline.py 执行,不得手动触发
  2. 禁止手动运行 weekly() 或 run_scorecard.sh(双冻结硬闸,维表护栏未落地)
  3. Brier 计算只用只读查询 + 现有纯函数 brier_stats()/calibration_block(),不新写计算逻辑
  4. 系统输出值按代码现有 round 位数核对(以代码为准,不自行统一位数):
     brier=round(...,4);flat_rate/p_mean/hit_rate=round(...,3)[scorecard.py:322-337]
  5. 同时报三个数:n、n_flat、flat_rate(brier_stats() 原生返回,不需额外开发)
  6. by_version 中"76节点"标签维持已登记 erratum 状态,只在交回材料里加注,不改代码字符串
  7. 到期批对账必须限定 trade_date=2026-07-06:
     · B6:该日最新卡中,已产生 card_score 的数量 + 仍无 card_score 的数量 = 8
     · B8:该日最新卡中,已产生 decision_score 的数量 + 仍无 decision_score 的数量 = 12
     两侧分别列出 scored/unresolved 及 card_id。
     禁止拿 score_mature() 顶层返回的全库 pending 直接与 8/12 比较——
     run_pipeline.py 执行顺序为 judgment_cards→decision_cards→card_scores
     [run_pipeline.py:62-66] 同一次跑,score_mature() 的 pending 不分 trade_date
     [scorecard.py:115-134],今晚一定会先生成 07-13 新卡,这些未到期新卡会被
     同一次调用计入全局 pending,污染对账。

六、今日绝对不动的三样(仍受硬闸约束,不因本令新增任何理由解冻)
  - B8 mechanical P0(alignment 恒正导致 mech_verdict 恒偏多)——不修
  - weekly() 维表 INNER JOIN bug——不修
  - "参照层v3(76节点)"错误标签——不改代码,只加 erratum 注记

七、交回时间与形式
  白天四项(一~四)完成后先交回留档,不必等 22:30;
  今晚五~七三项在 22:30 pipeline 跑完后交回,附全部取证(SQL/查询结果/截图)。
  无实证的"已完成"=未完成,交回时每一项须能被现查复现。

## 评审时现查核实过的全部锚(执行侧记录,供复现)

- main=db9ad45 本地=origin(git fetch 后 rev-parse 双值同)
- calibration_block "direction" 键取 direction≠中性 行 → scorecard.py:346
- stock_calibration 键 → scorecard.py:463,475
- brier_stats round(...,4)/n/n_flat/flat_rate → scorecard.py:316-337
- outcome 对=1/错=0 → scorecard.py:323
- calibration_freeze 默认冻结 → config.py:62-65
- run_pipeline 顺序 judgment_cards→decision_cards→card_scores → run_pipeline.py:62-66
- score_mature pending 全库口径不分 trade_date → scorecard.py:106-134
- HORIZON_DAYS=5 → decision.py:22 / evidence.py:23;_horizon_end=发卡日后第5开市日
  → scorecard.py:59-65(07-06→07-13 今晚到期;07-07批→07-14)
- 22:30 链路:crontab 14:30 UTC → run_afterhours.sh:27 ssh 数据节点 run_pipeline.py
- 06_acceptance.md 第2项 19-26/15-26 逐卡输出、prompt_hash 真值三处一致
  (DECISIONS #41 / _PROMPT_LABELS / 06_acceptance)
