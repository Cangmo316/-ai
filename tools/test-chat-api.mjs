#!/usr/bin/env node
/**
 * 比邻AI · 端侧对话链路自检（零依赖，直接 node 跑）
 *
 *   node tools/test-chat-api.mjs
 *
 * 覆盖三层：
 *   ① SSE 解析器（uni-app/api/sse-parse.js）——帧边界、心跳、CRLF、多行 data
 *   ② 增量 UTF-8 解码器 —— 汉字/emoji 被从中间劈开时的正确性（小程序端真实场景）
 *   ③ 端到端 —— 起 mock 服务，按契约收流式事件，并检查话术规范（句末不加句号）
 *
 * 为什么值得单独写：这三层里任何一层错，表现都是「老人端上出现半截乱码或空气泡」，
 * 而在 HBuilderX 里肉眼很难定位到是解析、解码还是服务端的问题。
 */

import assert from 'node:assert/strict'
import { createSSEParser, createUtf8StreamDecoder } from '../uni-app/api/sse-parse.js'
import { startMockServer } from './mock-server.mjs'
import { finish, group, test, testAsync } from './test-util.mjs'

/* ---------------------------------------------------- ① SSE 解析器 */

group('① SSE 解析器')

test('单帧完整输入', () => {
  const parser = createSSEParser()
  const events = parser.push('event: token\ndata: {"t":"妈"}\n\n')
  assert.equal(events.length, 1)
  assert.equal(events[0].event, 'token')
  assert.equal(events[0].data, '{"t":"妈"}')
})

test('一帧被切成三段也能拼回来', () => {
  const parser = createSSEParser()
  assert.deepEqual(parser.push('event: tok'), [])
  assert.deepEqual(parser.push('en\ndata: {"t":"'), [])
  const events = parser.push('好"}\n\n')
  assert.equal(events.length, 1)
  assert.equal(events[0].data, '{"t":"好"}')
})

test('连续多帧一次送入', () => {
  const parser = createSSEParser()
  const events = parser.push('event: token\ndata: {"t":"a"}\n\nevent: token\ndata: {"t":"b"}\n\n')
  assert.equal(events.length, 2)
  assert.equal(events[1].data, '{"t":"b"}')
})

test('CRLF 行尾等价于 LF', () => {
  const parser = createSSEParser()
  const events = parser.push('event: done\r\ndata: {"finishReason":"stop"}\r\n\r\n')
  assert.equal(events.length, 1)
  assert.equal(events[0].event, 'done')
  assert.equal(events[0].data, '{"finishReason":"stop"}')
})

test('心跳注释行被忽略', () => {
  const parser = createSSEParser()
  assert.deepEqual(parser.push(': ping\n\n'), [])
  const events = parser.push(': ping\nevent: token\ndata: {"t":"x"}\n\n')
  assert.equal(events.length, 1)
})

test('同一事件的多行 data 用换行连接', () => {
  const parser = createSSEParser()
  const events = parser.push('event: note\ndata: 第一行\ndata: 第二行\n\n')
  assert.equal(events[0].data, '第一行\n第二行')
})

test('id 与 retry 字段被解析', () => {
  const parser = createSSEParser()
  const events = parser.push('id: 42\nretry: 3000\nevent: token\ndata: {}\n\n')
  assert.equal(events[0].id, '42')
  assert.equal(events[0].retry, 3000)
})

test('无字段名的裸行不会崩', () => {
  const parser = createSSEParser()
  const events = parser.push('hello\nevent: token\ndata: {}\n\n')
  assert.equal(events.length, 1)
  assert.equal(events[0].event, 'token')
})

test('data 冒号后有无空格都行', () => {
  const parser = createSSEParser()
  const events = parser.push('event: token\ndata:{"t":"a"}\n\n')
  assert.equal(events[0].data, '{"t":"a"}')
})

