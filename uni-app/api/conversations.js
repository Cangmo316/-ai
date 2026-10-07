/**
 * 比邻AI · 会话接口（列表 / 历史 / 发送 / 已读 / 家人绑定）
 *
 * 契约见 server/app/api/conversations.py。要点：
 *  · 会话 id 由服务端约定（`ai:<账号id>` / `family:<小id>__<大id>`），端侧只透传
 *  · 未读数由服务端算（"不是自己发的 + 晚于自己已读边界"），端侧不自己数
 *  · 家人绑定后双方共享同一条会话，所以消息必须走服务端，不能用本地缓存当事实来源
 */

import { ENDPOINTS, resolveURL } from './config.js'
import { request } from './request.js'

function authHeader(token) {
  return token ? { Authorization: 'Bearer ' + token } : {}
}

/**
 * 我的会话列表（带未读数与最后一条消息）。
 * @returns {Promise<{conversations:Array, totalUnread:number}>}
 */
export function fetchConversations(token) {
  return request({
    url: resolveURL(ENDPOINTS.conversations),
    header: authHeader(token)
  })
}

/** 拉某会话的历史消息（按时间正序） */
export function fetchMessages(token, conversationId, limit) {
  const size = limit || 100
  return request({
    url: resolveURL(ENDPOINTS.conversationMessages)
      + '?conversationId=' + encodeURIComponent(conversationId || '')
      + '&limit=' + encodeURIComponent(String(size)),
    header: authHeader(token)
  })
}

/**
 * 发一条消息。
 * @param {object} params
 * @param {string} params.conversationId
 * @param {string} params.text
 * @param {string} [params.senderRole] 'elder'（本人，默认）/ 'agent'（智能体代发）
 * @param {string} [params.quoteId] 引用的那条消息 id（长按"引用"时带上）
 */
export function sendMessage(token, params = {}) {
  return request({
    url: resolveURL(ENDPOINTS.conversationMessages),
    method: 'POST',
    header: authHeader(token),
    data: {
      conversationId: params.conversationId || '',
      text: params.text || '',
      senderRole: params.senderRole || 'elder',
      quoteId: params.quoteId || ''
    }
  })
}

/**
 * 撤回一条自己发的消息（2 分钟窗口，服务端判定）。
 * 撤回是**打标记**不是删除：双方都会看到"已撤回"，但不显示正文。
 */
export function recallMessage(token, conversationId, messageId) {
  return request({
    url: resolveURL(ENDPOINTS.conversationMessages) + '/recall',
    method: 'POST',
    header: authHeader(token),
    data: { conversationId: conversationId || '', messageId: messageId || '' }
  })
}

/** 删除一条自己发的消息（物理删除，与"撤回"区分） */
export function deleteMessage(token, conversationId, messageId) {
  return request({
    url: resolveURL(ENDPOINTS.conversationMessages) + '/delete',
    method: 'POST',
    header: authHeader(token),
    data: { conversationId: conversationId || '', messageId: messageId || '' }
  })
}

/** 标记已读（进会话 1 秒后调用） */
export function markConversationRead(token, conversationId) {
  return request({
    url: resolveURL(ENDPOINTS.conversationRead),
    method: 'POST',
    header: authHeader(token),
    data: { conversationId: conversationId || '' }
  })
}

/** 我绑定的家人 */
export function fetchBindings(token) {
  return request({
    url: resolveURL(ENDPOINTS.conversationBindings),
    header: authHeader(token)
  })
}

/**
 * 绑定家人（按 8 位编号）。
 * 绑定成功会开通一条共享会话，双方都能看到并互发消息。
 */
export function bindFamily(token, number) {
  return request({
    url: resolveURL(ENDPOINTS.conversationBindings),
    method: 'POST',
    header: authHeader(token),
    data: { number: number || '' }
  })
}

/** 解绑家人 */
export function unbindFamily(token, number) {
  return request({
    url: resolveURL(ENDPOINTS.conversationBindings) + '?number=' + encodeURIComponent(number || ''),
    method: 'DELETE',
    header: authHeader(token)
  })
}

/**
 * 家人的查看管理数据（今日日程确认情况 + 未完成项 + 近期聊天活跃）。
 * 只有互相绑定的家人能取，否则服务端 403。
 * @param {string} number 家人的 8 位编号
 */
export function fetchFamilyOverview(token, number, date) {
  const query = ['number=' + encodeURIComponent(number || '')]
  if (date) query.push('date=' + encodeURIComponent(date))
  return request({
    url: resolveURL(ENDPOINTS.familyOverview) + '?' + query.join('&'),
    header: authHeader(token)
  })
}

/**
 * 让对方（不在线的家人）的智能体代回一句。
 *
 * **身份透明**：服务端以 `sender_role='agent'` 落库，端侧据此显示「AI 发送」角标。
 *
 * @param {object} params
 * @param {string} params.conversationId
 * @param {string} [params.schedule] 对方的日程摘要（端侧从 /v1/family/overview 取）
 * @param {string} [params.peerName] 对方名字（代回的署名）
 */
export function requestAutoReply(token, params = {}) {
  return request({
    url: resolveURL(ENDPOINTS.conversationMessages) + '/auto-reply',
    method: 'POST',
    header: authHeader(token),
    data: {
      conversationId: params.conversationId || '',
      schedule: params.schedule || '',
      peerName: params.peerName || ''
    }
  })
}
/* ══════════════════════════════════════════════════════════════════
   绑定要对方同意（2026-10）
   ══════════════════════════════════════════════════════════════════ */

/** 全部绑定关系，**含 pending 待同意 / rejected 已拒绝**（家人绑定页显示邀请用） */
export function fetchAllBindings(token) {
  return request({
    url: resolveURL(ENDPOINTS.conversationBindings) + '/all',
    method: 'GET',
    header: authHeader(token)
  })
}

/**
 * 同意 / 拒绝一条绑定邀请。
 * @param {string} number 发起邀请那一方的编号
 * @param {boolean} accept true=同意（此时才开通共享会话），false=拒绝
 */
export function respondBindFamily(token, number, accept) {
  return request({
    url: resolveURL(ENDPOINTS.conversationBindings) + '/respond',
    method: 'POST',
    header: authHeader(token),
    data: { number: number || '', accept: !!accept }
  })
}