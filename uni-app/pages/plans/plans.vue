<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <!-- 左侧：当日阳历 + 阴历；右侧：卷轴日历图标，点开看日历 -->
    <bl-navbar solid action="calmonth" action-label="查看日历" @action="toCalendar">
      <template #left>
        <view class="bl-datenav">
          <text class="bl-datenav__solar">{{ solarText }}</text>
          <text class="bl-datenav__lunar">{{ lunarText }}</text>
        </view>
      </template>
    </bl-navbar>

    <bl-reminder-bar :item="reminder.banner" @open="onReminderOpen" @dismiss="dismissBanner" />

    <scroll-view class="bl-body" scroll-y>
      <view class="bl-planhead">
        <text class="bl-planhead__sub">想安排什么，点一下就行</text>
      </view>

      <view class="bl-section-title--ink">
        <view class="bl-brush-rule" />
        <text class="bl-section-title__text">三类日程</text>
      </view>

      <view class="bl-plan-list">
        <!-- 三个入口：日常 / 每周 / 特殊。整张卡可点，不用瞄准小按钮 -->
        <view
          v-for="entry in ENTRIES"
          :key="entry.key"
          class="bl-plan-entry"
          role="button"
          :aria-label="entry.title"
          @click="openEntry(entry)"
        >
          <view class="bl-plan-entry__icon">
            <bl-icon :name="entry.icon" color="#2F5D4E" :size="52" />
          </view>

          <text class="bl-plan-entry__title">{{ entry.title }}</text>

          <bl-icon name="chev" color="#B9B3A4" :size="36" />
        </view>
      </view>
    </scroll-view>

    <bl-tabbar active="plans" />
  </view>
</template>

<script setup>
/**
 * 设置日程（老人端 Tab 2）
 *
 * 本页只做「入口」：日常 / 每周 / 特殊三类。具体计划与打卡交互放在各自的目标页，
 * 免得把老人淹没在一堆待办清单里。
 *
 * 数据侧仍调用 initPlan()：提醒轮询与端侧本地通知依赖它预排当天计划，
 * 所以继续初始化，但这里不把 items 渲染成清单。
 */
import { computed, onMounted } from 'vue'
import { settings } from '@/common/store.js'
import { toLunar } from '@/common/lunar.js'
import { initPlan } from '@/stores/plan.js'
import { dismissBanner, poll, reminder } from '@/stores/reminder.js'

/** 当日阳历：10 月 7 日 周三 */
const solarText = computed(() => {
  const d = new Date()
  const week = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][d.getDay()]
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日 ${week}`
})

/** 当日阴历：八月廿七（自算，见 common/lunar.js） */
const lunarText = computed(() => toLunar(new Date()).text)

const ENTRIES = [
  {
    key: 'daily',
    title: '日常计划',
    icon: 'clock',
    // 日常计划页：添加 / 开关 / 删除
    path: '/pages/daily/daily'
  },
  {
    key: 'weekly',
    title: '每周计划',
    icon: 'cal',
    // 每周计划页：添加 / 选星期 / 开关
    path: '/pages/weekly/weekly'
  },
  {
    key: 'special',
    title: '特殊计划',
    icon: 'heart',
    path: '' // [待定] 目标页未做，先给提示
  }
]

onMounted(() => {
  initPlan()
  // 进日程页顺手拉一次提醒（可能是从提醒条点进来的）
  poll()
})

function openEntry(entry) {
  if (entry.path) {
    uni.navigateTo({ url: entry.path })
    return
  }
  uni.showToast({ title: entry.title + '正在开发中', icon: 'none' })
}

/** 导航栏右侧日历图标：查看日历 */
function toCalendar() {
  uni.navigateTo({ url: '/pages/calendar/calendar' })
}

function onReminderOpen() {
  dismissBanner()
  uni.showToast({ title: '到点会提醒你，先记下来', icon: 'none' })
}
</script>

<style scoped>
.bl-planhead {
  padding: 8rpx var(--bl-space-lg) var(--bl-space-sm);
  display: flex;
  flex-direction: column;
  gap: 8rpx;
}
.bl-planhead__sub {
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  padding-top: 4rpx;
}

/* 导航栏左侧的日期块：阳历在上（加粗墨色），阴历在下（淡墨） */
.bl-datenav {
  display: flex;
  flex-direction: column;
  gap: 2rpx;
}
.bl-datenav__solar {
  font-size: var(--bl-font-title);
  font-weight: 700;
  color: var(--bl-text);
  line-height: 1.25;
  letter-spacing: .01em;
  white-space: nowrap;
}
.bl-datenav__lunar {
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  line-height: 1.25;
  white-space: nowrap;
}

.bl-plan-list {
  display: flex;
  flex-direction: column;
  gap: 24rpx;
  padding: 0 var(--bl-space-lg) var(--bl-space-md);
}
.bl-plan-list .bl-section-title--ink {
  padding: 0 0 4rpx;
}

/* 入口卡：整张卡可点，触控区远超 48px。无副文案，高度收紧到 120rpx */
.bl-plan-entry {
  display: flex;
  align-items: center;
  gap: 24rpx;
  padding: 28rpx 32rpx;
  min-height: 120rpx;
  background-color: var(--bl-surface);
  border: 1rpx solid var(--bl-border);
  border-radius: var(--bl-radius-card);
  box-shadow: var(--bl-shadow-card);
  box-sizing: border-box;
}
.bl-plan-entry:active {
  background-color: var(--bl-surface-2);
  border-color: var(--bl-border-strong);
}
.bl-plan-entry__icon {
  flex: none;
  width: 80rpx;
  height: 80rpx;
  border-radius: var(--bl-radius-pill);
  background-color: var(--bl-primary-soft);
  display: flex;
  align-items: center;
  justify-content: center;
}
.bl-plan-entry__title {
  flex: 1;
  min-width: 0;
  font-size: var(--bl-font-body);
  font-weight: 700;
  color: var(--bl-text);
  line-height: 1.35;
}
</style>
