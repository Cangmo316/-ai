<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar title="选择你的AI亲人" back @back="back" />

    <scroll-view class="bl-body" scroll-y>
      <view class="bl-role-list">
        <bl-role-card
          v-for="r in ROLES"
          :key="r.name"
          :name="r.name"
          :desc="r.desc"
          :avatar-color="r.color"
          :selected="settings.role === r.role"
          @select="pick(r)"
        />
      </view>

      <view class="bl-page-footer">
        <view class="bl-btn bl-btn--primary bl-btn--block" @click="startChat">
          <text class="bl-page-footer__text bl-page-footer__text--on">用这个角色开始聊天</text>
        </view>
      </view>
    </scroll-view>
  </view>
</template>

<script setup>
import { settings, setRole } from '@/common/store.js'

const ROLES = [
  { name: 'AI子女 · 小明', desc: '像儿子一样关心你', role: '儿子 · 小明', color: '#07C160' },
  { name: '老伴儿 · 老张', desc: '知冷知热说说话', role: '老伴儿 · 老张', color: '#F5A623' },
  { name: '亲友 · 李姐', desc: '老姐妹唠家常', role: '亲友 · 李姐', color: '#4C8DFF' }
]

function pick(r) {
  setRole(r.role)
  uni.showToast({ title: '已选择：' + r.role, icon: 'none' })
}
function startChat() {
  uni.reLaunch({ url: '/pages/chats/chats' })
}
function back() {
  const pages = getCurrentPages()
  if (pages.length > 1) uni.navigateBack()
  else uni.reLaunch({ url: '/pages/me/me' })
}
</script>

<style scoped>
.bl-role-list {
  display: flex;
  flex-direction: column;
  gap: 24rpx;
  padding: 32rpx;
}
</style>