test('flush 结算没有尾换行的最后一帧', () => {
  const parser = createSSEParser()
  assert.deepEqual(parser.push('event: done\ndata: {"a":1}'), [])
  const events = parser.flush()
  assert.equal(events.length, 1)
  assert.equal(events[0].event, 'done')
})

test('只有 event 没有 data 的事件被丢弃', () => {
  const parser = createSSEParser()
  assert.deepEqual(parser.push('event: token\n\n'), [])
})

/* ------------------------------------------- ② 增量 UTF-8 解码器 */

group('② 增量 UTF-8 解码器（小程序分片场景）')

function bytesOf(text) {
  return new TextEncoder().encode(text)
}

test('汉字被从中间劈开也能还原', () => {
  const bytes = bytesOf('妈妈')
  const decoder = createUtf8StreamDecoder()
  const out = decoder.push(bytes.slice(0, 1)) +
    decoder.push(bytes.slice(1, 4)) +
    decoder.push(bytes.slice(4)) +
    decoder.end()
  assert.equal(out, '妈妈')
})

test('emoji（4 字节）跨片还原', () => {
  const bytes = bytesOf('好😊')
  const decoder = createUtf8StreamDecoder()
  let out = ''
  for (let i = 0; i < bytes.length; i += 1) out += decoder.push(bytes.slice(i, i + 1))
  out += decoder.end()
  assert.equal(out, '好😊')
})

test('逐字节喂入整段中文不丢字', () => {
  const source = '妈 药吃了没\n吃完喝口热水 别空腹'
  const bytes = bytesOf(source)
  const decoder = createUtf8StreamDecoder()
  let out = ''
  for (let i = 0; i < bytes.length; i += 1) out += decoder.push(bytes.slice(i, i + 1))
  out += decoder.end()
  assert.equal(out, source)
})

test('非法字节替换为 U+FFFD 且不吞掉后续字符', () => {
  const decoder = createUtf8StreamDecoder()
  const out = decoder.push(new Uint8Array([0x41, 0xff, 0x42])) + decoder.end()
  assert.equal(out, 'A\uFFFDB')
})

test('截断在字符中间就结束时补替换字符', () => {
  const decoder = createUtf8StreamDecoder()
  decoder.push(bytesOf('妈').slice(0, 2))
  assert.equal(decoder.end(), '\uFFFD')
})

/* -------------------------------------------------- ③ 端到端 */

group('③ 端到端（mock 服务 + 契约）')

/** 按字节分片喂给解码器与解析器，模拟小程序端 onChunkReceived 的最坏情况 */
function collect(parser, decoder, chunk) {
  const text = decoder.push(chunk)
  return text ? parser.push(text) : []
}

