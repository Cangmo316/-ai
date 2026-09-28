<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar title="今日计划" solid />

    <bl-reminder-bar :item="reminder.banner" @open="onReminderOpen" @dismiss="dismissBanner" />

    <scroll-view class="bl-body" scroll-y>
      <view class="bl-plan-head">
        <text class="bl-plan-head__text">{{ headline }}</text>
        <text v-if="notice" class="bl-plan-head__notice">{{ notice }}</text>
      </view>

      <view v-if="plan.items.length" class="bl-plan-list">
        <bl-plan-check
          v-for="item in plan.items"
          :key="item.id"
          :time="item.time"
          :type="item.type"
          :title="item.title"
          :detail="item.detail"
          :done="item.done"
          :strong-remind="item.strongRemind"
          :busy="plan.pending.indexOf(item.id) !== -1"
          @toggle="onToggle(item)"
        />
      </view>

      <view v-else class="bl-empty">
        <bl-icon name="clock" color="#C4C4C4" :size="120" />
        <text class="bl-empty__title">{{ emptyTitle }}</text>
        <text class="bl-empty__desc">{{ emptyDesc }}</text>
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
/**
 * 今日计划（老人端 Tab 2）
 *
 * 数据全部来自 `/v1/plans/today`，且**只包含家属已确认的计划**——
 * 未确认的草稿不会出现在这里，也不会产生提醒（设计方案 §3.2 的关键闸门）。
 * 接口不可用时逐级降级：本地缓存 → 内置样例，页面永远有内容可看。
 */

import { computed, onMounted, watch } from 'vue'
import { settings } from '@/common/store.js'
import { initPlan, plan, planHeadline, toggleCheckin } from '@/stores/plan.js'
import { dismissBanner, poll, reminder } from '@/stores/reminder.js'
import { scheduleLocalNotifications } from '@/stores/push.js'

const headline = computed(() => planHeadline())

const notice = computed(() => {
  if (plan.source === 'sample') return '现在连不上，先看看这份计划'
  if (plan.source === 'cached') return '网络不太好，先看上回存的'
  return ''
})

const emptyTitle = computed(() =>
  plan.statusLabel === '还没有计划' ? '还没有计划' : '今天没有要提醒的事'
)

const emptyDesc = computed(() => {
  if (plan.statusLabel === '还没有计划') return '家里人确认之后 这里就会有每天要做的事'
  if (plan.statusLabel.indexOf('调整') !== -1) return '计划在调整 等家里人点头后就恢复'
  return '今天可以踏踏实实歇着'
})

onMounted(() => {
  initPlan()
  // 进日程页顺手拉一次提醒（可能是从提醒条点进来的）
  poll()
})

// 计划到位后预排当天的本地通知：断网、推送挂了也照样响（App 端专属，其它端静默跳过）
watch(
  () => plan.total + '|' + plan.items.map((item) => (item.done ? 1 : 0)).join(''),
  () => scheduleLocalNotifications(plan.items)
)

function onReminderOpen(item) {
  // 老人从提醒条点进来，就是为了打卡：滚到对应那一项，并给一句提示
  dismissBanner()
  const target = item && item.planItemId
  if (target && !plan.items.some((entry) => entry.id === target)) {
    uni.showToast({ title: '这项不在今天计划里', icon: 'none' })
    return
  }
  uni.showToast({ title: '点一下卡片就打卡', icon: 'none' })
}

function onToggle(item) {
  toggleCheckin(item).then((ok) => {
    if (!ok && plan.lastError) {
      uni.showToast({ title: plan.lastError, icon: 'none' })
    }
  })
}

function toCalendar() {
  uni.navigateTo({ url: '/pages/calendar/calendar' })
}
</script>

<style scoped>
.bl-plan-head {
  padding: 32rpx 32rpx 24rpx;
  display: flex;
  flex-direction: column;
  gap: 8rpx;
}
.bl-plan-head__text {
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
}
.bl-plan-head__notice {
  font-size: 24rpx;
  color: var(--bl-warm);
}
.bl-plan-list {
  display: flex;
  flex-direction: column;
  gap: 24rpx;
  padding: 0 32rpx 32rpx;
}
</style>
