# 取证7 · Brier 代码 vs BRIER_SPEC 六条逐条符合性(commit 6f69b4a)

| SPEC 条款 | 代码落点 | 符合性 |
|---|---|---|
| 1 样本域=对/错,平剔除但必报未判定率;NULL prob 跳过 | `brier_stats`: `pts=[...if v in ("对","错")]`,`n_flat` 计数,`flat_rate=n_flat/(n+n_flat)` 恒出;`withp=[...if p is not None]` 跳 NULL | ✅ 单测: (0.7对,0.7错,0.55平)→n=2,n_flat=1,flat_rate=0.333;全平→n=0,flat_rate=1.0 |
| 2 outcome 对=1/错=0,兑现完全继承主记分判定 | `1.0 if v=="对" else 0.0`(v 只剩对/错);verdict 来自 card_score/decision_score,无第二套判定 | ✅ 无独立兑现逻辑,查询 JOIN 记分表 |
| 3 card_kind/card_type 打标分层,禁混桶 | kind: `calibration_block` 按 direction 拆 direction/neutral 两组独立出桶;type: node/stock 由 calibration/stock_calibration 分表天然隔离。存储:direction 列在卡上(发卡即打标),数据点分层在 stats 内嵌套键 | ✅ 单测: 2方向+1中性→direction.n=2/neutral.n=1 各自成桶 |
| 4 固定边界 [0,.5,.6,.7,.8,.9,1),禁分位桶/事后改桶 | 模块常量 `_BIN_EDGES=(0.0,0.5,0.6,0.7,0.8,0.9,1.0)`,注释标"落档日起写死,禁分位桶/事后改桶";无任何分位数逻辑 | ✅ 单测断言 0.7 落 [0.7,0.8) |
| 5 复算规则 Brier=mean((prob−outcome)²) | `sum((p-o)**2 for ...)/len(pts)`,round 4 位 | ✅ 手算 0.29/0.16/0.64 三例与函数输出一致 |
| 6 预期声明(曲线难看禁改 prompt 引导措辞) | 非代码条款;prompt 终版无任何概率示例值(锚点已删),硬闸(#41)拦第三次变更 | ✅ 纪律层落 DECISIONS #41 |

附注符合性:`brier_by_version` 跨卡型仅出 n/n_flat/brier 标量,docstring 标明"仅作漂移检测,
不当校准曲线读"——不违反第 3 条禁混桶(无桶输出)。
