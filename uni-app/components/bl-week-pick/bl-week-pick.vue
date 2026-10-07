<template>
  <view class="bl-weekp">
    <!-- 一排七天：从今天起往后排，所以「已经过去的那几天」才存在 -->
    <view class="bl-weekp__row">
      <view
        v-for="d in days"
        :key="d.weekday"
        class="bl-weekp__day"
        :class="{ 'is-past': d.blocked, 'is-today': d.isToday, 'is-picked': d.picked }"
        :role="d.blocked ? '' : 'button'"
        :aria-label="d.blocked ? ('周' + d.label + '，' + d.reason) : ('周' + d.label)"
        :aria-pressed="d.picked ? 'true' : 'false'"
        @click="pick(d)"
      >
        <text class="bl-weekp__label">周{{ d.label }}</text>
      </view>
    </view>

    <text class="bl-weekp__tip">
      {{ hint }}
    </text>
  </view>
</template>

<script setup>
/**
 * 跳过星期选择。
 *
 * 配色规则（按需求指定）：
 *   · 已经过去的星期 —— 黑字白底，且不可点（这天这周已经过完了，跳过没有意义）
 *   · 今天及往后    —— 白字墨底
 *   · 点选之后      —— 白底黑字 + 描边（与日历选日的选中态一致）
 *
 * 排布：从「今天」开始往后 7 天，所以数组首项是今天，末项是「今天的前一天」。
 * 受控组件：选中集合由父级通过 v-model:picked 传入（元素是 1–7 的星期号）。
 *
 * 可选性规则：
 *   · 排在过去的那几天不可选（这周已经过完了，跳过没有意义）；
 *   · **今天若本轮已经开始**也不可选——提醒都已经发出去了，再跳过没有意义。
 *     判定用 windowStartedToday()，阈值与本地通知的最小提前量（30 秒）一致。
 */
import { computed } from 'vue'
import { WEEKDAY_LABELS, jsWeekday } from '@/stores/week-plans.js'
import { windowStartedToday } from '@/stores/reminder.js'

const props = defineProps({
  /** 已选中的星期号数组，如 [1, 3] */
  picked: { type: Array, default: () => [] },
  /** 该计划的开始时间 { fromH, fromM }，用于判断「今天本轮是否已开始」 */
  window: { type: Object, default: () => ({ fromH: 0, fromM: 0 }) }
})
const emit = defineEmits(['update:picked'])

const today = jsWeekday(new Date())

/** 从今天起往后的 7 天：blocked 表示不可选（已过去，或今天本轮已开始） */
const days = computed(() => {
  const out = []
  const todayStarted = windowStartedToday(props.window || {}, new Date())
  for (let i = 0; i < 7; i += 1) {
    const w = ((today - 1 + i) % 7) + 1 // 1..7 循环
    const raw = today + i
    const past = raw > 7 // 排在今天之前的那些项 = 本周已经过去的星期
    const isToday = i === 0
    const startedToday = isToday && todayStarted
    out.push({
      weekday: w,
      label: WEEKDAY_LABELS[w - 1],
      isToday,
      past,
      blocked: past || startedToday,
      reason: past ? '已经过了' : (startedToday ? '这轮已经开始了' : ''),
      picked: props.picked.indexOf(w) !== -1
    })
  }
  return out
})

const hint = computed(() => {
  if (windowStartedToday(props.window || {}, new Date())) {
    return '今天这一轮已经开始了，只能跳过往后的日子'
  }
  const n = props.picked.length
  if (!n) return '点日期选择要跳过的星期几（可多选）'
  return '已选 ' + n + ' 天'
})

function pick(d) {
  if (d.blocked) {
    uni.showToast({ title: '周' + d.label + d.reason, icon: 'none' })
    return
  }
  const set = props.picked.slice()
  const at = set.indexOf(d.weekday)
  if (at === -1) set.push(d.weekday)
  else set.splice(at, 1)
  set.sort((a, b) => a - b)
  emit('update:picked', set)
}
</script>

<style scoped>
.bl-weekp__row {
  display: flex;
  gap: 0;
}
/* 七格等分：面板内容宽约 356.75px ÷ 7 ≈ 51px（≥48px 触控下限） */
.bl-weekp__day {
  flex: 1;
  min-width: 0;
  height: 96rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  /* 默认＝今天及往后：白字墨底 */
  background-color: var(--bl-text);
  border: 2rpx solid var(--bl-text);
  border-left-width: 0;
  box-sizing: border-box;
}
.bl-weekp__day:first-child {
  border-left-width: 2rpx;
  border-radius: var(--bl-radius-bubble) 0 0 var(--bl-radius-bubble);
}
.bl-weekp__day:last-child {
  border-radius: 0 var(--bl-radius-bubble) var(--bl-radius-bubble) 0;
}
.bl-weekp__label {
  font-size: var(--bl-font-caption);
  font-weight: 600;
  color: #FFFDF8;
  line-height: 1;
  white-space: nowrap;
}

/* 已经过去的星期：黑字白底，不可点 */
.bl-weekp__day.is-past {
  background-color: #FFFFFF;
  border-color: var(--bl-border-strong);
}
.bl-weekp__day.is-past .bl-weekp__label {
  color: #1F211D;
  opacity: .45;
}

/* 点选之后：白底黑字 + 描边（与日历选日一致） */
.bl-weekp__day.is-picked {
  background-color: #FFFFFF;
  border-color: var(--bl-border-strong);
}
.bl-weekp__day.is-picked .bl-weekp__label {
  color: #1F211D;
  opacity: 1;
}

.bl-weekp__tip {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  padding-top: var(--bl-space-sm);
}
</style>
