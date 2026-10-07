/**
 * 比邻AI · 联系人（会话列表 + 未读 + 备注）
 *
 * 这个 store 是「对话」栏目和「我的 → 家人绑定」的共同数据源。
 *
 * ## 三件事的分工
 *
 * 1. **会话与未读**：事实来源在服务端（`/v1/conversations`）。
 *    为什么不能像以前那样只读本地缓存：家人绑定后**两个账号共享同一条会话**，
 *    各自登录都要看到同一份记录，本地缓存做不到这件事。
 * 2. **备注名**：按需求「只有我这边改，对方仍看到原名字」，
 *    所以备注**只存本机**、按账号隔离（key 带账号编号），不上传。
 * 3. **智能体会话**：单独一条，标题固定「比邻AI」，永远排在第一位。
 *
 * ## 备注与真实名字的关系
 *
 * 列表显示 `remark || title`。备注是本地覆盖层，删掉备注就回到服务端的名字。
 */

import { reactive } from 'vue'
import {
  bindFamily,
  fetchBindings,
  fetchConversations,
  unbindFamily
} from '@/api/index.js'
import { readAccount, readToken } from '@/stores/account.js'

/** 会话列表状态（模板请用 readConversations() 取副本） */
export const contacts = reactive({
  list: [],
  bindings: [],
  totalUnread: 0,
  ready: false,
  lastError: ''
})

/** 会话变化事件：对话栏目刷新用 */
export const EVENT_CONTACTS_CHANGED = 'bl:contacts-changed'

/**
 * 待打开/待改备注的会话（页面之间用这个传，不走 URL 查询参数）。
 *
 * 【为什么不走 URL 参数】会话 id 形如 `family:a_xxx__a_yyy`，里面带冒号；
 * 实测在 uni-app 的 H5 路由里这个参数会被**编码两次**
 * （`%3A` 又变成 `%253A`），到页面解出来就是错的 id：
 * 表现为"拉不到聊天记录 / 未读清不掉 / 消息发不出去 / 名字显示成 %E5%A5%B3…"。
 * 用内存传递就没有编码这回事。
 */
export const pending = reactive({
  conversationId: '',
  kind: 'ai',
  title: '',
  /** 对端账号编号：家人会话才有，用于调「家人查看管理」接口 */
  peerNumber: ''
})

/** 打开会话前登记上下文（chat-detail 读它） */
export function setPendingConversation(item) {
  pending.conversationId = (item && item.id) || ''
  pending.kind = (item && item.kind) || 'ai'
  pending.title = (item && (item.title || item.displayName)) || ''
  pending.peerNumber = (item && item.peerNumber) || ''
}

/** 改备注前登记上下文（remark 读它） */
export function setPendingRemark(item) {
  pending.conversationId = (item && item.id) || ''
  pending.title = (item && (item.title || item.displayName)) || ''
  pending.peerNumber = (item && item.peerNumber) || ''
}

/** 打开「家人查看管理」前登记上下文 */
export function setPendingFamily(item) {
  pending.conversationId = (item && item.id) || ''
  pending.kind = 'family'
  pending.title = (item && (item.title || item.displayName)) || ''
  pending.peerNumber = (item && item.peerNumber) || ''
}

const pad = (value) => String(value || '').padStart(8, '0')

function emitChanged() {
  try {
    uni.$emit(EVENT_CONTACTS_CHANGED)
  } catch (e) {
    // 发不出去不影响主流程
  }
}

/* ------------------------------------------------------------ 备注（本地） */

/** 备注存储 key：按账号隔离，换账号不会串 */
function remarkKey() {
  const account = readAccount()
  return 'bl_remarks_v1_' + (account && account.number ? pad(account.number) : 'guest')
}

function readRemarks() {
  try {
    const raw = uni.getStorageSync(remarkKey())
    const map = raw ? (typeof raw === 'string' ? JSON.parse(raw) : raw) : {}
    return map && typeof map === 'object' ? map : {}
  } catch (e) {
    return {}
  }
}

function writeRemarks(map) {
  try {
    uni.setStorageSync(remarkKey(), JSON.stringify(map || {}))
  } catch (e) {
    // 存不上不影响本次使用
  }
}

/** 取某会话的备注（空串表示没改过） */
export function remarkOf(conversationId) {
  const map = readRemarks()
  return map[conversationId] || ''
}

