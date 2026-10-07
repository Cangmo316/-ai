<template>
  <view class="bl-vision" :class="{ 'bl-large': settings.largeFont }">
    <!-- 教室场景：**纯 CSS 画**，零依赖、不加载外部图片。
         为什么不用 3D 背景：渲染器只做人物（`scene.background` 是空的），
         背景一直是 CSS 层。沿用这个分层就不必动渲染器，换场景也只是换样式。
         层次（从后到前）：墙 → 黑板 → 墙上挂钟 → 窗户 → 课桌 → 人物 -->
    <view class="bl-room">
      <view class="bl-room__board">
        <view class="bl-room__chalk" />
        <view class="bl-room__tray" />
      </view>
      <view class="bl-room__clock">
        <view class="bl-room__clock-hand" />
        <view class="bl-room__clock-hand bl-room__clock-hand--short" />
      </view>
      <view class="bl-room__window">
        <view class="bl-room__mullion-v" />
        <view class="bl-room__mullion-h" />
      </view>
      <view class="bl-room__desk" />
    </view>
    <view class="bl-vision__topbar">
      <view class="bl-vision__topbar-left">
        <!-- AI 身份标识：与「AI 数字人通话」**并排同一行**（产品红线：不冒充真人）。
             两者一起说明"这是 AI 通话、对面是数字人"，一眼看完。
             原来是居中独立一行、浮在人物额头附近——既遮脸又占一行高度。 -->
        <view class="bl-vision__topbar-row">
          <view class="bl-vision__tag">
            <text class="bl-vision__tag-text">AI 数字人通话</text>
          </view>
          <view class="bl-vision__aibadge">
            <text class="bl-vision__aibadge-text">{{ UI_COPY.aiBadge }}</text>
          </view>
        </view>
        <text class="bl-vision__timer">通话中 {{ clock }}</text>
      </view>
    </view>


    <!-- 真 3D 数字人（交付件：vis_* / expr_* 口型表情 + `wave` 招手动画）。
         App 端由 renderjs 模块 visionGl 接管；H5 端由本文件 onMounted 接管。
         两条路径都调用 common/face-gl/face-three.js 的同一个渲染器。 -->
    <view
      class="bl-vision__stage"
      id="blVisionStage"
      :gender="gender"
      :boot="bootTick"
      :change:gender="visionGl.onGender"
      :change:boot="visionGl.onBoot"
    >
      <!-- 降级态：WebGL 不可用或资产加载失败时兜住"白屏"（原来的 CSS 假人留作兜底） -->
      <view v-if="stage.fallback" class="bl-vision__person">
        <view class="bl-vision__head" />
        <view class="bl-vision__torso" />
      </view>
    </view>

    <view class="bl-vision__caption">
      <text class="bl-vision__caption-text">{{ caption }}</text>
    </view>

    <!-- 招手已改为**进场自动一次**（见 waveOnEntry）：真人视频通话里对方也只是接通时打个招呼，
         手动反复触发只会让"动作假"更显眼 —— 所以「让 TA 招手」按钮去掉了。
         一键停止（产品红线）由底部通话栏的「挂断」承担：它卸载本页，onUnmounted 里
         stopAudio + lipsync.stop 全停；原「停一下」按钮同理去掉，stopSpeaking 保留给打断与验收。 -->

    <!-- 问一句：走**真对话流**（SSE 流式文字 → 服务端合成音频 + 口型 → 端侧边说边动嘴）。
         现在还没有语音识别，"说"用输入框代替；等 ASR 接上后这里换成按住说话即可。 -->
    <view class="bl-vision__ask">
      <input
        v-model="question"
        class="bl-vision__ask-input"
        type="text"
        confirm-type="send"
        placeholder="想说什么，写在这里"
        placeholder-class="bl-vision__ask-ph"
        @confirm="askNow"
      />
      <view class="bl-vision__ask-btn" :class="{ 'is-busy': chat.streaming }" @click="askNow">
        <text class="bl-vision__ask-btn-text">{{ chat.streaming ? '正在说…' : '问一句' }}</text>
      </view>
    </view>

    <view class="bl-vision__controls">
      <view class="bl-call-btn" :class="{ 'is-off': muted }" @click="toggleMute">
        <bl-icon :name="muted ? 'muted' : 'mic'" color="#FFFFFF" :size="56" />
      </view>
      <view class="bl-call-btn bl-call-btn--hangup" @click="hangup">
        <bl-icon name="hangup" color="#FFFFFF" :size="56" />
      </view>
      <view class="bl-call-btn" :class="{ 'is-off': spkOff }" @click="toggleSpk">
        <bl-icon :name="spkOff ? 'muted' : 'speaker'" color="#FFFFFF" :size="56" />
      </view>
    </view>
  </view>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { settings } from '@/common/store.js'
import { UI_COPY } from '@/common/face/face-index.js'
import { DEFAULT_GENDER } from '@/common/face-gl/assets.js'
import { getBaseURL } from '@/api/config.js'
import { chat, send as sendChat, stop as stopChat, onLiveTurn, DEFAULT_CONVERSATION_ID } from '@/stores/chat.js'
// 口型驱动：把 SSE `lipsync` 事件的关键帧变成逐帧的 viseme 权重。
// 「渲染器只管把权重写进形态键」，插值 / 交叉淡化 / 最多混 2 个 的规则都在这个模块里。
import { createLipsyncPlayer } from '@/common/face-gl/lipsync.js'
// #ifdef H5
import { mountFaceStage, unmountFaceStage } from '@/common/face-gl/face-three.js'
// #endif

// 数字人形象性别：**跟着全局设置走**（在「数字人形象」页切了性别，这里要跟着换）。
// 用 computed 而不是快照，这样用户在别处改了 `settings.gender`、回到这里能自动生效。
const gender = computed(() => settings.gender || DEFAULT_GENDER)
const stage = ref({ fallback: false })
const bootTick = ref(0)
// 进场招手是否已经播过（只播一次）
let wavedOnEntry = false
let stageRef = null
/** 对话流订阅的取消函数（卸载时必须取消，否则页面销毁后回调仍会跑） */
let unsubscribeLive = null
/** 这一轮是"音频+口型"还是"只有口型"（诊断用；后端没配 TTS 时会是后者） */
let lastSpeechSource = ''
/** 最近一轮的原始数据（诊断用：回答"音频到底有没有到端侧"） */
let lastTurnInfo = null

