<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar :title="peerName" back solid @back="back" />

    <scroll-view class="bl-body" scroll-y>
      <!-- 对方是谁 -->
      <view class="bl-mg__head">
        <view class="bl-mg__avatar">
          <text class="bl-mg__initial">{{ (peerName || '家').slice(0, 1) }}</text>
        </view>
        <view class="bl-mg__head-main">
          <text class="bl-mg__name">{{ peerName }}</text>
          <text class="bl-mg__id">{{ peerNumber ? 'ID:' + peerNumber : '' }}</text>
        </view>
      </view>

      <view v-if="loading" class="bl-mg__loading">
        <text class="bl-mg__loading-text">正在加载…</text>
      </view>

      <view v-else-if="error" class="bl-mg__loading">
        <text class="bl-mg__loading-text">{{ error }}</text>
      </view>

      <template v-else>
        <!-- 一、今天的日程确认情况 -->
        <view class="bl-mg__section">
          <view class="bl-section-title--ink">
            <view class="bl-brush-rule" />
            <text class="bl-section-title__text">今天的日程（{{ today.date }}）</text>
          </view>

          <!-- 完成率大数字：一眼看清 -->
          <view class="bl-mg__rate">
            <view class="bl-mg__rate-main">
              <text class="bl-mg__rate-num">{{ today.done }}</text>
              <text class="bl-mg__rate-total">/ {{ today.total }}</text>
            </view>
            <view class="bl-mg__rate-side">
              <text class="bl-mg__rate-label">{{ rateLabel }}</text>
              <text class="bl-mg__rate-status">{{ today.statusLabel }}</text>
            </view>
          </view>

          <!-- 未完成：家属最关心的 -->
          <view v-if="today.pendingCount" class="bl-mg__pending">
            <text class="bl-mg__pending-title">还有 {{ today.pendingCount }} 项没完成</text>
            <view
              v-for="item in today.pending"
              :key="item.id"
              class="bl-mg__pending-row"
            >
              <text class="bl-mg__pending-dot">●</text>
              <text class="bl-mg__pending-text">{{ item.title }}</text>
              <text v-if="item.time" class="bl-mg__pending-time">{{ item.time }}</text>
            </view>
          </view>

          <!-- 已完成 -->
          <view v-if="doneItems.length" class="bl-mg__done">
            <text class="bl-mg__done-title">已完成的 {{ doneItems.length }} 项</text>
            <view v-for="item in doneItems" :key="item.id" class="bl-mg__done-row">
              <text class="bl-mg__done-check">✓</text>
              <text class="bl-mg__done-text">{{ item.title }}</text>
              <text v-if="item.doneAt" class="bl-mg__done-time">{{ clockOf(item.doneAt) }}</text>
            </view>
          </view>

          <view v-if="!today.total" class="bl-mg__none">
            <text class="bl-mg__none-text">今天还没有日程安排</text>
          </view>
        </view>

        <!-- 二、最近 7 天完成趋势 -->
        <view class="bl-mg__section">
          <view class="bl-section-title--ink">
            <view class="bl-brush-rule" />
            <text class="bl-section-title__text">最近 7 天完成情况</text>
          </view>
          <view class="bl-mg__trend">
            <view
              v-for="d in trend"
              :key="d.date"
              class="bl-mg__trend-col"
            >
              <view class="bl-mg__trend-bar-wrap">
                <view class="bl-mg__trend-bar" :style="{ height: d.height }" />
              </view>
              <text class="bl-mg__trend-day">{{ d.label }}</text>
            </view>
          </view>
          <text v-if="!trendHasData" class="bl-mg__none-text">最近 7 天还没有打卡记录</text>
        </view>

        <!-- 三、聊天活跃统计 -->
        <view class="bl-mg__section">
          <view class="bl-section-title--ink">
            <view class="bl-brush-rule" />
            <text class="bl-section-title__text">近期聊天活跃（近 {{ activity.days }} 天）</text>
          </view>

          <view class="bl-mg__stats">
            <view class="bl-mg__stat">
              <text class="bl-mg__stat-num">{{ activity.messagesFromHim }}</text>
              <text class="bl-mg__stat-label">他主动说的话</text>
            </view>
            <view class="bl-mg__stat">
              <text class="bl-mg__stat-num">{{ activity.messagesToHim }}</text>
              <text class="bl-mg__stat-label">收到的消息</text>
            </view>
            <view class="bl-mg__stat">
              <text class="bl-mg__stat-num">{{ activity.activeDays }}</text>
              <text class="bl-mg__stat-label">有说话的天数</text>
            </view>
            <view class="bl-mg__stat">
              <text class="bl-mg__stat-num">{{ activity.streak }}</text>
              <text class="bl-mg__stat-label">连续活跃天数</text>
            </view>
          </view>

          <text class="bl-mg__active-note">
            最近一次主动说话：{{ activity.lastActiveAt ? relativeOf(activity.lastActiveAt) : '近 7 天没有' }}
          </text>

          <!-- 逐日柱状：只看每天有没有在说话 -->
          <view class="bl-mg__trend bl-mg__trend--chat">
            <view v-for="d in chatTrend" :key="d.date" class="bl-mg__trend-col">
              <view class="bl-mg__trend-bar-wrap">
                <view class="bl-mg__trend-bar bl-mg__trend-bar--chat" :style="{ height: d.height }" />
              </view>
              <text class="bl-mg__trend-day">{{ d.label }}</text>
            </view>
          </view>
          <text class="bl-mg__hint">柱高 = 当天他主动说话的条数</text>
        </view>

        <!-- 去跟他说话：管理之外也要能直接联系 -->
        <view class="bl-mg__actions">
          <view class="bl-btn bl-btn--primary bl-btn--block" role="button" @click="toChat">
            <text class="bl-btn__text">给他发消息</text>
          </view>
          <text class="bl-mg__actions-hint">也可以去「对话」栏目，点他的名字说话</text>
        </view>
      </template>
    </scroll-view>
  </view>
