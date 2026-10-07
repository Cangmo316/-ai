<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar title="日常计划" back solid @back="back" />

    <!-- 到点提醒要能在本页显示：老人常常就停在这一页等提醒 -->
    <bl-reminder-bar :item="reminder.banner" @open="onReminderOpen" @dismiss="dismissBanner" />

    <scroll-view class="bl-body" scroll-y>
      <!-- 还没有计划：给一句人话 + 一个明确入口 -->
      <view v-if="!daily.items.length" class="bl-empty">
        <bl-icon name="clock" color="#B9B3A4" :size="120" />
        <text class="bl-empty__title">还没有日常计划</text>
        <text class="bl-empty__desc">点下面的按钮，把每天要做的事记下来</text>
      </view>

      <template v-else>
        <view class="bl-section-title--ink">
          <view class="bl-brush-rule" />
          <text class="bl-section-title__text">已经记下的（{{ daily.items.length }} 条）</text>
        </view>

        <view class="bl-daily-list">
          <!-- 计划名加粗、时间常规字重、右侧开关控制是否生效；长按可删除 -->
          <view
            v-for="item in daily.items"
            :key="item.id"
            class="bl-daily"
            :class="{ 'is-off': !isActive(item) }"
            @longpress="confirmRemove(item)"
          >
            <view class="bl-daily__main">
              <text class="bl-daily__name">{{ item.name }}</text>
              <text class="bl-daily__time">{{ rangeText(item) }}</text>
              <text v-if="closureNote(item)" class="bl-daily__note">{{ closureNote(item) }}</text>
            </view>

            <bl-switch
              :checked="effectiveEnabled(item)"
              @change="(v) => onToggle(item, v)"
            />
          </view>
        </view>

        <view class="bl-daily-hint">
          <text class="bl-daily-hint__text">按住一条不放，可以删除</text>
        </view>
      </template>

      <view class="bl-daily-add">
        <view class="bl-btn bl-btn--primary bl-btn--block" role="button" aria-label="添加日常计划" @click="openForm">
          <text class="bl-btn__text">添加日常计划</text>
        </view>
      </view>
    </scroll-view>

    <!-- 添加弹层：底部升起，遮住页面但保留关闭方式（点遮罩 / 取消） -->
    <view v-if="formOpen" class="bl-sheet">
      <view class="bl-sheet__mask" @click="closeForm" />
      <view class="bl-sheet__panel">
        <view class="bl-sheet__head">
          <text class="bl-sheet__title">添加日常计划</text>
          <view class="bl-sheet__close" role="button" aria-label="关闭" @click="closeForm">
            <text class="bl-sheet__close-text">✕</text>
          </view>
        </view>

        <scroll-view class="bl-sheet__body" scroll-y>
          <text class="bl-sheet__label">计划名称</text>
          <input
            v-model="form.name"
            class="bl-sheet__input"
            placeholder="请输入计划名称"
            placeholder-class="bl-input-ph"
            :maxlength="20"
            confirm-type="done"
          />

          <text class="bl-sheet__label">时间</text>
          <bl-time-wheel :config="form.time" @change="onTimeChange" />
        </scroll-view>

        <view class="bl-sheet__foot">
          <view class="bl-btn bl-btn--ghost bl-sheet__btn" role="button" @click="closeForm">
            <text class="bl-page-footer__text">取消</text>
          </view>
          <view class="bl-btn bl-btn--primary bl-sheet__btn" role="button" @click="save">
            <text class="bl-btn__text bl-sheet__btn-text--on">保存</text>
          </view>
        </view>
      </view>
    </view>

    <!-- 关闭方式弹层：点开关关掉时先问「怎么关」 -->
    <view v-if="closeSheet.open" class="bl-sheet bl-sheet--top">
      <view class="bl-sheet__mask" @click="closeSheet.open = false" />
      <view class="bl-sheet__panel">
        <view class="bl-sheet__head">
          <text class="bl-sheet__title">{{ closeSheet.name }}</text>
          <view class="bl-sheet__close" role="button" aria-label="关闭" @click="closeSheet.open = false">
            <text class="bl-sheet__close-text">✕</text>
          </view>
        </view>

        <text class="bl-sheet__lead">这条提醒怎么关？</text>

        <view class="bl-close-list">
          <view
            v-for="opt in CLOSE_OPTIONS"
            :key="opt.key"
            class="bl-close-opt"
            role="button"
            :aria-label="opt.title + '，' + opt.desc"
            @click="pickClose(opt.key)"
          >
            <view class="bl-close-opt__main">
              <text class="bl-close-opt__title">{{ opt.title }}</text>
              <text class="bl-close-opt__desc">{{ opt.desc }}</text>
            </view>
            <bl-icon name="chev" color="#B9B3A4" :size="32" />
          </view>
        </view>
      </view>
    </view>

    <!-- 日历选日弹层 -->
    <view v-if="calSheet.open" class="bl-sheet bl-sheet--top2">
      <view class="bl-sheet__mask" @click="calSheet.open = false" />
      <view class="bl-sheet__panel">
        <view class="bl-sheet__head">
          <text class="bl-sheet__title">选择关闭日期</text>
          <view class="bl-sheet__close" role="button" aria-label="关闭" @click="calSheet.open = false">
            <text class="bl-sheet__close-text">✕</text>
          </view>
        </view>

        <text class="bl-sheet__lead">{{ calSheet.name }}</text>

        <bl-calendar-pick v-model:picked="calSheet.dates" :window="calSheet.window" />

        <view class="bl-sheet__foot">
          <view class="bl-btn bl-btn--ghost bl-sheet__btn" role="button" @click="calSheet.open = false">
            <text class="bl-page-footer__text">取消</text>
          </view>
          <view class="bl-btn bl-btn--primary bl-sheet__btn" role="button" @click="saveDates">
            <text class="bl-btn__text bl-sheet__btn-text--on">确定（{{ calSheet.dates.length }} 天）</text>
          </view>
        </view>
      </view>
    </view>

    <bl-tabbar active="plans" />
  </view>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { settings } from '@/common/store.js'
