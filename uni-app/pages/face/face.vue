<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar title="数字人形象" back solid @back="back" />

    <view class="bl-face-page">
      <view class="bl-face-preview">
        <view class="bl-face-preview__badge">
          <text class="bl-face-preview__badge-text">{{ stageBadge }}</text>
        </view>

        <!-- 产品红线（规格书 §7.4）：AI 标识常驻，不可关闭 -->
        <view class="bl-face-preview__aibadge">
          <text class="bl-face-preview__aibadge-main">{{ UI_COPY.aiBadge }}</text>
          <text class="bl-face-preview__aibadge-sub">{{ UI_COPY.aiBadgeDetail }}</text>
        </view>

        <!-- 真 3D 舞台（规格书 §478 方案 A：只做端侧实时渲染，不做云渲染、不做接口预留）。
             App 端由 renderjs 模块 faceGl 接管；H5 端由本文件 onMounted 直接接管。
             两条路径都调用 common/face-gl/face-three.js 的同一个渲染器，不会各写一套。 -->
        <view
          class="bl-face-stage"
          id="blFaceStage"
          :gender="gender"
          :payload="payload"
          :boot="bootTick"
          :change:gender="faceGl.onGender"
          :change:payload="faceGl.onPayload"
          :change:boot="faceGl.onBoot"
        >
          <!-- 降级态：仅当 WebGL 不可用或模型加载失败时出现，用来兜住「白屏」而不是当主预览 -->
          <view v-if="stage.fallback" class="bl-face-stage__fallback">
            <view class="bl-face-model">
              <view class="bl-face__head" :style="headStyle">
                <view class="bl-face__hair" :style="hairStyle" />
                <view class="bl-face__eyes" :style="eyesStyle">
                  <view class="bl-face__eye" :style="eyeDotStyle" />
                  <view class="bl-face__eye" :style="eyeDotStyle" />
                </view>
                <view class="bl-face__mouth" :style="mouthStyle" />
              </view>
              <view class="bl-face__torso" :style="torsoStyle" />
            </view>
          </view>
        </view>

        <text class="bl-face-preview__hint">{{ stageHint }}</text>
      </view>

      <view class="bl-face-gender">
        <text class="bl-face-gender__label">形象</text>
        <view class="bl-face-gender__group">
          <view
            v-for="g in GENDER_OPTIONS"
            :key="g.value"
            class="bl-face-gender__item"
            :class="{ 'bl-face-gender__item--on': gender === g.value }"
            @click="switchGender(g.value)"
          >
            <text
              class="bl-face-gender__text"
              :class="{ 'bl-face-gender__text--on': gender === g.value }"
            >{{ g.label }}</text>
          </view>
        </view>
      </view>

      <scroll-view class="bl-face-controls" scroll-y>
        <view v-for="p in SLIDERS" :key="p.key" class="bl-face-controls__row">
          <bl-slider
            :name="p.name"
            :value="values[p.key]"
            :min="p.uMin"
            :max="p.uMax"
            :step="p.step"
            @update:value="onParam(p.key, $event)"
          />
        </view>
      </scroll-view>

      <view class="bl-face-actions">
        <view class="bl-btn bl-btn--ghost bl-face-actions__btn" @click="randomize">
          <bl-icon name="shuffle" color="#07C160" :size="36" />
          <text class="bl-face-actions__text bl-face-actions__text--ghost">随机生成</text>
        </view>
        <view class="bl-btn bl-btn--primary bl-face-actions__btn" @click="save">
          <bl-icon name="save" color="#FFFFFF" :size="36" />
          <text class="bl-face-actions__text bl-face-actions__text--on">保存形象</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
