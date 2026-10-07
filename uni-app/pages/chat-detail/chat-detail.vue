<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar
      :title="pageTitle"
      back
      :action="isFamily ? '' : 'video'"
      action-color="#2F5D4E"
      @back="back"
      @action="toVision"
    />

    <!-- 身份透明：AI 数字人标识常驻，不可移除（设计方案 §1.4 红线 2）。
         与家人的会话不是 AI，不该挂这条标识。 -->
    <view v-if="!isFamily" class="bl-ai-notice">
      <text class="bl-ai-notice__text">AI 数字人 · 内容仅供参考</text>
    </view>

    <scroll-view class="bl-chat-body" scroll-y :scroll-top="scrollTop" :scroll-with-animation="true">
      <view v-for="m in messages" :key="m.id" :id="'msg-' + m.id">
        <bl-chat-bubble
          :text="m.text"
          :type="m.type"
          :mine="isMine(m)"
          :seconds="m.seconds"
          :avatar-color="isMine(m) ? '#6E6A5E' : personaColor"
          :sticker="m.sticker"
          :card="m.card"
          :streaming="m.status === 'streaming'"
          :status="m.status"
          @play="playVoice(m)"
          @retry="onRetry"
        />
        <!-- 接收状态：对方最新的消息下面显示「未读」，进入本页 1 秒后变已读 -->
        <view v-if="m.id === newestOtherId && unreadShown > 0" class="bl-receipt">
          <text class="bl-receipt__dot">●</text>
          <text class="bl-receipt__text">未读 {{ unreadShown }}</text>
        </view>
        <view v-else-if="m.id === newestOtherId && readJustNow" class="bl-receipt">
          <text class="bl-receipt__text bl-receipt__text--read">已读</text>
        </view>
      </view>
      <view class="bl-chat-body__pad" />
    </scroll-view>

    <view v-if="emojiOpen" class="bl-emoji-panel">
      <view class="bl-emoji-grid">
        <view v-for="e in EMOJIS" :key="e.ch" class="bl-emoji" @click="insert(e.ch)">
          <text class="bl-emoji__ch">{{ e.ch }}</text>
          <text class="bl-emoji__label">{{ e.label }}</text>
        </view>
      </view>
    </view>

    <view class="bl-composer">
      <view class="bl-composer__btn" @click="toast('长按就能说话（语音在 P3 接入）')">
        <bl-icon name="mic" color="#1F211D" :size="48" />
      </view>
      <input
        v-model="draft"
        class="bl-composer__input"
        placeholder="说点什么…"
        placeholder-class="bl-composer__ph"
        confirm-type="send"
        @confirm="onSend"
      />
      <view class="bl-composer__btn" @click="emojiOpen = !emojiOpen">
        <bl-icon name="emoji" :color="emojiOpen ? '#2F5D4E' : '#1F211D'" :size="48" />
      </view>
      <view
        class="bl-composer__send"
        :class="sendClass"
        @click="onPrimary"
      >
        <text class="bl-composer__send-text">{{ chat.streaming ? '停止' : '发送' }}</text>
      </view>
    </view>
  </view>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { settings } from '@/common/store.js'
import { chat, initChat, onLiveTurn, retry, send, stop } from '@/stores/chat.js'
import { pending, remarkOf, refreshConversations } from '@/stores/contacts.js'
import { fetchMessages, markConversationRead, sendMessage } from '@/api/index.js'
import { readAccount, readToken } from '@/stores/account.js'

const EMOJIS = [
  { ch: '❤️', label: '爱心' },
  { ch: '☀️', label: '太阳' },
  { ch: '🤗', label: '拥抱' },
  { ch: '😊', label: '笑脸' },
  { ch: '💊', label: '药丸' },
  { ch: '🍚', label: '饭菜' }
]

const draft = ref('')
const emojiOpen = ref(false)
const scrollTop = ref(0)

/* ---------------------------------------------------------- 会话上下文 */

/** 从列表带过来的会话信息 */
const conversationId = ref('')
const conversationKind = ref('ai')
const serverTitle = ref('')
/** 与家人的共享会话：消息走服务端，且没有"AI 数字人"标识 */
const isFamily = computed(() => conversationKind.value === 'family')

/** 标题：备注优先（只有自己看得到），家人会话用对方名字 */
const pageTitle = computed(() => {
  if (isFamily.value) {
    return remarkOf(conversationId.value) || serverTitle.value || '家人'
  }
  return chat.persona.name || '比邻AI'
})

const personaColor = computed(() => (isFamily.value ? '#7A6A4F' : chat.persona.avatarColor))

