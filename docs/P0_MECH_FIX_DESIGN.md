# P0 机械基线修复设计(a 稿·预注册)

> 状态:**预注册已锁定(2026-07-14)**。实施批次由 07-19 排序会裁定。
> 硬闸期纸面 only:不 ALTER TABLE、不部署、**不生成或查看任何新列数值或存量重算数值**(本文档不含任何 raw 实算值,含实算值即违规)。
> 密封纪律:自锁定起,两种变体的**定义、名称、主次及 indeterminate 规则**不得因结果调整;正文只追加勘误(erratum),不改原文。
> 裁决时点核验:本裁决锁定于查看任何新列结果之前——满足 07-12 计划令"主变体语义裁决人拍须在算任何新列数字之前"。

## 0. 裁决正文(使用者 2026-07-14 拍板,照录,权威文本)

**主变体:**

> stock_raw_mech = sign(raw_directional_score)。
> raw_directional_score = 1.0\*price_z + 1.0\*mf_z + 0.8\*news_z + 0.6\*lhb_z。
> 研报/人气注意力不带方向,不参与 raw 方向计算。

**误差带(本裁决予以预注册;经核,0.017 数值条款此前无仓内可核实落档,不追认"此前已预注册"):**

> 存量 decision_card 只能使用 matrix 内两位小数 z 重算。
> 单项舍入误差上界为 0.005,权重绝对值之和为 3.4,
> 因而合成误差上界 = 0.005×3.4 = 0.017。
> - |raw_score| ≤ 0.017:indeterminate,禁止强判;
> - raw_score > 0.017:偏多;
> - raw_score < -0.017:偏空。

**新卡:**

> 新卡实施时,从内存中未经 matrix 两位小数展示舍入的 dz 计算 raw_directional_score,
> 并将该计算值与 weight_version 写入新增落库列;matrix 内各 z 继续保持现行两位小数存储,不改变其既有行为。
> 新卡使用未经 matrix 两位小数展示舍入的 raw_directional_score:>0 记偏多,<0 记偏空,=0 记中性、不判方向。
> 存量卡的 |raw_score| ≤ 0.017 仍记 indeterminate,不得与中性混同。
> 新卡全精度 raw_directional_score = 0 时记机械中性,其记分沿用现行中性卡口径:|超额|≤2pp 判对,超出判错。
> 该规则仅作用于机械基线,不改变 B8 正式卡的方向或记分。

**变更边界:**

> 给 decision_card 增加上述列属于 schema 及在线判断链变更:当前只进入 a 设计稿,
> 不在硬闸期 ALTER TABLE、不部署、不生成或查看新列结果;实施随 07-19 后正式 a 稿批次及变更流程进行。

**影子基线:**

> node_follow 保留为影子漏斗基线,用于衡量 B8 相对直接继承 B6 方向的增量,不作为 stock_raw_mech 主基线。
> 存量应用前必须审计 node_card_id 非空率、孤儿率和可解析率;未达到 100% 覆盖,不得表述为"存量全量适用"。

**披露:**

> 存量卡中被判为 indeterminate 者,不进入 stock_raw_mech 的方向记分样本;
> 必须单列披露 n_indeterminate,并同时报告总候选数、可判定样本数及其对账关系,
> 禁止静默剔除或只报告缩分母后的命中率。

**回指:**

> VNEXT_MEASUREMENT.md l 件所称"indeterminate 带规则",以本裁决定义为准;
> l 件密封正文不作改动,仅在允许追加的位置登记本裁决及其权威回指。

## 1. 问题定义(P0)

个股侧机械基线输入用错变量:`score_mature` 以 `_verdict(_mech_dir(align), excess)` 记 mech_verdict
(scorecard.py:200),而 align = decision_card.alignment。alignment 的构造
(decision.py:161)= `s * Σ(w·dz) + 0.3*attn`,且候选入池门槛 `align ≥ _MIN_ALIGN(1.0)`
(decision.py:165)——**入库的 alignment 按构造恒 ≥ 1.0 恒正**,`sign()` 之下个股机械基线恒偏多,
mech ≡ always_long(结构性,非巧合;节点侧输入 resonance 可负,不在本修复范围——07-12 更正令已核,
节点侧 mech≡always_long 系换卡等值巧合)。
后果:B7 stock_baseline.mech、override_slices 四桶(scorecard.py:263-281 以 alignment 符号配对)、
by-源归因中凡消费个股 mech 方向者,全部结构性失效(07-12 周报已按"结构性失效(机械方向≡恒多,P0待修)"标注)。

## 2. 主变体定义(锁定)

- 名称:**stock_raw_mech**(主机械基线,个股侧)。
- raw_directional_score = 1.0·price_z + 1.0·mf_z + 0.8·news_z + 0.6·lhb_z
  ——即现行 alignment 公式中乘节点方向号 s 之前的方向源加权和(decision.py:17 `_W` 现值,:161 求和项)。
