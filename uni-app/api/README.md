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
| 末（`lipsync` 之前） | `audio` | `{"assistantMsgId":"a_1","url":"/v1/audio/<id>?expires=1699999999&sig=abc123","durationMs":2340,"format":"mp3"}` | **合成音频**。`url` 是**短期签名地址**（相对路径，端侧自己拼 base）：端侧播放器（`innerAudioContext` / `<audio>`）**带不了 `Authorization` 请求头**，所以鉴权信息编进查询参数，端点自己校验签名与有效期。签名不对/过期一律 403，且**不区分原因**（避免探测 id 是否存在） |
| 末（`done` 之前） | `lipsync` | `{"assistantMsgId":"a_1","durationMs":2340,"source":"estimated","version":1,"cues":[{"c":"妈","b":0,"e":180,"v":["vis_MBP","vis_AA"]}]}` | **口型关键帧**（3D 数字人唇形同步用）。`cues[].b`/`e` 是毫秒区间，`v` 是该字对应的 viseme 形态键（**服务端已收敛到 ≤2 个、权重和 ≤1**，端侧只做时间插值）。`source`：`estimated`（时间轴按字数估算）/ `tts-aligned`（真语音对齐）。`version` 用于将来扩展 |
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

### 2.4 错误码表（唯一事实来源在服务端）

所有错误统一形状：

```json
{ "error": { "code": "plan_state", "message": "计划当前是「草稿」，不能确认", "retryable": false } }
```

- **`message` 会直接展示给老人**：服务端保证是人话（"服务器开小差了，一会儿再试"），
  端侧不要再自己拼一套文案，也不要把它当调试信息
- **`retryable` 决定端侧要不要给"重发"入口**：鉴权失败、格式错误、状态冲突都是 `false`
  （重试一百次也还是失败）；网络类、模型超时是 `true`
- 端侧 `request.js` 直接采信服务端的 `retryable`，服务端没给才按状态码猜
- **完整表可运行时拉取**：`GET /v1/errors`（公开，不需要 token）

主要错误码（完整表见服务端 `app/errors.py`）：

| code | HTTP | 端侧该做什么 |
|---|---|---|
| `auth_required` | 401 | 提示"让家里人帮你看一下"，**不给重试** |
| `unauthorized` | 401 | 提示"登录已过期"，**不给重试** |
| `invalid_date` / `invalid_request` | 400 / 422 | 不该发生（端侧参数 bug），记日志 |
| `plan_state` | 409 | 状态冲突（如确认一份草稿），刷新后重试 |
| `plan_not_active` | 409 | 还没有生效计划，引导让家里人确认 |
| `plan_item_not_found` | 404 | 刷新今日计划 |
| `duplicate_request` | 409 | 同一句话正在生成中，等一拍再拉 |
| `empty_text` | 400 | 输入为空，不该发请求 |
| `llm_timeout` | 504 | 可重试 |
| `llm_rate_limited` / `llm_unavailable` / `server_error` | 502 | 可重试，提示"服务器开小差了" |
| `internal` | 500 | 可重试 |
| `manual_tick_disabled` | 403 | 联调接口被关掉（生产环境正常） |

### 2.5 鉴权

服务端三档（`server/.env` 的 `AUTH_MODE`）：

| 模式 | 行为 | 用在哪 |
|---|---|---|
| `off` | 完全不校验 | 本机开发 |
| `auto`（默认） | **配了 `API_TOKENS` 就强制校验**，没配则放行并在启动日志里大声警告 | 过渡期 |
| `required` | 强制校验；没配 token **直接启动失败** | **上线用这个** |

端侧带 token 的方式：HTTP 头 `Authorization: Bearer <token>`（也接受 `X-API-Token`）。

```js
import { setApiToken } from '@/api/index.js'
setApiToken('服务端 API_TOKENS 里的那一串')   // 写本地缓存，下次启动仍生效
```

- **非流式与流式都要带**：两条路径共用 `config.js` 的 `authHeaders()`，
  不会出现"聊天能流式但历史拉不到"这种故障
- 公开路径（不需要 token）：`/healthz`、`/v1/errors`、`/docs`
- ⚠️ **这一版能防什么、不能防什么**（别误以为已经有账号体系了）：
  能防"接口被内网/公网随便扫到就调用"；**不能防**"从 App 里把 token 抠出来的人"
  （App 里的任何常量都能被逆向）。
  真正的做法（P2 随家人端一起做）：家人端手机号登录 → 签发短期 JWT + refresh token →
  老人端用绑定关系换只读自己数据的 scoped token → 支持设备级撤销

