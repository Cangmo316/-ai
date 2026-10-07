<template>
  <view class="bl-timewheel">
    <!-- 行一：从 -->
    <view class="bl-timewheel__row">
      <text class="bl-timewheel__lead">从</text>
      <picker-view
        class="bl-timewheel__wheels"
        :value="fromIndexes"
        indicator-style="height: 76rpx;"
        @change="onFromChange"
      >
        <picker-view-column>
          <view v-for="h in HOURS" :key="'fh' + h" class="bl-timewheel__cell">
            <text class="bl-timewheel__text">{{ pad(h) }}</text>
          </view>
        </picker-view-column>
        <picker-view-column>
          <view v-for="m in MINUTES" :key="'fm' + m" class="bl-timewheel__cell">
            <text class="bl-timewheel__text">{{ pad(m) }}</text>
          </view>
        </picker-view-column>
      </picker-view>
      <text class="bl-timewheel__unit">时 / 分</text>
    </view>

    <!-- 行二：到 -->
    <view class="bl-timewheel__row">
      <text class="bl-timewheel__lead">到</text>
      <picker-view
        class="bl-timewheel__wheels"
        :value="toIndexes"
        indicator-style="height: 76rpx;"
        @change="onToChange"
      >
        <picker-view-column>
          <view v-for="h in HOURS" :key="'th' + h" class="bl-timewheel__cell">
            <text class="bl-timewheel__text">{{ pad(h) }}</text>
          </view>
        </picker-view-column>
        <picker-view-column>
          <view v-for="m in MINUTES" :key="'tm' + m" class="bl-timewheel__cell">
            <text class="bl-timewheel__text">{{ pad(m) }}</text>
          </view>
        </picker-view-column>
      </picker-view>
      <text class="bl-timewheel__unit">时 / 分</text>
    </view>
  </view>
</template>

<script setup>
/**
 * 双行时间滚轮：「从」与「到」，每行各一列小时 + 一列分钟。
 *
 * 为什么用 picker-view 而不是 input type=time：
 * 老人对系统时间选择器（小键盘/滚轮弹窗）不熟，且它每端的样式不一致；
 * picker-view 是三端一致的滚轮，上下滑动改时间，符合"手指划一下"的直觉。
 *
 * 分钟按 5 分钟一档（见 stores/daily.js 的 MINUTES），滑起来省力。
 *
 * 用法：
 *   <bl-time-wheel :config="form" @change="onTimeChange" />
 *   config = { fromH, fromM, toH, toM }
 */
import { computed } from 'vue'
import { HOURS, MINUTES } from '@/stores/daily.js'

const props = defineProps({
  config: {
    type: Object,
    default: () => ({ fromH: 8, fromM: 0, toH: 9, toM: 0 })
  }
})

const emit = defineEmits(['change'])

const pad = (n) => String(n).padStart(2, '0')

/** picker-view 要的是「第几项」而不是值本身，所以做一次值→下标的换算 */
const hourIndex = (h) => {
  const i = HOURS.indexOf(Number(h))
  return i === -1 ? 0 : i
}
const minuteIndex = (m) => {
  const i = MINUTES.indexOf(Number(m))
  return i === -1 ? 0 : i
}

const fromIndexes = computed(() => [hourIndex(props.config.fromH), minuteIndex(props.config.fromM)])
const toIndexes = computed(() => [hourIndex(props.config.toH), minuteIndex(props.config.toM)])

function onFromChange(e) {
  const [hi, mi] = e.detail.value
  emit('change', Object.assign({}, props.config, {
    fromH: HOURS[hi],
    fromM: MINUTES[mi]
  }))
}

function onToChange(e) {
  const [hi, mi] = e.detail.value
  emit('change', Object.assign({}, props.config, {
    toH: HOURS[hi],
    toM: MINUTES[mi]
  }))
}
</script>

<style scoped>
.bl-timewheel {
  display: flex;
  flex-direction: column;
  gap: var(--bl-space-sm);
}

.bl-timewheel__row {
  display: flex;
  align-items: center;
  gap: var(--bl-space-md);
  background-color: var(--bl-surface);
  border: 1rpx solid var(--bl-border);
  border-radius: var(--bl-radius-bubble);
  padding: 0 var(--bl-space-md);
  box-sizing: border-box;
}

/* 「从」/「到」：18px，一眼看清这一行在设什么 */
.bl-timewheel__lead {
  flex: none;
  font-size: var(--bl-font-body);
  font-weight: 700;
  color: var(--bl-primary);
  /* 与滚轮选中项对齐（滚轮高 76rpx 的两倍，文字居中在中间那一格） */
  line-height: 152rpx;
}

.bl-timewheel__wheels {
  flex: 1;
  min-width: 0;
  height: 228rpx;
}

.bl-timewheel__cell {
  height: 76rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 滚轮里的数字：20px 加粗，老人看得清 */
.bl-timewheel__text {
  font-size: var(--bl-font-title);
  font-weight: 700;
  color: var(--bl-text);
  font-variant-numeric: tabular-nums;
}

.bl-timewheel__unit {
  flex: none;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
}
</style>