- 方向:>0 偏多,<0 偏空;新卡全精度 =0 记机械中性;存量走 §3 误差带。
- 研报(research)/人气(hot)为注意力项(`attn`,decision.py:18,"不带方向,只加不减"),不参与 raw 符号。
- 措辞纪律:只称"**在既定 B8 候选样本内方向独立计算**",不得称"完全独立于 B6"
  ——候选入池经 `align ≥ 1.0` 门槛,样本选择已条件于节点方向,raw 符号与 B6 在样本层面天然相关。
- 权重绑定:上述权重即 **weight_version = w1**。权重任何变更 = 新 weight_version,
  误差带按公式(§3)随之重算,新旧版本数值不混池。

## 3. 误差带(预注册,含推导)

- 依据:matrix 内 z 以 `round(z,2)` 存储(decision.py:116-119);alignment 列含 attn 与节点号且已 round,
  **无法反推全精度 raw**。存量重算唯一合法输入 = matrix 两位小数 z。
- 公式:**band = 0.005 × Σ|wᵢ|**。w1:Σ|w| = 3.4 → band = 0.017。
- 上界性质:最坏情况可达(四项同时踩舍入边界且同向,已数值验证差恰为 0.017 且带内存在符号翻转实例),
  端点必须划入 indeterminate,故取 ≤(含端点)。
- 保守方向声明:此为必然性上界而非统计带——带内卡中会混入部分实际可判者,接受;
  "禁强判"纪律要求宁可少判、不可错判。不得以 RMS/统计带替代(那是"大概率对",与禁强判措辞不匹配)。
- 判定三段(存量,w1):|raw| ≤ 0.017 → indeterminate;> 0.017 → 偏多;< -0.017 → 偏空。

## 4. 新卡实施(实施批次执行,本节为设计)

- schema:`ALTER TABLE decision_card ADD COLUMN raw_directional_score numeric, ADD COLUMN weight_version text`
  (nullable;ALTER 属 DDL,不触发 append-only 行触发器)。
- 写入:仅在发卡 INSERT 时写入(decision.py 落库段),值取自内存全精度 `f["dz"]`
  (未经 matrix 展示舍入),weight_version='w1'。matrix 存储行为零改动。
- **append-only 硬约束(sql/023 trg_dcard_no_mod 阻断 UPDATE/DELETE):存量行两列永为 NULL,
  禁止任何回填企图**;存量重算走 §5 派生层。此与 h 件先例同构(卡表本行零触碰,注记落派生层)。
- 记分(score_mature):个股 mech 输入由 alignment 换为 raw_directional_score
  (非 NULL = 新卡全精度路径;NULL = 存量派生重算路径,带 §3 误差带)。
  indeterminate 卡的 mech_verdict 记 NULL 并入 n_indeterminate 计数,不入方向记分样本。
- 机械中性记分:沿用现行中性口径(`_NEUTRAL_BAND=2.0`,scorecard.py:20,80-81:|超额|≤2pp 判对,超出判错,无平档)
  ——纯输入变量替换,判定机器(`_verdict`/`_mech_dir`)零新规则。
- 边界重申:仅作用机械基线列(mech_verdict),B8 正式卡 direction/verdict/记分零触碰;
  不动 prompt、不动发卡口径(raw 列是发卡已算数据的固化,非新判断输入)。

## 5. 存量处理与纪元切分

- **纪元 E0**(实施日前发卡):raw 由派生层纯函数从 matrix 两位小数 z 重算,
  标 weight_version='w1_recalc2dp',带 §3 误差带;**不落卡表**(append-only),
  统计输出一律带 rule_version 标签;如需留档,以审计目录 JSON 归档(哨兵第9项同路线:只读 SQL+纯函数)。
- **纪元 E1**(实施日起发卡):卡表两列非 NULL,全精度,无误差带。
- **已记分存量行的 mech_verdict 一律不改写**(07-12 勘误纪律:已出结果只追加勘误)。
  旧 mech_verdict 序列 = always_long artifact,封存展示、标注 erratum;
  修复后统计按纪元/weight_version 切分输出,**禁混池比较**——
  "旧结果留档禁静默覆盖"的落点:旧列原样 + 新统计带版本标签,两代数值并列可见。
- 下游消费方同口径清单(实施批次逐处落实,防派生层静默说谎):
  `baseline_stats`(scorecard.py:97)、`override_slices`(:263,现以 alignment 符号配对,须换 raw 并剔除
  indeterminate 且计数披露)、weekly baseline.mech、dashboard 成绩单展示。
  **凡消费 mech 方向的派生统计,同口径处理 indeterminate 并披露,不得只在主命中率处对账。**

## 6. 披露与对账(每期统计输出必含)

