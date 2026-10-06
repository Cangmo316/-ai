<template>
  <view class="bl-vision" :class="{ 'bl-large': settings.largeFont }">
    <view class="bl-vision__lamp" />
    <view class="bl-vision__plant" />

    <view class="bl-vision__topbar">
      <view>
        <view class="bl-vision__tag">
          <text class="bl-vision__tag-text">AI 数字人通话</text>
        </view>
        <text class="bl-vision__timer">通话中 {{ clock }}</text>
      </view>
      <view class="bl-vision__selfview">
        <bl-icon name="person" color="#FFFFFF" :size="88" />
      </view>
    </view>

    <!-- AI 标识常驻（产品红线：不冒充真人）。数字人换成了真 3D 交付件后，
         这行提示比原来更要紧——它明确告诉老人"对面不是真人实时画面"。 -->
    <view class="bl-vision__aibadge">
      <text class="bl-vision__aibadge-text">{{ UI_COPY.aiBadge }}</text>
    </view>

    <!-- 真 3D 数字人（交付件：vis_* / expr_* 口型表情 + `wave` 招手动画）。
         App 端由 renderjs 模块 visionGl 接管；H5 端由本文件 onMounted 接管。
         两条路径都调用 common/face-gl/face-three.js 的同一个渲染器。 -->
    <view
      class="bl-vision__stage"
      id="blVisionStage"
      :gender="gender"
      :boot="bootTick"
      :playing="waveToken"
      :change:gender="visionGl.onGender"
      :change:boot="visionGl.onBoot"
      :change:playing="visionGl.onPlaying"
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

    <!-- 招手互动：老人主动点一下，数字人就招手。放在通话按钮上方、按钮更大更好按。 -->
    <view class="bl-vision__wave">
      <view class="bl-wave-btn" :class="{ 'is-busy': waving }" @click="wave">
        <bl-icon name="person" color="#FFFFFF" :size="52" />
        <text class="bl-wave-btn__text">{{ waving ? '招手打招呼…' : '让 TA 招手' }}</text>
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
// 口型驱动：把 SSE `lipsync` 事件的关键帧变成逐帧的 viseme 权重。
// 「渲染器只管把权重写进形态键」，插值 / 交叉淡化 / 最多混 2 个 的规则都在这个模块里。
import { createLipsyncPlayer } from '@/common/face-gl/lipsync.js'// #ifdef H5
import { mountFaceStage, unmountFaceStage } from '@/common/face-gl/face-three.js'
// #endif

// 数字人形象性别：**跟着全局设置走**（在「数字人形象」页切了性别，这里要跟着换）。
// 用 computed 而不是快照，这样用户在别处改了 `settings.gender`、回到这里能自动生效。
const gender = computed(() => settings.gender || DEFAULT_GENDER)
const stage = ref({ fallback: false })
const bootTick = ref(0)
const waveToken = ref(0)
const waving = ref(false)
let stageRef = null
let waveTimer = null

/**
 * 口型播放器：把「服务端给的关键帧」变成逐帧的 viseme 权重，交给渲染器写形态键。
 *
 * 时钟是**自建的** `performance.now()`（`lipsync.js` 内部），不是音频时钟 ——
 * 因为当前还没有音频（后端暂无 TTS）。真 TTS 就绪后要改成"以音频播放时刻为基准"，
 * 否则音画会漂移；届时只需给 `player.start(cues, audioStartMs)` 传音频基准。
 */
