# e 件设计稿(b 稿·草案 v2):判断链入库结构校验

> 状态:**草案 v2(2026-07-14),已按使用者同日复核裁决修订;仍为草案,暂不锁定**。
> 实施属 **prompt 变更纪元件**:硬闸期不改在线 prompt、不实施任何 schema/代码变更、不运行真实数据;
> 实施批次归 07-19 排序会,与 3a/3b 分支合并、资金标准化、禁换算铁律(decision/evidence 两链补)**同纪元窗口**。
> v1 的【人拍】5 处已全部裁决(见 §12 落点表);v1→v2 修订清单见修改记录。

## 0. 依据(全部既有登记与裁决,本稿不开新号)

- VNEXT e 件登记原文(07-10 裁决/07-11 追加):B1 回指校验 + B6/B8 fact_id + 必填闸按卡型拆分
  ——缺失一律拒卡并记失败原因。
- C-1 裁决前瞻第 2 条:价位行机器可验格式统一覆盖 **entry/exit/falsify 三处**。
- 07-12 计划令 b 稿两项输入:①证据三分 fact/derived/inference + 三条必失败测试用例;
  ②外生催化标 + 独立事实计数按 event/claim 去重,聚类规则带版本,无法可靠聚类只披露来源条数。
- **2026-07-14 使用者复核裁决**(本 v2 修订依据):三处结构缺口(fact 载荷代码权威化/
  "全批拒=诚实空态"作废/run 级身份与对账)+5 处【人拍】裁决+duplicate 处置、
  B6 中性升必填、展示代价三项确认。

## 1. 现状结构事实(代码核对,2026-07-14)

- B6 evidence = `[{src∈六源, fact:自由文本带数字}]`(evidence.py:226,290);B8 同构(decision.py:214)。
  **fact 无结构锚**,溯源=事后人工回定位(07-11 抽验法,C-1 即此法产物)。
- B8 entry/exit/falsify 均自由文本;价位规约(D 类)纸面规则无机器校验(C-1 实证)。
- **拒卡机制现状为零**:解析失败只降级;direction 非法**静默归"中性"**(decision.py:252);
  evidence 空数组照样入库;subjective_prob 非法静默落 NULL(从 Brier 样本静默消失);
  **未知 code 的 LLM 输出静默丢弃(decision.py:250-251,不可见);同 code 重复输出无去重,会重复入库**。
- 输入块无编号(decision.py:176-192,evidence.py 同构)。

## 2. fact_id 与输入快照(裁决①已锁)

- **id 由代码生成,LLM 只能从输入清单照抄,不得自行拼接**。文法(已锁):
  - `news:<news_id>`——**raw_news.news_id 文本主键**(url 优先/hash 退化的去重键,非行号;sql/003:6);
  - `mx:<JSON Pointer>`——如 `mx:/price/ret_1w`,锚到落库 matrix 同一份;
  - `rsch:<report_id>`(research_report.report_id,sql/009:3);
  - `letter:<letter_id>`(fund_letter.letter_id,sql/009:27);
  - `hot:rank`——**仅在该 generation_run 输入快照内有效**(人气榜无稳定行锚)。
- **输入快照持久化**:generation_run 保存当次 **id→规范化事实载荷** 的输入快照
  (或其不可歧义快照锚),源表日后演化不致只剩指针无法复原当时输入(PIT,与 f 件护栏同族)。
- 入库校验(代码):evidence 每条 fact_id ∈ 该 run 输入快照 id 集合;src 与 id 前缀一致。
- 存量卡零触碰:fact_id 只约束新纪元卡,不回填(卡表 append-only)。

## 3. 证据三分 fact / derived / inference(缺口①修订:载荷代码权威化)

| kind | LLM 职责 | 代码职责 | 校验(入库,代码) |
|---|---|---|---|
| fact | **只选择 fact_id** | 展示文本、数字、单位由代码按输入快照解析渲染;**不接受 LLM 自写的 fact 数字作为权威值** | 指针有效性;载荷=快照,构造即真 |
| derived | 给结构化 `{operands:[fact_id...], op, parameter}` | **操作数由代码按 fact_id 取值,结果由代码复核或生成**;自由文本算式只作展示不作计算真值 | 复核失败拒卡 |
| inference | 写推断文本 | — | **禁新数字**(其数字须出现于所引 fact/derived);**禁直接 fact_id 冒充事实**,以 `supporting_fact_ids`(≥1)回指支撑 |

- 禁换算铁律的结构落点:换算数字只能以 derived 形态存在且由代码算出——
  C-1 同型(证伪行裸换算数字)在本闸下无法入库。
