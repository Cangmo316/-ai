<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar title="每周计划" back solid @back="back" />

    <!-- 到点提醒要能在本页显示：老人常常就停在这一页等提醒 -->
    <bl-reminder-bar :item="reminder.banner" @open="onReminderOpen" @dismiss="dismissBanner" />

    <scroll-view class="bl-body" scroll-y>
      <!-- 还没有计划：只给一个添加入口 -->
      <view v-if="!items.length" class="bl-empty">
        <bl-icon name="cal" color="#B9B3A4" :size="120" />
        <text class="bl-empty__title">还没有每周计划</text>
        <text class="bl-empty__desc">点下面的按钮，把每周固定要做的事记下来</text>
      </view>

      <view v-else class="bl-weekly-wrap">
        <view class="bl-section-title--ink">
          <view class="bl-brush-rule" />
          <text class="bl-section-title__text">已经记下的（{{ items.length }} 条）</text>
        </view>

        <view class="bl-weekly-list">
          <!-- 与日常计划一致：名称加粗、时间与星期常规字重、右侧开关；长按可删除 -->
          <view
            v-for="item in items"
            :key="item.id"
            class="bl-weekly"
            :class="{ 'is-off': !effectiveEnabled(item) }"
            @longpress="confirmRemove(item)"
          >
            <view class="bl-weekly__main">
              <text class="bl-weekly__name">{{ item.name }}</text>
              <text class="bl-weekly__meta">{{ daysText(item.days) }} · {{ rangeText(item) }}</text>
              <text v-if="closureNote(item)" class="bl-weekly__note">{{ closureNote(item) }}</text>
            </view>

            <bl-switch
              :checked="effectiveEnabled(item)"
              @change="(v) => onToggle(item, v)"
            />
          </view>
        </view>

        <view class="bl-weekly-hint">
          <text class="bl-weekly-hint__text">按住一条不放，可以删除</text>
        </view>
      </view>

      <view class="bl-weekly-add">
        <view class="bl-btn bl-btn--primary bl-btn--block" role="button" aria-label="添加每周计划" @click="openForm">
          <text class="bl-btn__text">添加每周计划</text>
        </view>
      </view>
    </scroll-view>

    <!-- 添加弹层：文本框 + 一排星期 + 从/到 时间滚轮 -->
    <view v-if="formOpen" class="bl-sheet">
      <view class="bl-sheet__mask" @click="closeForm" />
      <view class="bl-sheet__panel">
        <view class="bl-sheet__head">
          <text class="bl-sheet__title">添加每周计划</text>
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

          <text class="bl-sheet__label">星期几（可多选）</text>
          <view class="bl-weeks">
            <view
              v-for="d in WEEKDAYS"
              :key="d"
              class="bl-week-chip"
              :class="{ 'is-on': form.days.indexOf(d) !== -1 }"
              role="button"
              :aria-label="'星期' + WEEK_LABELS[d - 1]"
              :aria-pressed="form.days.indexOf(d) !== -1 ? 'true' : 'false'"
              @click="toggleDay(d)"
            >
              <text class="bl-week-chip__text">{{ WEEK_LABELS[d - 1] }}</text>
            </view>
          </view>
          <text class="bl-weeks__note">已选：{{ selectedText }}</text>

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

    <!-- 跳过星期弹层 -->
    <view v-if="skipSheet.open" class="bl-sheet bl-sheet--top2">
      <view class="bl-sheet__mask" @click="skipSheet.open = false" />
      <view class="bl-sheet__panel">
        <view class="bl-sheet__head">
          <text class="bl-sheet__title">选择跳过的星期</text>
          <view class="bl-sheet__close" role="button" aria-label="关闭" @click="skipSheet.open = false">
            <text class="bl-sheet__close-text">✕</text>
          </view>
        </view>

        <text class="bl-sheet__lead">{{ skipSheet.name }}</text>

        <bl-week-pick v-model:picked="skipSheet.weekdays" :window="skipSheet.window" />

        <view class="bl-sheet__foot">
          <view class="bl-btn bl-btn--ghost bl-sheet__btn" role="button" @click="skipSheet.open = false">
            <text class="bl-page-footer__text">取消</text>
          </view>
          <view class="bl-btn bl-btn--primary bl-sheet__btn" role="button" @click="saveSkip">
            <text class="bl-btn__text bl-sheet__btn-text--on">确定（{{ skipSheet.weekdays.length }} 天）</text>
          </view>
        </view>
      </view>
    </view>

    <bl-tabbar active="plans" />
  </view>