### 2.6 幂等（`clientMsgId`）

端侧每次发言都带一个本地消息 id（`clientMsgId`），服务端据此去重：

| 情况 | 服务端行为 | 端侧表现 |
|---|---|---|
| 第一次见 | 正常生成 | 逐字回填 |
| 同一 id 再次请求（已生成完） | **回放缓存**，不再调用模型、不再重复落库 | 事件里 `replayed: true`，内容与首次一致 |
| 同一 id 正在生成中 | `duplicate_request`（409 / SSE `error` 事件） | 提示"这句话我正在回，等我一下" |

- **重试必须复用同一个 `clientMsgId`**：`stores/chat.js` 的 `retry()` 传的就是上一条本地消息 id，
  所以"重试不重复"是自动成立的
- **第一轮失败时不写缓存**：失败（模型鉴权错/超时）与"一个字都没产出"都会放开记录，
  否则端侧重试永远拿到空回复——这种"越重试越坏"的 bug 最难查
- 不传 `clientMsgId` 时按老行为处理（不做幂等），便于手工 curl 调试

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

### 3.6 mock 与真实后端的差异

`tools/mock-server.mjs` 里的计划是**静态样本且直接是生效态**，跳过了「生成 → 家属确认」；
真实服务端必须走完闸门。端侧代码不感知这个差异，所以联调效果一致——
但**不要用 mock 验证闸门逻辑**，那部分由服务端单测（`server/tests/test_plan_engine.py`）守。

### 3.7 提醒投递与调度（P1）

计划生效之后还要有人"到点喊一声"，这一段是调度器的活：

```
active 计划 → 调度器登记 ReminderTask（幂等：同一项同一天同一时刻只有一条）
  → 到点投递：通道 ① 站内消息（写进会话）② 日志兜底
  → 端侧前台轮询拉到 → 顶部提醒条 + 震动 → 点进日程页打卡
  → 打卡即 ack：任务标 acked，"提醒送到没送到 / 做没做"都能追溯
```

| 接口 | 方法 | 用途 | 谁用 |
|---|---|---|---|
| `/v1/reminders/inbox` | GET | 未读提醒（已投递、还没被看到过） | 老人端 |
| `/v1/reminders/read` | POST | 回执已看到（不传 `taskId` = 整个收件箱） | 老人端 |
| `/v1/reminders/tasks` | GET | 任务与状态（可追溯） | 家属端 / 运营 |
| `/v1/scheduler/status` | GET | 调度器自检：通道、各状态任务数、下一条提醒时间 | 端侧 / 运维 |
| `/v1/scheduler/tick` | POST | 手动推进一次（联调/演示；**上线前应关掉** `SCHEDULER_MANUAL_TICK`） | 联调 |

`GET /v1/reminders/inbox` 响应：

```json
{
  "elderId": "e_1",
  "count": 1,
  "tasks": [
    {
      "id": "rt_xxx", "planId": "plan_xxx", "planItemId": "pi_xxx",
      "title": "量完血压记一下 下次给医生看", "label": "08:00 监测",
      "level": "normal", "levelLabel": "普通提醒",
      "sendAt": "2026-09-24T08:00:00", "sentAt": "2026-09-24T08:00:02",
      "readAt": "", "ackAt": "", "repeatCount": 0,
      "status": "sent", "statusLabel": "已送出", "channel": "inbox"
    }
  ]
}
```

`status` 的取值与中文（`statusLabel` 直接给家属/老人看，端侧**不要自己映射**）：

| `status` | `statusLabel` | 含义 |
|---|---|---|
| `pending` | 还没到点 | 已登记，等时间到 |
| `sent` | 已送出 | 已投递（`channel` 记录走的哪条通道） |
| `acked` | 已打卡 | 老人打卡即确认，家属端据此判断"送到且做了" |
| `read` | 已看过 | 老人看过提醒条但还没打卡 |
| `missed` | 没见回应 | 投递了但迟迟没响应（默认 60 分钟无响应） |
| `skipped` | 没发（超出时间窗） | 弱提醒超窗、或已过宽限期不补发 |
| `canceled` | 已作废（计划换了） | 计划变更后未发的任务作废 |
| `failed` | 发送失败 | 通道投递失败（`note` 里有原因） |

**提醒分级与四条策略**（设计方案 §3.2）：

