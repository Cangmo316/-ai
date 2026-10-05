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


      <!-- 捏脸功能按策略变更**暂时下线**（数字人只做唇形同步 + 招手互动）。
           这里保留"正在开发中"提示而不是删掉整块 —— 页面仍然开放，
           因为用户需要一个**切换男女形象**的入口（这块是可用的）。
           将来接回捏脸只需把 FACE_EDIT_ENABLED 改回 true。 -->
      <view v-if="!FACE_EDIT_ENABLED" class="bl-face-soon">
        <bl-icon name="settings" color="#9AA6A0" :size="72" />
        <text class="bl-face-soon__title">{{ UI_COPY.faceDeveloping }}</text>
        <text class="bl-face-soon__desc">精细调整五官的功能还在做，先上线形象切换</text>
        <text class="bl-face-soon__desc">上面选「女性 / 男性」即可切换数字人形象</text>
      </view>
      <!-- 分区 chips：目录来自参数表 + 适老裁剪，「不做」的参数不会出现在这里 -->
      <scroll-view v-if="FACE_EDIT_ENABLED" class="bl-face-zones" scroll-x>
        <view class="bl-face-zones__inner">
          <view
            v-for="g in SLIDER_GROUPS"
            :key="g.zone"
            class="bl-face-zones__chip"
            :class="{ 'bl-face-zones__chip--on': g.zone === activeZone }"
            @click="switchZone(g.zone)"
          >
            <text
              class="bl-face-zones__text"
              :class="{ 'bl-face-zones__text--on': g.zone === activeZone }"
            >{{ g.name }}</text>
            <text
              class="bl-face-zones__count"
              :class="{ 'bl-face-zones__count--on': g.zone === activeZone }"
            >{{ g.count }}</text>
          </view>
        </view>
      </scroll-view>

      <view v-if="FACE_EDIT_ENABLED" class="bl-face-summary">
        <text class="bl-face-summary__text">{{ summaryText }}</text>
      </view>

      <scroll-view v-if="FACE_EDIT_ENABLED" class="bl-face-controls" scroll-y>
        <view v-for="p in activeGroup.sliders" :key="p.key" class="bl-face-controls__row">
          <view v-if="!p.wired" class="bl-face-controls__tag">
            <text class="bl-face-controls__tag-text">{{ p.pendingReason || '未接线' }}</text>
          </view>
          <bl-slider
            :name="p.name"
            :value="values[p.key]"
            :min="p.uMin"
            :max="p.uMax"
            :step="p.step"
            @update:value="onParam(p.key, $event)"
          />
        </view>
        <view class="bl-face-controls__zone-hint">
          <text class="bl-face-controls__zone-hint-text">{{ zoneHint }}</text>
        </view>
      </scroll-view>

      <view v-if="FACE_EDIT_ENABLED" class="bl-face-actions">
        <view class="bl-btn bl-btn--ghost bl-face-actions__btn" @click="randomize">
          <bl-icon name="shuffle" color="#07C160" :size="36" />
          <text class="bl-face-actions__text bl-face-actions__text--ghost">随机生成</text>
        </view>
        <view class="bl-btn bl-btn--primary bl-face-actions__btn" @click="save">
          <bl-icon name="save" color="#FFFFFF" :size="36" />
          <text class="bl-face-actions__text bl-face-actions__text--on">保存形象</text>
        </view>
      </view>

      <!-- 分区级操作：只动当前分区，避免"想微调一处却整套随机" -->
      <view v-if="FACE_EDIT_ENABLED" class="bl-face-subactions">
        <view class="bl-face-subactions__item" @click="randomizeZone">
          <text class="bl-face-subactions__text">本区随机</text>
        </view>
        <view class="bl-face-subactions__sep" />
        <view class="bl-face-subactions__item" @click="resetZone">
          <text class="bl-face-subactions__text">重置本区</text>
        </view>
        <view class="bl-face-subactions__sep" />
        <view class="bl-face-subactions__item" @click="resetAll">
          <text class="bl-face-subactions__text">全部重置</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
