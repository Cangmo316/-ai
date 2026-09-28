#!/usr/bin/env node
/**
 * 比邻AI · 端侧对话状态机自检（零依赖）
 *
 *   node tools/test-chat-store.mjs
 *
 * 为什么需要它：stores/chat.js 里的「乐观发送 → 流式回填 → 停止 / 失败 / 重发 / 缓存恢复」
 * 是最容易出错、又最难在 HBuilderX 里手点覆盖的部分。这里用一个内存版 `uni` +
 * fetch 传输，把真实链路整个跑一遍（mock 服务当靶子）。
 *
 * 依赖 tools/node-alias-hook.mjs 把 `@/` 与 `vue` 补上；不安装任何 npm 包。
 */

import assert from 'node:assert/strict'
import { register } from 'node:module'
import { finish, group, sleep, test, testAsync, waitUntil } from './test-util.mjs'
import { installUniStub } from './uni-stub.mjs'
import { startMockServer } from './mock-server.mjs'

/* ------------------------------------------------ 内存版 uni 运行时 */

const storage = installUniStub()

// 必须在 import 业务模块之前注册：业务代码用了 `@/` 别名与 `vue`
register('./node-alias-hook.mjs', import.meta.url)

// 默认打自带的 mock；给 BILIN_TEST_BASE_URL 时改打真实后端
// （用来验证「端 → 服务 → 模型 → 端」这条跨语言链路，见 server/README.md）
const externalBase = process.env.BILIN_TEST_BASE_URL || ''
const mock = externalBase ? null : await startMockServer({ port: 0, delayMs: 0 })
const baseURL = externalBase || 'http://127.0.0.1:' + mock.port
/**
 * 是否按「内置假后端」的严格预期断言（固定话术、固定表情、固定卡片、__slow 触发词）。
 * 打真实模型时这些都不成立——真模型的回复不可预期，所以改成断言**不变量**
 * （非空、无句号、无网址、表情 token 合法），并把依赖触发词的用例标为跳过。
 */
const STRICT = !externalBase

console.log('联调目标: ' + baseURL + (externalBase ? '（外部后端，按不变量断言）' : '（内置 mock，严格断言）'))

const config = await import('../uni-app/api/config.js')
config.setBaseURL(baseURL)

const store = await import('../uni-app/stores/chat.js')
const { chat } = store

/** 上一次发送之后新增的消息 */
function turnSince(index) {
  return chat.messages.slice(index)
}

const agentTextsOf = (list) => list.filter((m) => m.role === 'agent' && m.type === 'text')

/* ------------------------------------------------------------------ 用例 */

group('① 初始化与降级')

await testAsync('首启：先上屏本地种子，随后被服务端历史替换', async () => {
  store.initChat()
  assert.ok(chat.messages.length >= 5, '初始化应立刻有种子消息，不能白屏')
  assert.equal(chat.persona.name, '儿子 小明')
  await waitUntil(
    () => chat.messages.some((m) => /上班去了/.test(m.text || '')),
    4000,
    '服务端历史回填'
  )
  assert.ok(chat.messages.length >= 1, '历史替换后不能为空')
})

await testAsync('历史接口不可用时保持种子内容，不抛错', async () => {
  config.setBaseURL('http://127.0.0.1:1') // 历史请求必然失败
  store.resetChat()
  store.initChat()
  assert.ok(chat.messages.length >= 5, '拿不到历史也要有种子内容（不白屏）')
  await sleep(250) // 等那次失败的请求回来
  assert.ok(chat.messages.length >= 5, '失败后不能被清空')
  assert.equal(chat.streaming, false)
  assert.equal(chat.lastError, '', '拉历史失败不该打扰老人')

  config.setBaseURL(baseURL)
  store.resetChat()
  store.initChat()
  await waitUntil(
    () => chat.messages.some((m) => /上班去了/.test(m.text || '')),
    4000,
    '恢复后重新拉到历史'
  )
})

group('② 流式发送')

/** 本轮发送的起始下标（后续断言只看这一轮，别把历史问候语算进来） */
let turnStart = 0

