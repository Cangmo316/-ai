<template>
  <view class="bl-tabbar">
    <view
      v-for="t in tabs"
      :key="t.key"
      class="bl-tabbar__item"
      :class="{ 'is-active': t.key === active }"
      @click="go(t)"
    >
      <bl-icon :name="t.icon" :color="t.key === active ? activeColor : inactiveColor" :size="52" />
      <text class="bl-tabbar__label">{{ t.label }}</text>
    </view>
    <view class="bl-tabbar__safe" />
  </view>
</template>

<script setup>
import { tokens } from '@/common/tokens.js'

const props = defineProps({
  /** chats | plans | me */
  active: { type: String, required: true }
})

const activeColor = tokens.color.primary
const inactiveColor = tokens.color.iconMuted

const tabs = [
  { key: 'chats', label: '对话', icon: 'chat', path: '/pages/chats/chats' },
  { key: 'plans', label: '日程', icon: 'cal', path: '/pages/plans/plans' },
  { key: 'me', label: '我的', icon: 'me', path: '/pages/me/me' }
]

function go(t) {
  if (t.key === props.active) return
  // 用 reLaunch 而非 switchTab：自绘 TabBar 需要清栈，避免页面无限堆叠
  uni.reLaunch({ url: t.path })
}
</script>

<style scoped>
.bl-tabbar {
  flex: none;
  display: flex;
  flex-wrap: wrap;
  height: var(--bl-tabbar);
  background-color: var(--bl-surface);
  border-top: 1rpx solid var(--bl-divider);
  box-sizing: content-box;
}
.bl-tabbar__item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--bl-icon-muted);
}
.bl-tabbar__label {
  font-size: 22rpx;
  line-height: 1;
  margin-top: 6rpx;
}
.bl-tabbar__item.is-active { color: var(--bl-primary); }
.bl-tabbar__item.is-active .bl-tabbar__label { font-weight: 600; }
.bl-tabbar__safe { width: 100%; height: env(safe-area-inset-bottom); }
</style>