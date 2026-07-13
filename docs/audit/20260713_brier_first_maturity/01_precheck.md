# 07-13 白天准备令·三 只读预检(七项全过)

> 执行:2026-07-13 14:44-14:48 UTC+8,全程只读 SELECT/grep,零写入。
> 查询脚本原文见本目录 `precheck.py`(scp 至数据节点 /tmp 执行,不落生产代码)。
> 判定基准:准备令(终稿)三·1-7,原文照录于本目录 `00_directive.md`。

## 1. 07-06 批数量核对 ✅

生产库现查(judgment_card/decision_card WHERE trade_date='2026-07-06'):

- B6 = **8 张**,card_id 19-26,与 06_acceptance.md 第2项完整输出逐张一致
  (node_id/direction/prob/hash 五列全同)
- B8 = **12 张**,card_id 15-26,同上逐张一致
- 与 ref_epoch_forensics.txt"首批 prob 卡 8 B6 + 12 B8"一致

```
(19, 'optical::光纤光缆', '偏空', 0.85, '8528ca795ca4c6b8')
(20, 'robotics::工业机器人本体', '偏多', 0.65, '8528ca795ca4c6b8')
(21, 'optical::光模块成品', '偏空', 0.55, '8528ca795ca4c6b8')
(22, 'compute_infra::服务器整机', '偏多', 0.8, '8528ca795ca4c6b8')
(23, 'optical::光器件/CPO封装', '偏空', 0.85, '8528ca795ca4c6b8')
(24, 'finance::证券', '偏多', 0.65, '8528ca795ca4c6b8')
(25, 'optical::通信设备', '偏多', 0.8, '8528ca795ca4c6b8')
(26, 'pharma::生物药/ADC', '偏多', 0.6, '8528ca795ca4c6b8')
(15, '000938', '偏多', 0.65, '780916554dc9be8b')
(16, '301191', '偏多', 0.7, '780916554dc9be8b')
(17, '002747', '偏多', 0.6, '780916554dc9be8b')
(18, '600105', '偏空', 0.75, '780916554dc9be8b')
(19, '002491', '偏空', 0.7, '780916554dc9be8b')
(20, '000988', '偏空', 0.55, '780916554dc9be8b')
(21, '601211', '偏多', 0.7, '780916554dc9be8b')
(22, '301165', '偏多', 0.6, '780916554dc9be8b')
(23, '300394', '偏空', 0.75, '780916554dc9be8b')
(24, '600487', '偏空', 0.65, '780916554dc9be8b')
(25, '600030', '中性', 0.5, '780916554dc9be8b')
(26, '000977', '偏多', 0.65, '780916554dc9be8b')
```

## 2. prob 非空且 ∈(0,1) ✅

B6 count/nonnull/in(0,1) = 8/8/8;B8 = 12/12/12(逐值复核输出见上表,
0.5 与 0.85 均为开区间内值)。

## 3. prompt_hash 一致 ✅

B6 distinct hash = {8528ca795ca4c6b8},B8 = {780916554dc9be8b},
各自单一、与 #41 登记真值及 _PROMPT_LABELS(scorecard.py:296-297)完全一致。

## 4. 07-06 批今晚 cron 前无任何记分 ✅

按 card_id 限定查询(不看全表):

```sql
SELECT card_id FROM card_score     WHERE card_id BETWEEN 19 AND 26;  -- → []
SELECT card_id FROM decision_score WHERE card_id BETWEEN 15 AND 26;  -- → []
```

两侧均为空集。

## 5. CALIBRATION_FREEZE=1 ✅

数据节点 /opt/research_view/.env 第21行现查:`CALIBRATION_FREEZE=1`(显式置1);
代码侧 config.py:65 默认即冻结(仅显式 =0 才解冻)。双保险成立。

## 6. 无参照层变更 ✅

- node 登记数 = **77**,stock_node 映射数 = **267**——与 890ecb4 纪元
  (77节点/267映射,ref_epoch_forensics.txt)一致,零变更。
- ref_membership_snap 近3日 (snap_date, rows, distinct_node):
  (2026-07-10, 267, 76) / (07-09, 267, 76) / (07-08, 267, 76)——行数与截面
  distinct 稳定(distinct=76 为已登记状态:77 登记节点中 1 节点零成员,
  见 ref_epoch_forensics.txt 截面细节,非新变化)。
- 07-11/12 为周末、07-13 快照待今晚 22:30 ref_snapshot 步写入,最新快照
  停在 07-10 属预期,不是缺失。

## 7. 07-12 23:20 扫描确有执行 ✅(三条证据臂齐全)

- **crontab 触发记录**(syslog 原行,UTC 时戳=23:20:01 UTC+8):
  ```
  2026-07-12T15:20:01.362432+00:00 ip-172-31-2-228 CRON[1995289]: (ubuntu) CMD
  (/usr/bin/bash /home/ubuntu/mofangrearch/logs/scan_tasklog_oneoff_20260712.sh
   >> .../logs/scan-oneoff-20260712.log 2>&1;
   crontab -l | grep -v scan-oneoff-20260712 | crontab - # scan-oneoff-20260712)
  ```
  当前 crontab 已无该行=脚本设计的跑完自删(脚本头注释明示),非证据缺失。
- **扫描自身日志**:`logs/scan_tasklog_20260712.result`(mtime 23:20:04 UTC+8)内容:
  ```
  2026-07-12 23:20:04 [07-12 23:20 cron扫描] task_log当日失败行=0(无); 周末新闻档fetch_news成功=8/8档
  ```
  stderr 日志 scan-oneoff-20260712.log 为 0 字节(无错误输出)。
- **飞书送达**:脚本内 notify_feishu.py test 调用先于 result 写入执行
  (逻辑序,送达记录以使用者飞书端为准)。
- 其读取的 task_log 扫描结果即上行:当日失败行=0,周末新闻档 8/8。
- 扫描器设计不写 task_log(只读 task_log+发飞书+写本地 result),
  按令不人造 task_log 记录。

## 结论

七项全过,未触发"当场停止"条款。今晚 22:30 正常 cron 档可按五·1-7 执行。
