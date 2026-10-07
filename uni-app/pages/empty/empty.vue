<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar title="比邻AI" />

    <view class="bl-body">
      <view class="bl-empty">
        <bl-icon name="empty" :color="iconMuted" :size="112" />
        <text class="bl-empty__title">还没有聊天</text>
        <text class="bl-empty__desc">绑定家人或选一位 AI 亲人，就能开始说话了</text>
        <view class="bl-btn bl-btn--primary bl-empty__cta" @click="toRoles">
          <text class="bl-btn__text bl-empty__cta-text">去选一位 AI 亲人</text>
        </view>
      </view>
    </view>

    <bl-tabbar active="chats" />
  </view>
</template>

<script setup>
import { settings } from '@/common/store.js'
import { tokens } from '@/common/tokens.js'

const iconMuted = tokens.color.iconMuted

function toRoles() {
  uni.navigateTo({ url: '/pages/roles/roles' })
}
</script>

<style scoped>
/* 原型 .empty：整体靠上，靠 padding 撑出留白，不垂直居中 */
.bl-empty {
  gap: var(--bl-space-md);
}
/* 用容器 gap 统一间距，抵消全局样式里的单独 margin */
.bl-empty__title,
.bl-empty__desc {
  margin-top: 0;
}
.bl-empty__cta {
  margin-top: var(--bl-space-xs);
}
.bl-empty__cta-text { color: var(--bl-surface); }
</style>