/**
 * 口型播放器：把「服务端给的关键帧」变成逐帧的 viseme 权重，交给渲染器写形态键。
 *
 * ## ⚠️ 时间源只有**一个**：音频位置
 *
 * 这是踩过坑之后定下的设计。第一版让播放器从 `start()` 那刻起跑一个自有时钟，
 * 音频另外异步加载 —— 而音频要**下载 + 解码**（实测几百毫秒到几秒），
 * 结果**嘴在这段时间里已经把整句演完了**，等声音出来时嘴已经停了，
 * 表现为"完全看不到唇形同步"。
 *
 * 根因是"两个时钟各自跑，再想办法对齐"。正确做法是**单一时间源**：
 * 音频播到第几毫秒，嘴就摆到第几毫秒 —— 这样不存在漂移，也不需要"校准"。
 *
 * 没有音频时（后端未配 TTS）才退回自有时钟：嘴照样动，只是与声音无关。
 */
const lipsync = createLipsyncPlayer({
  fps: 30,
  // 读"当前音频播放位置"；没有音频时返回 null → 播放器退回自有时钟
  clock: () => {
    if (!audioContext) return null
    const seconds = Number(audioContext.currentTime)
    if (!Number.isFinite(seconds)) return null
    return seconds * 1000
  },
  onFrame(frame) {
    lipsyncFrameCount += 1
    lastLipsyncFrame = frame
    if (stageRef && typeof stageRef.setVisemes === 'function') stageRef.setVisemes(frame)
  },
})
/** 诊断：驱动层回调计数 + 最近一帧（用来区分"驱动层没跑"和"渲染层没写"） */
let lipsyncFrameCount = 0
let lastLipsyncFrame = null

/**
 * 合成音频（后端给的是**短期签名 URL**，播放器能直取，不需要请求头）。
 *
 * ⚠️ 口型与音频**共用同一根时间轴**：播放器的 `clock` 直接读 `currentTime`（见上面
 * `createLipsyncPlayer` 的说明）。所以这里**不需要**猜测"音频什么时候开始"，
 * 也不需要定时校准 —— 音频没就绪时 `currentTime` 为 0，嘴就停在句首；
 * 一旦开始播，嘴自然跟着走。这比"自有时钟 + 事后校准"简单也更可靠。
 */
let audioContext = null
let lastAudioError = ''
/** 诊断：本次播放的音频信息（时长/是否真的在播）—— 用来回答"到底响了没有" */
let audioInfo = null
/**
 * 行为探针：说话期间定时采「音频位置 + 当前形态键权重」。
 *
 * 为什么要有它：上一版的验收只断言"收到了音频 URL / cues"，那是**形状断言**，
 * 结果放过了两个真 bug（音频只有 52ms；口型在音频就绪前就演完）。
 * 真正的判据必须是**行为**：播放中嘴有没有摆、摆的时候时钟是不是音频、说完有没有回静止。
 * 探针只在被显式开启时采样（`__blVisionProbeStart()`），不影响正常运行。
 */
let probeSamples = []
let probeTimer = null

function probeStart() {
  probeStop()
  probeSamples = []
  probeTimer = setInterval(() => {
    const morph = (stageRef && typeof stageRef.morphWeights === 'function')
      ? stageRef.morphWeights(['vis_AA', 'vis_MBP', 'vis_I', 'vis_L', 'vis_silence'])
      : null
    const active = morph ? Object.entries(morph).filter(([, v]) => v > 0.01) : []
    probeSamples.push({
      t: audioContext ? Number(audioContext.currentTime || 0) : -1,
      active: active.map(([k, v]) => k + '=' + Number(v).toFixed(2)),
      clock: lipsync.stats().clockSource,
    })
  }, 200)
  return { ok: true }
}

function probeStop() {
  if (probeTimer) { clearInterval(probeTimer); probeTimer = null }
}

function probeResult() {
  probeStop()
  const moved = probeSamples.filter((s) => s.active.length > 0)
  return {
    sampleCount: probeSamples.length,
    movedSampleCount: moved.length,
    mouthMoved: moved.length > 0,
    clockFromAudio: probeSamples.some((s) => s.clock === 'audio'),
    duration: audioInfo ? Number(audioInfo.duration || 0) : 0,
    played: audioInfo ? !!audioInfo.played : false,
    error: audioInfo ? audioInfo.error : '',
    samples: probeSamples.slice(0, 10),
  }
}

function stopAudio() {
  if (audioContext) {
    try { audioContext.stop() } catch (e) { void e }
    try { audioContext.destroy() } catch (e) { void e }
    audioContext = null
  }
}

// #ifdef H5
/* ----------------------------------------------- H5 音频：直接用原生 <audio> */

/**
 * H5 下**不用** `uni.createInnerAudioContext()`，改为直接用原生 `<audio>`。
 *
 * ## 根因（HBuilderX 内置浏览器实测，2026-10-06）
 *
 * uni-app H5 的 `InnerAudioContext.play()` 实现只有一行：
 *     `play() { this._stoping = false; this._audio.play() }`
 * —— 内部 `<audio>.play()` 返回的 Promise **被直接丢掉**。
 * 而浏览器的自动播放策略拒绝播放、或解码/取源失败时，**正是靠这个 Promise 的 reject 上报**；
 * 丢掉之后既不会触发 onError、也没有任何日志。端侧看到的就是
 * 「点了「问一句」→ 没声音，而且不知道为什么」。
 * 口型这边又因为读不到音频时钟（`currentTime` 恒为 0）而**定格在句首**，
 * 于是"没声音"与"没唇形"同时出现 —— 正是用户报的现象。
 *
 * 同一段 URL 的对照实测：普通 `new Audio()` 的 `play()` 能 resolve、`currentTime` 正常推进；
 * 而 uni 那个内部元素停在 `readyState=0 / networkState=3(NETWORK_NO_SOURCE)` —— 连源都没选上。
 *
 * ## 做法
 *
 * 直接用原生 `<audio>`，把 `play()` 的 Promise **接住**：
 *   · 成功 → 正常出声，口型跟着 `currentTime` 走；
 *   · 被拒/失败 → 原因记进 `audioInfo.error`（`__blVisionAskStats()` 可读），
 *     口型退回自有时钟把整句跑完 —— 不再"静默定格"。
 *
 * APP 端仍走 `uni.createInnerAudioContext()`（`#ifdef APP-PLUS`），行为不变。
 */