| 级别 | 适用 | 策略 |
|---|---|---|
| `strong` 强提醒 | 用药、午餐（知识库 `strong_remind`） | 到点发；未打卡则隔 5 分钟再响一次，最多 1 次 |
| `normal` 普通提醒 | 活动、监测 | 到点发一次，不重复 |
| `weak` 弱提醒 | 问候类 | 只在 9:00–20:00 发，**超窗直接不发、不顺延** |

另外两条容易漏掉但很影响体验的：

- **过期不补发**：超过 30 分钟（`REMINDER_GRACE_MINUTES`）才投递的提醒直接记 `skipped`。
  早上 8 点的用药提醒下午 3 点才响，只会让老人困惑
- **错过要留痕**：投递后 60 分钟没打卡记 `missed`，家属端据此区分
  "提醒送到了但他没做"和"提醒根本没送到"

**双保险的现状（重要）**：

| 腿 | 状态 |
|---|---|
| 服务端站内消息（写进会话，端侧轮询拉到） | ✅ 已实现 |
| 厂商推送（uni-push / 极光 / 个推 / 华为小米通道） | ⛔ **未接入**——需要开发者账号与资质，部分功能收费，按仓库约定须先确认 |
| 端侧本地定时通知（App 端，推送丢了也能响） | ⚠️ **未做**——需要真机验证 `plus.push` 的能力与字段，不写没验过的代码 |

所以现在老人端能收到提醒的**前提是 App 在前台**（打开着就能看到提醒条 + 震动）。
系统级推送要等通道确认后再补——这也是为什么通道做成了可插拔的
（`server/app/schedule/channels.py`）。

**端侧行为**（`stores/reminder.js` + `components/bl-reminder-bar/`）：

- App 前台每 30 秒拉一次（退到后台停掉，不白耗电）
- 新提醒：顶部提醒条 + 震动（强提醒长震、普通轻震）；**同一条只震一次**，
  否则每 30 秒震一下会把人烦死
- 点提醒条本体 → 跳日程页打卡；点「知道了」→ 回执已读并展示下一条
- 拉取失败静默处理：提醒是锦上添花，网络不好时不弹错误吓老人

---

### 3.8 推送通道与端侧本地提醒

提醒要送达老人，设计上是**三条腿**：

| 腿 | 现状 | 老人什么时候能收到 |
|---|---|---|
| ① 站内消息 | ✅ 已实现 | App 打开着（前台轮询拉到 → 提醒条 + 震动） |
| ② 系统推送（uni-push 2.0） | ✅ 代码已就绪，**待你开通 DCloud 侧配置** | 老人不开 App 也能在通知栏看到 |
| ③ 端侧本地通知 | ✅ 已实现（App 端） | 断网、推送挂了也照样响（预排当天的提醒） |

三条腿互相兜底，任何一条挂了提醒都不会消失——这也是为什么调度器把通道做成可插拔的。

**②的接口**（端侧登记 cid，服务端才知道提醒发到哪台设备）：

| 接口 | 方法 | 用途 |
|---|---|---|
| `/v1/push/register` | POST | 登记推送标识（同一 cid 幂等） |
| `/v1/push/unregister` | POST | 注销（关推送 / 换设备） |
| `/v1/push/status` | GET | 自检：云函数配好没、登记了几台设备 |

```json
// POST /v1/push/register
{ "cid": "cid_xxx", "elderId": "e_1", "platform": "android", "appVersion": "1.0.0" }
// 响应（⚠️ cid 只回显后 6 位，它是设备标识，不该到处传）
{ "ok": true, "elderId": "e_1", "cidTail": "123456", "updatedAt": "2026-09-24T08:00:00" }
```

**端侧行为**（`stores/push.js`）：

- App 启动/回前台时登记 cid（`uni.getPushClientId`）；**拿不到就静默跳过**——
  H5、小程序、标准 HBuilderX 基座都没有这个能力，不能因此让页面报错
- 登记失败不影响提醒的另外两条腿，cid 本地留一份，下次启动重试
- `uni.onPushMessage` 监听：在线收到只刷新提醒（不跳页），**点通知栏**才进日程页打卡
- 本地通知预排：只排**未来 12 小时内且未打卡**的项，按 `${日期}|${计划项 id}` 记账防重复
  （否则上午开三次 App，下午的提醒会响三次），跨天自动重置

