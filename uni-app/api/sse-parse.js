/**
 * 比邻AI · SSE 帧解析与增量 UTF-8 解码（纯函数，零平台依赖）
 *
 * 为什么单独抽出来：
 *   1) 小程序端 uni.request 的 onChunkReceived 给的是 ArrayBuffer，且**不保证**
 *      按字符边界切分——一个汉字（3 字节）很可能被劈成两半，必须先做增量解码；
 *   2) 解析逻辑与网络传输无关，抽成纯函数后可以直接用 node 跑单测
 *      （见 tools/test-chat-api.mjs），不用起 HBuilderX。
 *
 * 本文件的任何改动都必须让 `node tools/test-chat-api.mjs` 保持全绿。
 */

/**
 * 创建一个增量 SSE 解析器。
 *
 * 用法：
 *   const parser = createSSEParser()
 *   parser.push('event: token\ndata: {"t":"妈"}\n\n')  // → [{ event:'token', data:'{"t":"妈"}' }]
 *
 * 遵循 SSE 规范（https://html.spec.whatwg.org/multipage/server-sent-events.html）：
 *   - 空行结束一个事件；同一事件的多个 data: 行用 \n 连接
 *   - `:` 开头是注释（心跳 `: ping` 走这条），必须忽略
 *   - 行分隔支持 \n 与 \r\n（裸 \r 极少见，不单独处理：\r 会随缓冲区等到 \n 一起结算，
 *     因此不会把 \r\n 误判成两个空行）
 *   - 字段值冒号后允许一个空格；`data:x` 与 `data: x` 等价
 */
export function createSSEParser() {
  let buffer = ''
  let eventName = ''
  let dataLines = []
  let lastEventId = ''
  let retry = null

  function takeEvent() {
    // 没有 data 行的事件（例如只有 event: foo 又跟一个空行）按规范丢弃
    if (dataLines.length === 0) {
      eventName = ''
      return null
    }
    const event = {
      event: eventName || 'message',
      data: dataLines.join('\n')
    }
    if (lastEventId) event.id = lastEventId
    if (retry !== null) event.retry = retry
    eventName = ''
    dataLines = []
    return event
  }

  function handleLine(rawLine) {
    let line = rawLine
    if (line.charCodeAt(line.length - 1) === 13) line = line.slice(0, -1) // 去掉 \r
    if (line === '') return takeEvent()
    if (line.charCodeAt(0) === 58) return null // `:` 注释 / 心跳
    const colon = line.indexOf(':')
    let field
    let value
    if (colon === -1) {
      field = line
      value = ''
    } else {
      field = line.slice(0, colon)
      value = line.slice(colon + 1)
      if (value.charCodeAt(0) === 32) value = value.slice(1) // 吃掉一个前导空格
    }
    if (field === 'event') eventName = value
    else if (field === 'data') dataLines.push(value)
    else if (field === 'id') lastEventId = value
    else if (field === 'retry') {
      const n = parseInt(value, 10)
      if (!isNaN(n)) retry = n
    }
    return null
  }

  return {
    /** 送入一段（已解码的）文本，返回本次结算出的完整事件数组 */
    push(chunk) {
      if (!chunk) return []
      buffer += chunk
      const events = []
      let nl = buffer.indexOf('\n')
      while (nl !== -1) {
        const line = buffer.slice(0, nl)
        buffer = buffer.slice(nl + 1)
        const event = handleLine(line)
        if (event) events.push(event)
        nl = buffer.indexOf('\n')
      }
      return events
    },

    /**
     * 流结束时调用：把残留在缓冲区的最后一行（服务端可能没补换行）结算掉，
     * 并吐出尚未遇到空行但已有 data 的事件——避免丢最后一条消息。
     */
    flush() {
      const events = []
      if (buffer) {
        const rest = buffer
        buffer = ''
        const event = handleLine(rest)
        if (event) events.push(event)
      }
      const tail = takeEvent()
      if (tail) events.push(tail)
      return events
    }
  }
}

/**
 * 创建增量 UTF-8 解码器（小程序端专用：小程序无 TextDecoder）。
 *
 * 解决的核心问题：Uint8Array 分片可能把一个多字节字符劈开。
 * 不完整的尾部字节留在 pending 里等下一片，绝不吐半个字符。
 * 非法序列按 WHATWG 编码标准替换为 U+FFFD。
 */
export function createUtf8StreamDecoder() {
  let pending = []

  return {
    /** 送入 Uint8Array / ArrayBuffer，返回本次能完整解码出的字符串 */
    push(input) {
      if (!input) return ''
      const bytes = input instanceof Uint8Array ? input : new Uint8Array(input)
      let buf
      if (pending.length) {
        buf = new Uint8Array(pending.length + bytes.length)
        buf.set(pending, 0)
        buf.set(bytes, pending.length)
      } else {
        buf = bytes
      }

      let out = ''
      let i = 0
      const len = buf.length
      while (i < len) {
        const b0 = buf[i]
        let need
        let cp
        let min
        if (b0 < 0x80) {
          out += String.fromCharCode(b0)
          i += 1
          continue
        } else if ((b0 & 0xe0) === 0xc0) {
          need = 1; cp = b0 & 0x1f; min = 0x80
        } else if ((b0 & 0xf0) === 0xe0) {
          need = 2; cp = b0 & 0x0f; min = 0x800
        } else if ((b0 & 0xf8) === 0xf0) {
          need = 3; cp = b0 & 0x07; min = 0x10000
        } else {
          out += '\uFFFD' // 0x80–0xBF 作为首字节、或 0xF8+ 的非法首字节
          i += 1
          continue
        }
        if (i + need >= len) break // 尾部不完整：留给下一片
        let ok = true
        for (let k = 1; k <= need; k += 1) {
          const bk = buf[i + k]
          if ((bk & 0xc0) !== 0x80) { ok = false; break }
          cp = (cp << 6) | (bk & 0x3f)
        }
        if (!ok || cp < min || cp > 0x10ffff || (cp >= 0xd800 && cp <= 0xdfff)) {
          out += '\uFFFD'
          i += 1
          continue
        }
        out += String.fromCodePoint(cp)
        i += need + 1
      }

      pending = Array.prototype.slice.call(buf, i)
      return out
    },

    /** 流结束：残留的半个字符只能算坏字符 */
    end() {
      const dirty = pending.length > 0
      pending = []
      return dirty ? '\uFFFD' : ''
    }
  }
}