- 07-11 抽验 A/B/C/D 分级自此有结构对应物,抽验转为对闸的复核。

## 4. 必填闸按卡型拆分(缺失一律拒卡记因;裁决②扩容)

| 卡型 | 必填 |
|---|---|
| B6 偏多/偏空 | evidence≥2(≥1 条 kind=fact)+ scenarios≥1,**且其中至少一条 scenario.falsify 非空**、具体、horizon 内可验证 |
| **B6 中性** | thesis 明确说明为何中性及当前矛盾 + evidence≥2(≥1 fact,全部过结构校验)+ scenarios≥1,**且其中至少一条 scenario.falsify 非空**:具体、horizon 内可验证,说明什么情况证明"中性/未走出方向"错误。**不强套 B8 基于 decision_card.close 的价位结构文法**(节点卡无同类锚),但禁止"市场变化""趋势转强"等不可验证空话 |
| B8 偏多 | entry(带 §6 价位结构)+ exit(含止损价位锚)+ falsify + evidence≥2(≥1 fact) |
| B8 偏空 | 回避解除条件(exit 位)+ falsify + evidence≥2(≥1 fact) |
| **B8 中性** | thesis 说明放弃理由 + **falsify 必填**(什么信号说明本次放弃是错的,horizon 内可验证)+ evidence≥2(≥1 fact) |

- 裁决依据:中性是**会被 ±2pp 口径正式记分的放弃判断**,不是无判断空态,必须同样可证伪。
- **schema 落点约束(2026-07-14 使用者裁定)**:**B6 不新增 judgment_card 顶层 falsify 列**——
  B6 各方向(含中性)的 falsify 均落在 scenarios 数组元素内(现行 schema 即此形状:
  sql/021:14 `scenarios jsonb [{cond,expect,falsify}]`,无顶层列);
  **B8 的 falsify 仍使用 decision_card 顶层 falsify 字段**(sql/023:19)。
  本闸对 B6 校验的是 scenarios 元素内字段,不引入任何 judgment_card 加列。
- **真空通过禁令**:任何卡型不得出现"全数校验通过但 evidence 数组为空"。
- **subjective_prob**:所有新纪元卡必须合法落在 (0,1);非法**不得静默落 NULL 后入卡**,
  拒卡记因(reason=invalid_subjective_prob)——防从 Brier 样本静默消失。
- **direction 非法**:新纪元改为拒卡,reason=invalid_direction(替代现行静默归中性)。

## 5. generation_run 层与状态语义(缺口②③修订)

**run 级身份(仅按 trade_date 无法处理重跑,也无法证明候选/入库/拒卡同源):**

- **generation_run 表**(insert-only):run_id、card_kind(B6|B8)、trade_date、candidate_count、
  prompt_hash、gate_rule_version、model 及可取得的响应元数据(完整响应如需保留在此存一次)、
  状态、created_at。
- **rejected_card 表**(insert-only):run_id、candidate_key、reject_reasons jsonb、
  raw_candidate_json(**只存对应候选项,不把完整响应重复写多次**)、response_hash、created_at。
- 两表**禁止 UPDATE/DELETE/TRUNCATE**(与卡表 append-only 触发器同构)。
- 接受卡(judgment_card/decision_card)新增 generation_run_id、gate_rule_version 两列
  (INSERT 时写,存量 NULL,append-only 不回填)。表名可在实现稿调整,**能力不可删**。
- candidate_key:B6=node_id,B8=code;**同一 run 内按 candidate_key 唯一**。

**对账(单个 run 内成立):**

> **n_candidate = n_inserted + n_rejected + n_llm_missing**

- **n_orphan_output 单列**(LLM 输出了不在候选集内的 key),**不得混入候选分母**;
- **duplicate_output 处置(裁决已锁)**:同一 run 内同一 candidate_key 出现多份输出——
  该候选**全部输出作废**,不取第一条、不取最后一条、不择优;候选对账中只计一次
  n_rejected(reason=duplicate_output);全部重复副本**按原顺序**存入该拒卡记录的
  raw_candidate_json 数组,并记 duplicate_count;候选分母按 candidate 计,不按输出条数计。
  (目的:解析顺序不得成为隐藏裁决,杜绝事后挑选最有利输出。)

**状态语义("全批拒=诚实空态"措辞作废):**

- n_candidate = 0 → **honest_empty**(诚实空态,唯一合法空态);
- n_candidate > 0 且 n_inserted = 0 → **failed_validation**(或等价明确状态),
  **不得称诚实空态**;前端/health 必须明确显示"有候选但全部校验失败",不能伪装成无信号;