**②要你能先做三件事**（详见 [`server/deploy/unipush-cloudfunction/README.md`](../server/deploy/unipush-cloudfunction/README.md)）：

1. `manifest.json` 的 `appid` 现在是**空的**，先在 HBuilderX 里获取 DCloud appid
2. 在 DCloud 开发者中心开通 uni-push（App 端离线推送还要配厂商参数/iOS 证书）
3. 部署我们提供的云函数参考实现（`server/deploy/unipush-cloudfunction/`）并 URL 化，
   把地址填进 `server/.env` 的 `UNIPUSH_SEND_URL`

> **为什么要经过云函数**（已核实官方文档）：uni-push 2.0 的服务端 SDK 只能跑在 uniCloud 云函数里；
> 自建服务器想直连个推，官方要求改用老版 uni-push 1.0 的凭证体系。
> 走云函数还有个好处：**个推的 appkey/mastersecret 留在云函数侧，不进业务服务器**。

### 3.9 端侧文件（计划与提醒）

| 文件 | 职责 |
|---|---|
| `api/plans.js` | 计划接口（老人端只用 today / checkin） |
| `api/reminders.js` | 提醒收件箱与回执 |
| `api/push.js` | 推送标识登记 |
| `api/memory.js` | 三层记忆（老人端只读；写接口仅供家人端 `family/`） |
| `stores/plan.js` | 今日计划：乐观打卡、三级兜底 |
| `stores/reminder.js` | 前台轮询、提醒条、震动、去重 |
| `stores/push.js` | cid 登记、本地通知预排、推送消息监听 |
| `pages/plans/plans.vue` | 日程页（Tab 2） |
| `components/bl-plan-check/` | 计划项 + 大字打卡 |
| `components/bl-reminder-bar/` | 顶部提醒条 |

---

## 三点五、三层记忆接口（P2）

三层记忆里 **L1 是健康档案**（`GET /v1/elders`，一直在注入 system prompt），
这里说的是 **L2 经历事件**（"2023 年儿子带我去过海南"）与 **L3 兴趣偏好**（"爱听戏""喜欢下棋"）。

### 3.5.1 接口一览

| 方法 | 路径 | 谁用 | 说明 |
|---|---|---|---|
| `GET` | `/v1/memories?elderId=&kind=&q=&scope=&includePending=&limit=` | 老人端 / 家人端 | 列表；带 `q` 时走相关性检索（结果多一个 `score`） |
| `POST` | `/v1/memories` | 家人端 | 录入一条（`source` 默认 `family`） |
| `PATCH` | `/v1/memories/{id}` | 家人端 | 改内容 / 标签 / 可见性 |
| `DELETE` | `/v1/memories/{id}` | 两端 | **单条删除**（产品要求） |
| `POST` | `/v1/memories/clear` | 家人端 | **一键清空**（产品要求） |
| `POST` | `/v1/memories/review` | 家人端 | 复核自动整理的条目（`approve` true/false） |
| `GET`/`PUT` | `/v1/memories/settings` | 两端 | 自动整理开关（默认 **关**） |
| `GET` | `/v1/memories/topics` | 家人端 / 主动关怀 | L3 汇总出的"能聊什么"，按权重排序 |

端侧文件：`api/memory.js`；`api/config.js` 里对应 `ENDPOINTS.memories` / `memoryClear` /
`memoryReview` / `memorySettings` / `memoryTopics`。

**谁调哪些**（同一份客户端，两端共用）：

| 函数 | 老人端 `pages/**` | 家人端 `family/` |
|---|---|---|
| `fetchMemories` / `fetchMemoryTopics` / `fetchMemorySettings` | ✅ 只读 | ✅ |
| `createMemory` / `reviewMemory` / `updateMemorySettings` | ❌ **不许调用** | ✅ |
| `deleteMemory` / `clearMemories` | ✅（老人自己要求"忘掉"时） | ✅ |

⚠️ **`source=auto` 不能由客户端声明**：`POST /v1/memories` 只接受 `family` / `elder`，
传 `auto` 返回 422 `invalid_request`。原因：`auto` 表示"从聊天自动整理"，而这类记忆默认家属
不可见；若允许客户端声明 `auto` + `visibleToFamily=true`，就能从接口层把聊天转述的内容
送进家人视野——"家人端默认看不到聊天原文"这条边界会被绕开（真服务上实测过这个洞，已堵）。
自动整理只能由对话流程写入。

### 3.5.2 三条口径（端侧不许绕过）

