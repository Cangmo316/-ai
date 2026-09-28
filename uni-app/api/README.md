# 比邻AI · agent 接口层与接口契约

本目录是 uni-app 端与自建 agent 服务之间的**唯一对接面**。后端（`server/`）照着这里的
契约实现，端侧代码一行都不用改；后端没就绪时用 `tools/mock-server.mjs` 当靶子联调。

```
uni-app/api/
├── config.js       baseURL / 端点 / 超时（运行期可改，不用重新编译）
├── sse-parse.js    SSE 帧解析 + 增量 UTF-8 解码（纯函数，可被 node 直接单测）
├── transport.js    跨端「流式 POST」传输层（各端能力不同，见下表）
├── request.js      非流式请求封装（错误提示统一翻译成老人看得懂的话）
├── chat.js         对话接口：chatStream / chatSendOnce / chatHistory
└── index.js        页面只从这里 import
```

配套：
- 假后端：`node tools/mock-server.mjs`（零依赖，实现下面全部契约）
- 自检：`npm test`（25 项契约与解析测试 + 13 项端侧状态机测试）

---

## 一、各端流式能力（已核实，不是猜的）

| 端 | 手段 | 效果 | 依据 |
|---|---|---|---|
| H5 | 原生 `fetch` + `ReadableStream` + `TextDecoder` | 真逐字 | `uni.request` 的 `enableChunked` 平台差异**只写了微信小程序**，H5 拿不到分块 |
| 微信小程序 | `uni.request({enableChunked:true})` + `task.onChunkReceived` | 真逐字 | 同上；回调给的是 `ArrayBuffer`，需增量解码 |
| App（plus） | `plus.net.XMLHttpRequest`，在 `readyState === 3` 取 `responseText` 增量 | 真逐字 | HTML5+ 文档：`readyState 3` = 「响应体开始接收但未完成」，`responseText` 返回**目前已接收的部分数据**，「响应较长时可能在状态 3 中触发多次」 |
| 其它（支付宝/百度/鸿蒙…） | `uni.request` 收完整体，一次性喂给解析器 | **不打字，但内容完整** | 拿不到分块就降级——符合设计方案「降级可活」，绝不出现空白页 |

两个必须知道的坑：

1. **小程序分片会把汉字劈成两半**（一个汉字 3 字节）。所以 `sse-parse.js` 里有一个手写的
   增量 UTF-8 解码器（小程序没有 `TextDecoder`），不完整的尾部字节留在 pending 里等下一片。
   `tools/test-chat-api.mjs` 里有「逐字节喂入」的用例专门守这条。
2. **App 端 `responseText` 的尾部替换字符**。若原生层这一片正好把汉字劈开，末尾会出现
   `U+FFFD`；`transport.js` 检测到「非流末尾且以 U+FFFD 结尾」就不提交这一段，等下一次回调补全。

---

## 二、接口契约

所有接口都在 `baseURL` 下。请求与响应均为 UTF-8 JSON。
错误统一使用 `{ "error": { "code": "...", "message": "..." } }`，
`message` 会直接展示给老人，**请写人话**（"服务器开小差了，一会儿再试" 而不是 "500 Internal Error"）。

### 2.1 `POST /v1/chat/stream` —— 流式对话（SSE）

请求：

```json
{
  "conversationId": "c_son",
  "elderId": "e_1",
  "personaId": "p_son",
  "clientMsgId": "m_local_xxx",
  "text": "妈 药吃了没"
}
```

响应头：

```
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache, no-transform
X-Accel-Buffering: no          ← 少了这行，上了 nginx 会变成「一次性吐完」
```

事件序列（`event:` + `data:` JSON）：

| 顺序 | 事件 | data | 说明 |
|---|---|---|---|
| 1 | `meta` | `{conversationId, assistantMsgId, persona:{id,name,relation,avatarColor}}` | **必须最先发**。端侧用它拿到本条回复的服务端 id 与人设 |
| 2..n | `token` | `{"t":"妈"}` | 增量文本。`t` 与 `text` 都接受 |
| 任意 | `sticker` | `{"token":"pill"}` | 受控表情 id，**必须是端侧白名单里的 token**，不能发 URL |
| 任意 | `card` | `{"card":{"kind":"plan_item","plan":{...}}}` | 结构化卡片（计划卡 / 内容卡） |
| 末 | `done` | `{"assistantMsgId":"...","finishReason":"stop"}` | 正常结束 |
| 末 | `error` | `{"code":"server_error","message":"...","retryable":true}` | 可恢复错误；端侧会删掉空气泡并给「重发」入口 |

约定：