import { reactive, computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { settings, setGender } from '@/common/store.js'
import {
  SLIDER_GROUPS, GROUPED_KEYS, panelSummary, UI_COPY,
  defaultValues, computeView, randomValues, buildSave,
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
 * 滑杆目录（名称 / 区间 / 步长 / 是否已接线）全部来自参数表 + 适老裁剪层，
 * 页面不再自己维护一份；「不做」的参数（战斗妆容、纹身、胡须等）不在目录里。
 */
const values = reactive(defaultValues(GROUPED_KEYS))

/** 当前分区（A~J）。面板按分区展示，一次只显示一区的滑杆。 */
const activeZone = ref(SLIDER_GROUPS[0].zone)
const activeGroup = computed(
  () => SLIDER_GROUPS.find((g) => g.zone === activeZone.value) || SLIDER_GROUPS[0]
)

/** 面板总览文案：参数总数 / 本档开放 / 已接线通道 / 等资产条数。 */
const panel = panelSummary()
const summaryText = computed(() => {
  const g = activeGroup.value
  return g.zone + ' ' + g.name + ' · 本区 ' + g.count + ' 条'
    + (g.pending ? '（' + g.pending + ' 条等资产）' : '')
    + ' · 全档 ' + panel.open + '/' + panel.total + ' 条'
})

/** 本区提示：说明哪些条目的滑杆区间被适老裁剪收敛过。 */
const zoneHint = computed(() => {
  const softened = activeGroup.value.sliders.filter((s) => s.trim === '弱化').length
  if (!softened) return '本区参数滑杆区间按原规格开放'
  return '本区有 ' + softened + ' 条按适老裁剪收敛了可调区间（如妆容强度上限）'
})

function onParam(key, value) {
  values[key] = value
}

function switchZone(zone) {
  if (zone === activeZone.value) return
  activeZone.value = zone
}

/**
 * 一次算全：UI 值 → 参数 → 四通道指令 → 形态键权重。
 * keys 显式传面板全量键：逻辑层按「驱动的参数」过滤告警，
 * 不传会把整表 102 条的缺失提示一起放出来。
 */
const view = computed(() => computeView(values, { keys: GROUPED_KEYS }))
/** 形态键权重（name → 0~1），CSS 降级预览与 App 端 payload 都用它。 */
const weights = computed(() => view.value.weights)

/** 当前形象性别。默认女性，可切男性（交付 README：捏脸页默认形象 = 女性）。 */
/**
 * 捏脸（五官滑杆）是否开放。
 * 按策略变更**暂时关闭**：数字人只做「唇形同步 + 招手互动」。
 * 但**页面保持开放**——用户需要「切换男女形象」这个入口，那块功能是可用的。
 * 将来接回捏脸只需把这个常量改回 true（滑杆目录与接线都还在）。
 */
const FACE_EDIT_ENABLED = false
/**
 * 当前形象性别：**以全局 store 为准**（`settings.gender`），没选过时兜底 `DEFAULT_GENDER`。
 * 之前用局部 `ref(DEFAULT_GENDER)`，切了性别带不到通话页（换页面又回默认），
 * 所以改成"全局 store 持有 + 这里只做兜底与写入"。
 */
const gender = computed(() => settings.gender || DEFAULT_GENDER)

/** 宿主 → renderjs 的唯一数据通道（App 端 renderjs 拿不到逻辑层对象，只能靠 prop 下发）。 */
const payload = computed(() => JSON.stringify({ commands: view.value.cmds }))
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
  stageRef.load(gender.value, 'edit', { frameMode: 'bust', fitMargin: 1.15 }).catch(() => onStageError())
})

onUnmounted(() => {
  unmountFaceStage()
  stageRef = null
})

// 滑杆 → 30Hz 节流下发「整包四通道指令」（morph / bone / material / asset，规格书 §7.3）
watch(view, (v) => {
  if (stageRef) stageRef.applyCommandsThrottled(v.cmds)
})

// 性别切换 → 换一份 .glb（同一个舞台，只换模型）
watch(gender, (g) => {
  if (stageRef) stageRef.load(g, 'edit', { frameMode: 'bust', fitMargin: 1.15 }).catch(() => onStageError())
})
// #endif

/* ------------------------------- 操作 ------------------------------- */
function switchGender(value) {
  if (value === gender.value) return
  if (!GENDER_OPTIONS.some((g) => g.value === value)) return
  // 写全局 store（会落本地存储）→ 通话页也跟着变
  setGender(value)
  uni.showToast({ title: '已切换为' + genderLabel(value) + '形象', icon: 'none' })
}