/**
 * 页面上要显示的消息：
 *  · 家人会话 → 服务端历史（双方共享那一份）
 *  · 智能体会话 → chat store 的本地流式内容（保留打字机/语音/表情能力）
 */
const messages = computed(() => (isFamily.value ? familyMessages.value : chat.messages))

/** 家人会话的消息（服务端返回） */
const familyMessages = ref([])

/**
 * 我自己的账号 id。
 *
 * 【为什么必须按 senderId 判归属，不能按 role】
 * 服务端的 `senderRole` 只有 `agent` 与 `elder` 两个值（见 messaging/models.py），
 * **它不区分"哪一个老人"**。所以在家人会话里，双方的消息 role 都是 `elder`，
 * 用 `m.role === 'elder'` 判"是我发的"会把**对方的消息也画到我这一侧**——
 * 现象就是"我发的消息看起来像是对方发的"。
 * 数据库里每条消息都带 `sender_id`，按它判才准。
 */
const myAccountId = ref('')

/**
 * 一条消息是不是我发的。
 *
 * 判定顺序：
 *   1. 本地待发/失败的临时条目（`local_` / 带 optimistic 标记）→ 我发的
 *   2. 有 senderId 且等于我的账号 id → 我发的
 *   3. 家人会话里 senderId 明确是别人 → 不是我发的
 *   4. 智能体会话的 agent 消息 → 不是我发的
 *   5. 都取不到（比如本地流式内容没有 senderId）→ 退回按 role 判
 */
function isMine(m) {
  if (!m) return false
  // 本地临时条目（还没被服务端确认）一定是我发的
  if (m.optimistic) return true
  if (String(m.id || '').indexOf('local_') === 0) return true
  const sender = String(m.senderId || '')
  const mine = String(myAccountId.value || '')
  if (sender && mine) return sender === mine
  return m.role === 'elder'
}

/** 未读数（进入本页时快照，1 秒后归零） */
const unreadShown = ref(0)
const readJustNow = ref(false)
let readTimer = null
let stopLive = null

/** 对方最新一条消息的 id（未读/已读标记挂在它下面） */
const newestOtherId = computed(() => {
  const list = messages.value
  for (let i = list.length - 1; i >= 0; i -= 1) {
    if (!isMine(list[i])) return list[i].id
  }
  return ''
})

const sendClass = computed(() => {
  if (chat.streaming) return 'bl-composer__send--stop'
  if (!draft.value.trim()) return 'bl-composer__send--off'
  return ''
})

// 流式期间用「最后一条消息的文本长度」当信号：每来一个字都滚到底，
// 但只在真的变化时才 setData，避免低端机被刷爆。
watch(
  () => {
    const list = messages.value
    const last = list[list.length - 1]
    return list.length + '|' + (last ? (last.text || '').length : -1)
  },
  () => scrollToBottom()
)

onMounted(() => {
  // 会话上下文由列表页通过 store 登记（不走 URL 参数：
  // 会话 id 里带冒号，URL 传递会被重复编码成 %253A，解出来就是错的 id）
  conversationId.value = pending.conversationId || ''
  conversationKind.value = pending.kind === 'family' ? 'family' : 'ai'
  serverTitle.value = pending.title || ''

  // 我自己的账号 id：家人会话判"这条是不是我发的"要用它，
  // 不能按 senderRole（服务端只区分 agent/elder，不区分是哪个老人）
  const me = readAccount()
  myAccountId.value = (me && me.id) || ''

  if (isFamily.value) {
    loadFamilyMessages()
  } else {
    initChat()
    // 智能体会话也从服务端拉一次历史（跨设备可见）
    loadAiHistory()
  }

  // 按需求：进入对话界面 1 秒后显示为已读
  readTimer = setTimeout(() => {
    markRead()
  }, 1000)

  // 智能体这一轮说完后，把它的回复也存到服务端（跨设备可见）。
  // 用 onLiveTurn 而不是改 stores/chat.js：通话页也订阅它，两处互不干扰。
  if (!isFamily.value) {
    stopLive = onLiveTurn((payload) => {
      const text = (payload && payload.text) || ''
      if (text.trim()) persistAiMessage(text.trim(), 'agent')
    })
  }

  scrollToBottom()
})

onUnmounted(() => {
  if (readTimer) clearTimeout(readTimer)
  readTimer = null
  if (typeof stopLive === 'function') stopLive()
  stopLive = null
})