import { reactive, computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { settings } from '@/common/store.js'
import {
  SLIDERS, UI_COPY, SLIDER_KEYS, defaultValues, computeView, randomValues, buildSave,
} from '@/common/face/face-index.js'
// 资产路径与性别选项是纯数据（不 import three.js），任何端都能安全引
import { GENDER_OPTIONS, DEFAULT_GENDER, genderLabel } from '@/common/face-gl/assets.js'

// H5 端 renderjs 不接管（renderjs 只在 App 端跑），由本文件直接操作 DOM。
// 条件编译：App 端不会把 three.js 打进逻辑层包体。
// #ifdef H5
import { mountFaceStage, unmountFaceStage } from '@/common/face-gl/face-three.js'
// #endif

/**
 * 滑杆值（UI 整数）。双向参数 -100~100，单向参数 0~100。
 * 首批 3 条最小闭环：脸宽 / 眼睛大小 / 年龄感，三条均被康养裁剪判定为「保留」。
 * 滑杆元数据（名称 / 区间 / 步长）全部来自参数表，页面不再自己维护一份。
 */
const values = reactive(defaultValues())

function onParam(key, value) {
  values[key] = value
}

/**
 * 一次算全：UI 值 → 参数 → 四通道指令 → 形态键权重。
 * keys 必须显式传 SLIDER_KEYS：逻辑层按「驱动的参数」过滤告警，
 * 不传会把整表 102 条的缺失提示一起放出来。
 */
const view = computed(() => computeView(values, { keys: SLIDER_KEYS }))
/** 形态键权重（name → 0~1），3D 渲染器直接消费它。 */
const weights = computed(() => view.value.weights)

/** 当前形象性别。默认女性，可切男性（交付 README：捏脸页默认形象 = 女性）。 */
const gender = ref(DEFAULT_GENDER)

/** 宿主 → renderjs 的唯一数据通道（App 端 renderjs 拿不到逻辑层对象，只能靠 prop 下发）。 */
const payload = computed(() => JSON.stringify({ weights: weights.value }))
/** 首帧兜底：renderjs 的 mounted 里 getState() 在个别版本拿不到 setup 数据，靠这个 tick 补一次。 */
const bootTick = ref(0)

/** 3D 舞台运行态。fallback=true 才显示 CSS 示意图。 */
const stage = reactive({ ready: false, fallback: false, note: '' })

const stageBadge = computed(() => {
  if (stage.fallback) return '示意图预览'
  return stage.ready ? '3D 实时预览 · 可旋转' : '预览准备中…'
})
const stageHint = computed(() => {
  if (stage.fallback) return '当前环境不支持 3D 预览，以下为示意图'
  if (!stage.ready) return stage.note || '正在准备 3D 预览…'
  return '左右拖动可旋转视角'
})

/* ------------------------- 降级态外观（仅 error 时可见） ------------------------- */
/** 净驱动量：faceWidth / eyeSize ∈ [-1,1]，age ∈ [0,1]。 */
function drivers() {
  return view.value.drivers
}

const headStyle = computed(() => {
  const v = drivers()
  const width = 176 + v.faceWidth * 22
  const height = 208 + v.faceWidth * 18
  const radius = v.faceWidth > 0.1 ? '48% 48% 46% 46%' : '44% 44% 42% 42%'
  const hue = 26
  const sat = 38 + v.age * 12
  const light = 72 - v.age * 8
  return {
    width: width + 'rpx',
    height: height + 'rpx',
    borderRadius: radius,
    background: 'linear-gradient(180deg, hsl(' + hue + ', ' + sat + '%, ' + light + '%) 0%, hsl(' + hue + ', ' + sat + '%, ' + (light - 8) + '%) 100%)'
  }
})

const hairStyle = computed(() => {
  const v = drivers()
  const gray = Math.min(90, v.age * 90)
  return {
    height: '94rpx',
    background: 'hsl(30, ' + Math.max(6, 26 - gray / 5) + '%, ' + (16 + gray / 1.6) + '%)'
  }
})

const eyesStyle = computed(() => ({
  gap: '46rpx'
}))

/** 眼睛大小滑杆驱动瞳孔尺寸（间距由 eye_spacing 参数控制，未在首批滑杆内）。 */
const eyeDotStyle = computed(() => {
  const s = 1 + drivers().eyeSize * 0.55
  return { transform: 'scale(' + s + ')' }
})

/** 嘴角纹随年龄加深（嘴型由嘴部参数控制，未在首批滑杆内）。 */
const mouthStyle = computed(() => {
  const v = drivers()
  return {
    width: (26 + v.age * 14) + 'rpx',
    opacity: 0.55 + v.age * 0.3
  }
})

/** 服装由造型参数控制（未在首批滑杆内），此处给中性底色。 */
const torsoStyle = computed(() => ({
  background: 'linear-gradient(180deg, hsl(220, 42%, 68%) 0%, hsl(220, 38%, 58%) 100%)'
}))

/* ------------------------------ 3D 舞台接线 ------------------------------ */

/** H5 端的舞台句柄；App 端恒为 null（renderjs 在视图层持有）。 */
let stageRef = null

/** renderjs（视图层）回调进来的入口，必须 defineExpose 才允许 ownerInstance.callMethod 命中。 */
function onStageReady() {
  stage.ready = true
  stage.fallback = false
  stage.note = ''
}
function onStageError() {
  stage.ready = false
  stage.fallback = true
  stage.note = ''
}
function onStageStatus(payloadArg) {
  if (!stage.ready && payloadArg && payloadArg.note) stage.note = payloadArg.note
}
defineExpose({ onStageReady, onStageError, onStageStatus })

// #ifdef H5
onMounted(() => {
  bootTick.value = 1
  const el = document.getElementById('blFaceStage')
  if (!el) return
  try {
    stageRef = mountFaceStage(el, {
      onReady: onStageReady,
      onError: onStageError,
      onStatus: (note) => { stage.note = note },
    })
  } catch (e) {
    onStageError()
    return
  }
  stageRef.load(gender.value).catch(() => onStageError())
})

onUnmounted(() => {
  unmountFaceStage()
  stageRef = null
})

// 滑杆 → 30Hz 节流写权重（规格书 §7.3）
watch(weights, (w) => {
  if (stageRef) stageRef.applyWeightsThrottled(w)
})

// 性别切换 → 换一份 .glb（同一个舞台，只换模型）
watch(gender, (g) => {
  if (stageRef) stageRef.load(g).catch(() => onStageError())
})
// #endif

/* ------------------------------- 操作 ------------------------------- */
function switchGender(value) {
  if (value === gender.value) return
  if (!GENDER_OPTIONS.some((g) => g.value === value)) return
  gender.value = value
  uni.showToast({ title: '已切换为' + genderLabel(value) + '形象', icon: 'none' })
}

function randomize() {
  Object.assign(values, randomValues())
  uni.showToast({ title: '已随机生成一个新形象', icon: 'none' })
}

function save() {
  const built = buildSave(values, { name: '我的形象' })
  try {
    uni.setStorageSync('bl_face_active', JSON.stringify(built.preset))
    uni.setStorageSync('bl_face_gender', gender.value)
  } catch (e) {
    uni.showToast({ title: '保存失败，请重试', icon: 'none' })
    return
  }
  // 产品红线（§7.4）：保存成功后必须展示用途声明，文案统一取自 face-index
  uni.showModal({
    title: UI_COPY.saveTitle,
    content: UI_COPY.saveNotice,
    showCancel: false,
    confirmText: '知道了'
  })
}

function back() {
  const pages = getCurrentPages()
  if (pages.length > 1) uni.navigateBack()
  else uni.reLaunch({ url: '/pages/me/me' })
}
</script>

<script module="faceGl" lang="renderjs">
/**
 * App 端（app-vue）专用：renderjs 跑在视图层，是逻辑层唯一能碰到真 DOM / WebGL 的地方。
 *
 * 实测更正：renderjs 在 **H5 端同样会被加载并执行**，`:change:` 绑定也照常派发。
 * 若不拦住，renderjs 会和 <script setup> 里的 H5 挂载路径抢同一个舞台，
 * 并因「从 Options API 改 <script setup> 的绑定」抛
 * Vue warn: Cannot mutate <script setup> binding "stage" from Options API. + TypeError。
 * 因此本块用编译期条件（APP-PLUS）严格分叉：只有 App 端接管；H5 端保留同名空方法
 * 接住 :change: 派发（方法不能缺，缺了会报找不到方法）。两端调的是同一个渲染器。
 */
// #ifdef APP-PLUS
import { mountFaceStage, unmountFaceStage } from '@/common/face-gl/face-three.js'
import { DEFAULT_GENDER } from '@/common/face-gl/assets.js'
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
    /** 幂等挂载：mountFaceStage 内部有单例守卫，重复调用只会拿到同一个舞台。 */
    bootStage(ownerInstance, state) {
      const el = this.$el
      if (!el) return
      if (!this.gl) {
        this.gl = mountFaceStage(el, {
          onReady: () => ownerInstance.callMethod('onStageReady'),
          onError: () => ownerInstance.callMethod('onStageError'),
          onStatus: (note) => ownerInstance.callMethod('onStageStatus', { note }),
        })
      }
      const g = state.gender || DEFAULT_GENDER
      this.gl.load(g).catch(() => ownerInstance.callMethod('onStageError'))
      if (state.payload) {
        try { this.gl.applyPayload(JSON.parse(state.payload)) } catch (e) { void e }
      }
    },
    /** 首帧兜底：页面 onMounted 后递增 boot，保证这里一定会被调一次。 */
    onBoot(value, oldValue, ownerInstance) {
      this.bootStage(ownerInstance, ownerInstance.getState() || {})
    },
    onGender(value, oldValue, ownerInstance) {
      if (!this.gl) return this.bootStage(ownerInstance, ownerInstance.getState() || {})
      this.gl.load(value).catch(() => ownerInstance.callMethod('onStageError'))
    },
    onPayload(value, oldValue, ownerInstance) {
      if (!value) return
      if (!this.gl) return this.bootStage(ownerInstance, ownerInstance.getState() || {})
      try { this.gl.applyPayload(JSON.parse(value)) } catch (e) { void e }
    },
    // #endif

    // #ifndef APP-PLUS
    /** H5 端 renderjs 也会执行，保留同名空方法接住 :change: 派发；舞台由 <script setup> 独占。 */
    bootStage() {},
    onBoot() {},
    onGender() {},
    onPayload() {},
    // #endif
  },
}</script>

