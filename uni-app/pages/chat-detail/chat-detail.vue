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
          :recalled="!!m.recalledAt"
          :quote-text="quoteTextOf(m)"
          :ai-sent="isAiSent(m)"
          :seconds="m.seconds"
          :avatar-color="isMine(m) ? '#6E6A5E' : personaColor"
          :sticker="m.sticker"
          :card="m.card"
          :streaming="m.status === 'streaming'"
          :status="m.status"
          @play="playVoice(m)"
          @retry="onRetry"
          @longpress="onMessageLongPress(m)"
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

    <!-- 引用预览：选了"引用"之后，在输入框上方显示被引的那条（可取消） -->
    <view v-if="quote" class="bl-quote-bar">
      <view class="bl-quote-bar__main">
        <text class="bl-quote-bar__label">引用 {{ quote.who }}</text>
        <text class="bl-quote-bar__text">{{ quote.text }}</text>
      </view>
      <view class="bl-quote-bar__close" role="button" aria-label="取消引用" @click="quote = null">
        <bl-icon name="back" color="#8A8A8A" :size="36" />
      </view>
    </view>

    <view class="bl-composer">
      <!-- 语音输入：接入真 ASR（按住说话 → 上传 → 转文字进输入框） -->
      <view
        class="bl-composer__btn"
        :class="{ 'is-recording': recording }"
        role="button"
        :aria-label="recording ? '松开结束录音' : '按住说话'"
        @touchstart.prevent="startVoice"
        @touchend.prevent="stopVoice"
        @touchcancel.prevent="cancelVoice"
        @longpress="toast('按住说话，松开就把您说的变成字')"
      >
        <bl-icon name="mic" :color="recording ? '#FFFFFF' : '#1F211D'" :size="48" />
      </view>
      <input
        v-model="draft"
        class="bl-composer__input"
        :placeholder="recording ? '正在听您说…' : '说点什么…'"
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
import { deleteMessage, fetchFamilyOverview, fetchMessages, markConversationRead, recallMessage, requestAutoReply, sendMessage } from '@/api/index.js'
import { readAccount, readToken } from '@/stores/account.js'
// 语音输入：按住说话 → 识别成文字（两端录音 API 差异关在 common/voice-input.js 里）
import { VoiceRecorder, transcribeAudio, voiceSupported } from '@/common/voice-input.js'
import { getBaseURL } from '@/api/config.js'

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

/** 当前引用（长按"引用"后设置；发送时带上 quoteId）。null 表示没引用。 */
const quote = ref(null)

/** 正在录音 */
const recording = ref(false)
/** 当前录音器实例（一次录音一个） */
let recorder = null

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

/**
 * 这条是不是「对方的智能体」代他发的。
 *
 * 判定：senderId 带 `agent:` 前缀，且不是我自己这边产生的。
 * 端侧据此显示「AI 发送」角标 —— **代人发言必须看得出来**。
 */
function isAiSent(m) {
  if (!m || isMine(m)) return false
  const sender = String(m.senderId || '')
  return sender.indexOf('agent:') === 0
}

/**
 * 这条智能体回复是不是**我自己的**（也就是我这条 AI 会话里的那个）。
 *
 * 与 `isAiSent` 是互斥的两种 agent 消息：
 *   · 我 AI 会话里的 agent 回复 → 归我管（能删）
 *   · 家人会话里对方智能体代回的 → **不能删**（那是对方记录的一部分）
 *
 * 判据与服务端 `_can_manage` 一致：只有**非家人会话**里的 agent 消息才算我的。
 * 端侧不靠 senderId 里的会话 id 去解析——那等于把服务端的编码规则复制一份，
 * 两边一旦不同步就会「按钮给了但请求被拒」。这里只按会话类型分。
 */