1. **`source` 决定可见性**：`family`（家人录入）/ `elder`（老人自述）/ `auto`（从聊天整理）。
   `auto` 的记忆 **`visibleToFamily=false`**，`scope=family` 时不会返回——
   否则"家人端默认看不到聊天原文"会被记忆绕过去（设计方案 §3.4）
2. **`review=pending` 不参与检索**：自动整理里置信度低于 `0.75` 的先入待复核，
   `GET /v1/memories` 默认不返回，`q=` 检索也取不到；家属 `review` 通过后才可用
3. **自动整理默认关**：`autoExtract=false`。开启时服务端记 `consentedAt`；
   关闭只影响新增，已入库的仍可单条删除或一键清空

⚠️ 老人端**页面**不提供写入入口：记忆能被 App 直接改，就绕过了"家属确认"这道产品闸门。
老人端只做只读展示（`scope=all` 自查）；写接口在同一份客户端里，**只给家人端 `family/` 用**。

### 3.5.3 请求/响应示例

```jsonc
// POST /v1/memories
{ "elderId": "e_1", "kind": "experience", "text": "老人 2023 年跟儿子去过海南",
  "tags": ["儿子", "旅行"], "happenedAt": "2023年" }

// 200（GET 列表里的一个条目）
{ "id": "mem_1", "elderId": "e_1", "kind": "experience", "kindLabel": "经历",
  "text": "老人 2023 年跟儿子去过海南", "tags": ["儿子", "旅行"],
  "source": "family", "sourceLabel": "家里人填写", "confidence": 1,
  "review": "approved", "visibleToFamily": true, "happenedAt": "2023年",
  "createdAt": "2026-10-04T02:31:07+08:00", "updatedAt": "2026-10-04T02:31:07+08:00" }

// 404
{ "error": { "code": "memory_not_found", "message": "没找到这条记忆", "retryable": false } }
```

### 3.5.4 mock 与真实后端的差异

| 项 | 真服务 | mock |
|---|---|---|
| 检索打分 | 标签命中 + 词组/单字命中率 + 时间新鲜度 + 来源可信度；**只蹭上一个常用字不算相关**（否则"老家的桥"会捞出"老人爱听戏"） | 字符二元组命中数（**只求量级一致**，天然更严） |
| 种子数据 | 无（空库起步） | 预置 4 条（含一条 `auto`+`pending`，用来验证两处隐私口径） |
| 存储 | 看 `DATABASE_URL`：默认 `memory://`（重启即空）或 `sqlite:///data/bilin.db`（持久） | 内存 |
| 自动整理开关 | **按老人各一份**（`MemoryStore._settings[elder_id]`） | 同左（第一版写成全局一个 bool，等于"给 e_1 开了，e_2 也开着"——隐私开关错的那一侧，已修） |
| CORS | `allow_methods=["*"]` | 需显式列全（缺 PATCH/PUT 时**真浏览器**的预检会挡掉改可见性/开关，而 node fetch 不做预检、静默漏掉） |

两边**隐私口径与错误码必须一致**（`tools/test-memory-store.mjs` 同一套用例跑两边）。

⚠️ **跑契约测试不要用 `e_1`**：最后一条用例要验"一键清空"，会把该老人的记忆真的清掉。
测试默认用 `e_mem_test`（可用 `BILIN_TEST_ELDER_ID` 覆盖）——第一版就是用 `e_1` 跑的，
把演示数据清了，排查"模型怎么不记得了"花了半天。

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

契约回归（每个套件同时支持内置 mock 与真实后端）：

```bash
npm test                                            # 端侧全量（内置 mock）
node tools/test-memory-store.mjs                    # 只跑三层记忆契约
$env:BILIN_TEST_BASE_URL='http://127.0.0.1:8000'; node tools/test-memory-store.mjs   # 打真服务
```

Android 真机/模拟器要连本机服务，用 `adb reverse` 把设备的 8787 反向映射到电脑
（这样 App 里默认的 `127.0.0.1:8787` 不用改源码）：

```bash
adb reverse tcp:8787 tcp:8787
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
- 限流（错误码表已就绪，见 §2.4；限流本身还没做）
- 会话列表接口（`chats` 页除首个会话外仍是本地占位数据）

> 已不再属于"待做"：鉴权（`AUTH_MODE`，端侧 `setApiToken()`）、`clientMsgId` 幂等、
> 三层记忆接口（§三点五）都已实现，这里保留原文以对照历史。
