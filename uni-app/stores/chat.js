/**
 * 比邻AI · 对话状态（会话 / 消息 / 流式生命周期）
 *
 * 设计取舍：
 *   - 不引入 Pinia，沿用仓库既有的「reactive 单例」做法，保持零依赖
 *   - 发送是**乐观**的：老人点了发送立刻上屏，再走流式回填，网络慢也不会"点了没反应"
 *   - 任何一步失败都不留白屏：本地缓存 → 内置种子 → 系统提示，逐级兜底（设计方案 §1.3「降级可活」）
 *   - 一条消息的生命周期：sending → streaming → sent / stopped / failed
 */

import { reactive } from 'vue'
import { chatStream, chatHistory, CHAT_EVENT } from '@/api/index.js'

export const DEFAULT_CONVERSATION_ID = 'c_son'

export const DEFAULT_PERSONA = {
  id: 'p_bilin',
  name: '比邻',
  relation: '陪伴助手',
  // 会话列表里显示的开场白 = 这个智能体的自我介绍（能干什么）
  intro: '我是比邻 能陪你聊天、提醒吃药、还能帮你给家里人发消息',
  // 水墨版头像底色：松烟墨绿，替代原微信绿
  avatarColor: '#3C6B58'
}

const CACHE_PREFIX = 'bl_chat_v1_'
const CACHE_LIMIT = 60

export const chat = reactive({
  conversationId: DEFAULT_CONVERSATION_ID,
  persona: Object.assign({}, DEFAULT_PERSONA),
  messages: [],
  /** 是否正在流式接收 */
  streaming: false,
  /** 是否已经初始化过（避免重复灌种子） */
  ready: false,
  /** 最近一次失败原因（给「重试」按钮用） */
  lastError: '',
  canRetry: false
})

let handle = null
let lastUserText = ''
let lastUserMsgId = ''
let idSeq = 0

/**
 * 实时事件订阅（**只给通话页用**）。
 *
 * 为什么需要：`audio` 与 `lipsync` 是"这一轮说完才发"的数据，
 * 它们**不该进聊天历史**（历史里存的是文字/表情/卡片，音频链接几分钟后就过期），
 * 但通话页需要**实时拿到**才能让数字人开口动嘴。
 *
 * 所以做成"订阅"而不是塞进 `chat.messages`：历史干净、通话页按需接。
 * 回调收到的 payload：`{ text, audioUrl, cues, lipsyncSource, assistantMsgId }`
 */
const liveListeners = new Set()

/**
 * 订阅一轮"数字人说话"的完整数据（文字 + 音频 + 口型）。
 * @param {(payload:object)=>void} listener
 * @returns {()=>void} 取消订阅
 */
export function onLiveTurn(listener) {
  if (typeof listener !== 'function') return () => {}
  liveListeners.add(listener)
  return () => liveListeners.delete(listener)
}

function emitLiveTurn(payload) {
  for (const listener of liveListeners) {
    try {
      listener(payload)
    } catch (error) {
      // 一个订阅者出错不该影响其他订阅者（也不该影响对话本身）
      console.warn('[chat] liveTurn 订阅者抛错：', error)
    }
  }
}

/** 当前这一轮的收集状态 */
let turn = null

/* ------------------------------------------------------------------ 初始化 */

export function initChat() {
  if (chat.ready) return
  chat.ready = true
  const cached = readCache()
  if (cached && cached.length) {
    chat.messages = cached
    // 老缓存里通常没有自我介绍，补上后再落盘
    ensureIntroFirst()
    persist()
    return
  }
  const seeded = seedMessages()
  chat.messages = seeded
  loadHistoryOnce(seeded)
}

/**
 * 切到某个角色来聊（「对话」栏目点某一行时调用）。
 *
 * 每个角色一个独立会话：`conversationId` 就是角色的 id，
 * 而缓存 key 是 `bl_chat_v1_<conversationId>`（见 cacheKey），
 * 所以换角色不会串台——老人跟"棋友"说的话不会出现在"比邻AI"的对话里。
 *
 * @param {object} persona 角色转成的人设，见 stores/roles.js 的 roleToPersona
 */