<style scoped>
.bl-face-page {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

/* 预览区 */
.bl-face-preview {
  flex: none;
  height: 536rpx;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: linear-gradient(180deg, #E8F7EF 0%, #D6F0E3 100%);
}
/* 3D 舞台铺满预览区；canvas 由渲染器自己塞进来 */
.bl-face-stage {
  position: absolute;
  left: 0;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 0;
}
.bl-face-stage__fallback {
  position: absolute;
  left: 0;
  top: 0;
  right: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
.bl-face-preview__badge {
  position: absolute;
  left: 24rpx;
  top: 24rpx;
  z-index: 2;
  pointer-events: none;
  background-color: rgba(255, 255, 255, .85);
  border-radius: var(--bl-radius-pill);
  padding: 8rpx 18rpx;
}
.bl-face-preview__badge-text {
  font-size: 22rpx;
  color: #1A1A1A;
}
.bl-face-preview__hint {
  position: absolute;
  bottom: 20rpx;
  z-index: 2;
  pointer-events: none;
  font-size: 22rpx;
  color: #6D8A7C;
}

.bl-face-model {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 32rpx;
}
.bl-face__head {
  position: relative;
  box-shadow: inset -16rpx 0 32rpx rgba(0, 0, 0, .07);
}
.bl-face__hair {
  position: absolute;
  top: -12rpx;
  left: -8rpx;
  right: -8rpx;
  border-radius: 50% 50% 30% 30%;
}
.bl-face__eyes {
  position: absolute;
  left: 0;
  right: 0;
  top: 44%;
  display: flex;
  align-items: center;
  justify-content: center;
}
.bl-face__eye {
  width: 16rpx;
  height: 16rpx;
  border-radius: 50%;
  background-color: #3B3128;
}
.bl-face__mouth {
  position: absolute;
  left: 50%;
  bottom: 24%;
  height: 6rpx;
  border-radius: 3rpx;
  background-color: #B9805C;
  transform: translateX(-50%);
}
.bl-face__torso {
  width: 312rpx;
  height: 168rpx;
  margin-top: -20rpx;
  border-radius: 92rpx 92rpx 0 0;
}

/* 性别切换 */
.bl-face-gender {
  flex: none;
  display: flex;
  align-items: center;
  padding: 20rpx 32rpx 4rpx;
}
.bl-face-gender__label {
  font-size: var(--bl-font-body);
  color: var(--bl-text-sub);
  margin-right: 20rpx;
}
.bl-face-gender__group {
  display: flex;
  background-color: #E4EAE6;
  border-radius: var(--bl-radius-pill);
  padding: 4rpx;
}
.bl-face-gender__item {
  padding: 10rpx 32rpx;
  border-radius: var(--bl-radius-pill);
}
.bl-face-gender__item--on {
  background-color: #FFFFFF;
}
.bl-face-gender__text {
  font-size: 26rpx;
  color: var(--bl-text-sub);
}
.bl-face-gender__text--on {
  color: #1A1A1A;
  font-weight: 600;
}

/* 参数区 */
.bl-face-controls {
  flex: 1;
  min-height: 0;
  padding: 24rpx 32rpx 0;
  box-sizing: border-box;
}
.bl-face-controls__row { margin-bottom: 24rpx; }

.bl-face-actions {
  flex: none;
  display: flex;
  gap: 24rpx;
  padding: 24rpx 32rpx;
  padding-bottom: calc(32rpx + env(safe-area-inset-bottom));
  background-color: var(--bl-bg);
}
.bl-face-actions__btn { flex: 1; gap: 12rpx; }
.bl-face-actions__text {
  font-size: var(--bl-font-body);
  font-weight: 600;
  margin-left: 12rpx;
}
.bl-face-actions__text--ghost { color: var(--bl-primary); }
.bl-face-actions__text--on { color: #FFFFFF; }
/* 产品红线（规格书 §7.4）：AI 标识常驻，不可关闭 */
.bl-face-preview__aibadge {
  position: absolute;
  right: 24rpx;
  top: 24rpx;
  z-index: 2;
  pointer-events: none;
  max-width: 360rpx;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  background-color: rgba(255, 255, 255, .88);
  border-radius: var(--bl-radius-pill);
  padding: 10rpx 18rpx;
}
.bl-face-preview__aibadge-main {
  font-size: 22rpx;
  font-weight: 600;
  color: #1A1A1A;
}
.bl-face-preview__aibadge-sub {
  font-size: 20rpx;
  color: #6D8A7C;
  margin-top: 2rpx;
}
</style>