- n_total(候选总数,按纪元) = n_directional(可判方向) + n_neutral(机械中性) + n_indeterminate。
- 三项及对账等式随命中率一并输出;禁静默剔除、禁只报缩分母命中率。
- 与 SENTINEL 第 3 项扩容(应入样行数核对)同构,哨兵实现时本对账入其核对面。

## 7. node_follow 影子基线

- 定义:个股机械方向 = 直接继承上游节点卡方向(node_card_id → judgment_card.direction)。
- 地位:影子(l 件影子基线族成员),衡量 B8 相对直接继承 B6 方向的增量;不作主基线。
  raw 变体自本裁决起兼为个股主机械基线定义,其在 l 件影子族中与 node_follow 的并列对照关系不变。
- 存量应用审计前置(实施批次执行,预注册查询口径;三项均 100% 才可称"存量全量适用",
  否则只在覆盖子集内声明并披露缺口计数):
  1. 非空率:decision_card.node_card_id IS NOT NULL 占比;
  2. 孤儿率:node_card_id 在 judgment_card.card_id 中不存在的占比;
  3. 可解析率:所指节点卡 direction ∈ {偏多,偏空,中性} 的占比。

## 8. 测试预注册(实施批次带测试,全部先写后跑)

1. 偏空用例:合成负向 dz → stock_raw_mech=偏空(杀死"恒偏多"回归);
2. indeterminate 带用例:存量路径 |raw|=0.017(端点)与 0.01 → indeterminate,入 n_indeterminate,不入方向样本;
3. 带外用例:存量 raw=±0.018 → 正常判向;
4. 新卡全精度 =0 → 机械中性,±2pp 记分口径;
5. 非恒等验证:混合方向合成集 → mech 方向分布两侧非空(mech 不再恒等 always_long);
6. weight_version 落值:新卡='w1',存量派生='w1_recalc2dp';
7. append-only 合规:实施路径对 decision_card 存量行零 UPDATE(触发器兜底,测试显式断言);
8. 对账等式:n_total = n_directional + n_neutral + n_indeterminate;
9. override_slices 换输入后:indeterminate 剔除+计数,四桶配对用 raw 符号非 alignment 符号。

## 9. 实施顺序与验收(07-19 排序会定批次后)

裁决(✓已锁) → node_follow 三项审计 → ALTER(两列) → 发卡写入生效(E1 起点=部署 commit,记 DEPLOY_STATE/LOG)
→ score_mature 输入替换+披露计数 → 派生层 E0 重算对照(带版本留档) → 测试全绿 → 验收。
验收标准:①首个实施后发卡批 mech 方向分布非单侧(结合 5 号测试);②对账等式成立且披露齐全;
③存量 mech_verdict 零改写(SQL 抽核);④B8 正式卡 verdict 与实施前口径逐位一致(边界零泄漏)。

## 10. 与既有文档关系

- VNEXT l 件"indeterminate 带规则"以本裁决定义为准(l 件密封正文不动,文末登记回指,见该文 2026-07-14 节)。
- 07-12 CORRECTION.md:B8 侧结构退化论据、"结构性失效(机械方向≡恒多,P0未修)"标注——本设计即其修复预注册;
  实施前该标注措辞继续有效(金宏气体 688106 suppress 候选等个案沿用固定措辞)。
- BRIER_SPEC/概率链:零涉及(raw 列不进 prompt,不改 subjective_prob 任何口径)。
- #22 冻结:本设计不动 prompt/权重/发卡口径;schema 与记分输入替换属测量层变更,实施仍等硬闸解除后走正式批次。

## 修改记录

- 2026-07-14 初版落档(裁决同日锁定)。此后正文只追加勘误。
- 2026-07-14 使用者复核:主体通过;§9 验收标准①以勘误 E1 替代(见文末勘误节)。

## 勘误(erratum;密封正文零触碰,只追加)

### E1(2026-07-14,使用者复核指令):§9 验收标准①替代

原文"①首个实施后发卡批 mech 方向分布非单侧(结合 5 号测试)"**作废**——
单日全多/全空可为正常市场状态,原标准会将其误判为验收失败,
且与 SENTINEL 第 10 项(基线退化与非预期等价检测)的判定逻辑冲突。
替代标准(使用者措辞照录):

1. 合成混合方向测试必须产生偏多与偏空,证明 stock_raw_mech 在完整适用域内
   不存在结构性恒定;
2. 首个真实发卡批只披露方向分布,不以单批单侧作为验收失败条件;
3. 单批全多或全空不得报红;
4. 滚动窗口长期单侧按 SENTINEL 第 10 项先报黄,并披露独立发卡日、
   上游方向分布和样本量;
5. 只有公式/字段语义可证明的结构性退化,或满足预注册最小覆盖后与其他
   基线非预期全量等价,才判验收失败或红。

其余各节使用者 2026-07-14 复核验收通过。
