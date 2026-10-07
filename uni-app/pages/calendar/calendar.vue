<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar title="日历" back solid @back="back" />

    <scroll-view class="bl-body" scroll-y>
      <view class="bl-cal-wrap">
        <view class="bl-cal__head">
          <view class="bl-cal__nav" role="button" aria-label="上一月" @click="shiftMonth(-1)">
            <bl-icon name="back" color="#1F211D" :size="44" />
          </view>
          <text class="bl-cal__month">{{ monthLabel }}</text>
          <view class="bl-cal__nav" role="button" aria-label="下一月" @click="shiftMonth(1)">
            <bl-icon name="chev" color="#1F211D" :size="44" />
          </view>
        </view>

        <view class="bl-cal__week">
          <text v-for="w in WEEK" :key="w" class="bl-cal__week-item">{{ w }}</text>
        </view>

        <view class="bl-cal__grid">
          <view
            v-for="d in days"
            :key="d.key"
            class="bl-cal__day"
            :class="{
              'is-mute': !d.inMonth,
              'is-marked': d.inMonth && d.plans > 0,
              'is-today': d.isToday,
              'is-picked': picked && picked.key === d.key
            }"
            :role="d.inMonth ? 'button' : ''"
            :aria-label="d.inMonth ? `${month + 1}月${d.day}日 ${d.lunarFull}` : ''"
            @click="pick(d)"
          >
            <view class="bl-cal__day-inner">
              <text class="bl-cal__day-text">{{ d.label }}</text>
              <!-- 农历：初一显示月名（同时是节气/节日锚点），其余显示日名 -->
              <text v-if="d.inMonth" class="bl-cal__lunar" :class="{ 'is-first': d.isFestival }">
                {{ d.lunarShort }}
              </text>
            </view>
          </view>
        </view>
      </view>

      <!-- 点选某天后的说明：日期 + 农历 + 当天计划 -->
      <view v-if="pickedInfo" class="bl-cal-picked">
        <text class="bl-cal-picked__date">{{ pickedInfo.dateText }} · {{ pickedInfo.lunarText }}</text>
        <text class="bl-cal-picked__plans">
          {{ pickedInfo.plans > 0 ? `这天安排了 ${pickedInfo.plans} 条日常计划` : '这天没有安排' }}
        </text>
      </view>

      <view class="bl-group">
        <view class="bl-row">
          <view class="bl-row__icon" style="background-color:rgba(149, 86, 0, .12)">
            <bl-icon name="cal" color="#955600" :size="44" />
          </view>
          <text class="bl-row__label">日常计划</text>
          <text class="bl-row__value">共 {{ daily.items.length }} 条，生效中 {{ activePlanCount }} 条</text>
        </view>
        <view class="bl-row">
          <view class="bl-row__icon" style="background-color:rgba(47, 93, 78, .10)">
            <bl-icon name="clock" color="#2F5D4E" :size="44" />
          </view>
          <text class="bl-row__label">本月有安排的日子</text>
          <text class="bl-row__value">{{ monthPlanDays }} 天</text>
        </view>
      </view>

      <view class="bl-page-footer">
        <view class="bl-btn bl-btn--ghost bl-btn--block" role="button" @click="back">
          <text class="bl-page-footer__text">回到今日计划</text>
        </view>
      </view>
    </scroll-view>
  </view>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { settings } from '@/common/store.js'
import { toLunar } from '@/common/lunar.js'
import { daily, initDaily, effectiveEnabled } from '@/stores/daily.js'

/** 周一为一周起点（与原型一致） */
const WEEK = ['一', '二', '三', '四', '五', '六', '日']

const now = new Date()
/** 当前展示的年月（换月只改这两个值） */
const year = ref(now.getFullYear())
const month = ref(now.getMonth())
/** 当天 00:00 的时间戳，用于判断「今天」 */
const todayStamp = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
/** 用户点选的日期（戳 + 标签），默认不选 */
const picked = ref(null)

onMounted(() => {
  initDaily()
})

/**
 * 每天生效的日常计划条数。
 *
 * 注意：目前的「日常计划」是每天重复、还没接星期选择（见 stores/daily.js），
 * 所以每一天的条数就是「生效中的日常计划条数」。
 * 将来加了星期字段，这里按 date.getDay() 过滤即可，调用处不用改。
 */
const plansPerDay = computed(() => daily.items.filter((i) => effectiveEnabled(i)).length)

/**
 * 6 行 × 7 列固定网格。
 * 周一为起点：convertedDay() 是 JS 的「周日=0」，所以 (getDay() + 6) % 7 得到「周一=0」。
 */
