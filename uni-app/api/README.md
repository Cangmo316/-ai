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

---

## 三、康养计划接口（P1）

对应设计方案 §3.2 的计划链路。**这一层的核心不是接口，是那道闸门**：

```
知识库条目（guidelines.yaml，带来源与版本）
   → 计划引擎按老人档案匹配（慢病 / 65岁以上 / 全员）
   → LLM 只改写话术（越界就退回原文）
   → draft ──submit──▶ pending_confirm ──confirm──▶ active ──▶ adjusting / ended
                                    └──reject──▶ rejected
```

两条硬规则，服务端代码层面强制：

1. **未确认的草稿不产生任何提醒**——`GET /v1/plans/today` 只返回 `active` 计划，
   草稿/待确认拿不到数据，因此提醒、对话卡片、调度器都不可能基于它工作
2. **过渡期旧计划继续执行**——新草稿待确认期间旧计划照旧跑，直到 `confirm` 那一刻才结束旧计划

### 3.1 接口一览

| 接口 | 方法 | 用途 | 谁用 |
|---|---|---|---|
| `/v1/plans/draft` | POST | 按档案从知识库生成计划草稿（默认直接提交确认） | 家属端 / 运营端 |
| `/v1/plans/pending` | GET | 待确认的草稿列表 | 家属端 |
| `/v1/plans/confirm` | POST | 家属确认 → 生效（此刻结束旧计划） | 家属端 |
| `/v1/plans/reject` | POST | 驳回 | 家属端 |
| `/v1/plans/today` | GET | 今日计划 + 打卡状态（**只含 active**） | 老人端日程页 |
| `/v1/plans/checkin` | POST | 打卡 / 取消打卡（同天同项幂等） | 老人端 |
| `/v1/plans/summary` | GET | 完成率与调整建议 | 家属端 |
| `/v1/plans/adjust` | POST | 转入 `adjusting`（等家属确认，不自动改计划） | 家属端 |
| `/v1/plans/history` | GET | 计划历史与状态 | 家属端 |
| `/v1/elders` | GET | 老人档案（开发期是 3 个模拟档案） | 端侧 / 演示 |

### 3.2 `GET /v1/plans/today`

```json
{
  "elderId": "e_1",
  "date": "2026-09-24",
  "planId": "plan_xxx",
  "status": "active",
  "statusLabel": "正在执行",
  "items": [
    {
      "id": "pi_xxx",
      "time": "08:00",
      "type": "监测",
      "title": "量完血压记一下 下次给医生看",
      "detail": "家里的血压计比医院的更接近平时状态",
      "freq": "每日",
      "strongRemind": false,
      "done": false,
      "doneAt": "",
      "basis": {
        "entryId": "nphis_006",
        "source": "nphis3",
        "sourceName": "国家基本公共卫生服务规范（第三版）· 老年人健康管理服务规范",
        "version": "第三版",
        "boundary": "不根据血压值给出用药或剂量建议",
        "text": "国家基本公共卫生服务规范（第三版）… · 第三版 · §nphis_006"
      }
    }
  ],
  "total": 3,
  "done": 1,
  "rate": 0.333
}
```

- 没有生效计划时返回 `planId: ""`、`items: []`、`statusLabel: "还没有计划"`——**不是错误**
- `basis` 是"这条提醒照哪份指南来的"，家属端要展示；老人端不展示（避免界面变复杂）
- `statusLabel` 直接是给老人/家属看的中文，端侧不要再自己映射枚举

### 3.3 `POST /v1/plans/checkin`

```json
// 请求
{ "planItemId": "pi_xxx", "elderId": "e_1", "date": "2026-09-24", "done": true }
// 响应
{ "planItemId": "pi_xxx", "done": true, "checkin": {...}, "total": 3, "completed": 2, "rate": 0.667 }
```

- `done: false` = 取消打卡（老人点错了要能改）
- 同一天同一项重复提交是**幂等**的，不会产生两条记录
- 没有生效计划时返回 `409 { error.code: "plan_not_active" }`
- 端侧打卡是**乐观更新**：先变绿再发请求，失败回滚并给一句人话提示

### 3.4 频率与提醒窗口

知识库的 `plan_hint.freq` 只有枚举，没有具体哪天，服务端按下面的规则解释：

| 频率 | 什么时候出现在今日计划 |
|---|---|
| 每日 | 每天（做完打勾但不消失，老人要看到今天一共几件事） |
| 每周 | 整个自然周内（周一忘了，周二仍提醒——这才是依从性管理） |
| 每月 | 整个自然月内 |
| 每季度 | 季度起点后 **30 天**内 |
| 每年 | 年初后 **60 天**内 |

> 为什么长周期项要有窗口：否则「每年做一次体检」会从 1 月 1 日一直挂在今日计划里到 12 月 31 日，
> 老人每天看到同一件事，很快就学会无视——提醒失效比不提醒更糟。

### 3.5 对话里的计划卡（`card` 事件真正用上）

老人问「今天要做什么 / 有什么安排 / 提醒我 / 打卡」这类问题时，`/v1/chat/stream`
会在正文之后追加最多 3 个 `card` 事件，`card.kind = "plan_item"`：

```json
{ "kind": "plan_item", "plan": { "time": "08:00", "title": "…", "desc": "…", "state": "todo" } }
```

`state` 取 `todo` / `done`，端侧 `bl-chat-bubble` 收到后渲染成计划卡。
不含计划意图的对话不挂卡（每句话都甩一张卡会让老人烦）。

### 3.6 端侧文件

| 文件 | 职责 |
|---|---|
| `api/plans.js` | 计划接口封装（老人端只用 today / checkin） |
| `stores/plan.js` | 今日计划状态：乐观打卡、三级兜底（接口 → 缓存 → 内置样例） |
| `pages/plans/plans.vue` | 日程页（Tab 2） |
| `components/bl-plan-check/` | 计划项 + 大字打卡（整卡可点，状态三重表达） |

### 3.7 mock 与真实后端的差异

`tools/mock-server.mjs` 里的计划是**静态样本且直接是生效态**，跳过了「生成 → 家属确认」；
真实服务端必须走完闸门。端侧代码不感知这个差异，所以联调效果一致——
但**不要用 mock 验证闸门逻辑**，那部分由服务端单测（`server/tests/test_plan_engine.py`）守。

---

## 四、话术与内容约束（服务端责任，端侧只管展示）

1. **句末不加句号**：多句用换行代替句号，小数（`2.5mg`）与缩写除外
2. 第一人称、口语、短句；闲聊 1–2 句，说明类 ≤4 句，超出转 `card`
3. 表情只能发白名单 token（端侧白名单见 `uni-app/common/stickers.js`），**不能输出 URL**
4. 医疗边界：不做诊断、不做剂量调整、不做疾病判断，只做生活提醒与依从性管理
5. 消息末尾不要带 AI 免责声明——界面已有常驻「AI 数字人 · 内容仅供参考」标识，重复反而刺眼

---

## 五、端侧消息状态机

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

## 六、联调

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

## 七、后端接手时的替换点

端侧已按契约实现，后端只需保证：事件名与字段名一致、`meta` 先发、错误体结构一致。
另外这些还没做，属于 P0 之后的事：

- 鉴权（目前无 header / 无 token，接入时要加 `Authorization` 并处理 401）
- `clientMsgId` 幂等（端侧已传，服务端应据此去重，避免重试产生重复消息）
- 限流与错误码表（端侧已按 `code`/`statusCode` 显示人话，但服务端还没有稳定码表）
- 会话列表接口（`chats` 页除首个会话外仍是本地占位数据）