import {
  addDailyPlan,
  closeForever,
  closeOnce,
  closeOnDates,
  closureNote,
  daily,
  effectiveEnabled,
  initDaily,
  rangeText,
  removeDailyPlan,
  reopenPlan
} from '@/stores/daily.js'
import {
  dismissBanner,
  reminder,
  rescheduleLocalReminders
} from '@/stores/reminder.js'

/** 点提醒条：去日程页看这条计划 */
function onReminderOpen() {
  dismissBanner()
  uni.showToast({ title: '到点会提醒你，先记下来', icon: 'none' })
}

const formOpen = ref(false)
const form = reactive({
  name: '',
  time: { fromH: 8, fromM: 0, toH: 9, toM: 0 }
})

/** 关闭方式弹层 */
const closeSheet = reactive({ open: false, id: '', name: '' })
/** 日历选日弹层 */
const calSheet = reactive({ open: false, id: '', name: '', dates: [], window: { fromH: 0, fromM: 0 } })

const CLOSE_OPTIONS = [
  {
    key: 'once',
    title: '单次关闭',
    desc: '只关这一次，这个时段过完就自动打开'
  },
  {
    key: 'dates',
    title: '日历选择关闭',
    desc: '挑几天不开提醒，过完自动打开'
  },
  {
    key: 'forever',
    title: '永久关闭',
    desc: '一直不开，直到你自己再打开'
  }
]

onMounted(() => {
  initDaily()
  // 计划一到位就按最新计划排「开始/结束」两个提醒点
  rescheduleLocalReminders()
})

function openForm() {
  // 每次打开都回到干净状态，避免上一条的残留
  form.name = ''
  form.time = { fromH: 8, fromM: 0, toH: 9, toM: 0 }
  formOpen.value = true
}

function closeForm() {
  formOpen.value = false
}

function onTimeChange(next) {
  form.time = next
}

function save() {
  const res = addDailyPlan({
    name: form.name,
    fromH: form.time.fromH,
    fromM: form.time.fromM,
    toH: form.time.toH,
    toM: form.time.toM
  })
  if (!res.ok) {
    uni.showToast({ title: res.reason, icon: 'none' })
    return
  }
  formOpen.value = false
  rescheduleLocalReminders()
  uni.showToast({ title: '已添加', icon: 'none' })
}

