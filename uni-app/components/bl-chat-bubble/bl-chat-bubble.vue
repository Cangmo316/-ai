<template>
  <view class="bl-msg" :class="{ 'bl-msg--me': mine }">
    <view class="bl-msg__avatar" :style="{ backgroundColor: avatarColor }">
      <bl-icon name="person" color="#FFFFFF" :size="52" />
    </view>

    <view class="bl-bubble" :class="mine ? 'bl-bubble--me' : 'bl-bubble--ai'">
      <view v-if="type === 'voice'" class="bl-bubble__voice" @click="$emit('play')">
        <bl-icon name="speaker" :color="voiceColor" :size="36" />
        <view class="bl-wave">
          <view
            v-for="(h, i) in WAVE"
            :key="i"
            class="bl-wave__bar"
            :style="{ height: h + 'rpx' }"
          />
        </view>
        <text class="bl-bubble__dur">{{ seconds }}&#8243;</text>
      </view>

      <text v-else class="bl-bubble__text">{{ text }}</text>
    </view>
  </view>
</template>

<script setup>
defineProps({
  text: { type: String, default: '' },
  /** 右侧「我」的消息 */
  mine: { type: Boolean, default: false },
  /** text | voice */
  type: { type: String, default: 'text' },
  seconds: { type: [Number, String], default: 6 },
  avatarColor: { type: String, default: '#07C160' }
})

defineEmits(['play'])

/** 语音波纹高度（rpx），对应设计稿里的波形 */
const WAVE = [12, 24, 36, 20, 32, 16, 28, 24, 36, 12]
const voiceColor = '#07C160'
</script>

<style scoped>
.bl-msg {
  display: flex;
  align-items: flex-start;
  gap: 16rpx;
  margin-bottom: 32rpx;
}
.bl-msg--me { flex-direction: row-reverse; }

.bl-msg__avatar {
  width: 80rpx;
  height: 80rpx;
  border-radius: 50%;
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
}

.bl-bubble {
  max-width: 464rpx;
  padding: 20rpx 28rpx;
  border-radius: var(--bl-radius-bubble);
  box-sizing: border-box;
}
.bl-bubble--me {
  background-color: var(--bl-bubble-me);
  border-top-right-radius: 8rpx;
}
.bl-bubble--ai {
  background-color: var(--bl-surface);
  border-top-left-radius: 8rpx;
}
.bl-bubble__text {
  font-size: var(--bl-font-body);
  line-height: 1.5;
  color: var(--bl-text);
  word-break: break-word;
}

.bl-bubble__voice {
  display: flex;
  align-items: center;
  gap: 16rpx;
  min-width: 200rpx;
}
.bl-wave {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8rpx;
  height: 40rpx;
}
.bl-wave__bar {
  width: 6rpx;
  border-radius: 3rpx;
  background-color: var(--bl-primary);
}
.bl-bubble__dur { font-size: 24rpx; color: var(--bl-text-2); }
</style>