/**
 * 设置备注。传空串等于删除备注（回到原名）。
 * @returns {{ok:boolean, remark:string}}
 */
export function setRemark(conversationId, remark) {
  const cid = String(conversationId || '')
  if (!cid) return { ok: false, remark: '' }
  const map = readRemarks()
  const clean = String(remark || '').trim()
  if (clean) map[cid] = clean
  else delete map[cid]
  writeRemarks(map)
  emitChanged()
  return { ok: true, remark: clean }
}

/** 列表显示名：备注优先，没有就用服务端的 title */
export function displayNameOf(item) {
  if (!item) return ''
  return remarkOf(item.id) || item.title || ''
}

/* ------------------------------------------------------------ 读取 */

/**
 * 会话列表副本。每项额外带 `displayName`，模板直接用。
 * 智能体会话永远排第一。
 */
export function readConversations() {
  const list = contacts.list.map((item) => Object.assign({}, item, {
    displayName: displayNameOf(item)
  }))
  list.sort((a, b) => {
    if (a.kind === 'ai' && b.kind !== 'ai') return -1
    if (b.kind === 'ai' && a.kind !== 'ai') return 1
    return String(b.updatedAt || '').localeCompare(String(a.updatedAt || ''))
  })
  return list
}

export function readBindings() {
  return contacts.bindings.map((item) => Object.assign({}, item))
}

export function totalUnread() {
  return contacts.totalUnread
}

export function findConversation(conversationId) {
  return readConversations().find((item) => item.id === conversationId) || null
}

/* ------------------------------------------------------------ 同步 */

/**
 * 从服务端刷新会话列表。
 * @returns {Promise<{ok:boolean, conversations?:Array, message?:string}>}
 */
export function refreshConversations() {
  const token = readToken()
  if (!token) {
    contacts.list = []
    contacts.totalUnread = 0
    contacts.ready = true
    return Promise.resolve({ ok: false, message: '' })
  }
  return fetchConversations(token)
    .then((data) => {
      contacts.list = (data && data.conversations) || []
      contacts.totalUnread = (data && data.totalUnread) || 0
      contacts.lastError = ''
      contacts.ready = true
      emitChanged()
      return { ok: true, conversations: readConversations() }
    })
    .catch((error) => {
      contacts.lastError = (error && error.message) || ''
      contacts.ready = true
      // 拉不到不清空：老人断网时仍应看到上次的列表，而不是"一条会话都没有"
      return { ok: false, message: contacts.lastError }
    })
}

/** 刷新我绑定的家人 */
export function refreshBindings() {
  const token = readToken()
  if (!token) {
    contacts.bindings = []
    return Promise.resolve({ ok: false })
  }
  return fetchBindings(token)
    .then((data) => {
      contacts.bindings = (data && data.bindings) || []
      emitChanged()
      return { ok: true, bindings: readBindings() }
    })
    .catch(() => ({ ok: false }))
}

/* ------------------------------------------------------------ 家人绑定 */

/**
 * 绑定家人（按 8 位编号）。成功后双方多一条共享会话。
 * @returns {Promise<{ok:boolean, binding?:object, message?:string}>}
 */
export function bind(number) {
  const token = readToken()
  if (!token) return Promise.resolve({ ok: false, message: '请先登录' })
  return bindFamily(token, number)
    .then((data) => {
      const binding = (data && data.binding) || null
      return Promise.all([refreshBindings(), refreshConversations()]).then(() => ({
        ok: true,
        binding
      }))
    })
    .catch((error) => ({ ok: false, message: friendly(error) }))
}

/** 解绑 */
export function unbind(number) {
  const token = readToken()
  if (!token) return Promise.resolve({ ok: false, message: '请先登录' })
  return unbindFamily(token, number)
    .then(() => Promise.all([refreshBindings(), refreshConversations()]).then(() => ({ ok: true })))
    .catch((error) => ({ ok: false, message: friendly(error) }))
}

/** 已绑定的编号集合（家人绑定页用来标记"已绑定"） */
export function boundNumbers() {
  return contacts.bindings.map((item) => item.peerNumber).filter(Boolean)
}

function friendly(error) {
  if (!error) return '出了点问题，再试一次'
  if (error.code === 'network') return '连不上服务器，让家里人看一下'
  return error.message || '出了点问题，再试一次'
}

export default contacts
