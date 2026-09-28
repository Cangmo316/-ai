/**
 * 比邻AI · 跨端「流式 POST」传输层
 *
 * 逐端分工（依据官方文档实测能力，不要想当然）：
 *
 * | 端            | 手段                                            | 依据 |
 * |---------------|-------------------------------------------------|------|
 * | H5            | 原生 fetch + ReadableStream + TextDecoder        | uni.request 的 enableChunked 平台差异**只写了微信小程序**，H5 拿不到分块 |
 * | 微信小程序     | uni.request({enableChunked:true}) + onChunkReceived | 同上；回调给 ArrayBuffer，需增量 UTF-8 解码 |
 * | App(plus)     | plus.net.XMLHttpRequest，readyState 3            | HTML5+ 文档：readyState 3 = 「响应体开始接收但未完成」，responseText 返回**目前已接收的部分数据**，「响应较长时可能在状态 3 中触发多次」 |
 * | 其它（支付宝/百度/鸿蒙…） | uni.request 收完整体，一次性喂给解析器 | 拿不到分块就退化为「不打字，但一定收得到」——符合设计方案「降级可活」原则 |
 *
 * 本层只负责「字节 → 文本」，不做 SSE 解析（那是 sse-parse.js 的事），
 * 也不认识业务事件（那是 chat.js 的事）。
 */

import { createUtf8StreamDecoder } from './sse-parse.js'

let PLATFORM = 'unknown'
let CAN_STREAM = false

// #ifdef H5
PLATFORM = 'h5'
CAN_STREAM = true
// #endif

// #ifdef APP-PLUS
PLATFORM = 'app'
CAN_STREAM = true
// #endif

// #ifdef MP-WEIXIN
PLATFORM = 'mp-weixin'
CAN_STREAM = true
// #endif

export { PLATFORM, CAN_STREAM }

const DEFAULT_FIRST_BYTE_MS = 20000
/** 流中途的静默看门狗：超过这么久没有任何数据就判定链路已死，避免界面永远转圈 */
const DEFAULT_IDLE_MS = 30000

/**
 * 发起一次流式 POST。
 *
 * @param {object} options
 * @param {string} options.url
 * @param {object} options.body            请求体（对象，内部自行序列化）
 * @param {object} [options.header]        额外请求头
 * @param {number} [options.firstByteMs]   首字节超时
 * @param {number} [options.idleMs]        静默超时
 * @param {(text:string)=>void} options.onChunk  收到一段文本
 * @param {()=>void} [options.onDone]      正常结束
 * @param {(err:object)=>void} [options.onError] 出错（err.code 见下）
 * @returns {{ abort: () => void }}
 *
 * err.code 取值：network | http | timeout_first_byte | timeout_idle | aborted
 */
export function streamPost(options) {
  const firstByteMs = options.firstByteMs || DEFAULT_FIRST_BYTE_MS
  const idleMs = options.idleMs || DEFAULT_IDLE_MS

  let aborted = false
  let settled = false
  let idleTimer = null
  let firstTimer = null
  let inner = null

  function clearTimers() {
    if (idleTimer) { clearTimeout(idleTimer); idleTimer = null }
    if (firstTimer) { clearTimeout(firstTimer); firstTimer = null }
  }

  function armIdle() {
    if (idleTimer) clearTimeout(idleTimer)
    idleTimer = setTimeout(() => {
      fail({ code: 'timeout_idle', message: '等太久没有新消息了' })
    }, idleMs)
  }

  function emitChunk(text) {
    if (aborted || settled || !text) return
    if (firstTimer) { clearTimeout(firstTimer); firstTimer = null }
    armIdle()
    options.onChunk(text)
  }

  function finish() {
    if (aborted || settled) return
    settled = true
    clearTimers()
    if (options.onDone) options.onDone()
  }

  function fail(err) {
    if (settled) return
    settled = true
    clearTimers()
    const error = Object.assign({ retryable: true }, err)
    if (error.code === 'aborted') error.retryable = false
    if (options.onError) options.onError(error)
  }

  firstTimer = setTimeout(() => {
    if (inner && inner.abort) inner.abort()
    fail({ code: 'timeout_first_byte', message: '连不上服务器' })
  }, firstByteMs)

  const sink = { emitChunk, finish, fail }

  const sender = createSender(options, sink)
  inner = sender

  return {
    abort() {
      if (settled) return
      aborted = true
      clearTimers()
      settled = true
      if (sender && sender.abort) {
        try { sender.abort() } catch (e) { /* 中断失败无所谓，本地已经停了 */ }
      }
      if (options.onError) options.onError({ code: 'aborted', message: '已停止', retryable: false })
    }
  }
}

