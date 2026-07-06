# 开发流程规范(Process)

> 单人+AI 协作的"正规军最小集":想法可以有偏差,落地必须走流程、留痕迹、可纠正。

## 1. 变更流程(需求 → 上线)

```
提出 → 进 ROADMAP 排队(带优先级) → 评审(使用者拍板取舍)
  → 大改先写设计文档(docs/,如 B6/B7/B8) → 实现
  → 实测(见§3,必须真实数据或事务内假数据) → 两地部署(见§4)
  → 线上 8092 验证 → commit+push(见§5) → 文档/记忆同步更新(见§6) → 登记观察点(见§7)
```

- 想法与落地分离:讨论中被否/暂缓的方案也要写进 ROADMAP(已明确不做/三档),防止重复议。
- 判断链路(B1-B8 prompt/口径)的任何改动,commit message 必须写清改了哪个口径、实测结果。
- **进实现前过"反向自查四问"**(前置门,列表作答后再动手;吸收自 radar 审视纪律,DECISIONS #33):
  ①幻觉——这步会不会让 LLM 输出输入之外的数字/来源?怎么防(溯源校验/数值由代码算)?
  ②越界——会不会让某层填了不该它填的(事实层出判断、LLM 碰参照层/记分)?
  ③红线——违不违反 §8?
  ④地基——有没有事后补不上的决定(schema/口径/唯一键/时间戳)?种错要返工的单独标出等拍板。

## 2. SQL 迁移规范

- `sql/NNN_名称.sql` 严格递增编号,内容幂等(`IF NOT EXISTS`/`DROP TRIGGER IF EXISTS`),可重复应用。
- 应用方式:数据节点上执行(rv_conn 跑文件),**迁移先于依赖它的代码部署**。
- 判断类表(judgment_card/decision_card/ledger)一律 append-only(复用 `ledger_append_only()` 触发器);
  代码可重算的派生表(card_score/decision_score)用 PK upsert。分界:**判断不可改,分数是行情的函数**。
- 参照层变更(票池/节点)不走迁移:改 `data/*.json`(仓库源)+ 数据节点 DB DML + heatmap 重算 + dashboard 重建。

## 3. 测试规范(无独立测试环境的补偿)

- **append-only 表唯一安全测试法**:同一连接事务内插假数据→跑被测函数(支持传入 conn)→断言→ROLLBACK(零污染)。禁止直插测试行(删不掉)。
- LLM 路径:用合成输入直接调内部函数验证 prompt/解析(如 `_review_wrong`),不落库。
- 数学类(记分/z-score):用历史真实窗口对账(如 06-18→06-26),人工核对量级与符号。
- 手动跑编排**不接管道**(`flock -w` 超时是静默 exit 1,`| tail` 会吃退出码假装成功),先看 `webdata/alerts/`。
- **进审计链的手动验证,终端输出当场重定向留档**(tee/`>` 到取证目录,一律文件不靠终端回忆);事后确定性论证只作补救不作常规(2026-07-06 外部审查立惯例,起因:0c 周报手动输出未留存)。
- 前端:`npm run build` 过 TS 即部署闸门;真机效果靠使用者手机实测反馈(服务器无浏览器)。

## 4. 部署 Runbook

```bash
# ① 代码 → 数据节点(排除清单勿减)
RSYNC_RSH="ssh -i ~/.ssh/<key> -o IdentitiesOnly=yes" rsync -az \
  --exclude .env --exclude .git --exclude .venv --exclude .venv-taipei \
  --exclude __pycache__ --exclude web/node_modules --exclude web/dist \
  --exclude webdata --exclude logs --exclude backups --exclude exports \
  ./ <user>@<数据节点>:/opt/research_view/
# ①b 部署留痕(radar DEPLOY_STATE 教训:生产跑的是哪个 commit 必须可追溯;脏树部署纪律上视为阻断)
ssh <user>@<数据节点> "printf 'commit: %s\nat: %s UTC+8\ndirty: %s 条未提交\n' \
  '$(git rev-parse --short HEAD)' \"$(TZ=Asia/Shanghai date '+%F %T')\" \
  '$(git status --porcelain | wc -l)' > /opt/research_view/DEPLOY_STATE.md"
# ② 迁移(如有) → ③ 实测 → ④ 数据节点重建 dashboard(核对当天日期!误用未来日期会把线上翻空)
# ⑤ 拉回(brace 展开须在引号外)
rsync -az "<user>@<数据节点>:/opt/research_view/exports/"{dashboard,trends}.json webdata/
# ⑥ 前端有改动才重建容器
docker compose up -d --build
# ⑦ 验证(必须带浏览器 UA,否则 403)
curl -s -A "Mozilla/5.0" http://localhost:8092/data/dashboard.json | python3 -c "..."
```

## 5. 提交规范

- 单人直推 main;commit message 中文语义化:`feat|fix(范围): 摘要` + 正文列改动点 + **实测结果**(数字/结论)。
- `.env`/webdata/logs/backups/dist/node_modules 永不入库(gitignore 已焊)。
- cron 变更:只追加不覆盖他项,条目一律**绝对路径**(cron cwd=$HOME)。

## 6. 文档义务(每次上线随手做,不欠账)

| 文档 | 何时更新 |
|---|---|
| ROADMAP.md | 队列进出/里程碑完成/观察点变化 |
| ARCHITECTURE.md | 新表/新模块/新 cron/数据流变化 |
| DECISIONS.md | 使用者拍板的取舍(含否掉的) |
| 设计文档(B6/B7/B8 式) | 新子系统开工前 |
| README | 对外口径变化(定位/铁律/导航) |

## 7. 观察点制度

每次上线登记"次日/首跑观察点"(ROADMAP 当前阶段节),之后**回看 cron 日志与 task_log 确认**,不是发完就算完。规则:**观察点优先于新功能**——新机器先跑顺,再往上摞。

**季度全项目审视**(制度,DECISIONS #33):每季度(或大阶段收口后)做一次全项目体检——多路代码审查
+生产库实况核查+战略层审视,产出 P0/P1/P2 分级清单留档 docs/,逐项拍板实施;"查过没问题的"也留档,
防止将来重复怀疑。首次排 2026-10(首批战绩样本成熟后)。值班模式下这是新功能之外唯一的主动开发入口。

## 8. 红线(违反即 bug)

- 文档/README/commit 不出现具体云商/城市字样(中性称谓:数据节点(境内)/编排节点(境外))。
- 事实层零幻觉:LLM 输入之外的数字/来源一律不许出现;判断层每条必须可溯源+可证伪+进记分。
- 金额类隐私不出前端(持仓仅布尔标记,当前持仓层已停用)。
- marketdata 只读(DB 层焊死,代码层 read_only 双保险),不得绕过。
