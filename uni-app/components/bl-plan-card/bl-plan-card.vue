<template>
  <view class="bl-plan">
    <text class="bl-plan__time">{{ time }}</text>
    <view class="bl-plan__main">
      <text class="bl-plan__title">{{ title }}</text>
      <text v-if="desc" class="bl-plan__desc">{{ desc }}</text>
    </view>
    <view class="bl-plan__state" :style="{ backgroundColor: state.bg }">
      <bl-icon :name="state.icon" :color="state.color" :size="40" />
    </view>
  </view>
</template>

<script setup>
import { computed } from 'vue'
import { tokens } from '@/common/tokens.js'

const props = defineProps({
  time: { type: String, default: '' },
  title: { type: String, default: '' },
  desc: { type: String, default: '' },
  /** done 已完成 | todo 待办 | heart 关爱 */
  state: { type: String, default: 'todo' }
})

// 状态色统一取语义令牌：竹青=已完成、暖墨黄=待办、朱砂=关爱
const MAP = {
  done: { icon: 'check', color: tokens.color.success, bg: 'rgba(72, 113, 79, .12)' },
  todo: { icon: 'clock', color: tokens.color.warm, bg: 'rgba(149, 86, 0, .12)' },
  heart: { icon: 'heart', color: tokens.color.danger, bg: 'rgba(178, 58, 46, .12)' }
}

const state = computed(() => MAP[props.state] || MAP.todo)
</script>

<style scoped>
.bl-plan {
  display: flex;
  align-items: center;
  gap: 24rpx;
  padding: 32rpx;
  min-height: 176rpx;
  background-color: var(--bl-surface);
  border-radius: var(--bl-radius-card);
  box-shadow: var(--bl-shadow-card);
  box-sizing: border-box;
}
.bl-plan__time {
  flex: none;
  width: 116rpx;
  font-size: var(--bl-font-title);
  font-weight: 700;
  color: var(--bl-primary);
  line-height: 1;
}
.bl-plan__main { flex: 1; min-width: 0; }
.bl-plan__title {
  display: block;
  font-size: var(--bl-font-body);
  font-weight: 700;
  line-height: 1.3;
  color: var(--bl-text);
}
.bl-plan__desc {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  line-height: 1.4;
  margin-top: 6rpx;
}
.bl-plan__state {
  flex: none;
  width: 88rpx;
  height: 88rpx;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>