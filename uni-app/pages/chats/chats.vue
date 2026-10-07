<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar title="比邻AI" brand />

    <bl-reminder-bar :item="reminder.banner" @open="onReminderOpen" @dismiss="dismissBanner" />

    <scroll-view class="bl-body" scroll-y>
      <!-- 问候卡：水墨晕染 + 当日提示。老人打开 App 第一眼看到「今天怎么样」 -->
      <view class="bl-greet">
        <view class="bl-greet__row">
          <text class="bl-greet__hi">{{ greeting }}</text>
        </view>
        <text class="bl-greet__sub">{{ todayLine }}</text>
        <view class="bl-greet__tags">
          <text v-if="unreadTotal > 0" class="bl-greet__tag bl-greet__tag--unread">
            有 {{ unreadTotal }} 条消息没看
          </text>
          <text v-if="reminder.unread" class="bl-greet__tag">还有 {{ reminder.unread }} 条提醒没看</text>
          <text class="bl-greet__tag">点一下就能说话</text>
        </view>
      </view>

      <view class="bl-section-title--ink">
        <view class="bl-brush-rule" />
        <text class="bl-section-title__text">陪我说话</text>
      </view>

      <view class="bl-chat-list">
        <!-- 会话来自服务端：智能体会话 + 绑定的家人各一条。
             家人绑定后双方共享同一条会话，所以这里必须读服务端而不是本地缓存。 -->
        <view
          v-for="item in conversations"
          :key="item.id"
          class="bl-chat-row"
          role="button"
          :aria-label="ariaOf(item)"
          @click="open(item)"
        >
          <view class="bl-chat-row__avatar" :style="{ backgroundColor: colorOf(item) }">
            <text class="bl-chat-row__initial">{{ item.displayName.slice(0, 1) }}</text>
          </view>

          <view class="bl-chat-row__main">
            <view class="bl-chat-row__title-row">
              <text class="bl-chat-row__name">{{ item.displayName }}</text>
              <text v-if="item.kind === 'ai'" class="bl-chat-row__tag">默认</text>
              <text v-else class="bl-chat-row__tag bl-chat-row__tag--family">家人</text>
            </view>
            <text class="bl-chat-row__msg">{{ previewOf(item) }}</text>
          </view>

          <view class="bl-chat-row__side">
            <text class="bl-chat-row__time">{{ clockOf(item) }}</text>
            <!-- 未读：红点 + 条数（按需求） -->
            <view v-if="item.unread > 0" class="bl-chat-row__badge">
              <text class="bl-chat-row__badge-text">{{ item.unread > 99 ? '99+' : item.unread }}</text>
            </view>
            <!-- 备注入口：比长按更容易被发现 -->
            <view
              class="bl-chat-row__remark"
              role="button"
              :aria-label="'修改' + item.displayName + '的备注'"
              @click.stop="toRemark(item)"
            >
              <text class="bl-chat-row__remark-text">备注</text>
            </view>
          </view>
        </view>
      </view>

      <!-- 没登录时的兜底 -->
      <view v-if="!conversations.length" class="bl-chat-empty">
        <text class="bl-chat-empty__text">登录后这里会出现你的家人和比邻AI</text>
      </view>
    </scroll-view>

    <bl-tabbar active="chats" />
  </view>
</template>

<script setup>
/**
 * 对话栏目（会话列表）。
 *
 * 数据来自服务端 `/v1/conversations`：
 *   · 与智能体「比邻AI」的会话（每个账号一条，永远在）
 *   · 与**绑定的家人**的共享会话（绑定后出现，双方看同一份记录）
 *
 * 每行显示：头像首字 + 名字（可用备注覆盖）+ 最后一条消息 + 时间 + 未读红点。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { settings } from '@/common/store.js'
import { initChat, formatClock, usePersona } from '@/stores/chat.js'
import { listRoles, roleToPersona } from '@/stores/roles.js'
import { EVENT_CONTACTS_CHANGED, readConversations, refreshConversations, setPendingConversation, setPendingRemark, totalUnread } from '@/stores/contacts.js'
import { dismissBanner, poll, reminder } from '@/stores/reminder.js'

/** 会话列表（副本）。模板不直接绑 store 的模块导出。 */
const conversations = ref([])
/** 底部/标题用的未读总数 */
const unreadTotal = ref(0)

