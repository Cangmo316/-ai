<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar title="数字人形象" back solid @back="back" />

    <view class="bl-face-page">
      <view class="bl-face-preview">
        <view class="bl-face-preview__badge">
          <text class="bl-face-preview__badge-text">3D 实时预览 · 可旋转</text>
        </view>

        <view class="bl-face-model">
          <view class="bl-face__head" :style="headStyle">
            <view class="bl-face__hair" :style="hairStyle" />
            <view class="bl-face__eyes" :style="eyesStyle">
              <view class="bl-face__eye" />
              <view class="bl-face__eye" />
            </view>
            <view class="bl-face__mouth" :style="mouthStyle" />
          </view>
          <view class="bl-face__torso" :style="torsoStyle" />
        </view>

        <text class="bl-face-preview__hint">左右拖动可旋转视角</text>
      </view>

      <scroll-view class="bl-face-controls" scroll-y>
        <view v-for="p in PARAMS" :key="p.key" class="bl-face-controls__row">
          <bl-slider
            :name="p.name"
            :value="params[p.key]"
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
import { reactive, computed } from 'vue'
import { settings } from '@/common/store.js'

const PARAMS = [
  { key: 'face', name: '脸型' },
  { key: 'eyes', name: '眼睛' },
  { key: 'nose', name: '鼻子' },
  { key: 'mouth', name: '嘴巴' },
  { key: 'hair', name: '发型' },
  { key: 'skin', name: '肤色' },
  { key: 'age', name: '年龄感' },
  { key: 'outfit', name: '服饰' }
]

const params = reactive({
  face: 52, eyes: 46, nose: 50, mouth: 44,
  hair: 40, skin: 60, age: 58, outfit: 48
})

function onParam(key, value) {
  params[key] = value
}

/* ------------------------- 预览外观随参数变化 ------------------------- */
const headStyle = computed(() => {
  const w = 176 + (params.face / 100) * 44
  const h = 208 + (params.face / 100) * 36
  const radius = params.face > 55 ? '48% 48% 46% 46%' : '44% 44% 42% 42%'
  const hue = 26 + (params.skin / 100) * 6
  const light = 68 + (params.skin / 100) * 14
  const sat = 38 + (params.age / 100) * 12
  return {
    width: w + 'rpx',
    height: h + 'rpx',
    borderRadius: radius,
    background: 'linear-gradient(180deg, hsl(' + hue + ', ' + sat + '%, ' + light + '%) 0%, hsl(' + hue + ', ' + sat + '%, ' + (light - 8) + '%) 100%)'
  }
})

const hairStyle = computed(() => {
  const gray = Math.min(90, params.age * 1.15)
  return {
    height: (68 + (params.hair / 100) * 52) + 'rpx',
    background: 'hsl(30, ' + Math.max(6, 26 - gray / 5) + '%, ' + (16 + gray / 1.6) + '%)'
  }
})

const eyesStyle = computed(() => ({
  gap: (30 + (params.eyes / 100) * 40) + 'rpx'
}))

const mouthStyle = computed(() => ({
  width: (26 + (params.mouth / 100) * 34) + 'rpx',
  opacity: 0.55 + (params.mouth / 100) * 0.45
}))

const torsoStyle = computed(() => {
  const o = params.outfit / 100
  const hue = 200 + o * 40
  return {
    background: 'linear-gradient(180deg, hsl(' + hue + ', 42%, ' + (78 - o * 22) + '%) 0%, hsl(' + hue + ', 38%, ' + (68 - o * 22) + '%) 100%)'
  }
})

/* ------------------------------- 操作 ------------------------------- */
function randomize() {
  Object.keys(params).forEach((k) => {
    params[k] = Math.round(15 + Math.random() * 70)
  })
  uni.showToast({ title: '已随机生成一个新形象', icon: 'none' })
}
function save() {
  uni.showToast({ title: '形象已保存', icon: 'none' })
}
function back() {
  const pages = getCurrentPages()
  if (pages.length > 1) uni.navigateBack()
  else uni.reLaunch({ url: '/pages/me/me' })
}
</script>

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
.bl-face-preview__badge {
  position: absolute;
  left: 24rpx;
  top: 24rpx;
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
</style>