</template>

<script setup>
/**
 * 家人查看管理页。
 *
 * 按需求：绑定后的家人点进去是**查看管理界面**——今日日程确认情况、
 * 哪些没完成、近期聊天活跃统计。管理之外保留「给他发消息」入口，
 * 免得家属看完想说话还得退出去找。
 *
 * 授权在服务端（只有互相绑定才能取，见 app/api/family.py），
 * 端侧只是展示；拿不到就显示服务端给的原因。
 */
import { computed, ref } from 'vue'
import { settings } from '@/common/store.js'
import { pending } from '@/stores/contacts.js'
import { fetchFamilyOverview } from '@/api/index.js'
import { readToken } from '@/stores/account.js'
import { formatClock } from '@/stores/chat.js'

const peerName = ref(pending.title || '家人')
const peerNumber = ref(pending.peerNumber || '')
const loading = ref(true)
const error = ref('')

const today = ref({ date: '', statusLabel: '', total: 0, done: 0, rate: 0, items: [], pending: [], pendingCount: 0 })
const recent = ref({})
const activity = ref({
  days: 7, byDay: [], totalMessages: 0, messagesFromHim: 0,
  messagesToHim: 0, activeDays: 0, streak: 0, lastActiveAt: ''
})

const doneItems = computed(() => (today.value.items || []).filter((i) => i.done))

const rateLabel = computed(() => {
  const total = today.value.total || 0
  if (!total) return '今天没有安排'
  const rate = Math.round((today.value.done / total) * 100)
  if (rate === 100) return '全部完成，很好'
  if (rate >= 60) return '完成 ' + rate + '%'
  if (rate > 0) return '只完成 ' + rate + '%'
  return '一项都还没完成'
})

/** 最近 7 天完成率柱状（服务端 recent.byDay 是逐日数组） */
const trend = computed(() => {
  const days = []
  const source = (recent.value && recent.value.byDay) || []
  const map = {}
  source.forEach((item) => {
    if (item && item.date) map[String(item.date).slice(0, 10)] = item
  })
  for (let offset = 6; offset >= 0; offset -= 1) {
    const d = new Date()
    d.setDate(d.getDate() - offset)
    const key = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0')
    const item = map[key]
    const rate = item ? Number(item.rate || 0) : 0
    days.push({
      date: key,
      label: ['日', '一', '二', '三', '四', '五', '六'][d.getDay()],
      height: Math.max(4, Math.round(rate * 96)) + 'rpx',
      rate,
      done: item ? Number(item.done || 0) : 0
    })
  }
  return days
})

const trendHasData = computed(() => trend.value.some((d) => d.done > 0))