/** 家人会话：拉服务端历史 */
function loadFamilyMessages() {
  const token = readToken()
  if (!token || !conversationId.value) {
    toast('请先登录')
    return
  }
  fetchMessages(token, conversationId.value, 100)
    .then((data) => {
      familyMessages.value = (data && data.messages) || []
      unreadShown.value = (data && data.unread) || 0
      scrollToBottom()
    })
    .catch((error) => {
      toast((error && error.message) || '聊天记录没拉到')
    })
}

/**
 * 智能体会话的历史也拉一次服务端。
 * 服务端有就用服务端的（跨设备一致），没有就保留本地种子内容。
 */
function loadAiHistory() {
  const token = readToken()
  if (!token || !conversationId.value) return
  fetchMessages(token, conversationId.value, 100)
    .then((data) => {
      const list = (data && data.messages) || []
      unreadShown.value = (data && data.unread) || 0
      if (!list.length) return
      // 不覆盖正在进行的一轮，避免把刚发的话冲掉
      if (chat.streaming) return
      chat.messages = list.map((m) => ({
        id: m.id,
        role: m.senderRole === 'agent' ? 'agent' : 'elder',
        type: 'text',
        text: m.text,
        createdAt: m.createdAt
      }))
      scrollToBottom()
    })
    .catch(() => {
      // 拉不到就用本地内容，不打扰老人
    })
}

/** 标记已读：让列表红点消失、并显示「已读」 */
function markRead() {
  const token = readToken()
  if (!token || !conversationId.value) return
  markConversationRead(token, conversationId.value)
    .then(() => {
      if (unreadShown.value > 0) readJustNow.value = true
      unreadShown.value = 0
      // 列表的红点要跟着消失
      refreshConversations()
    })
    .catch(() => {
      // 标记失败不影响阅读；下次进来还会再试
    })
}



function scrollToBottom() {
  nextTick(() => {
    // scroll-top 必须是变化的值才会触发滚动；累加一个远超内容高度的数字即可贴底
    scrollTop.value += 100000
  })
}

function insert(ch) {
  draft.value = (draft.value || '') + ch
}

function onPrimary() {
  if (chat.streaming) {
    stop()
    return
  }
  onSend()
}

function onSend() {
  if (chat.streaming) {
    toast('等我说完再发哦')
    return
  }
  const text = draft.value
  if (!text || !text.trim()) {
    toast('说点什么吧')
    return
  }

  // 与家人的会话：消息走服务端，双方共享同一份记录
  if (isFamily.value) {
    draft.value = ''
    emojiOpen.value = false
    sendFamilyText(text.trim())
    return
  }

  // 与智能体的会话：保留原来的流式回复（打字机 / 语音 / 表情都在这条路上），
  // 同时把消息存到服务端，这样换设备也看得到。
  if (send(text)) {
    draft.value = ''
    emojiOpen.value = false
    persistAiMessage(text.trim(), 'elder')
    scrollToBottom()
  }
}

/** 家人会话发消息：先本地显示（老人立刻看到自己发的），再落服务端 */
function sendFamilyText(text) {
  const token = readToken()
  if (!token) {
    toast('请先登录')
    return
  }
  const local = {
    id: 'local_' + Date.now(),
    role: 'elder',
    type: 'text',
    text,
    createdAt: new Date().toISOString(),
    // 明确标记"这是我本地的待发条目"：归属判定优先看它，
    // 免得服务端还没回、senderId 还是空的时候被判到对方那一侧
    optimistic: true
  }
  familyMessages.value = familyMessages.value.concat([local])
  scrollToBottom()

  sendMessage(token, { conversationId: conversationId.value, text, senderRole: 'elder' })
    .then((data) => {
      // 用服务端返回的那条替换本地临时条目（拿到真 id / senderId / 时间）
      const saved = (data && data.message) || null
      if (saved) {
        familyMessages.value = familyMessages.value.map((m) =>
          m.id === local.id
            ? {
                id: saved.id,
                // 关键：把 senderId 一起带进来，归属判定要靠它
                senderId: saved.senderId || '',
                senderName: saved.senderName || '',
                role: 'elder',
                type: 'text',
                text: saved.text,
                createdAt: saved.createdAt
              }
            : m
        )
      }
      refreshConversations()
    })
    .catch((error) => {
      // 发失败就撤掉本地那条，别让老人以为发出去了
      familyMessages.value = familyMessages.value.filter((m) => m.id !== local.id)
      draft.value = text
      toast((error && error.message) || '没发出去，再试一次')
    })
}

/**
 * 把智能体会话的消息也存到服务端（跨设备可见）。
 * 智能体那条用 senderRole=agent，服务端会换成独立的 sender id，
 * 这样未读/已读才分得清"谁发给谁"。
 */