const days = computed(() => {
  const first = new Date(year.value, month.value, 1)
  const lead = (first.getDay() + 6) % 7
  const daysInMonth = new Date(year.value, month.value + 1, 0).getDate()
  const prevMonthDays = new Date(year.value, month.value, 0).getDate()
  const out = []

  // 前置：上月末尾几天（灰显，不可点）
  for (let i = lead - 1; i >= 0; i -= 1) {
    out.push({ key: 'p' + i, label: String(prevMonthDays - i), inMonth: false })
  }
  // 本月
  for (let d = 1; d <= daysInMonth; d += 1) {
    const date = new Date(year.value, month.value, d)
    const stamp = date.getTime()
    const lunar = toLunar(date)
    out.push({
      key: 'c' + d,
      day: d,
      label: String(d),
      inMonth: true,
      stamp,
      isToday: stamp === todayStamp,
      lunarShort: lunar.day === 1 ? lunar.monthText : lunar.dayText,
      lunarFull: lunar.text,
      isFestival: lunar.day === 1,
      plans: plansPerDay.value
    })
  }
  // 后置：下月开头几天（灰显，不可点）
  const rest = 42 - out.length
  for (let d = 1; d <= rest; d += 1) {
    out.push({ key: 'n' + d, label: String(d), inMonth: false })
  }
  return out
})

const monthLabel = computed(() => `${year.value} 年 ${month.value + 1} 月`)

/** 点选某天后的说明卡内容 */
const pickedInfo = computed(() => {
  const p = picked.value
  if (!p) return null
  return {
    dateText: `${month.value + 1} 月 ${p.day} 日`,
    lunarText: p.lunarFull,
    plans: p.plans
  }
})

/** 本月里配置了日常计划的天数 */
const monthPlanDays = computed(() => days.value.filter((d) => d.inMonth && d.plans > 0).length)
/** 生效中的日常计划条数 */
const activePlanCount = computed(() => daily.items.filter((i) => effectiveEnabled(i)).length)

function shiftMonth(step) {
  const d = new Date(year.value, month.value + step, 1)
  year.value = d.getFullYear()
  month.value = d.getMonth()
  picked.value = null
}

function pick(d) {
  if (!d.inMonth) return
  picked.value = d
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
/* 日期格：竖向排「阳历数字 + 农历小字」，高度按内容给足 */
.bl-cal__day {
  width: 14.2857%;
  height: 132rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}
.bl-cal__day-inner {
  position: relative;
  width: 88rpx;
  min-height: 88rpx;
  border-radius: 20rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2rpx;
  box-sizing: border-box;
}
.bl-cal__day-text {
  font-size: var(--bl-font-body);
  font-weight: 600;
  color: var(--bl-text);
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}
/* 农历小字：初一显示月名（加主色，作为节日/月首锚点） */
.bl-cal__lunar {
  font-size: 20rpx;
  color: var(--bl-text-2);
  line-height: 1.1;
  white-space: nowrap;
}
.bl-cal__lunar.is-first {
  color: var(--bl-primary);
  font-weight: 600;
}

/* 非本月：灰显且不可点 */
.bl-cal__day.is-mute .bl-cal__day-text { color: #C9C4B6; }
.bl-cal__day.is-mute .bl-cal__lunar { color: transparent; }

/* 有计划的日子：底部小圆点（暖墨黄） */
.bl-cal__day.is-marked .bl-cal__day-inner::after {
  content: '';
  position: absolute;
  bottom: 2rpx;
  width: 8rpx;
  height: 8rpx;
  border-radius: 50%;
  background-color: var(--bl-warm);
}

/* 今天：实心主色圆底 + 暖白字 */
.bl-cal__day.is-today .bl-cal__day-inner {
  background-color: var(--bl-primary);
  border-radius: 50%;
}
.bl-cal__day.is-today .bl-cal__day-text { color: #FFFDF8; font-weight: 700; }
.bl-cal__day.is-today .bl-cal__lunar { color: #FFFDF8; opacity: .9; }
.bl-cal__day.is-today .bl-cal__day-inner::after { background-color: #FFFDF8; }

/* 已点选：描边高亮（不动今天/有计划的既有标识） */
.bl-cal__day.is-picked .bl-cal__day-inner {
  border: 3rpx solid var(--bl-primary);
}

/* 点选说明卡 */
.bl-cal-picked {
  margin: 0 var(--bl-space-lg) var(--bl-space-md);
  padding: 24rpx 32rpx;
  background-color: var(--bl-surface);
  border: 1rpx solid var(--bl-border);
  border-radius: var(--bl-radius-card);
  box-shadow: var(--bl-shadow-card);
  display: flex;
  flex-direction: column;
  gap: 8rpx;
  box-sizing: border-box;
}
.bl-cal-picked__date {
  font-size: var(--bl-font-body);
  font-weight: 700;
  color: var(--bl-text);
}
.bl-cal-picked__plans {
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
}
</style>