const lipsync = createLipsyncPlayer({
  fps: 30,
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
 * ⚠️ 端侧时钟的关键：有音频时口型要**跟着音频走**，不能用 `performance.now()` 自由跑
 * ——否则音画必然漂移（网络抖动、缓冲都会让两者错开，且误差会累积）。
 * 这里用 `onTimeUpdate` 把音频的当前播放位置喂给驱动层做**校准**，
 * 帧与帧之间仍由 30fps 的自有时钟平滑推进（`onTimeUpdate` 回调粒度粗，不能直接驱动 30fps）。
 */
let audioContext = null
let audioTimer = null

function stopAudio() {
  if (audioTimer) { clearInterval(audioTimer); audioTimer = null }
  if (audioContext) {
    try { audioContext.stop() } catch (e) { void e }
    try { audioContext.destroy() } catch (e) { void e }
    audioContext = null
  }
}

/**
 * 播放一段合成音频，并让口型以音频时钟为基准。
 *
 * @param {string} url      服务端给的签名地址（相对路径）
 * @param {Array}  cues     同一轮的口型关键帧
 * @param {number} baseMs   音频在服务端时间轴上的起点（当前恒为 0：
 *                          `lipsync` 的 `b` 就是从音频开头算的）
 */
function playSpeech(url, cues, baseMs) {
  if (!url) return { ok: false, reason: '没有音频地址' }
  stopAudio()
  // 相对路径要拼成绝对地址：dev 是 5173、真机是后端地址，故用 API base（与 SSE 同源）
  const absolute = /^https?:/i.test(url) ? url : resolveApiUrl(url)
  try {
    // #ifdef H5 || APP-PLUS
    audioContext = uni.createInnerAudioContext()
    // #endif
  } catch (e) {
    audioContext = null
  }
  if (!audioContext) return { ok: false, reason: '当前环境没有音频上下文' }

  audioContext.src = absolute
  // 口型**先用自有时钟起跑**（等音频真正开始播再校准）：这样网络慢时嘴也不会干等
  const started = lipsync.start(cues)
  audioContext.onPlay(() => {
    // 音频真的开始播了 —— 把驱动层的时间基准对齐到"此刻"
    lipsync.resync()
    // 之后按 `onTimeUpdate` 的音频位置持续校准
    if (audioTimer) clearInterval(audioTimer)
    audioTimer = setInterval(() => {
      if (!audioContext) return
      // `currentTime` 单位秒 → 毫秒；这是音频的真实播放位置
      const ms = Math.max(0, Number(audioContext.currentTime || 0) * 1000) + (baseMs || 0)
      lipsync.resync(ms)
    }, 100)
  })
  audioContext.onEnded(() => { stopAudio() })
  audioContext.onError(() => {
    // 音频失败不该静默：口型退回自有时钟继续跑完，并记一条状态
    lastAudioError = 'audio error'
    stopAudio()
  })
  audioContext.play()
  return { ok: true, url: absolute, lipsync: started }
}
let lastAudioError = ''

/** 把服务端给的**相对**签名地址拼成绝对地址（dev 是 5173/8787、真机是内网地址）。 */
function resolveApiUrl(url) {
  const text = String(url || '')
  if (/^https?:/i.test(text)) return text
  let base = ''
  try { base = getBaseURL() } catch (e) { base = '' }
  return (base || '').replace(/\/+$/, '') + '/' + text.replace(/^\/+/, '')
}

const caption = ref('妈，今天药按时吃了没')

const seconds = ref(42)
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

/** 招手：播放交付件里的 `wave` 片段。用 token 递增触发 renderjs 的 :change 派发。 */
function wave() {
  if (waving.value) return
  waving.value = true
  waveToken.value += 1
  if (waveTimer) clearTimeout(waveTimer)
  // 动画 2.6s（78 帧 @30fps），留一点余量再复位按钮
  waveTimer = setTimeout(() => { waving.value = false }, 3000)
  if (stageRef && typeof stageRef.playAnimation === 'function') {
    const r = stageRef.playAnimation('wave', { loop: false })
    if (r && r.ok === false) {
      waving.value = false
      uni.showToast({ title: '这个形象还没有招手动作', icon: 'none' })
    }
  }
}

onMounted(() => {
  timer = setInterval(() => { seconds.value += 1 }, 1000)
  // #ifdef H5
  bootTick.value = 1
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
    stageRef.load(gender.value, 'delivery', { frameMode: 'bust', fitMargin: 1.15 })
      .then(() => {
        // 皮肤偏油亮：只压**镜面反射**（不碰漫反射，所以不会把脸调暗）。
        // 为什么是 0.55：全身取景下扫出来的拐点——
        //   镜面×1.00 → 平均亮度 91.5，>200 的"油光面积" **11.7%**
        //   镜面×0.80 → 78.3，                       1.90%
        //   镜面×0.65 → 68.3，                       0.35% ← 断崖
        //   镜面×0.55 → ≈62（采用），                ≈0.32%
        //   镜面×0.40 → 51.6，                       0.28%（收益很小、脸明显变暗）
        if (typeof stageRef.setSpecular === 'function') stageRef.setSpecular(0.55)
      })
      .catch(() => onStageError())
  }
  // #endif
})

// 形象性别变化（在「数字人形象」页切换）→ 这里跟着换模型。watch 优于快照，避免回页面看不到新形象。
watch(gender, (g) => {
  if (stageRef) stageRef.load(g, 'delivery', { frameMode: 'bust', fitMargin: 1.15 }).catch(() => onStageError())
})

onUnmounted(() => {
  if (timer) { clearInterval(timer); timer = null }
  if (waveTimer) { clearTimeout(waveTimer); waveTimer = null }
  lipsync.stop()
  stopAudio()
  // #ifdef H5
  unmountFaceStage()
  stageRef = null
  // #endif
})

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
  window.__blVisionStopAudio = stopAudio
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
    return { gl: null }
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
      this.gl.load(g, 'delivery', { frameMode: 'bust', fitMargin: 1.15 }).then(() => {
        if (typeof this.gl.setSpecular === 'function') this.gl.setSpecular(0.55)
      }).catch(() => ownerInstance.callMethod('onStageError'))
    },
    onBoot(value, oldValue, ownerInstance) {
      this.bootStage(ownerInstance, ownerInstance.getState() || {})
    },
    onGender(value, oldValue, ownerInstance) {
      if (!this.gl) return this.bootStage(ownerInstance, ownerInstance.getState() || {})
      this.gl.load(value, 'delivery', { frameMode: 'bust', fitMargin: 1.15 }).catch(() => ownerInstance.callMethod('onStageError'))
    },
    /** 招手：token 每次递增就播一次（不循环），播完停在静止姿势。 */
    onPlaying(value, oldValue, ownerInstance) {
      if (!value || value === oldValue) return
      if (!this.gl) return this.bootStage(ownerInstance, ownerInstance.getState() || {})
      this.gl.playAnimation('wave', { loop: false })
    },
    // #endif

    // #ifndef APP-PLUS
    /** H5 端 renderjs 也会执行，保留同名空方法接住 :change: 派发；舞台由 <script setup> 独占。 */
    bootStage() {},
    onBoot() {},
    onGender() {},
    onPlaying() {},
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
  background: linear-gradient(170deg, #6E5B4A 0%, #3E332A 55%, #241E18 100%);
  color: #FFFFFF;
  box-sizing: border-box;
}