/** 聊天活跃柱状：柱高按"他主动说的条数" */
const chatTrend = computed(() => {
  const source = (activity.value && activity.value.byDay) || []
  const max = Math.max(1, ...source.map((d) => Number(d.mineByHim || 0)))
  return source.map((item) => {
    const d = new Date(item.date)
    return {
      date: item.date,
      label: ['日', '一', '二', '三', '四', '五', '六'][d.getDay()],
      height: Math.max(4, Math.round((Number(item.mineByHim || 0) / max) * 96)) + 'rpx'
    }
  })
})

function clockOf(stamp) {
  const at = Date.parse(stamp)
  return isNaN(at) ? '' : formatClock(at)
}

/** "3 小时前"这种相对时间，比绝对时间更能说明"最近还爱不爱说话" */
function relativeOf(stamp) {
  const at = Date.parse(stamp)
  if (isNaN(at)) return ''
  const diff = Date.now() - at
  const min = Math.floor(diff / 60000)
  if (min < 1) return '刚刚'
  if (min < 60) return min + ' 分钟前'
  const hour = Math.floor(min / 60)
  if (hour < 24) return hour + ' 小时前'
  const day = Math.floor(hour / 24)
  if (day < 30) return day + ' 天前'
  return clockOf(stamp)
}

function load() {
  const token = readToken()
  if (!token) {
    loading.value = false
    error.value = '请先登录'
    return
  }
  if (!peerNumber.value) {
    loading.value = false
    error.value = '没拿到这位家人的编号，请从「家人绑定」页进入'
    return
  }
  fetchFamilyOverview(token, peerNumber.value)
    .then((data) => {
      loading.value = false
      if (data && data.peer) {
        peerName.value = data.peer.name || peerName.value
        peerNumber.value = data.peer.number || peerNumber.value
      }
      today.value = (data && data.today) || today.value
      recent.value = (data && data.recent) || {}
      activity.value = (data && data.activity) || activity.value
    })
    .catch((err) => {
      loading.value = false
      error.value = (err && err.message) || '看不到这位家人的情况'
    })
}

load()

function toChat() {
  uni.navigateTo({ url: '/pages/chat-detail/chat-detail' })
}

function back() {
  const pages = getCurrentPages()
  if (pages.length > 1) uni.navigateBack()
  else uni.reLaunch({ url: '/pages/chats/chats' })
}
</script>