await testAsync('乐观发送：老人那句话立刻上屏，随即进入流式', async () => {
  turnStart = chat.messages.length
  const accepted = store.send('妈 药吃了没')
  assert.equal(accepted, true)
  assert.equal(chat.streaming, true)
  const fresh = turnSince(turnStart)
  assert.equal(fresh.length, 1, '发送瞬间应只多出「我」的那条')
  assert.equal(fresh[0].role, 'elder')
  assert.equal(fresh[0].text, '妈 药吃了没')
})

await testAsync('流式回填：文本拼回完整回复，表情与卡片各成一条消息', async () => {
  await waitUntil(() => !chat.streaming, 20000, '流式结束')
  const fresh = turnSince(turnStart)
  const texts = agentTextsOf(fresh)
  const body = texts.map((m) => m.text).join('')

  if (STRICT) {
    assert.equal(body, '妈 药吃了没\n吃完喝口热水 别空腹')
  } else {
    // 真模型的回复不可预期，只守产品不变量
    assert.ok(body.length > 0, '真模型应给出非空回复')
    assert.ok(!body.includes('。'), '回复里不该有全角句号（风格后处理失效？）')
    assert.ok(!/https?:\/\/|www\./i.test(body), '回复里不该有网址')
    assert.ok(body === body.trim(), '正文首尾不该有空白')
  }
  assert.ok(texts.every((m) => m.status === 'sent'), '收完应标记为 sent')

  const stickers = fresh.filter((m) => m.type === 'sticker')
  if (STRICT) {
    assert.equal(stickers.length, 1, '表情应独立成一条消息（无气泡大图）')
    assert.equal(stickers[0].sticker, 'pill')
  } else if (stickers.length) {
    // 真模型发不发表情不固定；发了就必须是合法 token（受控白名单）
    stickers.forEach((m) => assert.match(m.sticker, /^[a-z_]+$/, '表情 token 应形如 love/pill'))
  }
  stickers.forEach((m) => assert.equal(m.role, 'agent'))

  const cards = fresh.filter((m) => m.type === 'card')
  if (STRICT) {
    assert.equal(cards.length, 1, '计划卡应独立成一条消息')
    assert.equal(cards[0].card.kind, 'plan_item')
    assert.equal(cards[0].card.plan.time, '08:00')
  } else {
    assert.equal(cards.length, 0, 'P0 的真模型服务端还不该发计划卡（那是 P1 计划引擎的活）')
  }
})

await testAsync('持久化：本轮消息写入本地缓存，且不留中间态', async () => {
  const raw = storage.get('bl_chat_v1_c_son')
  assert.ok(raw, '应有本地缓存')
  const list = JSON.parse(raw)
  if (STRICT) assert.ok(list.some((m) => m.type === 'sticker' && m.sticker === 'pill'))
  if (STRICT) assert.ok(list.some((m) => m.type === 'card'))
  assert.ok(list.every((m) => m.status !== 'streaming'), '缓存里不能留 streaming')
})

await testAsync('流式期间重复点击不会并发第二轮', async () => {
  // __slow 是 mock/假模型的触发词，真模型不认；真模型下随便发一句也行
  store.send(STRICT ? '__slow 早点睡' : '妈 我一会儿再跟你说')
  await waitUntil(() => chat.streaming, 4000, '进入流式')
  assert.equal(store.send('再发一条'), false, '流式中应拒绝新的一轮')
  assert.equal(store.stop() === undefined, true)
  await waitUntil(() => !chat.streaming, 4000, '停止后收尾')
})

group('③ 一键停止')

/** 跳过只在假后端下成立的用例（真模型不认触发词、回复长度不可预期） */
function skipAsync(name, reason) {
  console.log('  - ' + name + '（跳过：' + reason + '）')
}

