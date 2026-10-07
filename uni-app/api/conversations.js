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
 */
export function sendMessage(token, params = {}) {
  return request({
    url: resolveURL(ENDPOINTS.conversationMessages),
    method: 'POST',
    header: authHeader(token),
    data: {
      conversationId: params.conversationId || '',
      text: params.text || '',
      senderRole: params.senderRole || 'elder'
    }
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