</template>

<script setup>
/**
 * 每周计划页。
 *
 * 注意：列表数据放在页面自己的 ref 里，不把 store 的模块绑定直接放进模板——
 * 实测本项目的 uni-app H5 产物会把这个 store 内联进页面 chunk 并改名，
 * 导致模板里的模块绑定变成 undefined、整页白屏。所以统一用 store 函数
 * 返回的 items 副本来刷新本地 ref。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { settings } from '@/common/store.js'
import {
  addWeeklyPlan,
  closeForever,
  closeOnWeekdays,
  closeOnce,
  closureNote,
  daysText,
  effectiveEnabled,
  initWeekly,
  rangeText,
  removeWeeklyPlan,
  reopenPlan
} from '@/stores/week-plans.js'
import { dismissBanner, reminder, rescheduleLocalReminders } from '@/stores/reminder.js'

/** 点提醒条：去日程页看这条计划 */
function onReminderOpen() {
  dismissBanner()
  uni.showToast({ title: '到点会提醒你，先记下来', icon: 'none' })
}

/** 星期与时段：写成本地常量，模板直接用，避免任何模块绑定的不确定性 */
const WEEKDAYS = [1, 2, 3, 4, 5, 6, 7]
const WEEK_LABELS = ['一', '二', '三', '四', '五', '六', '日']

const items = ref([])

const formOpen = ref(false)
const form = reactive({
  name: '',
  days: [],
  time: { fromH: 8, fromM: 0, toH: 9, toM: 0 }
})

/** 关闭方式弹层 */
const closeSheet = reactive({ open: false, id: '', name: '' })
/** 跳过星期弹层 */
const skipSheet = reactive({ open: false, id: '', name: '', weekdays: [], window: { fromH: 0, fromM: 0 } })

const CLOSE_OPTIONS = [
  { key: 'once', title: '单次关闭', desc: '只关这一次，这个时段过完就自动打开' },
  { key: 'skip', title: '选择跳过', desc: '挑几个星期几不提醒，过完自动打开' },
  { key: 'forever', title: '永久关闭', desc: '一直不开，直到你自己再打开' }
]

const selectedText = computed(() => (form.days.length ? daysText(form.days) : '还没选'))

function refresh(next) {
  if (next) items.value = next
}

onMounted(() => {
  refresh(initWeekly())
  // 计划一到位就按最新计划排「开始/结束」两个提醒点
  rescheduleLocalReminders()
})

function openForm() {
  form.name = ''
  form.days = []
  form.time = { fromH: 8, fromM: 0, toH: 9, toM: 0 }
  formOpen.value = true
}

function closeForm() {
  formOpen.value = false
}

function toggleDay(d) {
  const at = form.days.indexOf(d)
  if (at === -1) form.days.push(d)
  else form.days.splice(at, 1)
  form.days.sort((a, b) => a - b)
}

function onTimeChange(next) {
  form.time = next
}

function save() {
  const res = addWeeklyPlan({
    name: form.name,
    days: form.days,
    fromH: form.time.fromH,
    fromM: form.time.fromM,
    toH: form.time.toH,
    toM: form.time.toM
  })
  if (!res.ok) {
    uni.showToast({ title: res.reason, icon: 'none' })
    return
  }
  refresh(res.items)
  rescheduleLocalReminders()
  formOpen.value = false
  uni.showToast({ title: '已添加', icon: 'none' })
}

/** 开关：打开即恢复；关闭要先问「怎么关」 */
function onToggle(item, value) {
  if (value) {
    refresh(reopenPlan(item.id))
  rescheduleLocalReminders()
    uni.showToast({ title: '已打开提醒', icon: 'none' })
    return
  }
  closeSheet.id = item.id
  closeSheet.name = item.name
  closeSheet.open = true
}

function pickClose(key) {
  const id = closeSheet.id
  const item = items.value.find((i) => i.id === id)
  if (!item) {
    closeSheet.open = false
    return
  }

  if (key === 'once') {
    refresh(closeOnce(id))
  rescheduleLocalReminders()
    closeSheet.open = false
    uni.showToast({ title: '这次先关掉，时段过后自动打开', icon: 'none' })
    return
  }

  if (key === 'forever') {
    refresh(closeForever(id))
  rescheduleLocalReminders()
    closeSheet.open = false
    uni.showToast({ title: '已永久关闭，想开就再点一下开关', icon: 'none' })
    return
  }

  closeSheet.open = false
  skipSheet.id = id
  skipSheet.name = item.name
  skipSheet.weekdays = (item.closedWeekdays || []).slice()
  skipSheet.window = { fromH: item.fromH, fromM: item.fromM }
  skipSheet.open = true
}