function isMyAgentReply(m) {
  if (!m || isFamily.value) return false
  return String(m.senderId || '').indexOf('agent:') === 0
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
/**
 * 把服务端历史合并进 `chat.messages`，**不是整体替换**。
 *
 * ⚠️ 原来这里是 `chat.messages = list.map(...)`（覆盖赋值），有两个后果：
 *   1. **本地刚推上去、服务端还没落库的消息会被冲掉** ——
 *      `onSend` 先本地 push（乐观上屏）再发请求，而进页面时那次
 *      `loadAiHistory` 是异步的；它晚一步回来就把刚发的话抹了。
 *      现象就是用户反馈的「我发的消息没显示在聊天框里」。
 *   2. 服务端某次返回空（或只回了早先几条）时，本地已渲染的内容会整段消失。
 *
 * 合并规则：
 *   · 以服务端那份为准（它有真实 id / 顺序）
 *   · 本地有、服务端没有的（还在路上 / 存失败）→ **保序插回**，不能丢
 *   · 两边都有 → 用服务端的覆盖（正文更权威）
 */
function mergeAiHistory(serverList) {
  const fromServer = serverList.map((m) => ({
    id: m.id,
    role: m.senderRole === 'agent' ? 'agent' : 'elder',
    type: 'text',
    text: m.text,
    createdAt: m.createdAt
  }))
  const serverIds = {}
  fromServer.forEach((m) => {
    serverIds[m.id] = true
  })
  // 服务端没有、但本地已有的：保留（id 形如 local_ / 乐观条目）
  const localOnly = chat.messages.filter((m) => m && m.id && !serverIds[m.id])
  chat.messages = fromServer.concat(localOnly)
}

function loadAiHistory() {
  const token = readToken()
  if (!token || !conversationId.value) return
  fetchMessages(token, conversationId.value, 100)
    .then((data) => {
      const list = (data && data.messages) || []
      unreadShown.value = (data && data.unread) || 0
      // 正在流式回复时不打断（否则会把正在打字的那条冲掉）。
      // 注意与旧版的区别：**不再**因为 list 为空就整体跳过——
      // 合并逻辑本身已经保证本地内容不丢，空历史同样不该抹掉它。
      if (chat.streaming) return
      mergeAiHistory(list)
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
  if (recording.value) {
    toast('正在录音，先松开手')
    return
  }
  const text = draft.value
  if (!text || !text.trim()) {
    toast('说点什么吧')
    return
  }

  // 引用：带着 quoteId 发出去，发完清掉引用态
  const quotedId = quote.value ? quote.value.id : ''

  // 与家人的会话：消息走服务端，双方共享同一份记录
  if (isFamily.value) {
    draft.value = ''
    emojiOpen.value = false
    quote.value = null
    sendFamilyText(text.trim(), quotedId)
    return
  }

  // 与智能体的会话：保留原来的流式回复（打字机 / 语音 / 表情都在这条路上），
  // 同时把消息存到服务端，这样换设备也看得到。
  if (send(text)) {
    draft.value = ''
    emojiOpen.value = false
    quote.value = null
    persistAiMessage(text.trim(), 'elder', quotedId)
    scrollToBottom()
  }
}

/* --------------------------------------- 对方不在线时，他的智能体代回一句 */

/** 正在等代回（避免连点造成多条代回） */
let autoReplyBusy = false

/**
 * 把对方今天的日程拼成一句话，给代回的 prompt 用。
 *
 * 需求：「回复的内容为对方现在正在干嘛（参考日程安排）比如有特殊安排时」。
 *
 * 取不到（没绑定 / 接口失败 / 今天没安排）都返回空串 —— 代回照常进行，
 * 只是不提"在干嘛"，而不是整条代回失败。
 */
function buildPeerSchedule() {
  const token = readToken()
  if (!token || !pending.peerNumber) return Promise.resolve('')
  return fetchFamilyOverview(token, pending.peerNumber)
    .then((data) => {
      const today = (data && data.today) || {}
      const items = Array.isArray(today.items) ? today.items : []
      if (!items.length) return ''
      // 只挑"还没做"的：已完成的事说"正在做"就不对了
      const pendingItems = items.filter((it) => !it.done)
      const list = (pendingItems.length ? pendingItems : items).slice(0, 3)
      const parts = list.map((it) => {
        const time = it.time ? it.time + ' ' : ''
        return time + (it.title || it.type || '有事')
      })
      return '他今天的安排：' + parts.join('；') + '。'
    })
    .catch(() => '')
}

/**
 * 我发完消息后，请求服务端让**对方的智能体**代他回一句。
 *
 * 为什么放在端侧触发而不是服务端自动：
 * "对方在不在线"这个判断只有端侧知道（他在用 App 就不会需要代回）。
 * 服务端一旦自动代回，真人自己回的时候就会变成两个人各说一句。
 *
 * 代回失败**不打扰老人**：这只是"对方没及时回"的兜底，不是主流程。
 */
function maybePeerAutoReply() {
  if (!isFamily.value || autoReplyBusy) return
  if (!pending.peerNumber) return
  autoReplyBusy = true
  buildPeerSchedule()
    .then((schedule) => {
      const token = readToken()
      if (!token) return null
      return requestAutoReply(token, {
        conversationId: conversationId.value,
        schedule,
        peerName: serverTitle.value || ''
      })
    })
    .then((data) => {
      if (!data || !data.ok) return
      // 直接把代回那条追加进来，不等下一次拉历史（老人很快就能看到回应）
      const msg = data.message
      if (!msg || !msg.id) return
      const exists = familyMessages.value.some((m) => m.id === msg.id)
      if (!exists) {
        familyMessages.value = familyMessages.value.concat([msg])
        scrollToBottom()
      }
      refreshConversations()
    })
    .catch(() => {
      // 代回是兜底能力，失败就静默（老人不该为这个看到报错）
    })
    .then(() => {
      autoReplyBusy = false
    })
}

/* ------------------------------------------------- 长按菜单：撤回 / 引用 / 删除 */

/**
 * 取一条消息要显示的引用文字。
 * 被引的那条可能已被撤回（text 为空）或已被删掉（本地找不到），两种都给明确占位。
 */
function quoteTextOf(m) {
  if (!m || !m.quoteId) return ''
  const all = messages.value
  const target = all.find((x) => x.id === m.quoteId)
  if (!target) return '引用的消息已不在'
  if (target.recalledAt) return '引用的消息已撤回'
  return String(target.text || '').slice(0, 60)
}

/** 引用弹层里显示"谁说的" */
function whoOf(m) {
  if (isMine(m)) return '我'
  return serverTitle.value || pageTitle.value || '对方'
}

/** 撤回时间窗（秒），与服务端 RECALL_WINDOW_SECONDS 对齐 */
const RECALL_WINDOW_SECONDS = 120

/** 这条消息现在还能不能撤回（自己发的、未撤回、且在窗口内） */
function canRecall(m) {
  if (!m || m.recalledAt) return false
  if (!isMine(m)) return false
  // 本地还没落库的条目本来就没发出去，谈不上撤回
  if (String(m.id || '').indexOf('local_') === 0) return false
  const stamp = Date.parse(m.createdAt || '')
  if (isNaN(stamp)) return true
  return (Date.now() - stamp) / 1000 <= RECALL_WINDOW_SECONDS
}

/**
 * 能不能删。
 *
 * 允许删两种：
 *   · 我发的
 *   · **我这条 AI 会话里的智能体回复** —— 它就是替我说话的，归我管
 *
 * 不允许删：家人会话里对方发的、以及**对方智能体代他回的**。
 * 共享会话是双方共用的一份记录，单方面删掉等于篡改对方看到的内容。
 * （与服务端 `_can_manage` 同一套判据，两边一致才不会出现"按钮给了却被拒"。）
 */
function canDelete(m) {
  if (!m) return false
  if (String(m.id || '').indexOf('local_') === 0) return false
  return isMine(m) || isMyAgentReply(m)
}

/**
 * 长按一条消息 → 弹选项。
 *
 * 与微信/QQ 一致：「引用」双方消息都有；「撤回」只有自己发的；
 * 「删除」除了自己发的，还包括**我 AI 会话里的智能体回复**
 * （它就是替我说话的，用户反馈"删不掉"指的就是它）。
 * 家人会话里对方的消息与对方智能体的代回都不给删除入口。
 *
 * 用 `uni.showActionSheet` 而不是自绘弹层：原生弹层在 App 与 H5 上行为一致、
 * 层级不会被 WebView 里的 3D canvas 盖住，也不必处理滚动锁定。
 */
function onMessageLongPress(m) {
  if (!m || m.type === 'time' || m.type === 'system') return
  if (chat.streaming) { toast('等我说完再操作') ; return }

  const actions = []
  if (canRecall(m)) actions.push({ key: 'recall', label: '撤回' })
  actions.push({ key: 'quote', label: '引用' })
  if (canDelete(m)) actions.push({ key: 'delete', label: '删除' })

  // 只有一项（比如对方的消息）时也照常弹，保持行为一致
  uni.showActionSheet({
    itemList: actions.map((a) => a.label),
    success: (res) => {
      const picked = actions[res.tapIndex]
      if (!picked) return
      if (picked.key === 'recall') doRecall(m)
      else if (picked.key === 'quote') doQuote(m)
      else if (picked.key === 'delete') doDelete(m)
    },
    fail: () => {}
  })
}

/** 引用：记下来，发送时带上 quoteId */
function doQuote(m) {
  const text = m.recalledAt ? '（已撤回）' : String(m.text || '')
  quote.value = { id: m.id, text: text.slice(0, 60), who: whoOf(m) }
  // 引用文本不该把输入框占满
  if (m.type === 'voice') quote.value.text = '[语音]'
  else if (m.type === 'sticker') quote.value.text = '[表情]'
  else if (m.type === 'card') quote.value.text = '[卡片]'
  toast('已引用，说点什么吧')
}

/** 撤回：先本地乐观更新，再落服务端；失败则回滚 */
function doRecall(m) {
  const token = readToken()
  if (!token) { toast('请先登录'); return }
  const backup = m.recalledAt
  m.recalledAt = new Date().toISOString()
  recallMessage(token, conversationId.value, m.id)
    .then(() => {
      // 家人会话要重新拉（撤回是双方共享的状态）；
      // AI 会话本地已经有乐观标记了，不必再请求一次
      if (isFamily.value) loadFamilyMessages()
      toast('已撤回')
    })
    .catch((error) => {
      m.recalledAt = backup || ''
      toast((error && error.message) || '撤不回来了')
    })
}

/** 移除一条消息（按当前会话类型改对应的数据源）。
 *
 * ⚠️ 这里必须分岔：AI 会话显示的是 `chat.messages`，家人会话是 `familyMessages`。
 * 只改后者的话，AI 会话里删完界面毫无变化——用户看到的就是"删不掉"。
 */
function dropMessage(id) {
  if (isFamily.value) {
    familyMessages.value = familyMessages.value.filter((x) => x.id !== id)
    return
  }
  chat.messages = chat.messages.filter((x) => x.id !== id)
}

/** 删除：二次确认，删完刷新列表 */
function doDelete(m) {
  const token = readToken()
  if (!token) { toast('请先登录'); return }
  uni.showModal({
    title: '删除这条消息？',
    // 家人会话是双方共享的记录，删了对方也看不到；自己这边则是清掉本地记录
    content: isFamily.value ? '删除后双方都看不到了' : '删除后这条消息就没有了',
    confirmText: '删除',
    cancelText: '再想想',
    success: (res) => {
      if (!res.confirm) return
      deleteMessage(token, conversationId.value, m.id)
        .then(() => {
          dropMessage(m.id)
          refreshConversations()
          toast('已删除')
        })
        .catch((error) => toast((error && error.message) || '删不掉'))
    }
  })
}

/* --------------------------------------------------------------- 语音输入 */

/**
 * 按住麦克风 → 录音 → 松开 → 上传识别 → 文字落进输入框。
 *
 * 为什么不做成"识别完直接发出去"：识别难免有错（尤其方言），
 * 让老人**先看到文字、确认后再发**比自动发出更稳妥。
 */
function startVoice() {
  if (recording.value) return
  const support = voiceSupported()
  if (!support.ok) { toast(support.reason); return }
  if (chat.streaming) { toast('等我说完再说') ; return }

  recorder = new VoiceRecorder({ onError: (why) => toast(why) })
  recording.value = true
  recorder.start().then((res) => {
    if (!res.ok) { recording.value = false; recorder = null }
  }).catch(() => { recording.value = false; recorder = null })
}

function stopVoice() {
  if (!recording.value || !recorder) return
  recording.value = false
  const token = readToken()
  recorder.stop().then((res) => {
    recorder = null
    if (!res.ok) { if (res.reason) toast(res.reason); return }
    toast('正在识别…')
    return transcribeAudio(res.audio, { baseUrl: getBaseURL(), token })
      .then((out) => {
        if (!out.ok) { toast(out.reason); return }
        // 落到输入框末尾，不覆盖已经打了一半的字
        draft.value = (draft.value ? draft.value + ' ' : '') + out.text
      })
  }).catch((error) => {
    recorder = null
    toast((error && error.message) || '录音失败')
  })
}

function cancelVoice() {
  if (recorder) { recorder.cancel(); recorder = null }
  recording.value = false
}

/** 家人会话发消息：先本地显示（老人立刻看到自己发的），再落服务端 */
function sendFamilyText(text, quoteId) {
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
    // 本地也带上 quoteId，这样"引用"的效果是**立刻**可见的，
    // 不用等服务端回包（弱网下等回包会有一段"引用没生效"的空窗）
    quoteId: quoteId || '',
    // 明确标记"这是我本地的待发条目"：归属判定优先看它，
    // 免得服务端还没回、senderId 还是空的时候被判到对方那一侧
    optimistic: true
  }
  familyMessages.value = familyMessages.value.concat([local])
  scrollToBottom()

  sendMessage(token, { conversationId: conversationId.value, text, senderRole: 'elder', quoteId: quoteId || '' })
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
                createdAt: saved.createdAt,
                quoteId: saved.quoteId || '',
                recalledAt: saved.recalledAt || ''
              }
            : m
        )
      }
      refreshConversations()
      // 我发出去了 → 让对方（不在线时）的智能体代他回一句
      maybePeerAutoReply()
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
function persistAiMessage(text, role, quoteId) {
  const token = readToken()
  if (!token || !conversationId.value) return
  sendMessage(token, {
    conversationId: conversationId.value,
    text,
    senderRole: role === 'agent' ? 'agent' : 'elder',
    quoteId: quoteId || ''
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
/* 录音中：按钮变实心主色，给一个明确的"正在听"的视觉信号
   （老人看不见后台状态，只能靠这个判断手有没有按住生效） */
.bl-composer__btn.is-recording {
  background-color: var(--bl-primary, #2F5D4E);
}

/* 引用预览条：贴在输入框上方，可点右侧取消 */
.bl-quote-bar {
  flex: none;
  display: flex;
  align-items: center;
  gap: 12rpx;
  padding: 12rpx var(--bl-space-lg);
  background-color: rgba(47, 93, 78, .08);
  border-top: 1rpx solid var(--bl-divider);
}
.bl-quote-bar__main { flex: 1; min-width: 0; }
.bl-quote-bar__label {
  display: block;
  font-size: 22rpx;
  color: var(--bl-primary, #2F5D4E);
}
.bl-quote-bar__text {
  display: block;
  font-size: 24rpx;
  color: var(--bl-text-2);
  /* 单行省略：引用条不该把输入区顶高 */
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.bl-quote-bar__close {
  width: 56rpx;
  height: 56rpx;
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
  /* 复用返回图标（一个箭头），转 90 度当"关闭"用，省一个图标资源 */
  transform: rotate(90deg);
}
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