<style scoped>
.bl-mg__head {
  display: flex;
  align-items: center;
  gap: 24rpx;
  margin: 16rpx var(--bl-space-lg) 0;
  padding: 28rpx 32rpx;
  background-color: var(--bl-surface);
  border: 1rpx solid var(--bl-border);
  border-radius: var(--bl-radius-card);
  box-shadow: var(--bl-shadow-card);
  box-sizing: border-box;
}
.bl-mg__avatar {
  width: 96rpx;
  height: 96rpx;
  flex: none;
  border-radius: 50%;
  background-color: #7A6A4F;
  display: flex;
  align-items: center;
  justify-content: center;
}
.bl-mg__initial { font-size: 42rpx; font-weight: 700; color: #FFFDF8; line-height: 1; }
.bl-mg__head-main { flex: 1; min-width: 0; }
.bl-mg__name {
  display: block;
  font-size: var(--bl-font-title);
  font-weight: 700;
  color: var(--bl-text);
}
.bl-mg__id {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  margin-top: 6rpx;
  font-variant-numeric: tabular-nums;
}

.bl-mg__loading { padding: 64rpx var(--bl-space-lg); }
.bl-mg__loading-text { font-size: var(--bl-font-body); color: var(--bl-text-2); }

.bl-mg__section { padding-top: 32rpx; }
.bl-mg__section .bl-section-title--ink { padding: 0 var(--bl-space-lg) 8rpx; }

/* 完成率 */
.bl-mg__rate {
  display: flex;
  align-items: center;
  gap: 32rpx;
  margin: 8rpx var(--bl-space-lg) 0;
  padding: 28rpx 32rpx;
  background-color: var(--bl-surface);
  border: 1rpx solid var(--bl-border);
  border-radius: var(--bl-radius-card);
  box-shadow: var(--bl-shadow-card);
  box-sizing: border-box;
}
.bl-mg__rate-main { display: flex; align-items: baseline; gap: 8rpx; flex: none; }
.bl-mg__rate-num {
  font-size: 72rpx;
  font-weight: 700;
  color: var(--bl-primary);
  line-height: 1;
}
.bl-mg__rate-total { font-size: var(--bl-font-body); color: var(--bl-text-2); }
.bl-mg__rate-side { flex: 1; min-width: 0; }
.bl-mg__rate-label {
  display: block;
  font-size: var(--bl-font-body);
  font-weight: 600;
  color: var(--bl-text);
}
.bl-mg__rate-status {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  margin-top: 6rpx;
}

/* 未完成 */
.bl-mg__pending {
  margin: 16rpx var(--bl-space-lg) 0;
  padding: 24rpx 28rpx;
  background-color: #FDF3F2;
  border: 1rpx solid #E8C4C0;
  border-radius: var(--bl-radius-card);
  box-sizing: border-box;
}
.bl-mg__pending-title {
  display: block;
  font-size: var(--bl-font-body);
  font-weight: 700;
  color: #C81E1E;
  margin-bottom: 12rpx;
}
.bl-mg__pending-row {
  display: flex;
  align-items: center;
  gap: 12rpx;
  padding: 10rpx 0;
}
.bl-mg__pending-dot { font-size: 20rpx; color: #C81E1E; line-height: 1; }
.bl-mg__pending-text {
  flex: 1;
  min-width: 0;
  font-size: var(--bl-font-body);
  color: var(--bl-text);
  line-height: 1.4;
}
.bl-mg__pending-time {
  flex: none;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
}

/* 已完成 */
.bl-mg__done { margin: 16rpx var(--bl-space-lg) 0; }
.bl-mg__done-title {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  margin-bottom: 8rpx;
}
.bl-mg__done-row { display: flex; align-items: center; gap: 12rpx; padding: 8rpx 0; }
.bl-mg__done-check { font-size: 28rpx; color: var(--bl-success); line-height: 1; }
.bl-mg__done-text {
  flex: 1;
  min-width: 0;
  font-size: var(--bl-font-body);
  color: var(--bl-text-2);
  line-height: 1.4;
}
.bl-mg__done-time { flex: none; font-size: var(--bl-font-caption); color: var(--bl-text-2); }

.bl-mg__none { margin: 16rpx var(--bl-space-lg) 0; }
.bl-mg__none-text { font-size: var(--bl-font-caption); color: var(--bl-text-2); }

/* 柱状图（完成率 / 聊天活跃共用） */
.bl-mg__trend {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 8rpx;
  margin: 16rpx var(--bl-space-lg) 0;
  padding: 20rpx 24rpx 12rpx;
  background-color: var(--bl-surface);
  border: 1rpx solid var(--bl-border);
  border-radius: var(--bl-radius-card);
  box-shadow: var(--bl-shadow-card);
  box-sizing: border-box;
}
.bl-mg__trend--chat { margin-top: 12rpx; }
.bl-mg__trend-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8rpx;
}
.bl-mg__trend-bar-wrap {
  height: 96rpx;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  width: 100%;
}
.bl-mg__trend-bar {
  width: 100%;
  max-width: 40rpx;
  background-color: var(--bl-primary);
  border-radius: 8rpx 8rpx 0 0;
}
.bl-mg__trend-bar--chat { background-color: #7A6A4F; }
.bl-mg__trend-day { font-size: 22rpx; color: var(--bl-text-2); }

/* 活跃统计 */
.bl-mg__stats {
  display: flex;
  flex-wrap: wrap;
  gap: 16rpx;
  margin: 8rpx var(--bl-space-lg) 0;
}
.bl-mg__stat {
  flex: 1 1 40%;
  min-width: 0;
  padding: 24rpx;
  background-color: var(--bl-surface);
  border: 1rpx solid var(--bl-border);
  border-radius: var(--bl-radius-card);
  box-shadow: var(--bl-shadow-card);
  box-sizing: border-box;
}
.bl-mg__stat-num {
  display: block;
  font-size: 56rpx;
  font-weight: 700;
  color: var(--bl-text);
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}
.bl-mg__stat-label {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  margin-top: 8rpx;
  line-height: 1.4;
}
.bl-mg__active-note {
  display: block;
  margin: 16rpx var(--bl-space-lg) 0;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
}
.bl-mg__hint {
  display: block;
  margin: 8rpx var(--bl-space-lg) 0;
  font-size: 22rpx;
  color: var(--bl-text-2);
}

.bl-mg__actions { padding: var(--bl-space-xl) var(--bl-space-lg) var(--bl-space-xxl); }
.bl-mg__actions-hint {
  display: block;
  margin-top: 16rpx;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  text-align: center;
}
</style>