function saveSkip() {
  if (!skipSheet.weekdays.length) {
    uni.showToast({ title: '还没选星期', icon: 'none' })
    return
  }
  refresh(closeOnWeekdays(skipSheet.id, skipSheet.weekdays))
  rescheduleLocalReminders()
  const n = skipSheet.weekdays.length
  skipSheet.open = false
  uni.showToast({ title: '已跳过 ' + n + ' 天', icon: 'none' })
}

/** 删除：长按卡片，二次确认防误触 */
function confirmRemove(item) {
  uni.showModal({
    title: '删除这条计划？',
    content: item.name + '（' + daysText(item.days) + '）',
    confirmText: '删除',
    cancelText: '再想想',
    success(res) {
      if (!res.confirm) return
      refresh(removeWeeklyPlan(item.id))
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
.bl-weekly-list {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
  padding: 0 var(--bl-space-lg) var(--bl-space-md);
}
.bl-weekly-list .bl-section-title--ink {
  padding: 0 0 4rpx;
}

/* 与日常计划卡片完全同一套尺寸与层级 */
.bl-weekly {
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
.bl-weekly.is-off { opacity: .62; }

.bl-weekly__main { flex: 1; min-width: 0; }
/* 计划名称：加粗 */
.bl-weekly__name {
  display: block;
  font-size: var(--bl-font-body);
  font-weight: 700;
  color: var(--bl-text);
  line-height: 1.35;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
/* 星期与时间：正常字重 */
.bl-weekly__meta {
  display: block;
  font-size: var(--bl-font-caption);
  font-weight: 400;
  color: var(--bl-text-2);
  line-height: 1.4;
  margin-top: 6rpx;
  font-variant-numeric: tabular-nums;
}
/* 关闭状态说明 */
.bl-weekly__note {
  display: block;
  font-size: var(--bl-font-caption);
  font-weight: 400;
  color: var(--bl-warm);
  line-height: 1.4;
  margin-top: 4rpx;
}

.bl-weekly-hint { padding: 0 var(--bl-space-lg) var(--bl-space-sm); }
.bl-weekly-hint__text {
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
}
.bl-weekly-add {
  padding: 8rpx var(--bl-space-lg) var(--bl-space-xl);
}

/* ---------- 弹层 ---------- */
.bl-sheet {
  position: fixed;
  left: 0; right: 0; top: 0; bottom: 0;
  z-index: 70;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
}
.bl-sheet__mask {
  position: absolute;
  left: 0; right: 0; top: 0; bottom: 0;
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

/* 一排星期：等分 7 格，共边以拿到 ≥48px 宽度 */
.bl-weeks { display: flex; gap: 0; }
.bl-week-chip {
  flex: 1;
  min-width: 0;
  height: 96rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: #FFFFFF;
  border: 2rpx solid var(--bl-border-strong);
  border-left-width: 0;
  box-sizing: border-box;
}
.bl-week-chip:first-child {
  border-left-width: 2rpx;
  border-radius: var(--bl-radius-bubble) 0 0 var(--bl-radius-bubble);
}
.bl-week-chip:last-child {
  border-radius: 0 var(--bl-radius-bubble) var(--bl-radius-bubble) 0;
}
.bl-week-chip__text {
  font-size: var(--bl-font-body);
  font-weight: 600;
  color: #1F211D;
  line-height: 1;
}
/* 选中：墨底白字 */
.bl-week-chip.is-on {
  background-color: var(--bl-text);
  border-color: var(--bl-text);
}
.bl-week-chip.is-on .bl-week-chip__text { color: #FFFDF8; }
.bl-week-chip:active { opacity: .85; }

.bl-weeks__note {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  padding-top: var(--bl-space-sm);
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

/* 弹层层级：添加/关闭 < 跳过 */
.bl-sheet--top { z-index: 80; }
.bl-sheet--top2 { z-index: 90; }

.bl-sheet__foot {
  flex: none;
  display: flex;
  gap: var(--bl-space-md);
  padding-top: var(--bl-space-lg);
}
.bl-sheet__btn { flex: 1; }
.bl-sheet__btn-text--on { color: var(--bl-surface); }
</style>