export function usePersona(persona) {
  if (!persona || !persona.id) return false
  chat.persona = Object.assign({}, DEFAULT_PERSONA, persona)
  chat.conversationId = persona.id
  // 换会话必须清掉"已初始化"标记，否则新角色会沿用上一个角色的消息
  chat.ready = false
  chat.messages = []
  chat.lastError = ''
  chat.canRetry = false
  initChat()
  return true
}

/** 首次启动拉一次服务端历史；拉不到就安静地用本地种子（不弹错） */
function loadHistoryOnce(snapshot) {
  chatHistory({ conversationId: chat.conversationId, limit: 50 })
    .then((res) => {
      // 期间老人已经发过消息，或者已经在流式接收 → 放弃覆盖，避免把新消息冲掉
      if (chat.messages !== snapshot || chat.streaming) return
      if (!res.messages || !res.messages.length) return
      chat.messages = res.messages.map(fromServer)
      ensureIntroFirst()
      persist()
    })
    .catch(() => {
      // 服务端还没起、或没有历史：保持种子内容即可
    })
}

/**
 * 保证对话以「比邻的自我介绍」开头。
 * 服务端历史 / 本地缓存都可能不含这条（老数据），因此每次取回历史后补一次；
 * 已经说过就不再重复插入。
 */
function ensureIntroFirst() {
  const intro = chat.persona.intro
  if (!intro) return
  const already = chat.messages.some((m) => m.role === 'agent' && m.text === intro)
  if (already) return
  chat.messages.unshift(makeMessage({ type: 'time', text: '今天 09:10' }))
  chat.messages.unshift(makeMessage({ role: 'agent', text: intro }))
}

/* -------------------------------------------------------------------- 发送 */

export function send(rawText) {
  const text = String(rawText == null ? '' : rawText).trim()
  if (!text || chat.streaming) return false

  chat.lastError = ''
  chat.canRetry = false
  lastUserText = text

  const elderMsg = push({ role: 'elder', type: 'text', text, status: 'sent' })
  lastUserMsgId = elderMsg.id
  beginStream(text, elderMsg.id)
  return true
}

/** 重发上一条：清掉失败痕迹后重新跑一次，不重复上屏用户那句话 */
export function retry() {
  if (chat.streaming || !lastUserText) return false
  trimFailedTail()
  chat.lastError = ''
  chat.canRetry = false
  beginStream(lastUserText, lastUserMsgId)
  return true
}

/**
 * 一键停止（产品红线：老人可随时停下）。
 * 已收到的部分保留在气泡里，不整段消失——老人看到"说到这儿停了"比看到空白踏实。
 */
export function stop() {
  if (!chat.streaming) return
  if (handle && handle.abort) {
    handle.abort() // 会同步回调 onError({code:'aborted'}) → finishTurn('stopped')
    return
  }
  finishTurn('stopped')
}

function beginStream(text, clientMsgId) {
  turn = { textMsg: null, produced: false, serverId: '', audioUrl: '', cues: null, lipsyncSource: '' }
  chat.streaming = true
  handle = chatStream({
    conversationId: chat.conversationId,
    personaId: chat.persona.id,
    text,
    clientMsgId,
    onEvent: handleEvent,
    onError: handleTransportError,
    onDone(info) {
      // 服务端没发 done 就断了：按"说到这儿"处理，不报错、不清屏
      if (info && info.businessDone) return
      finishTurn('sent')
    }
  })
}

