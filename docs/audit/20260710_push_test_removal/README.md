# 取证 · /api/push/test 群发测试端点删除 + /api/push 专属限流(2026-07-10)

**DECISIONS #44 固定措辞:紧急安全修复:仅删除群发测试能力并加限流,不改变任何判断/评分/提示词语义。**
07-11 追加单第1项,使用者批准提前至 07-10 当晚执行(缺口=端点公网零鉴权可对全部订阅者
群发;缓解因素=文案硬编码非内容注入;删除零损失=测试通知既有宿主 pywebpush 直发替代)。

## 改动(fix.diff)

1. `chat/app.py`:删 `/api/push/test` 端点(公网唯一群发入口);
2. `chat/push.py`:删 `send_to_all()`(唯一调用方即上述端点,死代码同删——容器自此
   无群发能力;pywebpush import/VAPID_SUB 一并清,py_vapid 仍由 vapid_public_key 使用);
3. `web/nginx.conf`:`/api/push` 加 pushlim 每 IP 10次/分 burst5(原仅继承全局 10r/s);
4. 文档同步:ARCHITECTURE.md §7 端点清单、DECISIONS #44。

异动推送主链(台北宿主 push_alerts.py 直读订阅文件+pywebpush)零触碰。

## curl 复测(retest.txt,重建 chat+web 容器后实测)

| # | 用例 | 预期 | 实测 |
|---|---|---|---|
| 1 | POST /api/push/test(8092 直连) | 404 | **404** ✅ |
| 2 | GET /api/push/vapid-key | 200 | **200**(key 正常返回)✅ |
| 3 | POST /api/push/subscribe 空体 | 400 校验拒 | **400** ✅(处理器存活,订阅链不受影响) |
| 4 | 12 连打 vapid-key | 放行≤6 后 429 | **3×200 后全 429** ✅ |
| 5 | POST /api/push/test(HTTPS 域名) | 404 | **404** ✅(反代路径同拒) |

用例4读数说明:pushlim=10r/m(1次/6s)+burst5 ⇒ 同分钟同 IP 总放行 6 次;
用例 1-3 已消耗 3 次,循环内再放 3 次后 429——与配置数学严格吻合,非异常。
(curl 全程带 -A "Mozilla/5.0",平台 UA 防护 403 先例。)
