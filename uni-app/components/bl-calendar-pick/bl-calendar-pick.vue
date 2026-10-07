<template>
  <view class="bl-calp">
    <!-- 月份切换 -->
    <view class="bl-calp__head">
      <view class="bl-calp__nav" role="button" aria-label="上一月" @click="shift(-1)">
        <bl-icon name="back" color="#1F211D" :size="40" />
      </view>
      <text class="bl-calp__month">{{ year }} 年 {{ month + 1 }} 月</text>
      <view class="bl-calp__nav" role="button" aria-label="下一月" @click="shift(1)">
        <bl-icon name="chev" color="#1F211D" :size="40" />
      </view>
    </view>

    <!-- 星期表头 -->
    <view class="bl-calp__week">
      <text v-for="w in WEEK" :key="w" class="bl-calp__week-item">{{ w }}</text>
    </view>

    <!-- 日期格 -->
    <view class="bl-calp__grid">
      <view
        v-for="(cell, i) in cells"
        :key="i"
        class="bl-calp__day"
        :class="{
          'is-empty': !cell.day,
          'is-today': cell.isToday,
          'is-blocked': cell.blocked,
          'is-picked': cell.day && picked.indexOf(cell.key) !== -1
        }"
        :role="cell.day && !cell.blocked ? 'button' : ''"
        @click="pick(cell)"
      >
        <text class="bl-calp__day-text">{{ cell.label }}</text>
      </view>
    </view>

    <text class="bl-calp__tip">{{ todayStarted ? '今天这一轮已经开始了，只能关往后的日子' : '点日期选择要关闭的这一天（可多选）' }}</text>
  </view>
</template>

<script setup>
/**
 * 选择关闭日期的日历。
 *
 * 配色按需求指定：
 *   · 可点的日期 —— 绿底 + 白字
 *   · 今天       —— 绿底 + 红字（比白字更抢眼，一眼找到"今天"）
 *   · 点选之后   —— 白底 + 黑字（明确的"已选中"）
 *   · 非本月日期 —— 不可点，灰字
 *
 * 受控组件：选中集合由父级通过 v-model:picked 传入，本组件只负责点选与换月。
 *
 * 可选性：**今天若本轮已经开始，则不可选**——提醒都发出去了，再关闭没有意义。
 * 阈值与本地通知的最小提前量（30 秒）一致，见 stores/week-plans.js 的 windowStartedToday。
 */
import { computed, ref } from 'vue'
import { dayKey } from '@/stores/daily.js'
import { windowStartedToday } from '@/stores/reminder.js'

const props = defineProps({
  /** 已选中的日期数组 ['YYYY-MM-DD'] */
  picked: { type: Array, default: () => [] },
  /** 该计划的开始时间 { fromH, fromM }，用于判断「今天本轮是否已开始」 */
  window: { type: Object, default: () => ({ fromH: 0, fromM: 0 }) }
})
const emit = defineEmits(['update:picked'])

const WEEK = ['日', '一', '二', '三', '四', '五', '六']
const now = new Date()
const year = ref(now.getFullYear())
const month = ref(now.getMonth())
const todayKey = dayKey(now)

/** 今天这一轮是否已开始（只有今天受影响） */
const todayStarted = computed(() => windowStartedToday(props.window || {}, new Date()))

/** 6 行 × 7 列固定网格：月份切换时高度不跳 */
const cells = computed(() => {
  const first = new Date(year.value, month.value, 1)
  const daysInMonth = new Date(year.value, month.value + 1, 0).getDate()
  const lead = first.getDay()
  const list = []
  for (let i = 0; i < 42; i += 1) {
    const dayNum = i - lead + 1
    if (dayNum < 1 || dayNum > daysInMonth) {
      list.push({ day: 0, label: '', key: '', isToday: false, blocked: false })
      continue
    }
    const d = new Date(year.value, month.value, dayNum)
    const key = dayKey(d)
    const isToday = key === todayKey
    list.push({
      day: dayNum,
      label: String(dayNum),
      key,
      isToday,
      blocked: isToday && todayStarted.value
    })
  }
  return list
})

function shift(step) {
  const d = new Date(year.value, month.value + step, 1)
  year.value = d.getFullYear()
  month.value = d.getMonth()
}

function pick(cell) {
  if (!cell.day) return // 非本月日期不可点
  if (cell.blocked) {
    uni.showToast({ title: '今天这一轮已经开始了', icon: 'none' })
    return
  }
  const set = props.picked.slice()
  const at = set.indexOf(cell.key)
  if (at === -1) set.push(cell.key)
  else set.splice(at, 1)
  set.sort()
  emit('update:picked', set)
}
</script>

<style scoped>
.bl-calp__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: var(--bl-space-sm);
}
.bl-calp__nav {
  width: var(--bl-touch);
  height: var(--bl-touch);
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
}
.bl-calp__nav:active { background-color: var(--bl-primary-soft); }
.bl-calp__month {
  font-size: var(--bl-font-body);
  font-weight: 700;
  color: var(--bl-text);
}

.bl-calp__week {
  display: flex;
  padding: var(--bl-space-xs) 0;
}
.bl-calp__week-item {
  flex: 1;
  text-align: center;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
}

.bl-calp__grid {
  display: flex;
  flex-wrap: wrap;
}

/* 每个格子占 1/7；内部留 4rpx 间隙做"圆点块"的观感 */
.bl-calp__day {
  width: 14.285%;
  padding: 4rpx;
  box-sizing: border-box;
}
.bl-calp__day-text {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 76rpx;
  border-radius: 12rpx;
  font-size: var(--bl-font-body);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  /* 默认＝可点的日期：绿底白字 */
  background-color: var(--bl-cal-on);
  color: #FFFFFF;
}
/* 今天：浅绿底 + 深红字。
   红字压在深绿底上对比度只有 3.17:1（红绿亮度太接近，数学上无解），
   改浅绿底后红字 5.06:1 达标，红字观感保留。 */
.bl-calp__day.is-today .bl-calp__day-text {
  background-color: var(--bl-cal-on-today);
  color: var(--bl-cal-today);
  border: 2rpx solid var(--bl-cal-today);
}
/* 已选中：白底黑字 */
.bl-calp__day.is-picked .bl-calp__day-text {
  background-color: #FFFFFF;
  color: #1F211D;
  border: 2rpx solid var(--bl-border-strong);
}
/* 非本月：不可点 */
.bl-calp__day.is-empty .bl-calp__day-text {
  background-color: transparent;
  color: var(--bl-cal-off);
}
.bl-calp__tip {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  padding-top: var(--bl-space-sm);
}
</style>