- 事件之间用**空行**分隔；每帧形如 `event: token\ndata: {...}\n\n`
- 心跳用注释行 `: ping`，端侧解析器会忽略（建议 15s 一次，防中间层掐连接）
- 端侧容忍：`data: [DONE]`（等价 `done`）、字段缺省、坏 JSON 帧（**丢弃该帧继续收**，不整条流失败）
- 服务端可随时断开；没发 `done` 也按「说到这儿」处理，不报错

### 2.2 `POST /v1/chat/send` —— 非流式一次性回复

降级路径（服务端还没实现 SSE，或端侧想省电时）。请求体同 2.1，响应：

```json
{
  "conversationId": "c_son",
  "assistantMsgId": "c_son_a_xxx",
  "persona": { "name": "儿子 小明", "relation": "儿子", "avatarColor": "#07C160" },
  "text": "妈 药吃了没\n吃完喝口热水 别空腹",
  "sticker": "pill",
  "card": null,
  "finishReason": "stop"
}
```

端侧会把它合成为 `meta → sticker → token → card → done` 同一套事件，页面逻辑不分叉。

### 2.3 `GET /v1/chat/history?conversationId=c_son&limit=50`

```json
{
  "conversationId": "c_son",
  "messages": [
    { "id": "m1", "role": "agent", "type": "text", "text": "妈 我上班去了", "createdAt": "2026-09-24T09:10:00+08:00" }
  ]
}
```

- `role`：`elder`（老人，`user` 也接受）/ `agent`（数字人）/ `system`
- `type`：`text` / `voice`（带 `seconds`）/ `sticker`（`sticker` 字段是 token）/ `card`（`card` 字段同 2.1）
- **拉历史失败端侧不报错**：本地缓存与内置种子会顶上（老人端不允许白屏）

---

## 三、话术与内容约束（服务端责任，端侧只管展示）

1. **句末不加句号**：多句用换行代替句号，小数（`2.5mg`）与缩写除外
2. 第一人称、口语、短句；闲聊 1–2 句，说明类 ≤4 句，超出转 `card`
3. 表情只能发白名单 token（端侧白名单见 `uni-app/common/stickers.js`），**不能输出 URL**
4. 医疗边界：不做诊断、不做剂量调整、不做疾病判断，只做生活提醒与依从性管理
5. 消息末尾不要带 AI 免责声明——界面已有常驻「AI 数字人 · 内容仅供参考」标识，重复反而刺眼

---

## 四、端侧消息状态机

```
sending → streaming → sent
                    ↘ stopped（老人点了「停止」，保留已收到的部分）
                    ↘ failed （可重发；一个字都没收到就不留空气泡）
```

对应实现见 `uni-app/stores/chat.js`。几条刻意的选择：

- **乐观发送**：点发送立刻上屏，不等网络（老人不能接受"点了没反应"）
- **一键停止**：`发送` 按钮在流式期间变成 `停止`，不需要二次确认，符合红线「老人可控」
- **失败可活**：连不上服务器时保留已有消息 + 给系统提示 + 提供重发，不整屏报错

---

## 五、联调

```bash
node tools/mock-server.mjs            # 127.0.0.1:8787，逐字输出 110ms/字
node tools/mock-server.mjs --delay 0  # 不等待，便于脚本联调
node tools/mock-server.mjs --host 0.0.0.0   # 真机联调（手机与电脑同局域网）
```

改 baseURL 的两种方式（`uni-app/api/config.js`）：

```js
// ① 源码：改 DEFAULT_BASE_URL
// ② 运行期（写本地缓存，不用重新编译）：
import { setBaseURL } from '@/api/index.js'
setBaseURL('http://192.168.1.5:8787')
```

各端地址不一样，联调前先对齐：

| 运行方式 | baseURL 应填 |
|---|---|
| HBuilderX 运行到浏览器（H5） | `http://127.0.0.1:8787` |
| Android 模拟器 | `http://10.0.2.2:8787`（模拟器里的 127.0.0.1 指它自己） |
| 真机 / 微信开发者工具真机预览 | `http://<电脑局域网IP>:8787`，并加 `--host 0.0.0.0` |
| 微信开发者工具 | 需在「详情 → 本地设置」勾选**不校验合法域名** |

mock 里预置了三个触发词方便验边界：消息含 `__error` → 走错误分支；含 `__slow` → 700ms/字（方便点「停止」）。

---

## 六、后端接手时的替换点

端侧已按契约实现，后端只需保证：事件名与字段名一致、`meta` 先发、错误体结构一致。
另外这些还没做，属于 P0 之后的事：

- 鉴权（目前无 header / 无 token，接入时要加 `Authorization` 并处理 401）
- `clientMsgId` 幂等（端侧已传，服务端应据此去重，避免重试产生重复消息）
- 限流与错误码表（端侧已按 `code`/`statusCode` 显示人话，但服务端还没有稳定码表）
- 会话列表接口（`chats` 页除首个会话外仍是本地占位数据）