/**
 * 开关：打开就是直接恢复；关闭要先问「怎么关」——
 * 单次 / 日历选几天 / 永久，三种语义完全不同，不能让老人自己猜。
 */
function onToggle(item, value) {
  if (value) {
    reopenPlan(item.id)
    rescheduleLocalReminders()
    uni.showToast({ title: '已打开提醒', icon: 'none' })
    return
  }
  closeSheet.id = item.id
  closeSheet.name = item.name
  closeSheet.open = true
}

/** 卡片是否按"生效中"显示。与开关同一判据，避免开关关着而卡片还是亮的 */
function isActive(item) {
  return effectiveEnabled(item)
}

function pickClose(key) {
  const id = closeSheet.id
  const item = daily.items.find((i) => i.id === id)
  if (!item) {
    closeSheet.open = false
    return
  }

  if (key === 'once') {
    closeOnce(id)
    rescheduleLocalReminders()
    closeSheet.open = false
    uni.showToast({ title: '这次先关掉，时段过后自动打开', icon: 'none' })
    return
  }

  if (key === 'forever') {
    closeForever(id)
    rescheduleLocalReminders()
    closeSheet.open = false
    uni.showToast({ title: '已永久关闭，想开就再点一下开关', icon: 'none' })
    return
  }

  // 日历选择：带上已有的关闭日期，方便继续加
  closeSheet.open = false
  calSheet.id = id
  calSheet.name = item.name
  calSheet.dates = (item.closedDates || []).slice()
  calSheet.window = { fromH: item.fromH, fromM: item.fromM }
  calSheet.open = true
}

function saveDates() {
  if (!calSheet.dates.length) {
    uni.showToast({ title: '还没选日期', icon: 'none' })
    return
  }
  closeOnDates(calSheet.id, calSheet.dates)
  const n = calSheet.dates.length
  rescheduleLocalReminders()
  calSheet.open = false
  uni.showToast({ title: '已关闭 ' + n + ' 天', icon: 'none' })
}

/** 删除：长按卡片，二次确认防误触（老人手抖，不做滑动删除） */
function confirmRemove(item) {
  uni.showModal({
    title: '删除这条计划？',
    content: item.name,
    confirmText: '删除',
    cancelText: '再想想',
    success(res) {
      if (!res.confirm) return
      removeDailyPlan(item.id)
      rescheduleLocalReminders()
      uni.showToast({ title: '已删除', icon: 'none' })
    }
  })
}

function back() {
  const pages = getCurrentPages()
  if (pages.length > 1) uni.navigateBack()
  else uni.reLaunch({ url: '/pages/plans/plans' })
}
</script>

<style scoped>
.bl-daily-list {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
  padding: 0 var(--bl-space-lg) var(--bl-space-md);
}
.bl-daily-list .bl-section-title--ink {
  padding: 0 0 4rpx;
}

.bl-daily {
  display: flex;
  align-items: center;
  gap: 24rpx;
  padding: 28rpx 32rpx;
  min-height: 132rpx;
  background-color: var(--bl-surface);
  border: 1rpx solid var(--bl-border);
  border-radius: var(--bl-radius-card);
  box-shadow: var(--bl-shadow-card);
  box-sizing: border-box;
}
/* 关闭状态：整卡降对比但文字仍可读（禁用态不参与对比度门槛，但别让老人看不清） */
.bl-daily.is-off { opacity: .62; }