/* 房间氛围：暖色落地灯光 + 虚化的绿植 */
.bl-vision__lamp {
  position: absolute;
  left: 68rpx;
  top: 120rpx;
  width: 300rpx;
  height: 300rpx;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(255, 214, 150, .55) 0%, rgba(255, 190, 110, 0) 70%);
}
.bl-vision__plant {
  position: absolute;
  right: -40rpx;
  bottom: 300rpx;
  width: 260rpx;
  height: 420rpx;
  border-radius: 50% 50% 20% 20%;
  background: radial-gradient(circle at 40% 30%, #4E7A4A 0%, #2F4A2D 70%);
  opacity: .5;
}

.bl-vision__topbar {
  position: relative;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 32rpx;
  padding-top: calc(68rpx + env(safe-area-inset-top));
}
.bl-vision__tag {
  display: inline-flex;
  align-items: center;
  background-color: rgba(7, 193, 96, .92);
  padding: 12rpx 20rpx;
  border-radius: var(--bl-radius-pill);
  align-self: flex-start;
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
  margin-top: 16rpx;
}
.bl-vision__selfview {
  width: 184rpx;
  height: 248rpx;
  flex: none;
  border-radius: var(--bl-radius-bubble);
  border: 4rpx solid rgba(255, 255, 255, .7);
  background: linear-gradient(180deg, #8A9AA8 0%, #5D6B78 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

/* AI 标识：常驻、不遮挡数字人（放顶部条下方居中） */
.bl-vision__aibadge {
  position: relative;
  align-self: center;
  background-color: rgba(0, 0, 0, .45);
  border-radius: var(--bl-radius-pill);
  padding: 8rpx 24rpx;
  margin-top: -8rpx;
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

/* 招手互动按钮：比通话按钮更宽、更好按（适老） */
.bl-vision__wave {
  position: relative;
  display: flex;
  justify-content: center;
  margin-top: 24rpx;
}
.bl-wave-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16rpx;
  min-width: 420rpx;
  min-height: 96rpx;
  padding: 20rpx 40rpx;
  border-radius: var(--bl-radius-pill);
  background-color: rgba(7, 193, 96, .92);
}
.bl-wave-btn:active { background-color: rgba(6, 170, 84, .95); }
.bl-wave-btn.is-busy { background-color: rgba(255, 255, 255, .3); }
.bl-wave-btn__text {
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
.bl-call-btn--hangup { background-color: #E64340; }
.bl-call-btn--hangup:active { background-color: #C93A37; }
</style>