const nowClock = ref('')

const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 6) return '夜深了，早点歇着'
  if (h < 11) return '早上好'
  if (h < 14) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
})

const todayLine = computed(() => {
  const d = new Date()
  const week = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][d.getDay()]
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日 ${week}`
})

/** 会话的头像色：智能体用墨绿，家人用赭石 */
function colorOf(item) {
  return item.kind === 'ai' ? '#3C6B58' : '#7A6A4F'
}

/** 消息预览：有最后一条就显示它，否则显示智能体自我介绍 */
function previewOf(item) {
  if (item.lastMessage && item.lastMessage.text) return item.lastMessage.text
  if (item.kind === 'ai') {
    const persona = listRoles().map(roleToPersona).find((p) => p.id === 'p_bilin')
    return persona ? persona.intro : '我是比邻 能陪你聊天、提醒吃药'
  }
  return '还没聊过，点一下说句话'
}

function clockOf(item) {
  const stamp = (item.lastMessage && item.lastMessage.createdAt) || item.updatedAt
  if (!stamp) return ''
  const at = Date.parse(stamp)
  if (isNaN(at)) return ''
  return formatClock(at)
}

function ariaOf(item) {
  const unread = item.unread > 0 ? '，' + item.unread + '条未读' : ''
  return item.displayName + '，' + previewOf(item) + unread
}

function refresh() {
  conversations.value = readConversations()
  unreadTotal.value = totalUnread()
}

onMounted(() => {
  initChat()
  poll()
  nowClock.value = formatClock(Date.now())
  refresh()
  // 登录后 / 绑定家人后 / 改完备注回来，都要刷新
  uni.$on(EVENT_CONTACTS_CHANGED, refresh)
  refreshConversations().then(refresh)
})

onUnmounted(() => {
  uni.$off(EVENT_CONTACTS_CHANGED, refresh)
})

function onReminderOpen() {
  dismissBanner()
  uni.navigateTo({ url: '/pages/plans/plans' })
}

/**
 * 点某一行：**一律进对话界面**（家人会话也是聊天，不是管理）。
 * 「查看管理」的入口在「我的 → 家人绑定」里点家人卡片
 * （见 pages/family/family.vue）。两处分开，避免"想聊天却进了看板"。
 */
function open(item) {
  if (item.kind === 'ai') {
    const persona = listRoles().map(roleToPersona).find((p) => p.id === 'p_bilin')
    if (persona) usePersona(persona)
  }
  setPendingConversation(item)
  uni.navigateTo({ url: '/pages/chat-detail/chat-detail' })
}

/** 去改备注 */
function toRemark(item) {
  setPendingRemark(item)
  uni.navigateTo({ url: '/pages/remark/remark' })
}
</script>

<style scoped>
/* 问候卡：宣纸晕染 + 淡墨描边，语气比列表更"有人味" */
.bl-greet {
  margin: 8rpx var(--bl-space-lg) var(--bl-space-md);
  padding: 32rpx;
  border-radius: var(--bl-radius-card);
  border: 1rpx solid var(--bl-border);
  background-color: var(--bl-surface);
  background-image: radial-gradient(circle at 92% 8%, rgba(47, 93, 78, .10), transparent 46%);
  box-shadow: var(--bl-shadow-card);
  box-sizing: border-box;
}
.bl-greet__row { display: flex; align-items: baseline; }
.bl-greet__hi {
  font-size: var(--bl-font-title);
  font-weight: 700;
  color: var(--bl-text);
  letter-spacing: .01em;
}
.bl-greet__sub {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  margin-top: 12rpx;
  line-height: 1.5;
}
.bl-greet__tags { display: flex; flex-wrap: wrap; gap: 12rpx; margin-top: 20rpx; }
.bl-greet__tag {
  font-size: var(--bl-font-caption);
  color: var(--bl-primary);
  background-color: var(--bl-primary-soft);
  border-radius: var(--bl-radius-pill);
  padding: 8rpx 20rpx;
}
/* 未读提示用醒目色：白字红底，与列表里的红点呼应 */
.bl-greet__tag--unread {
  color: #FFFFFF;
  background-color: #C81E1E;
  font-weight: 600;
}

.bl-chat-list {
  margin: 0 var(--bl-space-lg) var(--bl-space-md);
  border-radius: var(--bl-radius-card);
  border: 1rpx solid var(--bl-border);
  background-color: var(--bl-surface);
  box-shadow: var(--bl-shadow-card);
  overflow: hidden;
  box-sizing: border-box;
}
.bl-chat-row {
  display: flex;
  align-items: center;
  gap: 24rpx;
  min-height: 152rpx;
  padding: 24rpx 32rpx;
  background-color: var(--bl-surface);
  position: relative;
  box-sizing: border-box;
}
.bl-chat-row:active { background-color: var(--bl-surface-2); }
/* 多行之间加细分割线（第一行不加） */
.bl-chat-row + .bl-chat-row::before {
  content: '';
  position: absolute;
  left: 32rpx;
  right: 0;
  top: 0;
  height: 1rpx;
  background-color: var(--bl-divider);
}

.bl-chat-row__avatar {
  width: var(--bl-avatar);
  height: var(--bl-avatar);
  border-radius: 50%;
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
}
/* 头像里画角色名首字：自建角色没有现成头像，首字比通用小人更容易认 */
.bl-chat-row__initial {
  font-size: 40rpx;
  font-weight: 700;
  color: #FFFDF8;
  line-height: 1;
}

.bl-chat-row__main { flex: 1; min-width: 0; }
.bl-chat-row__title-row {
  display: flex;
  align-items: center;
  gap: 12rpx;
}
.bl-chat-row__name {
  font-size: var(--bl-font-body);
  font-weight: 700;
  line-height: 1.3;
  color: var(--bl-text);
}
/* 标记：默认角色 / 自己建的，让老人分得清 */
.bl-chat-row__tag {
  flex: none;
  font-size: 20rpx;
  color: var(--bl-primary);
  background-color: var(--bl-primary-soft);
  border-radius: 999rpx;
  padding: 2rpx 12rpx;
  line-height: 1.6;
}
.bl-chat-row__tag--mine {
  color: var(--bl-text-2);
  background-color: var(--bl-surface-2);
}
/* 家人会话的标记：赭石色，与家人头像色一致 */
.bl-chat-row__tag--family {
  color: #7A6A4F;
  background-color: rgba(122, 106, 79, .14);
}
/* 预览文案信息量大，允许折两行，不做单行省略 */
.bl-chat-row__msg {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  line-height: 1.5;
  margin-top: 6rpx;
}

.bl-chat-row__side {
  flex: none;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 10rpx;
}
.bl-chat-row__time { font-size: var(--bl-font-caption); color: var(--bl-text-2); }

/* 未读红点 + 条数。红底白字，对比 8.6:1，老人一眼能看到 */
.bl-chat-row__badge {
  min-width: 44rpx;
  height: 44rpx;
  padding: 0 12rpx;
  border-radius: 999rpx;
  background-color: #C81E1E;
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
}
.bl-chat-row__badge-text {
  font-size: 24rpx;
  font-weight: 700;
  color: #FFFFFF;
  line-height: 1;
}

/* 备注入口：小按钮但触控区够 48px（内边距撑起来） */
.bl-chat-row__remark {
  min-height: var(--bl-touch);
  min-width: var(--bl-touch);
  padding: 0 16rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2rpx solid var(--bl-border-strong);
  border-radius: 999rpx;
  box-sizing: border-box;
}
.bl-chat-row__remark-text {
  font-size: 22rpx;
  color: var(--bl-text-2);
  line-height: 1;
}
.bl-chat-row__remark:active { background-color: var(--bl-surface-2); }

.bl-chat-empty {
  padding: var(--bl-space-lg);
  text-align: center;
}
.bl-chat-empty__text {
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
}
</style>