function persistAiMessage(text, role) {
  const token = readToken()
  if (!token || !conversationId.value) return
  sendMessage(token, {
    conversationId: conversationId.value,
    text,
    senderRole: role === 'agent' ? 'agent' : 'elder'
  })
    .then(() => refreshConversations())
    .catch(() => {
      // 存不上不影响本次对话；下次进来自会重新拉历史
    })
}

function onRetry() {
  if (retry()) scrollToBottom()
}

function playVoice() {
  toast('正在播放语音（P3 接入 CosyVoice 2）')
}

function toast(title) {
  uni.showToast({ title: title, icon: 'none' })
}

function back() {
  const pages = getCurrentPages()
  if (pages.length > 1) uni.navigateBack()
  else uni.reLaunch({ url: '/pages/chats/chats' })
}

function toVision() {
  uni.navigateTo({ url: '/pages/vision/vision' })
}
</script>

<style scoped>
.bl-ai-notice {
  flex: none;
  display: flex;
  justify-content: center;
  padding: 0 24rpx 12rpx;
  background-color: var(--bl-bg);
}
.bl-ai-notice__text {
  font-size: 22rpx;
  color: var(--bl-text-2);
  line-height: 1.6;
}

.bl-chat-body {
  flex: 1;
  min-height: 0;
  padding: 16rpx 24rpx 0;
  background-color: var(--bl-bg);
  box-sizing: border-box;
}
.bl-chat-body__pad { height: 32rpx; }

/* 接收状态：挂在对方最新一条消息下面（左缩进对齐对方气泡） */
.bl-receipt {
  display: flex;
  align-items: center;
  gap: 8rpx;
  padding: 0 var(--bl-space-lg) 12rpx 128rpx;
}
.bl-receipt__dot {
  font-size: 20rpx;
  color: #C81E1E;
  line-height: 1;
}
.bl-receipt__text {
  font-size: var(--bl-font-caption);
  color: #C81E1E;
  line-height: 1.4;
}
.bl-receipt__text--read {
  color: var(--bl-text-2);
}

.bl-emoji-panel {
  flex: none;
  background-color: var(--bl-surface-2);
  border-top: 1rpx solid var(--bl-divider);
}
.bl-emoji-grid {
  display: flex;
  flex-wrap: wrap;
  padding: 24rpx 16rpx;
}
.bl-emoji {
  width: 33.33%;
  padding: 16rpx 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  border-radius: var(--bl-radius-bubble);
}
.bl-emoji:active { background-color: var(--bl-primary-soft); }
.bl-emoji__ch { font-size: 52rpx; line-height: 1.2; }
.bl-emoji__label {
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  margin-top: 4rpx;
}

.bl-composer {
  flex: none;
  display: flex;
  align-items: center;
  gap: 12rpx;
  padding: 16rpx 24rpx;
  background-color: var(--bl-surface-2);
  border-top: 1rpx solid var(--bl-divider);
  padding-bottom: calc(16rpx + env(safe-area-inset-bottom));
}
.bl-composer__btn {
  width: 80rpx;
  height: 80rpx;
  flex: none;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}
.bl-composer__btn:active { background-color: rgba(0, 0, 0, .06); }
.bl-composer__input {
  flex: 1;
  min-width: 0;
  height: 80rpx;
  padding: 0 24rpx;
  background-color: var(--bl-surface);
  border-radius: 40rpx;
  font-size: var(--bl-font-caption);
  color: var(--bl-text);
  box-sizing: border-box;
}
.bl-composer__ph { color: var(--bl-icon-muted); }

/* 发送 / 停止：一个按钮两种身份，老人只需要记一个位置 */
.bl-composer__send {
  flex: none;
  min-width: 148rpx;
  height: 88rpx;
  padding: 0 28rpx;
  border-radius: var(--bl-radius-pill);
  background-color: var(--bl-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
}
.bl-composer__send:active { background-color: var(--bl-primary-pressed); }
/* 停止态用朱砂：白字压在其上 5.94:1，达到适老化 4.5:1 */
.bl-composer__send--stop { background-color: var(--bl-danger); }
.bl-composer__send--stop:active { background-color: #96302A; }
/* 输入为空时置灰：文字 #5A5A5A 压灰底，对比度约 5.6:1，仍然达标 */
.bl-composer__send--off { background-color: #E4E0D5; }
.bl-composer__send--off:active { background-color: #D8D4C8; }
.bl-composer__send--off .bl-composer__send-text { color: #5A5A5A; }
.bl-composer__send-text {
  font-size: var(--bl-font-body);
  font-weight: 600;
  color: var(--bl-surface);
  line-height: 1.2;
}
</style>