.bl-daily__main { flex: 1; min-width: 0; }
/* 计划名称：加粗 */
.bl-daily__name {
  display: block;
  font-size: var(--bl-font-body);
  font-weight: 700;
  color: var(--bl-text);
  line-height: 1.35;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
/* 时间：正常字重，跟在名称后面一行 */
.bl-daily__time {
  display: block;
  font-size: var(--bl-font-caption);
  font-weight: 400;
  color: var(--bl-text-2);
  line-height: 1.4;
  margin-top: 6rpx;
  font-variant-numeric: tabular-nums;
}
/* 关闭状态说明：告诉老人为什么现在是关的、什么时候会自己打开 */
.bl-daily__note {
  display: block;
  font-size: var(--bl-font-caption);
  font-weight: 400;
  color: var(--bl-warm);
  line-height: 1.4;
  margin-top: 4rpx;
}

/* ---------- 三种关闭方式 ---------- */
.bl-sheet__lead {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  padding-bottom: var(--bl-space-sm);
}

.bl-close-list {
  display: flex;
  flex-direction: column;
  gap: var(--bl-space-sm);
}
.bl-close-opt {
  display: flex;
  align-items: center;
  gap: var(--bl-space-md);
  padding: 28rpx 32rpx;
  min-height: 132rpx;
  background-color: var(--bl-surface);
  border: 1rpx solid var(--bl-border);
  border-radius: var(--bl-radius-card);
  box-sizing: border-box;
}
.bl-close-opt:active {
  background-color: var(--bl-surface-2);
  border-color: var(--bl-border-strong);
}
.bl-close-opt__main { flex: 1; min-width: 0; }
.bl-close-opt__title {
  display: block;
  font-size: var(--bl-font-body);
  font-weight: 700;
  color: var(--bl-text);
  line-height: 1.35;
}
.bl-close-opt__desc {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  line-height: 1.5;
  margin-top: 6rpx;
}

/* 三级弹层的层级：关闭方式 < 日历选日 */
.bl-sheet--top { z-index: 70; }
.bl-sheet--top2 { z-index: 80; }

.bl-daily-hint {
  padding: 0 var(--bl-space-lg) var(--bl-space-sm);
}
.bl-daily-hint__text {
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
}

.bl-daily-add {
  padding: 8rpx var(--bl-space-lg) var(--bl-space-xl);
}

/* ---------- 底部弹层 ---------- */
.bl-sheet {
  position: fixed;
  left: 0;
  right: 0;
  top: 0;
  bottom: 0;
  z-index: 60;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
}
.bl-sheet__mask {
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  bottom: 0;
  background-color: var(--bl-overlay);
}
.bl-sheet__panel {
  position: relative;
  background-color: var(--bl-bg);
  border-radius: 32rpx 32rpx 0 0;
  padding: var(--bl-space-lg) var(--bl-space-lg) calc(var(--bl-space-lg) + env(safe-area-inset-bottom));
  box-sizing: border-box;
  max-height: 88vh;
  display: flex;
  flex-direction: column;
}
.bl-sheet__head {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: var(--bl-space-md);
}
.bl-sheet__title {
  font-size: var(--bl-font-title);
  font-weight: 700;
  color: var(--bl-text);
}
/* 关闭按钮：触控 48px */
.bl-sheet__close {
  width: var(--bl-touch);
  height: var(--bl-touch);
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
}
.bl-sheet__close:active { background-color: var(--bl-primary-soft); }
.bl-sheet__close-text {
  font-size: var(--bl-font-title);
  color: var(--bl-text-2);
  line-height: 1;
}

.bl-sheet__body { flex: 1; min-height: 0; }

.bl-sheet__label {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  letter-spacing: .04em;
  margin: var(--bl-space-md) 0 var(--bl-space-sm);
}
.bl-sheet__label:first-child { margin-top: 0; }

/* 输入框：正文 16px，高度 ≥48px，实心暖白底 + 表意描边 */
.bl-sheet__input {
  width: 100%;
  height: 104rpx;
  padding: 0 var(--bl-space-md);
  box-sizing: border-box;
  background-color: var(--bl-surface);
  border: 2rpx solid var(--bl-border-strong);
  border-radius: var(--bl-radius-bubble);
  font-size: var(--bl-font-body);
  color: var(--bl-text);
}
/* 占位符色见 App.vue 的 .bl-input-ph（uni H5 的占位符元素在 scoped 作用域之外） */

.bl-sheet__foot {
  flex: none;
  display: flex;
  gap: var(--bl-space-md);
  padding-top: var(--bl-space-lg);
}
.bl-sheet__btn { flex: 1; }
.bl-sheet__btn-text--on { color: var(--bl-surface); }
</style>