if (STRICT) {
  await testAsync('停止：保留已收到的部分，状态标 stopped', async () => {
    const from = chat.messages.length
    store.send('__slow 早点睡')
    await waitUntil(
      () => agentTextsOf(turnSince(from)).some((m) => m.text.length >= 2),
      8000,
      '收到部分文字'
    )
    store.stop()
    await waitUntil(() => !chat.streaming, 3000, '停止生效')

    const fresh = turnSince(from)
    const texts = agentTextsOf(fresh)
    assert.equal(texts.length, 1)
    assert.equal(texts[0].status, 'stopped')
    assert.ok(texts[0].text.length > 0 && texts[0].text.length < 12, '应只保留部分文字：' + texts[0].text)
    assert.ok(!fresh.some((m) => m.type === 'system'), '已有部分内容时不该再插「已停止」提示')
  })
} else {
  skipAsync('停止：保留已收到的部分，状态标 stopped', '需要 __slow 触发词，真模型不认')

  await testAsync('停止：真模型下随时能停，且不产生错误提示', async () => {
    const from = chat.messages.length
    store.send('妈 你再说会儿话')
    await waitUntil(() => chat.streaming, 8000, '进入流式')
    store.stop()
    await waitUntil(() => !chat.streaming, 8000, '停止生效')
    const fresh = turnSince(from)
    assert.ok(
      !fresh.some((m) => m.type === 'system' && /连不上|开小差/.test(m.text)),
      '老人主动停止不该被当成错误'
    )
  })
}

group('④ 失败与重发')

if (STRICT) {
  await testAsync('服务端 error：删掉空气泡，给出可重发提示', async () => {
    const from = chat.messages.length
    store.send('__error 药')
    await waitUntil(() => !chat.streaming, 5000, '错误收尾')

    const fresh = turnSince(from)
    assert.ok(
      fresh.some((m) => m.type === 'system' && /服务器开小差/.test(m.text)),
      '应给出系统提示'
    )
    assert.equal(agentTextsOf(fresh).length, 0, '一个字都没收到就不该留空气泡')
    assert.equal(chat.canRetry, true)
    assert.equal(chat.lastError.length > 0, true)
  })

  await testAsync('重发：先清掉失败痕迹再重跑一轮', async () => {
    const from = chat.messages.length
    assert.equal(store.retry(), true)
    await waitUntil(() => !chat.streaming, 8000, '重发结束')
    const systems = chat.messages.filter((m) => m.type === 'system' && /服务器开小差/.test(m.text))
    assert.equal(systems.length, 1, '重发前应清掉上一条失败提示，不能越堆越多')
    assert.ok(chat.messages.length >= from, '消息列表不能被清空')
  })
} else {
  skipAsync('服务端 error：删掉空气泡，给出可重发提示', '需要 __error 触发词，真模型不认')
  skipAsync('重发：先清掉失败痕迹再重跑一轮', '依赖上一条失败用例')
}

await testAsync('连不上服务器：明确提示 + 可重发 + 不清空历史', async () => {
  config.setBaseURL('http://127.0.0.1:1') // 必然拒绝连接
  const keep = chat.messages.length
  const from = chat.messages.length
  store.send('妈 在吗')
  await waitUntil(() => !chat.streaming, 10000, '失败收尾')

  const fresh = turnSince(from)
  assert.ok(
    fresh.some((m) => m.type === 'system' && /连不上服务器/.test(m.text)),
    '应提示连不上服务器'
  )
  assert.equal(chat.canRetry, true)
  assert.ok(chat.messages.length > keep, '已有消息不能被清掉')
  config.setBaseURL(baseURL)
})

group('⑤ 缓存与列表页取用')

await testAsync('缓存恢复：再次进入不再依赖服务端', async () => {
  const cached = JSON.parse(storage.get('bl_chat_v1_c_son'))
  chat.ready = false
  chat.messages = []
  store.initChat()
  assert.equal(chat.messages.length, cached.length, '应从缓存恢复同样条数')
  if (STRICT) assert.ok(chat.messages.some((m) => m.type === 'card'), '卡片也要能从缓存还原')
})

await testAsync('列表页预览取最后一条可读内容', async () => {
  const preview = store.lastPreview()
  assert.equal(typeof preview, 'string')
  assert.ok(preview.length > 0)
  assert.match(store.lastTime(), /^\d{2}:\d{2}$/)
})

await testAsync('resetChat 清空内存与本地缓存', async () => {
  store.resetChat()
  assert.equal(chat.messages.length, 0)
  assert.equal(storage.has('bl_chat_v1_c_son'), false)
  assert.equal(chat.ready, false)
})

/* ------------------------------------------------------------------ 收尾 */

if (mock) await mock.close()
finish()