function bodyText(body) {
  return typeof body === 'string' ? body : JSON.stringify(body || {})
}

function headersOf(options) {
  return Object.assign({
    'Content-Type': 'application/json',
    Accept: 'text/event-stream'
  }, options.header || {})
}

/**
 * 平台分派。条件编译在构建时只保留当前端的分支；
 * 源码整体在 node 里跑时三个分支都在，但只有被调用的那个会执行。
 */
function createSender(options, sink) {
  // #ifdef H5
  if (typeof fetch === 'function') return fetchSender(options, sink)
  // #endif

  // #ifdef APP-PLUS
  if (typeof plus !== 'undefined' && plus.net && plus.net.XMLHttpRequest) {
    return plusSender(options, sink)
  }
  // #endif

  // #ifdef MP-WEIXIN
  return miniProgramSender(options, sink)
  // #endif

  /* eslint-disable no-unreachable */
  // 其它平台 / 上面分支都不可用时的兜底：收完整体一次性解析
  return bufferedSender(options, sink)
}

/* ------------------------------------------------------------------ H5 */

function fetchSender(options, sink) {
  const controller = typeof AbortController === 'function' ? new AbortController() : null
  const bytesDecoder = createUtf8StreamDecoder()
  const hasTextDecoder = typeof TextDecoder === 'function'
  const textDecoder = hasTextDecoder ? new TextDecoder('utf-8') : null
  let reader = null
  let stopped = false

  fetch(options.url, {
    method: 'POST',
    headers: headersOf(options),
    body: bodyText(options.body),
    signal: controller ? controller.signal : undefined
  }).then((res) => {
    if (stopped) return
    if (!res.ok) {
      res.text().then((text) => {
        sink.fail({ code: 'http', statusCode: res.status, message: httpMessage(res.status, text) })
      }).catch(() => {
        sink.fail({ code: 'http', statusCode: res.status, message: '服务器返回 ' + res.status })
      })
      return
    }
    // 老 WebView 没有流式 body：退化为一次性文本（不打字，但内容完整）
    if (!res.body || typeof res.body.getReader !== 'function') {
      res.text().then((text) => {
        if (stopped) return
        sink.emitChunk(text)
        sink.finish()
      }).catch((err) => sink.fail({ code: 'network', message: String(err && err.message || err) }))
      return
    }

    reader = res.body.getReader()
    pump()

    function pump() {
      reader.read().then(({ done, value }) => {
        if (stopped) return
        if (done) {
          if (hasTextDecoder) {
            const tail = textDecoder.decode()
            if (tail) sink.emitChunk(tail)
          } else {
            const tail = bytesDecoder.end()
            if (tail) sink.emitChunk(tail)
          }
          sink.finish()
          return
        }
        const text = hasTextDecoder
          ? textDecoder.decode(value, { stream: true })
          : bytesDecoder.push(value)
        if (text) sink.emitChunk(text)
        pump()
      }).catch((err) => {
        if (stopped) return
        sink.fail({ code: 'network', message: String(err && err.message || err) })
      })
    }
  }).catch((err) => {
    if (stopped) return
    if (err && err.name === 'AbortError') return
    sink.fail({ code: 'network', message: '连不上服务器' })
  })

  return {
    abort() {
      stopped = true
      if (reader) { try { reader.cancel() } catch (e) { /* 忽略 */ } }
      if (controller) { try { controller.abort() } catch (e) { /* 忽略 */ } }
    }
  }
}

/* ------------------------------------------------------- App（HTML5+） */

function plusSender(options, sink) {
  const xhr = new plus.net.XMLHttpRequest()
  let committed = 0
  let stopped = false

  xhr.open('POST', options.url)
  xhr.responseType = 'text'
  // 明确按 UTF-8 处理，避免服务端少写 charset 时中文变乱码
  if (typeof xhr.overrideMimeType === 'function') {
    try { xhr.overrideMimeType('text/plain; charset=utf-8') } catch (e) { /* 忽略 */ }
  }
  const header = headersOf(options)
  Object.keys(header).forEach((key) => {
    try { xhr.setRequestHeader(key, header[key]) } catch (e) { /* 个别头不受支持，忽略 */ }
  })

  function emitDelta() {
    const full = xhr.responseText || ''
    if (full.length <= committed) return
    const delta = full.slice(committed)
    // responseText 是原生层解码后的字符串：若这一片正好把某个汉字劈开，
    // 末尾会出现替换字符 U+FFFD。不是流末尾就先不提交，等下一次回调补全。
    if (xhr.readyState !== 4 && delta.charCodeAt(delta.length - 1) === 0xfffd) return
    committed = full.length
    sink.emitChunk(delta)
  }

  xhr.onreadystatechange = function () {
    if (stopped) return
    if (xhr.readyState === 3) {
      // readyState 3 时 status 已可用；非 200 说明是错误响应，等 readyState 4 统一报错
      if (xhr.status && xhr.status !== 200) return
      emitDelta()
    } else if (xhr.readyState === 4) {
      if (xhr.status !== 200) {
        sink.fail({
          code: 'http',
          statusCode: xhr.status,
          message: httpMessage(xhr.status, xhr.responseText || '')
        })
        return
      }
      emitDelta()
      sink.finish()
    }
  }
  xhr.onerror = function () { sink.fail({ code: 'network', message: '连不上服务器' }) }
  xhr.ontimeout = function () { sink.fail({ code: 'timeout_first_byte', message: '连不上服务器' }) }

  try {
    xhr.send(bodyText(options.body))
  } catch (e) {
    sink.fail({ code: 'network', message: '请求发送失败' })
  }

  return {
    abort() {
      stopped = true
      try { xhr.abort() } catch (e) { /* 忽略 */ }
    }
  }
}