function handleEvent(event) {
  if (!chat.streaming) return

  switch (event.type) {
    case CHAT_EVENT.meta:
      if (event.assistantMsgId) {
        turn.serverId = event.assistantMsgId
        if (turn.textMsg) turn.textMsg.serverId = event.assistantMsgId
      }
      if (event.persona && event.persona.name) {
        chat.persona = Object.assign({}, chat.persona, event.persona)
      }
      break

    case CHAT_EVENT.token:
      ensureTextMessage().text += event.text
      turn.produced = true
      break

    case CHAT_EVENT.sticker:
      push({
        role: 'agent',
        type: 'sticker',
        sticker: event.token,
        status: 'sent',
        serverId: turn.serverId
      })
      turn.produced = true
      break

    case CHAT_EVENT.card:
      push({
        role: 'agent',
        type: 'card',
        card: event.card,
        status: 'sent',
        serverId: turn.serverId
      })
      turn.produced = true
      break

    case CHAT_EVENT.done:
      // 先广播"这一轮说完"的完整数据（文字 + 音频 + 口型），再收尾。
      // 顺序重要：通话页要靠 audio 先起播、再用音频时钟驱动口型，
      // 所以这里必须把两者**一起**给出去，让调用方自己决定怎么起播。
      emitLiveTurn({
        assistantMsgId: turn.serverId || '',
        text: turn.textMsg ? turn.textMsg.text : '',
        audioUrl: turn.audioUrl || '',
        cues: turn.cues || null,
        lipsyncSource: turn.lipsyncSource || ''
      })
      finishTurn('sent')
      break

    case CHAT_EVENT.audio:
      // 合成音频的**短期签名 URL**（端侧播放器能直取，不需要请求头）
      turn.audioUrl = event.url || ''
      break

    case CHAT_EVENT.lipsync:
      // 口型关键帧（服务端已把 viseme 收敛到 ≤2 个）；`source` 区分估算/真对齐
      turn.cues = event.cues || null
      turn.lipsyncSource = event.source || 'estimated'
      break

    case CHAT_EVENT.error:
      failTurn(event.message || '出了点小问题', event.retryable !== false)
      break

    default:
      break
  }
}

function handleTransportError(err) {
  if (!err) return
  if (err.code === 'aborted') {
    finishTurn('stopped')
    return
  }
  failTurn(err.message || '连不上服务器', err.retryable !== false)
}

function ensureTextMessage() {
  if (!turn.textMsg) {
    turn.textMsg = push({
      role: 'agent',
      type: 'text',
      text: '',
      status: 'streaming',
      serverId: turn.serverId
    })
  }
  return turn.textMsg
}

function finishTurn(status) {
  if (!chat.streaming || !turn) return
  chat.streaming = false
  handle = null

  if (turn.textMsg) {
    if (turn.textMsg.text) turn.textMsg.status = status
    else removeMessage(turn.textMsg) // 一个字都没收到就别留空气泡
  }
  if (!turn.produced) {
    push({ role: 'system', type: 'system', text: '没听清 再说一遍' })
  }

  turn = null
  persist()
}

function failTurn(message, retryable) {
  if (!chat.streaming || !turn) return
  chat.streaming = false
  handle = null

  if (turn.textMsg) {
    if (turn.textMsg.text) turn.textMsg.status = 'failed'
    else removeMessage(turn.textMsg)
  }
  chat.lastError = message
  chat.canRetry = !!retryable
  push({ role: 'system', type: 'system', text: message })

  turn = null
  persist()
}

/* -------------------------------------------------------------- 消息工具 */

function makeMessage(partial) {
  idSeq += 1
  return Object.assign({
    id: 'm_' + Date.now().toString(36) + '_' + idSeq,
    role: 'agent',
    type: 'text',
    text: '',
    sticker: '',
    card: null,
    seconds: 0,
    createdAt: Date.now(),
    status: 'sent',
    serverId: ''
  }, partial)
}

function push(partial) {
  const message = makeMessage(partial)
  chat.messages.push(message)
  return message
}

function removeMessage(message) {
  const at = chat.messages.indexOf(message)
  if (at !== -1) chat.messages.splice(at, 1)
}

/** 重发前把末尾的失败气泡与系统提示清掉 */
function trimFailedTail() {
  while (chat.messages.length) {
    const last = chat.messages[chat.messages.length - 1]
    if (last.type === 'system' || last.status === 'failed') chat.messages.pop()
    else break
  }
}

/**
 * 原型基线文案（服务端不可用时的兜底内容）。
 *
 * 第一条**必须是当前角色的自我介绍**：会话列表里显示的那句话和点进来看到的第一句
 * 要是同一句，否则老人会以为点错了人。之前这里硬编码 `DEFAULT_PERSONA.intro`，
 * 导致切换到自建角色后开场白还是"比邻"的。
 *
 * 后两条按角色类型给不同的示例对话：自建角色用老人自己填的关系与故事，
 * 这样一进来就是"像那个人"的语气，而不是通用客服话术。
 */