/** 一帧静音 WAV（data URI）：只为"解锁"音频用，不产生网络请求 */
const SILENT_WAV_DATA_URI = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAACABAAZGF0YQAAAAA='
let h5AudioEl = null
let h5AudioUnlocked = false

function ensureH5AudioEl() {
  if (!h5AudioEl && typeof document !== 'undefined') {
    h5AudioEl = document.createElement('audio')
    h5AudioEl.preload = 'auto'
    h5AudioEl.setAttribute('playsinline', '')
  }
  return h5AudioEl
}

/**
 * 首次用户手势里解锁音频。
 * 移动端 Safari 只认"手势内成功 play() 过"的元素，之后 SSE 异步回来的音频才可能自动起播。
 * ⚠️ 这里用**同一个元素**且**不静音**地播一帧静音 WAV：
 *   · 换个元素播是没用的（Safari 认的是被播放过的那个元素）；
 *   · 静音 play() 本来就允许，起不到解锁作用。
 * 桌面 Chrome 本就是 sticky activation，这一步无害。
 */
function unlockH5Audio() {
  if (h5AudioUnlocked) return
  h5AudioUnlocked = true
  try {
    const el = ensureH5AudioEl()
    if (!el || el.getAttribute('src')) return
    el.src = SILENT_WAV_DATA_URI
    const playing = el.play()
    if (playing && typeof playing.catch === 'function') playing.catch(() => {})
  } catch (error) { void error }
}

/**
 * 把原生 `<audio>` 包成端侧用到的那个小接口
 * （src / play / stop / destroy / currentTime / duration / paused / onCanplay / onPlay / onEnded / onError）。
 * 包装的意义：口型时钟读的就是 `audioContext.currentTime`，
 * 包完之后 H5 与 APP 共用同一段播放与口型代码，不必各写一套。
 */
function createH5AudioContext() {
  const el = ensureH5AudioEl()
  if (!el) return null
  const handlers = { canplay: null, play: null, ended: null, error: null }
  const listeners = {
    canplay: () => { if (handlers.canplay) handlers.canplay() },
    play: () => { if (handlers.play) handlers.play() },
    ended: () => { if (handlers.ended) handlers.ended() },
    error: () => {
      const mediaError = el.error
      if (handlers.error) handlers.error({ errMsg: 'audio element error', code: mediaError ? mediaError.code : 0 })
    },
  }
  el.addEventListener('canplay', listeners.canplay)
  el.addEventListener('play', listeners.play)
  el.addEventListener('ended', listeners.ended)
  el.addEventListener('error', listeners.error)
  return {
    _el: el,
    get src() { return el.currentSrc || el.src || '' },
    set src(value) {
      el.src = value
      try { el.load() } catch (error) { void error }
    },
    get currentTime() { return Number(el.currentTime || 0) },
    get duration() { return Number(el.duration || 0) },
    get paused() { return !!el.paused },
    // ⚠️ 关键：把 Promise 原样交出去，调用方才能接住"起播失败"
    play() {
      const playing = el.play()
      return playing && typeof playing.then === 'function' ? playing : Promise.resolve()
    },
    stop() { try { el.pause() } catch (error) { void error } },
    destroy() {
      Object.keys(listeners).forEach((name) => el.removeEventListener(name, listeners[name]))
      try { el.pause() } catch (error) { void error }
    },
    onCanplay(fn) { handlers.canplay = fn },
    onPlay(fn) { handlers.play = fn },
    onEnded(fn) { handlers.ended = fn },
    onError(fn) { handlers.error = fn },
  }
}
// #endif

/**
 * 播放一段合成音频，并让口型跟着音频走。
 *
 * @param {string} url      服务端给的签名地址（相对路径）
 * @param {Array}  cues     同一轮的口型关键帧
 */
function playSpeech(url, cues) {
  if (!url) return { ok: false, reason: '没有音频地址' }
  stopAudio()
  // 相对路径要拼成绝对地址：dev 是 5173、真机是后端地址，故用 API base（与 SSE 同源）
  const absolute = /^https?:/i.test(url) ? url : resolveApiUrl(url)
  try {
    // #ifdef H5
    // H5 直接创建原生 <audio>（uni 的 H5 封装会吞掉 play() 的失败，见上面说明）
    audioContext = createH5AudioContext()
    // #endif
    // #ifdef APP-PLUS
    audioContext = uni.createInnerAudioContext()
    // #endif
  } catch (e) {
    audioContext = null
  }
  if (!audioContext) return { ok: false, reason: '当前环境没有音频上下文' }

  audioInfo = { url: absolute, duration: 0, played: false, error: '' }
  audioContext.src = absolute
  // 口型**立刻挂上**：音频没就绪时 currentTime 为 0（嘴停在句首），
  // 开始播之后自然跟着走 —— 不需要等 onPlay 再启动，也就不会"漏掉开头"
  const started = lipsync.start(cues)
  // #ifdef H5 || APP-PLUS
  audioContext.onCanplay(() => {
    if (audioInfo) audioInfo.duration = Number(audioContext.duration || 0)
  })
  audioContext.onPlay(() => {
    if (audioInfo) {
      audioInfo.played = true
      audioInfo.duration = Number(audioContext.duration || audioInfo.duration || 0)
    }
  })
  // #endif
  audioContext.onEnded(() => { stopAudio() })
  audioContext.onError((error) => {
    // 音频失败不该静默：口型退回自有时钟继续跑完，并把原因记下来给验收读
    lastAudioError = 'audio error ' + ((error && (error.errMsg || error.code)) || '')
    if (audioInfo) audioInfo.error = lastAudioError
    stopAudio()
  })
  // ⚠️ 必须接住 play() 的 Promise：
  //    H5 原生 `<audio>.play()` 在"自动播放被拦 / 解码失败 / 源不可达"时会 **reject**；
  //    不接住就又是"静默无声"（老代码丢的正是 uni 封装里那个 Promise，见上面根因）。
  const ctx = audioContext
  const playing = ctx.play()
  if (playing && typeof playing.then === 'function') {
    playing
      .then(() => {
        // 已被下一轮或"一键停止"取代：这条成功不再算数（否则会污染新那轮的诊断）
        if (audioContext !== ctx) return
        if (!audioInfo) return
        audioInfo.played = true
        audioInfo.duration = Number(ctx.duration || audioInfo.duration || 0)
      })
      .catch((error) => {
        // 换 src / stop 会把上一轮挂起的 play() 打断成 AbortError —— 那不是真失败，直接忽略
        if (audioContext !== ctx) return
        lastAudioError = 'play() rejected: ' + ((error && (error.name || error.message)) || error)
        if (audioInfo) audioInfo.error = lastAudioError
        // 起播失败：口型退回自有时钟把整句跑完（有嘴动没声音，好过整体定格），
        // 并在 stopAudio 里把元素与监听一并收掉，避免下一轮串音。
        stopAudio()
      })
  }
  return { ok: true, url: absolute, lipsync: started }
}

