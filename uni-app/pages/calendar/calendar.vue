<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar title="日历" back solid @back="back" />

    <scroll-view class="bl-body" scroll-y>
      <view class="bl-cal-wrap">
        <view class="bl-cal__head">
          <view class="bl-cal__nav" @click="toast('上一月（原型演示）')">
            <bl-icon name="back" color="#1A1A1A" :size="44" />
          </view>
          <text class="bl-cal__month">2026 年 9 月</text>
          <view class="bl-cal__nav" @click="toast('下一月（原型演示）')">
            <bl-icon name="chev" color="#1A1A1A" :size="44" />
          </view>
        </view>

        <view class="bl-cal__week">
          <text v-for="w in WEEK" :key="w" class="bl-cal__week-item">{{ w }}</text>
        </view>

        <view class="bl-cal__grid">
          <view
            v-for="(d, i) in DAYS"
            :key="i"
            class="bl-cal__day"
            :class="{ 'is-mute': !d.day, 'is-marked': d.marked, 'is-today': d.today }"
            @click="pick(d)"
          >
            <view class="bl-cal__day-inner">
              <text class="bl-cal__day-text">{{ d.label }}</text>
            </view>
          </view>
        </view>
      </view>

      <view class="bl-group">
        <view class="bl-row">
          <view class="bl-row__icon" style="background-color:#FFF5E5">
            <bl-icon name="cal" color="#F5A623" :size="44" />
          </view>
          <text class="bl-row__label">本月计划</text>
          <text class="bl-row__value">19 项，已打卡 12 项</text>
        </view>
      </view>

      <view class="bl-page-footer">
        <view class="bl-btn bl-btn--ghost bl-btn--block" @click="back">
          <text class="bl-page-footer__text">回到今日计划</text>
        </view>
      </view>
    </scroll-view>
  </view>
</template>

<script setup>
import { settings } from '@/common/store.js'

const WEEK = ['一', '二', '三', '四', '五', '六', '日']

/** 2026-09-01 是周二，周一为一周起点 → 首行前面补 1 格（上月 31 日） */
const TODAY = 23
const MARKED = [3, 5, 8, 11, 15, 18, 22, 23, 26, 29]

const DAYS = (function build() {
  const out = [{ label: '31', day: 0, marked: false, today: false }]
  for (let i = 1; i <= 30; i += 1) {
    out.push({
      label: String(i),
      day: i,
      marked: MARKED.indexOf(i) !== -1,
      today: i === TODAY
    })
  }
  return out
})()

function toast(title) {
  uni.showToast({ title: title, icon: 'none' })
}
function pick(d) {
  if (!d.day) return
  toast('9 月 ' + d.day + ' 日 · ' + (d.marked ? '有计划' : '暂无计划'))
}
function back() {
  const pages = getCurrentPages()
  if (pages.length > 1) uni.navigateBack()
  else uni.reLaunch({ url: '/pages/plans/plans' })
}
</script>

<style scoped>
.bl-cal-wrap {
  margin: 32rpx;
  padding: 32rpx 24rpx;
  background-color: var(--bl-surface);
  border-radius: var(--bl-radius-card);
  box-shadow: var(--bl-shadow-card);
}
.bl-cal__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 32rpx;
  padding: 0 8rpx;
}
.bl-cal__month {
  font-size: var(--bl-font-title);
  font-weight: 700;
  color: var(--bl-text);
}
.bl-cal__nav {
  width: 80rpx;
  height: 80rpx;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}
.bl-cal__nav:active { background-color: rgba(0, 0, 0, .06); }

.bl-cal__week { display: flex; }
.bl-cal__week-item {
  width: 14.2857%;
  text-align: center;
  font-size: 24rpx;
  color: var(--bl-text-2);
}

.bl-cal__grid { display: flex; flex-wrap: wrap; }
.bl-cal__day {
  width: 14.2857%;
  height: 96rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}
.bl-cal__day-inner {
  position: relative;
  width: 88rpx;
  height: 88rpx;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}
.bl-cal__day-text {
  font-size: var(--bl-font-caption);
  color: var(--bl-text);
}
.bl-cal__day.is-mute .bl-cal__day-text { color: #C4C4C4; }
.bl-cal__day.is-marked .bl-cal__day-inner::after {
  content: '';
  position: absolute;
  bottom: 8rpx;
  width: 10rpx;
  height: 10rpx;
  border-radius: 50%;
  background-color: var(--bl-warm);
}
.bl-cal__day.is-today .bl-cal__day-inner { background-color: var(--bl-primary); }
.bl-cal__day.is-today .bl-cal__day-text { color: #FFFFFF; font-weight: 700; }
.bl-cal__day.is-today .bl-cal__day-inner::after { background-color: #FFFFFF; }
</style>