function seedMessages() {
  const persona = chat.persona || DEFAULT_PERSONA
  const intro = persona.intro || DEFAULT_PERSONA.intro

  if (!persona.id || persona.id === DEFAULT_PERSONA.id) {
    return [
      makeMessage({ type: 'time', text: clockLabel() }),
      makeMessage({ role: 'agent', text: intro }),
      makeMessage({ role: 'elder', text: '那你能帮我做点啥' }),
      makeMessage({
        role: 'agent',
        text: '吃药、量血压这些事，到点我会提醒你；\n想孩子了，跟我说一声，我帮你把消息发过去'
      })
    ]
  }

  // 自建角色：用老人填的关系/故事做两句"像那个人"的话
  const relation = persona.relation || ''
  const lead = relation ? '我是你的' + relation + '啊' : '我在呢'
  return [
    makeMessage({ type: 'time', text: clockLabel() }),
    makeMessage({ role: 'agent', text: intro }),
    makeMessage({ role: 'elder', text: '你还记得我啊' }),
    makeMessage({
      role: 'agent',
      text: lead + '，怎么会忘。\n你想说什么，我听着呢'
    })
  ]
}

/** 当前时刻的会话时间标签（用它代替写死的"今天 09:10"） */
function clockLabel() {
  return '今天 ' + formatClock(Date.now())
}

function fromServer(m) {
  const message = makeMessage({})
  if (m.id) message.id = String(m.id)
  if (m.role === 'elder' || m.role === 'user') message.role = 'elder'
  else if (m.role === 'system') message.role = 'system'
  else message.role = 'agent'
  message.type = m.type || 'text'
  message.text = m.text || ''
  message.sticker = m.sticker || ''
  message.card = m.card || null
  message.seconds = m.seconds || 0
  const at = m.createdAt ? Date.parse(m.createdAt) : NaN
  message.createdAt = isNaN(at) ? Date.now() : at
  message.status = 'sent'
  return message
}

/* ---------------------------------------------------------------- 本地缓存 */

function cacheKey() {
  return CACHE_PREFIX + chat.conversationId
}

function persist() {
  try {
    const plain = chat.messages.slice(-CACHE_LIMIT).map((m) => ({
      id: m.id,
      role: m.role,
      type: m.type,
      text: m.text,
      sticker: m.sticker,
      card: m.card,
      seconds: m.seconds,
      createdAt: m.createdAt,
      // 未完成的中间态不落盘，重启后一律视作已完成
      status: m.status === 'streaming' || m.status === 'sending' ? 'sent' : m.status
    }))
    uni.setStorageSync(cacheKey(), JSON.stringify(plain))
  } catch (e) {
    // 存储失败不影响本次会话
  }
}

function readCache() {
  try {
    const raw = uni.getStorageSync(cacheKey())
    if (!raw) return null
    const list = typeof raw === 'string' ? JSON.parse(raw) : raw
    if (!Array.isArray(list)) return null
    return list.map(fromServer)
  } catch (e) {
    return null
  }
}

/** 清空本地缓存（调试 / 「清空聊天记录」用） */
export function resetChat() {
  chat.messages = []
  chat.ready = false
  handle = null
  turn = null
  chat.streaming = false
  try { uni.removeStorageSync(cacheKey()) } catch (e) { /* 忽略 */ }
}

/* ------------------------------------------------------------ 列表页取用 */

/** 会话列表的「最后一条」预览文案 */
export function lastPreview() {
  for (let i = chat.messages.length - 1; i >= 0; i -= 1) {
    const m = chat.messages[i]
    if (m.type === 'time') continue
    if (m.type === 'sticker') return '[表情]'
    if (m.type === 'card') return '[计划提醒]'
    if (m.text) return m.text.replace(/\n/g, ' ')
  }
  return '还没有消息'
}

/** 会话列表的时间（HH:MM） */
export function lastTime() {
  for (let i = chat.messages.length - 1; i >= 0; i -= 1) {
    const m = chat.messages[i]
    if (m.type === 'time') continue
    return formatClock(m.createdAt)
  }
  return ''
}

export function formatClock(ts) {
  const d = new Date(ts || Date.now())
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return hh + ':' + mm
}

export default chat