- export 是否继续留给 g 稿裁决,本稿只锁状态语义与可见性义务。

## 6. 价位机器可验结构(裁决④已锁:结构化子字段,不解析中文自由文本)

```json
{"anchor": "close", "anchor_value": 488, "delta_pct": -5.0,
 "derived_price": 463.60, "formula_version": "close_pct_v1"}
```

- **delta_pct=-5.0 明确表示 -5%**,禁止 0.95/百分数倍数混用(与 percent-vs-multiple 铁律同源);
- 计算用 **Decimal**,按 A股价格 tick=0.01 与预注册舍入规则(实现稿定死,round-half-up【实现稿列明】);
- entry/exit/falsify 凡出现价位均**复用同一结构与同一校验函数**(单点实现);
- narrative 文本与结构字段分离,展示归 narrative,校验只认结构字段;
- anchor=close 取 decision_card.close(既有列);
- 复核失败拒卡 reason=price_formula_mismatch——**(488, -5%, 460.0) 必须触发**(应 463.60)。

## 7. 外生催化标 + 独立事实计数(裁决⑤已锁)

- **外生催化标**:kind=fact 条目可带 `exogenous: true`(政策/订单/业绩预告/停复牌等非行情内生)。
  LLM 标注属推断,规则文本带版本(exo_rule_v1);错标不拒卡,只作归因维度;周报按 exogenous 切片。
- **cluster_v1(保守确定性规则,版本固定)**——以下条件**全部满足**才允许合并为同一独立事实:
  1. 同一股票/节点 scope;
  2. 同一枚举 event_type;
  3. primary_entity 一致;
  4. 规范化 claim_key 一致;
  5. 同一 cluster 最早至最晚发布时间跨度 ≤48 小时。
- 任何关键字段缺失或无法可靠规范化 → **不输出 n_independent_facts**;
  只披露 source_count、n_confirmed_clusters、n_unclustered,并标
  cluster_status=unavailable/partial。**禁止为凑独立事实数强行聚类**。纯代码实现,零 LLM。
- 用途边界:只落计数与标注,不改共振/对齐权重、不改候选门槛(n_directional_active 增强另行登记)。

## 8. prompt 纪元、实施顺序与拒卡率阈值(裁决⑤后半已锁)

- SYSTEM/_USER_TMPL/evidence 输出格式变更 → 新 prompt_hash;_PROMPT_LABELS 登新键、旧键留历史标签;
  B6/B8 两链同批换纪元;同纪元窗口合并件(3a/3b、资金标准化、禁换算两链补)次序由 07-19 排序会统一定。
- 实施顺序:v2 复核锁定 → 测试先行(§9 必失败为红)→ 闸+新 prompt+两表+新列同批部署(DEPLOY_LOG)
  → 首批观察拒卡率。
- **首周拒卡率 >50% 仅作为黄色人工复核阈值,不是自动放松闸门的授权**:
  - 必须按 reject_reason × prompt_hash 分解;
  - **只允许修复有合成正向样例证明的"合法卡被语法误拒"**;
  - 不得降低 fact_id、必填项、算式复核或数字禁令;
  - parser 变更须登记 gate_rule_version、补测试并经人拍;
  - **不得因首周真实结果自动调规则**。

## 9. 必失败测试用例(预注册;实施前必须为红,闸上线后转绿=闸生效证明)

核心三条(计划令义务):

1. **幽灵指针**:evidence 引用输入快照不存在的 fact_id(`news:999999`)→ 拒卡 reason=fact_id_not_found;
2. **缺止损锚**:B8 偏多卡 exit 为空或无价位结构 → 拒卡 reason=missing_exit_anchor;
3. **算式不可复核(C-1 同型)**:falsify 价位结构 (488, -5.0%, 460.0) → 拒卡
   reason=price_formula_mismatch(应 463.60)。

v2 增补(缺口与裁决对应,同为必失败):

