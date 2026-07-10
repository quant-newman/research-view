# OFFICIAL 结果读法规则(使用者 2026-07-10 定,不改脚本)

official_result.json 出来后,先看各 window 的 `dropped_no_af`:

- **为空** → raw / adj 两腿同池(n_priced_raw == n_priced_adj 且无剔票),
  excess 与 flip 判定直接有效,按既定结论边界处理。
- **非空** → 两腿池成分不同,excess 差里混入成分噪音(raw 池均值含 adj 腿没有的票),
  处理法:将 **raw 腿限制到与 adj 腿相同票集(交集)重算一遍**,作为敏感性对照;
  **flip 判定以交集口径为准**;原始双腿结果并列留档,不覆盖。

交集重算属只读敏感性对照,届时以一次性脚本执行(输入=同一 official_result.json
的窗口参数+交集票单,复用 audit_adj_dual.py 同款取数函数),产出与原结果
同目录并列归档(intersection_result.json),audit_adj_dual.py 本体零改动。

既定结论边界不变:交集口径无翻转→本批按现行 raw 口径展示,除权修正降 vNext
常规项(仅此维度);有翻转→07-12 周报该卡加注,处置等外部审查。
