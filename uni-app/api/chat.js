/**
 * 比邻AI · 对话接口（流式 + 非流式 + 历史）
 *
 * 服务端契约见 api/README.md。这里做三件事：
 *   1) 把 SSE 文本帧解析成业务事件（token / sticker / card / done / error / meta）
 *   2) 容忍字段名差异（`{t}` 与 `{text}`、`[DONE]` 与 done 事件）
 *   3) 把传输层错误统一交给调用方，不在这一层弹 toast
 */

import { createSSEParser } from './sse-parse.js'
import { streamPost } from './transport.js'
import { request } from './request.js'
import { resolveURL, ENDPOINTS, TIMEOUT } from './config.js'

/** 业务事件类型（端侧只认这几种，多出来的服务端事件会被忽略） */
export const CHAT_EVENT = {
  meta: 'meta',
  token: 'token',
  sticker: 'sticker',
  card: 'card',
  /** 口型关键帧（3D 数字人唇形同步用，在 done 之前发一次） */
  lipsync: 'lipsync',
  done: 'done',
  error: 'error'
}

/**
 * 发起流式对话。
 *
 * @param {object} params
 * @param {string} params.conversationId
 * @param {string} [params.elderId]
 * @param {string} [params.personaId]
 * @param {string} params.text           老人说的话
 * @param {string} [params.clientMsgId]  端侧消息 id，用于服务端幂等
 * @param {(event:object)=>void} params.onEvent
 * @param {(err:object)=>void} [params.onError]
 * @param {()=>void} [params.onDone]     传输层正常结束（不代表业务 done）
 * @returns {{ abort: () => void }}
 */
export function chatStream(params) {
  const parser = createSSEParser()
  let businessDone = false

  function dispatch(rawEvent) {
    const event = normalize(rawEvent)
    if (!event) return
    if (event.type === CHAT_EVENT.done || event.type === CHAT_EVENT.error) businessDone = true
    params.onEvent(event)
  }

  const handle = streamPost({
    url: resolveURL(ENDPOINTS.chatStream),
    body: {
      conversationId: params.conversationId,
      elderId: params.elderId,
      personaId: params.personaId,
      text: params.text,
      clientMsgId: params.clientMsgId
    },
    firstByteMs: params.firstByteMs || TIMEOUT.firstByte,
    onChunk(text) {
      const events = parser.push(text)
      for (let i = 0; i < events.length; i += 1) dispatch(events[i])
    },
    onDone() {
      // 服务端没发 done 就把残帧冲出来；业务层据此兜底收尾
      const rest = parser.flush()
      for (let i = 0; i < rest.length; i += 1) dispatch(rest[i])
      if (params.onDone) params.onDone({ businessDone })
    },
    onError(err) {
      if (params.onError) params.onError(err)
    }
  })

  return {
    abort() {
      handle.abort()
    }
  }
}

/**
 * 非流式一次性回复。
 *
 * 用途：① 服务端还没实现 /v1/chat/stream 时的降级；② 提醒类消息预生成校验。
 * 为了和流式走同一条事件通路，这里会合成 meta → token → done 三个事件。
 */
export function chatSendOnce(params) {
  return request({
    url: resolveURL(ENDPOINTS.chatSend),
    method: 'POST',
    data: {
      conversationId: params.conversationId,
      elderId: params.elderId,
      personaId: params.personaId,
      text: params.text,
      clientMsgId: params.clientMsgId
    }
  }).then((body) => {
    const data = body || {}
    params.onEvent({
      type: CHAT_EVENT.meta,
      conversationId: data.conversationId || params.conversationId,
      assistantMsgId: data.assistantMsgId || '',
      persona: data.persona || null
    })
    if (data.sticker) params.onEvent({ type: CHAT_EVENT.sticker, token: data.sticker })
    if (data.text) params.onEvent({ type: CHAT_EVENT.token, text: data.text })
    if (data.card) params.onEvent({ type: CHAT_EVENT.card, card: data.card })
    params.onEvent({
      type: CHAT_EVENT.done,
      finishReason: data.finishReason || 'stop',
      assistantMsgId: data.assistantMsgId || ''
    })
    return data
  })
}

/**
 * 拉历史消息。
 * @returns {Promise<{conversationId:string, messages:Array}>}
 */
export function chatHistory(params) {
  const query = []
  query.push('conversationId=' + encodeURIComponent(params.conversationId))
  if (params.limit) query.push('limit=' + params.limit)
  return request({
    url: resolveURL(ENDPOINTS.chatHistory) + '?' + query.join('&'),
    method: 'GET'
  }).then((body) => ({
    conversationId: (body && body.conversationId) || params.conversationId,
    messages: (body && body.messages) || []
  }))
}

/* ------------------------------------------------------------------ 内部 */

/**
 * 把 SSE 帧转成业务事件。返回 null 表示这条帧不该往上抛（未知事件 / 坏 JSON）。
 */
function normalize(rawEvent) {
  const name = rawEvent.event
  const data = rawEvent.data

  if (name === 'message' && data === '[DONE]') return { type: CHAT_EVENT.done, finishReason: 'stop' }

  let payload
  try {
    payload = JSON.parse(data)
  } catch (e) {
    // 坏帧不打断整条流：丢掉这一帧继续收后面的
    return null
  }
  if (!payload || typeof payload !== 'object') return null

  switch (name) {
    case 'meta':
      return {
        type: CHAT_EVENT.meta,
        conversationId: payload.conversationId || '',
        assistantMsgId: payload.assistantMsgId || payload.messageId || '',
        persona: payload.persona || null
      }
    case 'token': {
      const text = payload.t !== undefined ? payload.t : payload.text
      if (typeof text !== 'string' || text === '') return null
      return { type: CHAT_EVENT.token, text }
    }
    case 'sticker':
      return { type: CHAT_EVENT.sticker, token: payload.token || payload.id || '' }
    case 'card':
      return { type: CHAT_EVENT.card, card: payload.card || payload }
    case 'lipsync':
      // 口型关键帧（3D 数字人用）。契约见 uni-app/api/README.md 的事件表。
      // 只做**形状校验**：cues 必须是数组、每项要有 b/e/v（少一个就整帧丢弃，
      // 免得半截数据把口型驱动带偏 —— 驱动层假定 cues 结构完整）。
      return {
        type: CHAT_EVENT.lipsync,
        assistantMsgId: payload.assistantMsgId || '',
        durationMs: Number(payload.durationMs) || 0,
        source: payload.source || 'estimated',
        version: Number(payload.version) || 1,
        cues: Array.isArray(payload.cues)
          ? payload.cues.filter((cue) => cue && typeof cue.b === 'number'
            && typeof cue.e === 'number' && Array.isArray(cue.v))
          : []
      }
    case 'done':
      return {
        type: CHAT_EVENT.done,
        finishReason: payload.finishReason || payload.reason || 'stop',
        assistantMsgId: payload.assistantMsgId || ''
      }
    case 'error':
      return {
        type: CHAT_EVENT.error,
        code: payload.code || 'server_error',
        message: payload.message || '出了点小问题',
        retryable: payload.retryable !== false
      }
    default:
      return null
  }
}
