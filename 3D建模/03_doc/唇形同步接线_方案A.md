# 唇形同步接线（方案 A）：契约 + 假数据 + 端侧驱动（2026-10-05）

> 用户选择方案 A：**先做契约与端侧驱动，用假时间戳把链路跑通**，不碰 GPU/CosyVoice。
> 调研结论（子代理）：后端原本**完全没有** TTS/音频层，端侧也没有音频通道，
> 所以 lip-sync 的上游「AI 说话有声音」整体还没做 —— 本方案先把**下游（口型）**打通。

---

## 1. 数据流（新增的一环在正中间）

```
回复文本
  → 后端 server/app/avatar/visemes.py        把文字编成**带时间的关键帧**
  → SSE 事件 `lipsync`（done 之前发一次）      { assistantMsgId, durationMs, source, cues[] }
  → 端侧 uni-app/api/chat.js 解析             CHAT_EVENT.lipsync（形状校验，坏帧丢弃）
  → 端侧 uni-app/common/face-gl/lipsync.js    插值 / 交叉淡化 / 最多混 2 个
  → 渲染器 stage.setVisemes(frame)            写 15 个 vis_* 形态键
```

**为什么"字 → viseme"放后端**：`uni-app/` 是**零 npm 依赖**、没有拼音表（全仓 grep `pinyin` 为 0）；
把它放后端，端侧只剩"按时间插值"这一件小事。

---

## 2. 逐处改动（契约要求三处同步）

| 位置 | 改动 |
|---|---|
| `server/app/avatar/visemes.py`（新） | 字→viseme 映射（23 声母 + 36 韵母，口径同 `morph-viseme-cosyvoice2.json`）+ 时间轴生成 + `build_lipsync_payload()` |
| `server/app/orchestration/events.py` | 新增 `EVENT_LIPSYNC` 与 `lipsync_frame()` |
| `server/app/orchestration/service.py` | 在 `done` 之前 yield（**只在有正文时发**：纯表情/卡片不该让数字人"对空气张嘴"）；生成失败只记日志、不中断对话 |
| `uni-app/api/README.md` | 事件表新增 `lipsync` 行（字段、单位、`source` 语义） |
| `uni-app/api/chat.js` | `CHAT_EVENT.lipsync` + `normalize()` 分支（**结构校验**，缺 `b/e/v` 的 cue 直接丢） |
| `tools/mock-server.mjs` | 等价实现（精简字表）+ 在 `done` 前发，**时序与逐字吐字对齐**（`perCharDelay`） |
| `uni-app/common/face-gl/lipsync.js`（新） | 驱动层：`buildTrack` / `sampleAt` / `createLipsyncPlayer` |
| `uni-app/common/face-gl/face-three.js` | `setVisemes` 改为**只写权重+`schedule()`**（不再每次同步渲染，否则一帧渲两次）；新增 `morphWeights()` 诊断读数 |
| `uni-app/pages/vision/vision.vue` | 接上播放器；H5 暴露 `__blVisionPlayLipsync` / `__blVisionLipsyncStats` |
| `tools/test-lipsync.mjs`（新） | 9 条断言；已并入 `npm run test:face` |

---

## 3. 驱动层的三条硬规则（都有测试守着）

来自 `morph-viseme-cosyvoice2.json` 的 `timingHint`，肉眼看不出来，只能靠断言：

1. **每帧必须给完整 15 个键** —— 渲染器的 `setVisemes` **只写传入的键、不归零**，
   漏键会让上一帧的口型**残留挂在脸上**。
2. **同时最多混 2 个 viseme**（`maxCoarticulationBlend`）。
3. **权重和 ≤ 1** —— 超了形态键叠加过度（"嘴被拉爆"）。

### 写这层时被测试抓出的 4 个真 bug（都不是测试写错）

| bug | 现象 | 修法 |
|---|---|---|
| 交叉淡化越过区间 | `t=120` 处前一个 viseme 还留着 0.5 | 淡化窗取 `min(50ms, 本区间一半)` |
| "本帧 2 音 + 相邻 2 音" = **4 个同时混** | `t=170` 出现 `vis_AA/vis_I/vis_MBP/vis_NN` | 自带 2 个音的帧**不做额外淡化**（单音帧才淡化） |
| 仍然到 3 个（淡出到静止 + 本帧 2 音） | 边界处 3 个 | 最后按权重**裁到最多 2 个**再归一化 —— 这条对任何输入都成立 |
| 负数时间被夹成 0 | `t=-10` 返回了第一帧的口型（"还没开始"被当成"正在进行"） | **夹紧之前**先判 `tMs < cues[0].b` |

---

## 4. ⚠️ 还有一个静默失效被揪出来（重要）

`face-three.js` 的 `setVisemes` 在交付件上**一直返回 `applied: 0`** —— 手工直接调也一样，
也就是**口型怎么写都写不进去**，而 `stats()` 却能报出 23 个形态键（它走另一条读法）。

根因：`morphOwners` 在 load 期间收集到的是**空容器**。
修法：**容器为空时按需重建**（并在注释里写明"没有这个兜底，口型会静默失效：
驱动层照常每帧调用、计数全是 0、脸上一点不动"）。

> 这类"不报错、但功能全无"的问题，靠看画面是发现不了的 ——
> 所以本轮补了 `stage.morphWeights()` 读数口子：**口型是写进形态键的，
> 而渲染出的画面在无头浏览器里截不到，只能读权重来验**。

---

## 5. 实测验收

**驱动层单元测试**：`node tools/test-lipsync.mjs` → **9/9**
（含"每帧 15 键""最多 2 个""权重和 ≤1""越界回静止""负时间回静止"）

**端到端（无头 Edge + CDP，同步读权重）**：
```
播放前： vis_AA=0,   vis_MBP=0
播放后： vis_AA=0.5, vis_MBP=0.5      ← "妈"的口型（闭+开）
写入计数：visemeWrites = 315
```
即：**服务端风格的关键帧喂进去 → 形态键真的被写动**。

**三套测试全绿**：`npm test` / `npm run test:face`（20 + 9）/ 后端 `unittest` 286 项。

---

## 6. 诚实的边界（不要当成最终形态）

- **时间轴是按字数估算的**（`source: 'estimated'`，mock 110ms/字、后端 180ms/字），
  **不是真实语音对齐**。真 TTS（CosyVoice 2）就绪后：
  - 开源 CosyVoice 2 **不原生给字级时间戳**（已核实其 `inference_*` 只 yield 音频张量）；
    可行路径是 ASR 侧强制对齐（FunASR / WhisperX）或托管版 WS 的 `sentence.words[]`。
  - `build_cues` 已按"时间由外部给"设计，届时**只换数据来源，端侧与契约都不用动**。
- **端侧时钟是自建的** `performance.now()`，不是音频时钟。真音频接入后必须改成
  "以音频播放时刻为基准"，否则**音画会漂移**（`player.start(cues, audioStartMs)` 已留好形参）。
- **拼音表是精选常用字**（不是全字表），未收录回退 `vis_AA`。仓库只允许 4 个依赖，
  引拼音库不合适；全字表体积也不划算。要提覆盖率就扩表，或改由 TTS 侧直接给音素。
- 通话页目前**没有对话流入口**（caption 是静态的），所以口型只能靠
  `window.__blVisionPlayLipsync(cues)` 手工触发。要真正联通需要把聊天流的
  `lipsync` 事件转发到通话页 —— 这是下一步（依赖"AI 说话"那条链先做出来）。
