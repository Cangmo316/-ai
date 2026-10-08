<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar title="特殊计划" back solid @back="back" />

    <!-- 到点提醒要能在本页显示：老人常常就停在这一页等提醒 -->
    <bl-reminder-bar :item="reminder.banner" @open="onReminderOpen" @dismiss="dismissBanner" />

    <scroll-view class="bl-body" scroll-y>
      <!-- 还没有计划：给一句人话 + 一个明确入口 -->
      <view v-if="!special.items.length" class="bl-empty">
        <bl-icon name="heart" color="#B9B3A4" :size="120" />
        <text class="bl-empty__title">还没有特殊计划</text>
        <text class="bl-empty__desc">生日、体检、走亲戚…挑好日子记在这里，到那天提醒你</text>
      </view>

      <template v-else>
        <view class="bl-section-title--ink">
          <view class="bl-brush-rule" />
          <text class="bl-section-title__text">已经记下的（{{ special.items.length }} 条）</text>
        </view>

        <view class="bl-daily-list">
          <!-- 日期是这条计划的主信息，所以放在名称下面第一行、并用强调色；
               长按可删除；右侧开关控制是否提醒 -->
          <view
            v-for="item in special.items"
            :key="item.id"
            class="bl-daily"
            :class="{ 'is-off': !isActive(item), 'is-today': isToday(item) }"
            @longpress="confirmRemove(item)"
          >
            <view class="bl-daily__main">
              <text class="bl-daily__name">{{ item.name }}</text>
              <text class="bl-daily__date">
                {{ dateText(item.date) }}
                <text v-if="relativeText(item.date)" class="bl-daily__rel">· {{ relativeText(item.date) }}</text>
              </text>
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
        <view class="bl-btn bl-btn--primary bl-btn--block" role="button" aria-label="添加特殊计划" @click="openForm">
          <text class="bl-btn__text">添加特殊计划</text>
        </view>
      </view>
    </scroll-view>

    <!-- 添加弹层：比日常计划多了「日期」一项 -->
    <view v-if="formOpen" class="bl-sheet">
      <view class="bl-sheet__mask" @click="closeForm" />
      <view class="bl-sheet__panel">
        <view class="bl-sheet__head">
          <text class="bl-sheet__title">添加特殊计划</text>
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
            :maxlength="NAME_MAX"
            confirm-type="done"
          />

          <!-- 与日常计划的唯一差别：先选具体哪一天 -->
          <text class="bl-sheet__label">哪一天</text>
          <view
            class="bl-date-field"
            :class="{ 'is-empty': !form.date }"
            role="button"
            aria-label="选择日期"
            @click="openDatePick"
          >
            <text class="bl-date-field__text">
              {{ form.date ? dateText(form.date) + '（' + relativeText(form.date) + '）' : '点这里选日期' }}
            </text>
            <!-- 用 calmonth（纯日历卷轴）而不是 cal：
                 cal 的图形里画了一条折线（给「日程/健康」用的），
                 放在「选日期」旁边会被看成折线图标，反而不像日历。 -->
            <bl-icon name="calmonth" color="#8C8778" :size="40" />
          </view>

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

    <!-- 选日期弹层（单选模式） -->
    <view v-if="dateSheet.open" class="bl-sheet bl-sheet--top">
      <view class="bl-sheet__mask" @click="dateSheet.open = false" />
      <view class="bl-sheet__panel">
        <view class="bl-sheet__head">
          <text class="bl-sheet__title">选择日期</text>
          <view class="bl-sheet__close" role="button" aria-label="关闭" @click="dateSheet.open = false">
            <text class="bl-sheet__close-text">✕</text>
          </view>
        </view>

        <bl-calendar-pick v-model:picked="dateSheet.picked" mode="single" />

        <view class="bl-sheet__foot">
          <view class="bl-btn bl-btn--ghost bl-sheet__btn" role="button" @click="dateSheet.open = false">
            <text class="bl-page-footer__text">取消</text>
          </view>
          <view class="bl-btn bl-btn--primary bl-sheet__btn" role="button" @click="saveDate">
            <text class="bl-btn__text bl-sheet__btn-text--on">确定</text>
          </view>
        </view>
      </view>
    </view>

    <!-- 关闭前先确认：这条计划只有一次，"这次不提醒"其实就是"以后都不提醒"，
         所以不做多选项，只让老人确认一下（避免手滑关掉） -->
    <view v-if="closeSheet.open" class="bl-sheet bl-sheet--top">
      <view class="bl-sheet__mask" @click="closeSheet.open = false" />
      <view class="bl-sheet__panel">
        <view class="bl-sheet__head">
          <text class="bl-sheet__title">{{ closeSheet.name }}</text>
          <view class="bl-sheet__close" role="button" aria-label="关闭" @click="closeSheet.open = false">
            <text class="bl-sheet__close-text">✕</text>
          </view>
        </view>

        <!-- 把后果说清楚：特殊计划只落一天，关掉就没有别的提醒了 -->
        <text class="bl-sheet__lead">
          {{ closeSheet.lead }}
        </text>

        <view class="bl-sheet__foot">
          <view class="bl-btn bl-btn--ghost bl-sheet__btn" role="button" @click="closeSheet.open = false">
            <text class="bl-page-footer__text">再想想</text>
          </view>
          <view class="bl-btn bl-btn--primary bl-sheet__btn" role="button" @click="confirmClose">
            <text class="bl-btn__text bl-sheet__btn-text--on">不再提醒</text>
          </view>
        </view>
      </view>
    </view>

    <bl-tabbar active="plans" />
  </view>
