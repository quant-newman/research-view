# 2026-07-08 "6万倍"错误换算修复取证

## 错误

江波龙 H1 业绩预告:净利 92亿-110亿元,同比增长 62204.03%-74393.95%(即约 622-744 倍)。
日报生成层(report.py 盘前/盘后 LLM)把 62204% 错写成"增超6万倍"——丢了百分号,放大 100 倍。
使用者 07-08 指出,且为**第二次**发生(第一次纠错只在 structure.py 新闻摘要链加了护栏,
report.py 链未覆盖,见 src/research_view/structure.py:42)。

## 事实核对

上游新闻摘要层数字全部正确(62204.03%/743倍/超600倍均照抄原文),错误只发生在
report.py 的 SYSTEM 无"禁换算"铁律的几条 LLM 链(盘前/盘后日报、盘中增量、热点)。

## 修复(全部 2026-07-08 当日完成)

1. **代码护栏**:report.py SYSTEM 铁律新增"数字与单位原样照抄,禁自行换算;百分比≠倍"
   (与 structure.py 同口径),已 rsync 至阿里云 /opt/research_view(推送前校验远端文件
   与本地 git HEAD 逐字节一致)。report.py 无 prompt_hash 注册,不涉版本重登。
2. **存量数据**:阿里云 research_view 库全文本列扫描"6万倍",命中并修复:
   - daily_report(headline/top3/narrative/sectors):20260703:afterhours、20260706:premarket、
     20260706:afterhours、20260707:afterhours、20260708:premarket
   - report_increment.entry:2026-07-07 16:00
   - hotspot_daily.items:1 行
   替换口径:照公告原文"62204%-74394%(约622-744倍)"或"约622-744倍"。
3. **台北侧 webdata/dashboard.json**:同步修复 2 处(容器挂载即时生效,8092)。

## 验证(输出当场重定向留档,per PROCESS.md 惯例)

- verify_db_clean.txt:阿里云全库文本列扫描残留 = [],并抽查 20260708:premarket headline.fact
- verify_webdata_clean.txt:台北 webdata/dashboard.json "6万倍" = 0
- fix_script_round1.py:第一轮修复脚本存档(第二三轮为措辞变体兜底,逻辑同)

## 未尽事项

decision.py / evidence.py 两条链的 SYSTEM 也无此铁律,但其改动触发 prompt_hash 版本重登
(#28/#41 冻结期硬闸:头两份周报 07-12/07-19 落地前第三次变更自动拒绝),本次不碰;
待冻结期后若该两链复现同类错误再议。
