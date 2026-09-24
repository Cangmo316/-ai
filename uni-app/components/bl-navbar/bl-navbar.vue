<template>
  <view class="bl-navbar" :class="{ 'is-solid': solid }">
    <view class="bl-navbar__safe" />
    <view class="bl-navbar__bar">
      <view v-if="back" class="bl-navbar__btn" @click="$emit('back')">
        <bl-icon name="back" :color="iconColor" :size="48" />
      </view>
      <text class="bl-navbar__title">{{ title }}</text>
      <view v-if="action" class="bl-navbar__btn bl-navbar__btn--right" @click="$emit('action')">
        <bl-icon :name="action" :color="actionColor" :size="48" />
      </view>
    </view>
  </view>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  title: { type: String, default: '' },
  back: { type: Boolean, default: false },
  /** 右侧动作图标名；留空则不渲染 */
  action: { type: String, default: '' },
  actionColor: { type: String, default: '#07C160' },
  solid: { type: Boolean, default: false }
})

defineEmits(['back', 'action'])
const iconColor = computed(() => '#1A1A1A')
</script>

<style scoped>
.bl-navbar { flex: none; background-color: var(--bl-bg); }
.bl-navbar.is-solid {
  background-color: var(--bl-surface);
  border-bottom: 1rpx solid var(--bl-divider);
}
/* 刘海/状态栏让位：env() 在 H5 与 App 都可用，非全面屏自然为 0 */
.bl-navbar__safe { height: calc(env(safe-area-inset-top) + 10px); }
.bl-navbar__bar {
  height: 92rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
}
.bl-navbar__title {
  font-size: var(--bl-font-title);
  font-weight: 700;
  color: var(--bl-text);
  max-width: 60%;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.bl-navbar__btn {
  position: absolute;
  left: 12rpx;
  top: 50%;
  transform: translateY(-50%);
  width: 80rpx;
  height: 80rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
}
.bl-navbar__btn--right { left: auto; right: 20rpx; }
.bl-navbar__btn:active { background-color: rgba(0, 0, 0, .06); }
</style>