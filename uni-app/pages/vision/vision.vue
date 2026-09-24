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

    <view class="bl-vision__person">
      <view class="bl-vision__head" />
      <view class="bl-vision__torso" />
    </view>

    <view class="bl-vision__caption">
      <text class="bl-vision__caption-text">妈，今天药按时吃了没</text>
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
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { settings } from '@/common/store.js'

const seconds = ref(42)
const muted = ref(false)
const spkOff = ref(false)
let timer = null

const clock = computed(() => {
  const m = Math.floor(seconds.value / 60)
  const s = seconds.value % 60
  return (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s
})

onMounted(() => {
  timer = setInterval(() => { seconds.value += 1 }, 1000)
})
onUnmounted(() => {
  if (timer) { clearInterval(timer); timer = null }
})

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

/* 3D 数字人 */
.bl-vision__person {
  position: absolute;
  left: 50%;
  bottom: 352rpx;
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
  margin: auto 32rpx 0;
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

.bl-vision__controls {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 72rpx;
  padding: 48rpx 0;
  padding-bottom: calc(68rpx + env(safe-area-inset-bottom));
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