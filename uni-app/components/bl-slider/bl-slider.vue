<template>
  <view class="bl-slider">
    <view class="bl-slider__top">
      <text class="bl-slider__name">{{ name }}</text>
      <text class="bl-slider__value">{{ value }}</text>
    </view>
    <slider
      class="bl-slider__ctl"
      :value="value"
      :min="min"
      :max="max"
      :step="step"
      :activeColor="tokens.color.primary"
      :backgroundColor="tokens.color.divider"
      :blockSize="28"
      @changing="emitValue"
      @change="emitValue"
    />
  </view>
</template>

<script setup>
import { tokens } from '@/common/tokens.js'

defineProps({
  name: { type: String, default: '' },
  value: { type: Number, default: 50 },
  min: { type: Number, default: 0 },
  max: { type: Number, default: 100 },
  step: { type: Number, default: 1 }
})

const emit = defineEmits(['update:value', 'change'])

function emitValue(e) {
  const v = e.detail.value
  emit('update:value', v)
  emit('change', v)
}
</script>

<style scoped>
.bl-slider {
  background-color: var(--bl-surface);
  border-radius: var(--bl-radius-bubble);
  padding: 16rpx 32rpx 8rpx;
}
.bl-slider__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.bl-slider__name {
  font-size: var(--bl-font-body);
  color: var(--bl-text);
}
.bl-slider__value {
  font-size: var(--bl-font-body);
  font-weight: 700;
  color: var(--bl-primary);
}
/* 适老化：滑杆本体也留出足够高度，方便拖拽 */
.bl-slider__ctl { margin: 8rpx 0; }
</style>