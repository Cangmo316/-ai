<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar title="今日计划" solid />

    <scroll-view class="bl-body" scroll-y>
      <view class="bl-plan-head">
        <text class="bl-plan-head__text">9月23日 周三 · 共 4 项，已完成 2 项</text>
      </view>

      <view class="bl-plan-list">
        <bl-plan-card
          v-for="p in PLANS"
          :key="p.time"
          :time="p.time"
          :title="p.title"
          :desc="p.desc"
          :state="p.state"
        />
      </view>

      <view class="bl-page-footer">
        <view class="bl-btn bl-btn--ghost bl-btn--block" @click="toCalendar">
          <text class="bl-page-footer__text">查看日历</text>
        </view>
      </view>
    </scroll-view>

    <bl-tabbar active="plans" />
  </view>
</template>

<script setup>
import { settings } from '@/common/store.js'

const PLANS = [
  { time: '08:00', title: '用药提醒', desc: '降压药 1 片，饭后温水送服', state: 'done' },
  { time: '12:00', title: '午餐提醒', desc: '少油少盐，多吃青菜', state: 'done' },
  { time: '15:00', title: '散步提醒', desc: '小区公园 30 分钟', state: 'todo' },
  { time: '19:00', title: '晚间问候', desc: '儿子会发来消息', state: 'heart' }
]

function toCalendar() {
  uni.navigateTo({ url: '/pages/calendar/calendar' })
}
</script>

<style scoped>
.bl-plan-head { padding: 32rpx 32rpx 24rpx; }
.bl-plan-head__text {
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
}
.bl-plan-list {
  display: flex;
  flex-direction: column;
  gap: 24rpx;
  padding: 0 32rpx 32rpx;
}
</style>