</template>

<script setup>
/**
 * 特殊计划：某个**具体日期**要做的事。
 *
 * 需求原话：「布局与日程计划一致，只是上方写的是特殊计划，点击添加计划
 * 相比于添加日常计划多了一个选择具体日期的选项」。
 *
 * 所以这一页就是 `pages/daily/daily.vue` 的形状：
 *   名称输入 → （**多一个「哪一天」**）→ 时间轮 → 保存
 * 卡片也与日常计划一致，只是把"时间"换成了"日期 + 时间"。
 *
 * 与日常计划的差别只在数据语义（见 stores/special.js 的说明）：
 * 日常计划每天重复、有"关闭某几天"；特殊计划本身落在一个日期上。
 * 因此关闭方式只有两种（跳过这一天 / 永久关闭），没有"日历选关闭日"——
 * 一条只落在一天的计划，再选关闭日期是同一件事说两遍。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { settings } from '@/common/store.js'
import {
  addSpecialPlan,
  closeSpecialForever,
  closureNote,
  dateText,
  effectiveEnabled,
  initSpecial,
  isToday,
  NAME_MAX,
  rangeText,
  relativeText,
  removeSpecialPlan,
  reopenSpecial,
  special
} from '@/stores/special.js'
// dayKey 用来算「明天」，给添加层的日期做默认值
import { dayKey } from '@/stores/daily.js'
import {
  dismissBanner,
  reminder,
  rescheduleLocalReminders
} from '@/stores/reminder.js'

/** 点提醒条：告诉老人这条计划是到点会提醒的 */
function onReminderOpen() {
  dismissBanner()
  uni.showToast({ title: '到点会提醒你，先记下来', icon: 'none' })
}

const formOpen = ref(false)
const form = reactive({
  name: '',
  date: '',
  time: { fromH: 8, fromM: 0, toH: 9, toM: 0 }
})

/** 关闭确认弹层 */
const closeSheet = reactive({ open: false, id: '', name: '', lead: '' })
/** 选日期弹层（单选） */
const dateSheet = reactive({ open: false, picked: [] })

onMounted(() => {
  initSpecial()
  // 计划一到位就按最新计划排「开始/结束」两个提醒点
  rescheduleLocalReminders()
})

function openForm() {
  // 每次打开都回到干净状态，避免上一条的残留。
  // 日期默认给"明天"——特殊计划多半是往后的事，给今天反而要改。
  const tomorrow = new Date(Date.now() + 86400000)
  form.name = ''
  form.date = dayKey(tomorrow)
  form.time = { fromH: 8, fromM: 0, toH: 9, toM: 0 }
  formOpen.value = true
}

function closeForm() {
  formOpen.value = false
}

function onTimeChange(next) {
  form.time = next
}

/** 打开选日期弹层：带上已选的日期，方便看和改 */
function openDatePick() {
  dateSheet.picked = form.date ? [form.date] : []
  dateSheet.open = true
}