4. duplicate_output:同 run 同 candidate_key 两份输出 → 全部作废计一次拒卡,副本按序存档+duplicate_count;
5. orphan_output:LLM 输出候选集外 code → 入 n_orphan_output,不动候选分母;
6. invalid_direction:direction="强烈看多" → 拒卡(不得静默归中性);
7. invalid_subjective_prob:prob=1.0/缺失/非数 → 拒卡(不得静默 NULL 入卡);
8. 真空通过:evidence=[] → 拒卡(任何卡型);
9. fact 数字冒写:LLM 在 fact 条目自写数字 ≠ 快照载荷 → 载荷以代码渲染为准(自写值不进权威字段);
10. inference 带新数字/带直接 fact_id → 拒卡;
11. B6 中性卡 scenarios 所有元素 falsify 均空 / B8 中性卡顶层 falsify 空 → 拒卡;
12. cluster 关键字段缺失 → 不输出独立计数,只披露三计数+cluster_status;
13. 对账等式:构造 n_candidate=5(入3/拒1/漏1)+orphan1 → 等式成立且 orphan 不入分母。

## 10. 展示影响与边界(裁决③确认)

- **接受 fact 展示文本由代码按持久化输入快照渲染,语言更机械——
  这是事实层零幻觉结构保证的预期代价,不是回归**。
- LLM 语言能力限定在 thesis 与 inference;fact 的文本/数字/单位由代码渲染;
  derived 的操作数与结果由代码解析、复核或生成;
  **前端可做排版润色,但不得让 LLM 重新改写事实载荷**。
- B6/B8 解析失败、漏答、拒卡、未知输出**分开计数**,不得合并科目。
- 不动 B7 记分口径、共振/对齐权重、候选门槛;B8 正式卡方向语义零变化;
  不做 NLP 语义核验(归抽验/哨兵);subjective_prob 仅新增合法性闸,Brier 计算零涉及;
  存量卡不回填。

## 11. 与既有文档关系

- VNEXT e 件:本稿即其设计稿义务;措辞出入以 e 件登记原文为准。
- CARD_TRACE_AUDIT C-1:前瞻两条在 §6 落实。
- a 稿(P0_MECH_FIX_DESIGN.md):对账披露同构(§5↔其 §6);两稿实施批次独立,排序会定序。
- g 件:failed_validation 态下 export 是否继续归 g 稿;本稿锁卡级语义与可见性义务。

## 12. v1【人拍】5 处裁决落点(2026-07-14 使用者裁决)

| # | v1 待拍项 | 裁决 | 落点 |
|---|---|---|---|
| 1 | fact_id 文法 | 带类型前缀的代码生成 opaque id;news:<news_id>(text 主键)/mx:<JSON Pointer>/rsch:<report_id>/letter:<letter_id>/hot:rank(run 内有效);LLM 只照抄;快照持久化 | §2 |
| 2 | B8 中性 falsify | 升必填;B6 中性同升(同被记分);全卡型 evidence≥2 含 1 fact;prob 非法拒卡 | §4 |
| 3 | 拒因载体 | 方案 A 扩为 run 级双表(generation_run+rejected_card,insert-only,禁改删截),接受卡加 run_id/gate_rule_version 两列;表名可调能力不可删 | §5 |
| 4 | 价位文法 | 结构化子字段(anchor/anchor_value/delta_pct/derived_price/formula_version=close_pct_v1),Decimal+tick=0.01,不解析中文自由文本 | §6 |
| 5 | 聚类判据+拒卡率阈值 | cluster_v1 五条件全满足才合并,不可靠即只披露三计数;>50% 仅黄色人工复核阈值,只修有合成正向样例证明的语法误拒,不降闸,parser 变更登版本经人拍 | §7/§8 |

## 修改记录

- 2026-07-14 草案 v1 落档(【人拍】5 处待裁)。
- 2026-07-14 草案 v2:按使用者同日复核裁决修订——①fact 载荷代码权威化(LLM 只选 id,
  derived 结构化 operands 代码复核,inference 用 supporting_fact_ids,输入快照持久化);
  ②"全批拒=诚实空态"作废,改 honest_empty/failed_validation 双态,前端/health 可见性义务;
  ③run 级身份与单 run 对账等式(n_orphan_output 单列/duplicate_output 全作废计一次);
  ④【人拍】5 处全部裁决落点见 §12;⑤B6 中性 falsify 同升必填、prob 非法拒卡、
  direction 非法拒卡;⑥展示机械化确认为预期代价非回归。仍为草案,暂不锁定。
- 2026-07-14 补一项 schema 落点约束(使用者裁定):B6 不新增 judgment_card 顶层 falsify 列,
  falsify 落 scenarios 数组元素内(必填=scenarios≥1 且至少一条 scenario.falsify 非空、具体、
  horizon 内可验证);B6 中性同规则、不强套 B8 基于 decision_card.close 的价位结构文法;
  B8 falsify 仍用 decision_card 顶层字段。§4 两行、schema 落点注记、§9 用例 11 同步修订。
