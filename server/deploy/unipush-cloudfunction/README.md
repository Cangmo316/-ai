# 比邻AI · uni-push 2.0 云函数（需要你部署）

这个目录**不是给 FastAPI 用的**，是要上传到你自己 uniCloud 空间的一段云函数代码。
它负责把业务服务端的提醒请求真正发成手机系统通知。

## 为什么必须经过云函数（已核实官方文档）

| 事实 | 出处 |
|---|---|
| uni-push 2.0 的服务端 SDK（`uni-cloud-push` 扩展库的 `uniPush.sendMessage`）只跑在 uniCloud 云函数里 | [uni-push 2.0 入门文档](https://uniapp.dcloud.net.cn/unipush-v2.html) |
| 自建服务器要直连个推，官方要求改用老版 uni-push 1.0 的凭证体系（appkey/mastersecret） | 同上「如果你的项目由于特殊原因不能通过 uniCloud 的云函数使用 uni-push2.0」一节 |
| uni-push 2.0 本身免费，但依赖 uniCloud（按量计费：1 万次云函数调用约 0.0133 元） | 同上「费用说明」 |

所以架构是：

```
FastAPI 调度器（到点）
  → UniPushChannel：POST {cid, title, content, force_notification, payload}
  → 本云函数（uniCloud）：uniPush.sendMessage()
  → 个推 → 手机厂商通道 → 老人手机的通知栏
```

**个推的 appkey / mastersecret 全程留在云函数侧**，业务服务器只有一个 URL + 一个自定义 token。

## 你要做的事（按顺序）

1. **拿到 DCloud appid**
   现在 `uni-app/manifest.json` 里的 `appid` 是**空的**。在 HBuilderX 里打开 `uni-app/`，
   菜单「发行 → 原生App-云打包」或「manifest.json → 基础配置 → 重新获取 appid」，
   拿到形如 `__UNI__XXXXXX` 的 appid 并写入 manifest。

2. **开通 uni-push**
   登录 [DCloud 开发者中心](https://dev.dcloud.net.cn) → 左侧 `uni-push` → 开通
   （2.0 支持全端；App 端离线推送还需要配置厂商参数：华为/小米/OPPO/vivo/魅族，
   iOS 需要上传推送证书）。客户端启用方式：`manifest.json → App模块配置 → 勾选 uni-push 2.0`。

3. **部署本云函数**
   - 开通一个 uniCloud 服务空间（阿里云/腾讯云/支付宝云均可）
   - HBuilderX 里新建云函数（例如 `bilin-unipush`），右键「管理公共模块或扩展库依赖」→ 勾选
     **uni-cloud-push**
   - 把本目录的 `index.js` 与 `package.json` 覆盖进去，然后把文件里的
     `APP_ID` 改成第 1 步的 appid、`TOKEN` 改成一串随机字符串
   - 上传部署

4. **URL 化云函数**
   uniCloud 控制台 → 云函数 → 该函数 → 「URL 化」，得到一个 https 地址。

5. **填到服务端 `server/.env`**
   ```ini
   UNIPUSH_SEND_URL=https://你的云函数URL化地址
   UNIPUSH_TOKEN=与云函数里一致的随机字符串
   UNIPUSH_FORCE_NOTIFICATION=true
   ```
   改完重启服务，`GET /v1/push/status` 里 `unipushConfigured` 应该变成 `true`。

## 验证

```powershell
# 1) 端侧在真机上跑一次，拿到 cid 并自动登记到服务端
Invoke-RestMethod http://127.0.0.1:8000/v1/push/status
#    clients 里应该能看到一台设备（cid 只回显后 6 位）

# 2) 让调度器投递一条提醒（手动推进到某个提醒时间）
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/scheduler/tick `
  -ContentType 'application/json' -Body '{"at":"2026-09-24T08:00:00"}'
#    返回的 summary.sent 应为 1，status.channels 里 unipush 的 configured 为 true

# 3) 看服务端日志：应该出现「uni-push 已投递 N 台设备」
```

## 已知限制与注意事项

- **标准 HBuilderX 基座不含 uni-push 模块**：真机调试要用「自定义调试基座」，否则
  `uni.getPushClientId` 会失败（端侧代码对此是安全降级的，只是拿不到 cid）
- **Android 通知渠道**：Android 8+ 建议用 `uni.getChannelManager()` 建一个渠道
  （可以对提醒类消息单独设重要级别与铃声），本期未做
- **cid 会变**：重装/清数据后会拿到新 cid，端侧每次启动都会重新登记（服务端按 cid 幂等 upsert）
- **个推与厂商通道的送达率**：受手机省电策略影响，这也是为什么还要保留
  「端侧本地通知」与「站内消息」两条腿（见 `uni-app/stores/push.js`）