/* --------------------------------------------------------- 微信小程序 */

function miniProgramSender(options, sink) {
  const decoder = createUtf8StreamDecoder()
  let chunked = false
  let stopped = false

  const task = uni.request({
    url: options.url,
    method: 'POST',
    data: options.body,
    header: headersOf(options),
    enableChunked: true,
    responseType: 'arraybuffer',
    success(res) {
      if (stopped) return
      if (res.statusCode !== 200) {
        sink.fail({
          code: 'http',
          statusCode: res.statusCode,
          message: httpMessage(res.statusCode, decodeWhole(res.data))
        })
        return
      }
      // 没走到分块回调（老基础库/平台不支持）→ 把完整体一次性解出来
      if (!chunked) {
        const whole = decodeWhole(res.data)
        if (whole) sink.emitChunk(whole)
      } else {
        const tail = decoder.end()
        if (tail) sink.emitChunk(tail)
      }
      sink.finish()
    },
    fail(err) {
      if (stopped) return
      sink.fail({ code: 'network', message: (err && err.errMsg) || '连不上服务器' })
    }
  })

  if (task && typeof task.onChunkReceived === 'function') {
    task.onChunkReceived((res) => {
      if (stopped) return
      chunked = true
      const text = decoder.push(res.data)
      if (text) sink.emitChunk(text)
    })
  }

  return {
    abort() {
      stopped = true
      if (task && typeof task.abort === 'function') {
        try { task.abort() } catch (e) { /* 忽略 */ }
      }
    }
  }
}

/* ------------------------------------------------------------ 通用兜底 */

function bufferedSender(options, sink) {
  let stopped = false
  const task = uni.request({
    url: options.url,
    method: 'POST',
    data: options.body,
    header: headersOf(options),
    success(res) {
      if (stopped) return
      if (res.statusCode !== 200) {
        sink.fail({
          code: 'http',
          statusCode: res.statusCode,
          message: httpMessage(res.statusCode, stringifyBody(res.data))
        })
        return
      }
      sink.emitChunk(stringifyBody(res.data))
      sink.finish()
    },
    fail(err) {
      if (stopped) return
      sink.fail({ code: 'network', message: (err && err.errMsg) || '连不上服务器' })
    }
  })

  return {
    abort() {
      stopped = true
      if (task && typeof task.abort === 'function') {
        try { task.abort() } catch (e) { /* 忽略 */ }
      }
    }
  }
}

/* ---------------------------------------------------------------- 工具 */

function decodeWhole(data) {
  if (!data) return ''
  if (typeof data === 'string') return data
  const decoder = createUtf8StreamDecoder()
  return decoder.push(data) + decoder.end()
}

function stringifyBody(data) {
  if (data === undefined || data === null) return ''
  if (typeof data === 'string') return data
  // uni.request 在 dataType=json 时已自动 JSON.parse，非流式错误体可能是对象
  try { return JSON.stringify(data) } catch (e) { return String(data) }
}

/** 尽量把服务端的 JSON 错误体转成人话 */
function httpMessage(statusCode, raw) {
  if (raw) {
    try {
      const parsed = JSON.parse(raw)
      const message = parsed && parsed.error && parsed.error.message
      if (message) return message
    } catch (e) {
      // 不是 JSON 就退回到状态码
    }
  }
  if (statusCode === 401 || statusCode === 403) return '登录已过期，让家里人重新登录一下'
  if (statusCode === 429) return '说得太快了，歇一会儿再说'
  if (statusCode >= 500) return '服务器开小差了'
  return '请求失败（' + statusCode + '）'
}
