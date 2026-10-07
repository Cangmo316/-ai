<template>
  <view class="bl-tabbar">
    <view
      v-for="t in tabs"
      :key="t.key"
      class="bl-tabbar__item"
      :class="{ 'is-active': t.key === active }"
      role="button"
      :aria-label="t.label"
      :aria-current="t.key === active ? 'page' : 'false'"
      @click="go(t)"
    >
      <!-- 图标实际 26px：bl-icon 的数字按 rpx 处理（1px = 2rpx），故传 52 -->
      <bl-icon :name="t.icon" :color="t.key === active ? activeColor : inactiveColor" :size="52" />
      <!-- 文字标签必须保留：老年用户对纯图标的识别率偏低 -->
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
  background-color: rgba(255, 253, 248, .92);
  border-top: 1rpx solid var(--bl-divider);
  box-sizing: content-box;
  position: relative;
}
/* 毛玻璃只在支持的端生效；小程序端会忽略，退化为上面的半透明暖白底 */
@supports (backdrop-filter: blur(24rpx)) {
  .bl-tabbar { backdrop-filter: blur(24rpx); }
}
/* 顶部一道淡墨横线，强化「纸面分层」 */
.bl-tabbar::before {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  height: 1rpx;
  background-color: var(--bl-divider);
}
.bl-tabbar__item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6rpx;
  /* 触控硬下限：适老化要求 ≥48px */
  min-height: var(--bl-touch);
  position: relative;
  color: var(--bl-icon-muted);
}
.bl-tabbar__label {
  /* 26rpx = 13px；原 22rpx(11px) 低于适老化可读下限 */
  font-size: var(--bl-font-tab);
  line-height: 1;
  color: var(--bl-text-2);
  font-weight: 500;
  letter-spacing: .02em;
}
.bl-tabbar__item.is-active { color: var(--bl-primary); }
.bl-tabbar__item.is-active .bl-tabbar__label {
  color: var(--bl-primary);
  font-weight: 600;
}
/* 按键反馈：激活态不再画下方横线，只用图标与文字颜色 + 字重区分 */
.bl-tabbar__item:active { background-color: var(--bl-primary-soft); }
.bl-tabbar__safe { width: 100%; height: env(safe-area-inset-bottom); }
</style>