/** 把服务端给的**相对**签名地址拼成绝对地址（dev 是 5173/8787、真机是内网地址）。 */
function resolveApiUrl(url) {
  const text = String(url || '')
  if (/^https?:/i.test(text)) return text
  let base = ''
  try { base = getBaseURL() } catch (e) { base = '' }
  return (base || '').replace(/\/+$/, '') + '/' + text.replace(/^\/+/, '')
}

const caption = ref('妈，今天药按时吃了没')
/** 输入框内容（暂时用"打字"代替说话；等 ASR 接上后换成按住说话） */
const question = ref('')

/**
 * 通话计时（秒）。
 *
 * ⚠️ 初值必须是 **0**：这里曾经硬编码 `ref(42)`（原型期为了看效果随手填的），
 * 结果是"一进通话页就显示 00:42"，看起来像已经通了 42 秒——
 * 当演示值用久了会被当成真的。
 */
const seconds = ref(0)
const muted = ref(false)
const spkOff = ref(false)
let timer = null

const clock = computed(() => {
  const m = Math.floor(seconds.value / 60)
  const s = seconds.value % 60
  return (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s
})

function onStageReady() {
  stage.value = { fallback: false }
}
function onStageError() {
  // 加载失败才显示兜底假人，并且**明确告知**（不让老人以为对面坏了）
  stage.value = { fallback: true }
}

/**
 * 进场招手：**只在刚进通话页时挥一次**。
 * 用户原话："挥手的动作太假，挥手只需要在刚打开语音的时候就行" —— 所以不再提供手动入口。
 * 幂等：H5 与 App 两条路径的就绪回调都可能调到这里，第二次直接返回。
 */
function waveOnEntry() {
  if (wavedOnEntry) return
  wavedOnEntry = true
  if (!stageRef || typeof stageRef.playAnimation !== 'function') return
  const result = stageRef.playAnimation('wave', { loop: false })
  // 编辑期资产没有这段动画：进场挥手失败**不打扰老人**（原来的 toast 是给手动按钮用的反馈）。
  // 但要打印**资产实际有哪些片段**：历史上交付件用过 `Wave`（大写），
  // 渲染器只认小写 `wave`——只报"没有动画"会让人往错方向查。
  if (result && result.ok === false && typeof console !== 'undefined') {
    console.info('[vision] 进场招手没播成：', result.reason, '| 该资产的片段：', clipNamesOf())
  }
}

/** 当前资产里有哪些动画片段（进场招手失败时打印，便于判断是不是命名对不上） */
function clipNamesOf() {
  try {
    const stats = stageRef && typeof stageRef.stats === 'function' ? stageRef.stats() : null
    return (stats && stats.clips && stats.clips.join(',')) || '(读不到)'
  } catch (e) {
    return '(读不到)'
  }
}

/**
 * 开始待机动作。
 *
 * 待机驱动**骨骼动画**，口型写**形态键**——两条独立通道，互不覆盖，
 * 所以说话时底层的 `Idle` 循环不用停。
 * 但**一次性动作**（点头/招手）在说话时会跳过：嘴里在动、人还在点头，
 * 看着不像在听人说话。这个判断做在渲染层的待机控制器里（它才知道谁在播）。
 */
function startIdle() {
  if (!stageRef || typeof stageRef.startIdle !== 'function') return
  const result = stageRef.startIdle()
  if (!result || !result.ok) {
    if (typeof console !== 'undefined') {
      console.info('[vision] 待机动作没起起来：', (result && result.reason) || '未知原因')
    }
    return
  }
  if (!result.pool || !result.pool.length) {
    if (typeof console !== 'undefined') {
      console.info('[vision] 该资产没有可用的待机动作片段 | 片段：', clipNamesOf())
    }
  }
}

onMounted(() => {
  timer = setInterval(() => { seconds.value += 1 }, 1000)
  // #ifdef H5
  bootTick.value = 1
  // 首次用户手势里解锁音频：移动端 Safari 只认"手势内同步 play()"，
  // 桌面 Chrome 本就是 sticky activation，这一步无害。
  // 不这么做的话，"点了按钮 → SSE 异步回来的音频"在 Safari 上会被自动播放策略拦掉。
  if (typeof document !== 'undefined') {
    const unlock = () => {
      unlockH5Audio()
      document.removeEventListener('pointerdown', unlock)
      document.removeEventListener('keydown', unlock)
    }
    document.addEventListener('pointerdown', unlock, { passive: true })
    document.addEventListener('keydown', unlock)
  }
  const el = document.getElementById('blVisionStage')
  if (el) {
    try {
      stageRef = mountFaceStage(el, {
        onReady: onStageReady,
        onError: onStageError,
        onStatus: () => {},
      })
    } catch (e) {
      onStageError()
      return
    }
    // 通话中用**交付件**（vis_*/expr_* + 招手动画），不是捏脸页的编辑期件。
    // `frameMode: 'bust'` —— 通话页看**半身**（像视频通话那样），人物才够大。
    //   演进过程：只有头（用户："只有一个头"）→ 全身（用户："人太小"）→ **半身**。
    //   实测全身取景下人物只占画面高度约 53%；半身取景截"胯以上"，高度约占身高 60%，
    //   再配合 `fitMargin: 1.15`（捏脸页默认 2.2 太松）让人物撑满画面。
    // #ifdef H5
    // 调试钩子：渲染器的 stats 在模块闭包里，出错时（"待机到底有没有在触发"、
    // "招手为什么不播"）在控制台拿不到任何读数。挂到 window 上，
    // 端到端测试与线上排查都能直接读。**只在 H5**，不影响 App 端。
    if (typeof window !== 'undefined') window.__blStage = stageRef
    // #endif
    stageRef.load(gender.value, 'delivery', {
      // **全身取景**：需求是「头顶顶到黑板上沿、脚落在黑板底部」，
      // 那画面里就必须有脚 —— 原来的 bust（半身，截到胯）根本看不到腿。

      frameMode: 'body',
      fitMargin: 1.72,
      frameLiftY: 0,
    })
      .then(() => {
        // 皮肤偏油亮：只压**镜面反射**（不碰漫反射，所以不会把脸调暗）。
        // 为什么是 0.55：全身取景下扫出来的拐点——
        //   镜面×1.00 → 平均亮度 91.5，>200 的"油光面积" **11.7%**
        //   镜面×0.80 → 78.3，                       1.90%
        //   镜面×0.65 → 68.3，                       0.35% ← 断崖
        //   镜面×0.55 → ≈62（采用），                ≈0.32%
        //   镜面×0.40 → 51.6，                       0.28%（收益很小、脸明显变暗）
        if (typeof stageRef.setSpecular === 'function') stageRef.setSpecular(0.55)
        // 模型**就绪之后**才挥手：资产还没加载完就播会定格在第一帧（看起来更假）
        waveOnEntry()
        // 待机动作：起身先起 `Idle` 循环，然后不定时随机点头/转身/招手。
        // 放在 waveOnEntry 之后——招手是"接通时的招呼"，待机是之后的常态。
        startIdle()
      })
      .catch(() => onStageError())
  }
  // #endif

  // 接对话流：订阅"这一轮数字人说完"的完整数据（文字 + 音频 + 口型）。
  //
  // 为什么走 store 的订阅而不是在本页另起一条 SSE：
  // 仓库约定"家人端与老人端共用 `uni-app/api/` 那一层客户端"，
  // 而 `stores/chat.js` 已经把 SSE 解析、幂等、停止、重试都处理好了。
  // 在本页再写一套 = 两份实现，日后必然走偏。
  unsubscribeLive = onLiveTurn((payload) => {
    if (!payload) return
    // 记下这一轮的原始数据（诊断用：能回答"音频到底有没有到端侧"这个问题）
    lastTurnInfo = {
      text: payload.text || '',
      audioUrl: payload.audioUrl || '',
      cueCount: payload.cues ? payload.cues.length : 0,
      lipsyncSource: payload.lipsyncSource || '',
      at: Date.now(),
    }
    if (payload.text) caption.value = payload.text
    if (payload.audioUrl) {
      // 有音频：音频 + 口型一起起播（口型以音频时钟为基准）
      lastSpeechSource = 'audio+lipsync'
      playTurn(payload.audioUrl, payload.cues)
    } else if (payload.cues) {
      // 没有音频（后端没配 TTS）：只动嘴，用自有时钟 —— 比完全不动好，但要如实标注
      lastSpeechSource = 'lipsync-only'
      playLipsync(payload.cues)
    } else {
      lastSpeechSource = 'text-only'
    }
  })
})

// 形象变化（在「数字人形象」页切换）→ 这里跟着换模型。watch 优于快照，避免回页面看不到新形象。
// 换模型后要**重新起待机**：渲染层的 load() 会停掉待机（片段表变了），
// 不重起的话切完形象人物就静止不动了。
watch(gender, (g) => {
  if (!stageRef) return
  // 构图参数要跟首次加载一致：`load()` 的幂等判断也看 frameLiftY，
  // 少传一个就会在切形象时把人物位置还原。
  stageRef.load(g, 'delivery', { frameMode: 'body', fitMargin: 1.72, frameLiftY: 0 })
    .then(() => startIdle())
    .catch(() => onStageError())
})

onUnmounted(() => {
  if (timer) { clearInterval(timer); timer = null }
  if (unsubscribeLive) { unsubscribeLive(); unsubscribeLive = null }
  // 待机定时器必须先停：它会去碰 stageRef 里的骨骼，而下面就要把它拆掉了
  if (stageRef && typeof stageRef.stopIdle === 'function') stageRef.stopIdle()
  lipsync.stop()
  stopAudio()
  // #ifdef H5
  unmountFaceStage()
  stageRef = null
  // #endif
})

/**
 * 问一句，让数字人回答（真跑一轮对话流）。
 *
 * 这一句会走完整链路：SSE 流式文字 → 服务端合成音频 + 口型关键帧 →
 * 端侧一边上屏一边等齐音频与口型，然后**边说边动嘴**。
 */
function ask(text) {
  const question = String(text || '').trim()
  if (!question) return { ok: false, reason: '没有内容' }
  if (chat.streaming) return { ok: false, reason: '还在说上一句' }
  caption.value = '…'          // 先给个反馈，避免点了没反应
  lastSpeechSource = ''
  try {
    sendChat(question)
  } catch (error) {
    caption.value = '连不上，稍后再试'
    return { ok: false, reason: String(error && error.message ? error.message : error) }
  }
  return { ok: true, question, conversationId: chat.conversationId || DEFAULT_CONVERSATION_ID }
}

/**
 * 一键停止（产品红线：老人可随时停下）。
 * ⚠️ 页面上**不再有**独立按钮（原「停一下」已去掉）：这条红线现在由通话栏的「挂断」承担
 * —— 它卸载本页，onUnmounted 里 stopAudio + lipsync.stop 会把声音与口型全部停掉。
 * 这个函数保留给「打断」（pipeline 上的 VAD / 未来入口）与自动化验收（window.__blVisionStop）。
 */
function stopSpeaking() {
  stopAudio()
  lipsync.stop()
  if (chat.streaming) {
    try { stopChat() } catch (e) { void e }
  }
}

/** 输入框里的问题提交流程（点按钮或回车都走这里）。 */
function askNow() {
  const result = ask(question.value)
  if (result && result.ok) question.value = ''
  else if (result && result.reason) uni.showToast({ title: result.reason, icon: 'none' })
}

/**
 * 播放"一整轮说话"：音频 + 口型一起（对话流收到 audio / lipsync 事件后调用）。
 *
 * 顺序很关键：先 `audio` 后 `lipsync`（服务端按这个顺序发），
 * 端侧攒齐两者再一起起播 —— 这样口型与音频**从一开始就对齐**。
 */
function playTurn(audioUrl, cues) {
  return playSpeech(audioUrl, cues || [], 0)
}

/** 只播口型（没有音频时；用自有时钟，会与真实语音不同步但比不动好）。 */
function playLipsync(cues) {
  if (!cues || !cues.length) return { ok: false, reason: '没有口型关键帧' }
  return lipsync.start(cues)
}

// 自动化验收入口：H5 下把播放函数挂到 window，
// 便于"无头浏览器给一段 cues → 看形态键是否真的动了"（渲染出的画面截图抓不到 WebGL）。
// #ifdef H5
if (typeof window !== 'undefined') {
  window.__blVisionPlayLipsync = playLipsync
  // 自动化验收：喂"音频 + 口型"一整轮（音频用后端给的签名 URL）
  window.__blVisionPlayTurn = playTurn
  // 自动化验收：真跑一轮对话流（问一句 → 服务端合成 → 端侧边说边动嘴）
  window.__blVisionAsk = ask
  window.__blVisionStop = stopSpeaking
  window.__blVisionStopAudio = stopAudio
  // 自动化验收：读"当前音频的真实播放状态"（位置/暂停/解码状态/错误）。
  // 为什么需要它：`uni` 那条封装读不到底层元素状态，而 H5 原生元素的状态
  // 才是"到底响了没有"的判据（旧验收只读 uni 的包装层，所以看不出静默失败）。
  window.__blVisionAudioState = () => {
    if (!audioContext) return null
    const el = audioContext._el || null
    return {
      src: String(audioContext.src || ''),
      pos: Number(audioContext.currentTime || 0),
      paused: 'paused' in audioContext ? !!audioContext.paused : null,
      readyState: el ? el.readyState : null,
      networkState: el ? el.networkState : null,
      volume: el ? el.volume : null,
      muted: el ? el.muted : null,
      mediaError: el && el.error ? { code: el.error.code, message: el.error.message } : null,
    }
  }
  // 行为探针：`__blVisionProbeStart()` → ask → `__blVisionProbeResult()`
  window.__blVisionProbeStart = probeStart
  window.__blVisionProbeResult = probeResult
  window.__blVisionAskStats = () => ({
    streaming: !!chat.streaming,
    caption: caption.value,
    lastSpeechSource,
    lastTurn: lastTurnInfo,
    audioError: lastAudioError,
    /** 音频的**真实播放情况**（时长/是否真的起播）—— "到底响了没有"看这里 */
    audio: audioInfo,
    lipsync: lipsync.stats(),
    morph: stageRef && typeof stageRef.morphWeights === 'function'
      ? stageRef.morphWeights(['vis_AA', 'vis_MBP', 'vis_I', 'vis_L', 'vis_silence'])
      : null,
    conversationId: chat.conversationId || '',
    messages: (chat.messages || []).length,
  })
  window.__blVisionLipsyncStats = () => Object.assign({}, lipsync.stats(), {
    frameCount: lipsyncFrameCount,
    lastFrame: lastLipsyncFrame,
    hasStage: !!stageRef,
    setVisemes: stageRef ? typeof stageRef.setVisemes : 'no-stage',
    audioError: lastAudioError,
  })
}
// #endif

function toggleMute() {
  muted.value = !muted.value
  uni.showToast({ title: muted.value ? '已静音' : '麦克风已开', icon: 'none' })
}
function toggleSpk() {
  spkOff.value = !spkOff.value
  uni.showToast({ title: spkOff.value ? '已关闭扬声器' : '扬声器已开', icon: 'none' })
}
function hangup() {
  const pages = getCurrentPages()
  if (pages.length > 1) uni.navigateBack()
  else uni.reLaunch({ url: '/pages/chat-detail/chat-detail' })
}
</script>

<script module="visionGl" lang="renderjs">
/**
 * App 端（app-vue）专用：renderjs 跑在视图层，是逻辑层唯一能碰到真 DOM / WebGL 的地方。
 * 与 face.vue 同一套做法（renderjs 在 H5 端也会被加载，故用编译期条件严格分叉，两端调同一个渲染器）。
 */
// #ifdef APP-PLUS
import { mountFaceStage, unmountFaceStage } from '../../common/face-gl/face-three.js'
import { DEFAULT_GENDER } from '../../common/face-gl/assets.js'
// #endif

export default {
  data() {
    // 字段名避开 stage：与 <script setup> 暴露的 stage 同名会被 Vue 拦下。
    return { gl: null, waved: false }
  },
  mounted(ownerInstance) {
    // #ifdef APP-PLUS
    this.bootStage(ownerInstance, ownerInstance.getState() || {})
    // #endif
  },
  beforeDestroy() {
    // #ifdef APP-PLUS
    unmountFaceStage()
    this.gl = null
    // #endif
  },
  methods: {
    // #ifdef APP-PLUS
    bootStage(ownerInstance, state) {
      const el = this.$el
      if (!el) return
      if (!this.gl) {
        this.gl = mountFaceStage(el, {
          onReady: () => ownerInstance.callMethod('onStageReady'),
          onError: () => ownerInstance.callMethod('onStageError'),
          onStatus: () => {},
        })
      }
      const g = state.gender || DEFAULT_GENDER
      this.gl.load(g, 'delivery', { frameMode: 'body', fitMargin: 1.72, frameLiftY: 0 }).then(() => {
        if (typeof this.gl.setSpecular === 'function') this.gl.setSpecular(0.55)
        // 进场招手只播一次：切性别会重载模型，但**不该再挥一次**（与 H5 同口径）
        if (!this.waved) {
          this.waved = true
          this.gl.playAnimation('wave', { loop: false })
        }
      }).catch(() => ownerInstance.callMethod('onStageError'))
    },
    onBoot(value, oldValue, ownerInstance) {
      this.bootStage(ownerInstance, ownerInstance.getState() || {})
    },
    onGender(value, oldValue, ownerInstance) {
      if (!this.gl) return this.bootStage(ownerInstance, ownerInstance.getState() || {})
      this.gl.load(value, 'delivery', { frameMode: 'body', fitMargin: 1.72, frameLiftY: 0 }).catch(() => ownerInstance.callMethod('onStageError'))
    },
    // #endif

    // #ifndef APP-PLUS
    /** H5 端 renderjs 也会执行，保留同名空方法接住 :change: 派发；舞台由 <script setup> 独占。 */
    bootStage() {},
    onBoot() {},
    onGender() {},
    // #endif
  },
}
</script>

<style scoped>
.bl-vision {
  position: relative;
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  /* 教室墙面：上浅下深的暖白，靠窗一侧偏冷 */
  background: linear-gradient(180deg, #D9CFBD 0%, #C4B7A1 46%, #A79A83 100%);
  color: #FFFFFF;
  box-sizing: border-box;
}

/* ═══════════ 教室场景（纯 CSS）═══════════
   全部用 rpx 与百分比定位，不依赖外部图片；
   人物由 3D 画布画在上层（canvas 在 .bl-vision__stage 里，`position: relative`），
   所以这些元素天然在人物**后面**。 */
.bl-room {
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  bottom: 0;
  overflow: hidden;
  pointer-events: none;
}

/* 黑板：居中挂在墙上，人物正好站在它前面（像老师站在讲台前）。
   ⚠️ `top` 必须避开顶栏：顶栏（标签 + 计时）占到约 190rpx，
   黑板从 300rpx 起才不会被"AI 数字人通话"和计时压住。 */
.bl-room__board {
  position: absolute;
  left: 50%;
  top: calc(300rpx + env(safe-area-inset-top));
  transform: translateX(-50%);
  width: 660rpx;
  height: 660rpx;
  /* 深绿板面 + 一点高光，避免纯色看着像色块 */
  background:
    radial-gradient(120% 80% at 30% 18%, rgba(255, 255, 255, .08) 0%, rgba(255, 255, 255, 0) 60%),
    linear-gradient(180deg, #354F3F 0%, #2B4133 60%, #243528 100%);
  border: 16rpx solid #8A6A45;          /* 木框 */
  border-radius: 12rpx;
  box-shadow:
    inset 0 0 60rpx rgba(0, 0, 0, .35),
    0 14rpx 30rpx rgba(0, 0, 0, .22);
  box-sizing: border-box;
}
/* 粉笔字：几道淡白痕，暗示"写过字"，不写具体内容（写了会跟对话打架）。
   放在**左上方**：人物挡中间，右侧留给挂钟，左上最空。 */
.bl-room__chalk {
  position: absolute;
  left: 56rpx;
  top: 64rpx;
  width: 300rpx;
  height: 8rpx;
  border-radius: 4rpx;
  background: rgba(255, 255, 255, .22);
  box-shadow:
    0 46rpx 0 rgba(255, 255, 255, .16),
    0 92rpx 0 rgba(255, 255, 255, .13),
    0 138rpx 0 rgba(255, 255, 255, .10);
}
/* 粉笔槽：黑板下沿的一道木条 */
.bl-room__tray {
  position: absolute;
  left: 24rpx;
  right: 24rpx;
  bottom: -34rpx;
  height: 22rpx;
  border-radius: 6rpx;
  background: linear-gradient(180deg, #A07C51 0%, #7A5B39 100%);
  box-shadow: 0 6rpx 12rpx rgba(0, 0, 0, .25);
}

/* 墙上挂钟：靠右上，**在黑板之上**（原来 top 434rpx 掉到板面中间去了） */
.bl-room__clock {
  position: absolute;
  right: 46rpx;
  top: calc(122rpx + env(safe-area-inset-top));
  width: 104rpx;
  height: 104rpx;
  border-radius: 50%;
  background: radial-gradient(circle at 40% 35%, #FFFFFF 0%, #E8E2D6 70%, #CFC7B8 100%);
  border: 8rpx solid #6E5A42;
  box-shadow: 0 8rpx 16rpx rgba(0, 0, 0, .22);
  box-sizing: border-box;
}
.bl-room__clock-hand {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 4rpx;
  height: 32rpx;
  margin-left: -2rpx;
  margin-top: -32rpx;
  border-radius: 2rpx;
  background: #4A4038;
  transform-origin: 50% 100%;
  transform: rotate(38deg);
}
.bl-room__clock-hand--short {
  height: 22rpx;
  margin-top: -22rpx;
  width: 5rpx;
  transform: rotate(128deg);
}

/* 窗户：**只从左边露出一条**（负 left 把它推出画面外）。
   ⚠️ 不能让它压到左上角的顶栏：那里有"AI 数字人通话"标签和计时，
   所以 `top` 从 250rpx 起、宽度也只露一条。 */
.bl-room__window {
  position: absolute;
  left: -230rpx;
  top: calc(250rpx + env(safe-area-inset-top));
  width: 300rpx;
  height: 460rpx;
  background: linear-gradient(180deg, #BFDCEA 0%, #DCEAF0 55%, #EAF1F2 100%);
  border: 14rpx solid #F1ECE2;
  border-radius: 10rpx;
  box-shadow:
    0 0 80rpx rgba(214, 236, 246, .55),   /* 窗光外溢 */
    0 12rpx 26rpx rgba(0, 0, 0, .18);
  box-sizing: border-box;
}
.bl-room__mullion-v {
  position: absolute;
  left: 50%;
  top: 0;
  bottom: 0;
  width: 12rpx;
  margin-left: -6rpx;
  background: #F1ECE2;
}
.bl-room__mullion-h {
  position: absolute;
  left: 0;
  right: 0;
  top: 52%;
  height: 12rpx;
  margin-top: -6rpx;
  background: #F1ECE2;
}

/* 课桌：画面下沿一道木色桌面，把"教室"落到实处（也给底部 UI 一个视觉依托） */
.bl-room__desk {
  position: absolute;
  left: -4%;
  right: -4%;
  bottom: 0;
  height: 190rpx;
  background: linear-gradient(180deg, #B98B57 0%, #96683C 40%, #7A5330 100%);
  border-top: 8rpx solid #D8B183;
  box-shadow: 0 -10rpx 30rpx rgba(0, 0, 0, .25);
}

.bl-vision__topbar {
  position: relative;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 32rpx;
  padding-top: calc(68rpx + env(safe-area-inset-top));
}
.bl-vision__topbar-left { min-width: 0; }
/* 「AI 数字人通话」与「本形象为 AI 数字人」并排同一行 */
.bl-vision__topbar-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12rpx;
}
.bl-vision__tag {
  display: inline-flex;
  align-items: center;
  background-color: rgba(7, 193, 96, .92);
  padding: 12rpx 20rpx;
  border-radius: var(--bl-radius-pill);

}
.bl-vision__tag-text {
  font-size: 24rpx;
  font-weight: 600;
  color: #FFFFFF;
}
.bl-vision__timer {
  display: block;
  font-size: 30rpx;
  font-weight: 600;
  color: #FFFFFF;
  margin-top: 16rpx;
}

/* AI 标识：常驻、**紧贴顶部**（原来是 `margin-top: -8rpx` 贴在顶栏下沿、
   浮在人物额头位置，把脸挡住了一部分）。
   位置提前之后既醒目又不挡人；`pointer-events: none` 让它不吃点击。 */
.bl-vision__aibadge {
  position: relative;
  /* 并排后不再需要 align-self / 负 margin —— 由 .bl-vision__topbar-row 统一对齐 */
  background-color: rgba(0, 0, 0, .45);
  border-radius: var(--bl-radius-pill);
  padding: 8rpx 24rpx;

  pointer-events: none;
}
.bl-vision__aibadge-text {
  font-size: 22rpx;
  color: rgba(255, 255, 255, .92);
}

/* 真 3D 数字人舞台：占住中部、铺满宽度。
   `position: relative` 是必须的——渲染器把画布绝对定位铺满宿主，
   宿主没有定位上下文时画布会相对更外层定位、盖住整屏 UI。
   `min-height` 刻意取小：通话页是"100vh 竖向 flex + 底部按钮"，
   舞台的最小高加上 topbar/caption/按钮会超过一屏、把按钮顶出视口（实测总高 816 > 485）。 */
.bl-vision__stage {
  position: relative;
  flex: 1 1 auto;
  min-height: 300rpx;
  width: 100%;
  overflow: hidden;
}

/* 降级态（WebGL 不可用或资产加载失败）才用的 CSS 假人 */
.bl-vision__person {
  position: absolute;
  left: 50%;
  bottom: 0;
  transform: translateX(-50%);
  width: 500rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.bl-vision__head {
  width: 216rpx;
  height: 216rpx;
  border-radius: 50%;
  background: linear-gradient(180deg, #E7B78F 0%, #D9A375 100%);
  box-shadow: inset 0 -12rpx 24rpx rgba(0, 0, 0, .12);
}
.bl-vision__torso {
  width: 460rpx;
  height: 300rpx;
  margin-top: -28rpx;
  border-radius: 120rpx 120rpx 0 0;
  background: linear-gradient(180deg, #F2EDE4 0%, #DCD5C9 100%);
}

.bl-vision__caption {
  position: relative;
  margin: 0 32rpx;
  background-color: rgba(0, 0, 0, .55);
  border-radius: var(--bl-radius-bubble);
  padding: 24rpx 32rpx;
}
.bl-vision__caption-text {
  font-size: var(--bl-font-body);
  line-height: 1.5;
  color: #FFFFFF;
  text-align: center;
}


/* 问一句：输入框 + 提交（这一条走真对话流，数字人会边说边动嘴） */
.bl-vision__ask {
  position: relative;
  display: flex;
  align-items: center;
  gap: 16rpx;
  margin-top: 16rpx;
  padding: 0 32rpx;
}
.bl-vision__ask-input {
  flex: 1;
  height: 88rpx;
  padding: 0 28rpx;
  border-radius: var(--bl-radius-pill);
  background-color: rgba(255, 255, 255, .92);
  color: #1F2A24;
  font-size: 30rpx;
}
.bl-vision__ask-ph { color: #8B968F; }
.bl-vision__ask-btn {
  flex: none;
  min-width: 176rpx;
  height: 88rpx;
  padding: 0 28rpx;
  border-radius: var(--bl-radius-pill);
  background-color: var(--bl-primary);
  display: flex;
  align-items: center;
  justify-content: center;
}
.bl-vision__ask-btn:active { background-color: var(--bl-primary-pressed); }
.bl-vision__ask-btn.is-busy { background-color: rgba(255, 255, 255, .3); }
.bl-vision__ask-btn-text {
  font-size: 30rpx;
  font-weight: 600;
  color: #FFFFFF;
}

.bl-vision__controls {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 72rpx;
  padding: 40rpx 0;
  padding-bottom: calc(48rpx + env(safe-area-inset-bottom));
}
.bl-call-btn {
  width: 120rpx;
  height: 120rpx;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: rgba(255, 255, 255, .22);
}
.bl-call-btn:active { background-color: rgba(255, 255, 255, .35); }
.bl-call-btn.is-off { background-color: rgba(255, 255, 255, .55); }
.bl-call-btn--hangup { background-color: var(--bl-danger); }
.bl-call-btn--hangup:active { background-color: #96302A; }
</style>