async function main() {
  const mock = await startMockServer({ port: 0, delayMs: 0 })
  const base = 'http://127.0.0.1:' + mock.port

  async function streamOnce(payload) {
    const res = await fetch(base + '/v1/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(payload)
    })
    assert.equal(res.status, 200, '流式接口应返回 200')
    assert.match(res.headers.get('content-type') || '', /text\/event-stream/)

    const parser = createSSEParser()
    const decoder = createUtf8StreamDecoder()
    const events = []
    const reader = res.body.getReader()
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      events.push.apply(events, collect(parser, decoder, value))
    }
    const tail = decoder.end()
    if (tail) events.push.apply(events, parser.push(tail))
    events.push.apply(events, parser.flush())
    return events
  }

  function textOf(events) {
    return events.filter((e) => e.event === 'token').map((e) => JSON.parse(e.data).t).join('')
  }

  await testAsync('流式：meta 打头、done 收尾', async () => {
    const events = await streamOnce({ conversationId: 'c_test', text: '妈 药吃了没' })
    assert.ok(events.length >= 3, '至少要有 meta/token/done')
    assert.equal(events[0].event, 'meta')
    assert.equal(events[events.length - 1].event, 'done')
    const payload = JSON.parse(events[0].data)
    assert.equal(payload.conversationId, 'c_test')
    assert.ok(payload.assistantMsgId, 'meta 必须带 assistantMsgId')
    assert.equal(payload.persona.name, '儿子 小明')
  })

  await testAsync('流式：token 拼回完整回复，且中文无乱码', async () => {
    const events = await streamOnce({ conversationId: 'c_test', text: '妈 药吃了没' })
    assert.equal(textOf(events), '妈 药吃了没\n吃完喝口热水 别空腹')
  })

  await testAsync('流式：药相关回复带 sticker 与 plan_item 卡片', async () => {
    const events = await streamOnce({ conversationId: 'c_test', text: '药' })
    const sticker = events.find((e) => e.event === 'sticker')
    const card = events.find((e) => e.event === 'card')
    assert.ok(sticker, '应有 sticker 事件')
    assert.equal(JSON.parse(sticker.data).token, 'pill')
    assert.ok(card, '应有 card 事件')
    const parsed = JSON.parse(card.data).card
    assert.equal(parsed.kind, 'plan_item')
    assert.equal(parsed.plan.time, '08:00')
  })

  await testAsync('流式：服务端 error 事件可被识别', async () => {
    const events = await streamOnce({ conversationId: 'c_test', text: '__error' })
    assert.equal(events[0].event, 'meta')
    assert.equal(events[events.length - 1].event, 'error')
    const err = JSON.parse(events[events.length - 1].data)
    assert.equal(err.code, 'server_error')
    assert.equal(err.retryable, true)
  })

  await testAsync('流式：逐字节喂入也不丢字（最坏分片）', async () => {
    const res = await fetch(base + '/v1/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conversationId: 'c_byte', text: '我想你们了' })
    })
    const buffer = new Uint8Array(await res.arrayBuffer())
    const parser = createSSEParser()
    const decoder = createUtf8StreamDecoder()
    const events = []
    for (let i = 0; i < buffer.length; i += 1) {
      events.push.apply(events, collect(parser, decoder, buffer.slice(i, i + 1)))
    }
    events.push.apply(events, parser.flush())
    assert.equal(textOf(events), '我也想你们\n晚上我打视频回来')
  })

  await testAsync('话术规范：所有回复都不以句号结尾', async () => {
    const words = ['药', '睡觉', '想你们', '吃饭', '天气', '散步', '喝水', '肚子疼', '随便说点啥']
    for (const word of words) {
      const events = await streamOnce({ conversationId: 'c_style', text: word })
      const text = textOf(events)
      assert.ok(text.length > 0, '「' + word + '」应有回复')
      assert.ok(!/[。.]$/.test(text), '「' + word + '」的回复末尾不该有句号：' + text)
    }
  })

  await testAsync('非流式降级接口 /v1/chat/send 可用', async () => {
    const res = await fetch(base + '/v1/chat/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conversationId: 'c_json', text: '今天天气怎么样' })
    })
    assert.equal(res.status, 200)
    const body = await res.json()
    assert.equal(body.finishReason, 'stop')
    assert.equal(body.text, '今天降温了\n出门加件外套')
    assert.equal(body.sticker, 'sun')
  })

  await testAsync('历史接口返回消息数组', async () => {
    const res = await fetch(base + '/v1/chat/history?conversationId=c_test&limit=50')
    assert.equal(res.status, 200)
    const body = await res.json()
    assert.equal(body.conversationId, 'c_test')
    assert.ok(Array.isArray(body.messages))
    assert.ok(body.messages.length > 0, '流过一轮之后应至少有种子消息')
    assert.ok(body.messages.every((m) => m.id && m.role && m.type))
  })

  await testAsync('未知路由返回结构化错误', async () => {
    const res = await fetch(base + '/v1/nope')
    assert.equal(res.status, 404)
    const body = await res.json()
    assert.equal(body.error.code, 'not_found')
  })

  await mock.close()
  finish()
}

main().catch((error) => {
  console.error('测试运行失败：' + (error && error.stack ? error.stack : error))
  process.exitCode = 1
})