function randomize() {
  Object.assign(values, randomValues(GROUPED_KEYS))
  uni.showToast({ title: '已随机生成一个新形象', icon: 'none' })
}

/** 只随机当前分区：想微调一处时，不必整套重来。 */
function randomizeZone() {
  const keys = activeGroup.value.keys
  Object.assign(values, randomValues(keys))
  uni.showToast({ title: '已随机' + activeGroup.value.name, icon: 'none' })
}

/** 当前分区恢复默认（0 / 区间内默认值）。 */
function resetZone() {
  Object.assign(values, defaultValues(activeGroup.value.keys))
}

/** 全部参数恢复默认。 */
function resetAll() {
  Object.assign(values, defaultValues(GROUPED_KEYS))
  uni.showToast({ title: '已恢复默认形象', icon: 'none' })
}

function save() {
  const built = buildSave(values, { keys: GROUPED_KEYS, name: '我的形象' })
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
      this.gl.load(g, 'edit', { frameMode: 'bust', fitMargin: 1.15 }).catch(() => ownerInstance.callMethod('onStageError'))
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
      this.gl.load(value, 'edit', { frameMode: 'bust', fitMargin: 1.15 }).catch(() => ownerInstance.callMethod('onStageError'))
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
/* 「正在开发中」占位块：替代被下线的捏脸滑杆区 */
.bl-face-soon {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12rpx;
  padding: 72rpx 40rpx;
  margin: 24rpx 32rpx;
  border-radius: var(--bl-radius-bubble);
  background-color: rgba(154, 166, 160, .10);
  border: 2rpx dashed rgba(154, 166, 160, .5);
}
.bl-face-soon__title {
  font-size: 34rpx;
  font-weight: 600;
  color: #3E4A44;
  margin-top: 8rpx;
}
.bl-face-soon__desc {
  font-size: 26rpx;
  color: #7A857F;
  text-align: center;
  line-height: 1.5;
}

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

/* 分区 chips */
.bl-face-zones {
  flex: none;
  white-space: nowrap;
  padding: 16rpx 0 4rpx;
}
.bl-face-zones__inner {
  display: inline-flex;
  padding: 0 32rpx;
  gap: 12rpx;
}
.bl-face-zones__chip {
  flex: none;
  display: flex;
  align-items: center;
  gap: 8rpx;
  padding: 10rpx 22rpx;
  border-radius: var(--bl-radius-pill);
  background-color: #E4EAE6;
}
.bl-face-zones__chip--on {
  background-color: var(--bl-primary);
}
.bl-face-zones__text {
  flex: none;
  white-space: nowrap;
  font-size: 26rpx;
  color: var(--bl-text-sub);
}
.bl-face-zones__text--on {
  color: #FFFFFF;
  font-weight: 600;
}
.bl-face-zones__count {
  flex: none;
  white-space: nowrap;
  font-size: 22rpx;
  color: #9AA8A1;
}
.bl-face-zones__count--on {
  color: rgba(255, 255, 255, .85);
}

/* 面板总览 */
.bl-face-summary {
  flex: none;
  padding: 12rpx 32rpx 0;
}
.bl-face-summary__text {
  font-size: 22rpx;
  color: var(--bl-text-sub);
}

/* 参数区（含"等资产"标注） */
.bl-face-controls__tag {
  align-self: flex-start;
  background-color: #FFF3D6;
  border-radius: var(--bl-radius-pill);
  padding: 2rpx 14rpx;
  margin-bottom: 8rpx;
}
.bl-face-controls__tag-text {
  font-size: 20rpx;
  color: #A97A16;
}
.bl-face-controls__zone-hint {
  padding: 4rpx 0 24rpx;
}
.bl-face-controls__zone-hint-text {
  font-size: 20rpx;
  color: #9AA8A1;
  line-height: 1.5;
}

/* 分区级操作 */
.bl-face-subactions {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 32rpx 12rpx;
}
.bl-face-subactions__item {
  padding: 8rpx 24rpx;
}
.bl-face-subactions__text {
  font-size: 24rpx;
  color: var(--bl-primary);
}
.bl-face-subactions__sep {
  width: 2rpx;
  height: 24rpx;
  background-color: var(--bl-divider);
}

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