function saveDate() {
  if (!dateSheet.picked.length) {
    uni.showToast({ title: '还没选日期', icon: 'none' })
    return
  }
  form.date = dateSheet.picked[0]
  dateSheet.open = false
}

function save() {
  const res = addSpecialPlan({
    name: form.name,
    date: form.date,
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
 * 开关：打开就是恢复提醒；关掉要先确认。
 *
 * 这里**不做"单次 / 跳过 / 永久"三选一**（日常计划有，特殊计划没有意义）：
 * 一条特殊计划只落在**一个**日期上，"这次不提醒"和"以后都不提醒"
 * 是同一个结果。给两个结果一样的选项，只会让老人犹豫。
 */
function onToggle(item, value) {
  if (value) {
    reopenSpecial(item.id)
    rescheduleLocalReminders()
    uni.showToast({ title: '已打开提醒', icon: 'none' })
    return
  }
  closeSheet.id = item.id
  closeSheet.name = item.name
  closeSheet.lead = isToday(item)
    ? '这条计划就是今天。关掉之后今天不会提醒你，想留着就再点开关打开。'
    : '这条计划只在' + dateText(item.date) + '提醒一次。关掉之后那天不会提醒你，想留着就再点开关打开。'
  closeSheet.open = true
}

/** 卡片是否按"生效中"显示。与开关同一判据，避免开关关着而卡片还是亮的 */
function isActive(item) {
  return effectiveEnabled(item)
}

function confirmClose() {
  closeSpecialForever(closeSheet.id)
  rescheduleLocalReminders()
  closeSheet.open = false
  uni.showToast({ title: '已关掉提醒，想开就再点一下开关', icon: 'none' })
}

/** 删除：长按卡片，二次确认防误触（老人手抖，不做滑动删除） */
function confirmRemove(item) {
  uni.showModal({
    title: '删除这条计划？',
    content: item.name + '（' + dateText(item.date) + '）',
    confirmText: '删除',
    cancelText: '再想想',
    success(res) {
      if (!res.confirm) return
      removeSpecialPlan(item.id)
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
/* 就是今天：左侧加一道主色竖条，一眼能挑出来 */
.bl-daily.is-today {
  border-left: 8rpx solid var(--bl-primary);
}

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
/* 日期：特殊计划的主信息，用主色强调 */
.bl-daily__date {
  display: block;
  font-size: var(--bl-font-caption);
  font-weight: 600;
  color: var(--bl-primary);
  line-height: 1.4;
  margin-top: 6rpx;
}
/* 「还有 3 天」这种相对说法：比绝对日期更好懂，但不抢主信息的注意力 */
.bl-daily__rel { font-weight: 400; color: var(--bl-text-2); }
/* 时间：正常字重，跟在日期后面一行 */
.bl-daily__time {
  display: block;
  font-size: var(--bl-font-caption);
  font-weight: 400;
  color: var(--bl-text-2);
  line-height: 1.4;
  margin-top: 4rpx;
  font-variant-numeric: tabular-nums;
}
/* 关闭状态说明：告诉老人为什么现在是关的 */
.bl-daily__note {
  display: block;
  font-size: var(--bl-font-caption);
  font-weight: 400;
  color: var(--bl-warm);
  line-height: 1.4;
  margin-top: 4rpx;
}

/* ---------- 选日期字段（添加弹层里多出来的那一项） ---------- */
.bl-date-field {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--bl-space-sm);
  min-height: 104rpx;
  padding: 0 var(--bl-space-md);
  box-sizing: border-box;
  background-color: var(--bl-surface);
  border: 2rpx solid var(--bl-border-strong);
  border-radius: var(--bl-radius-bubble);
}
.bl-date-field:active { background-color: var(--bl-surface-2); }
.bl-date-field__text {
  flex: 1;
  min-width: 0;
  font-size: var(--bl-font-body);
  color: var(--bl-text);
}
/* 还没选：用次要色，和「已选好」区分开 */
.bl-date-field.is-empty .bl-date-field__text { color: var(--bl-text-2); }

/* ---------- 关闭方式 ---------- */
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

/* 弹层层级：选日期 / 关闭方式都在最上面 */
.bl-sheet--top { z-index: 70; }

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
