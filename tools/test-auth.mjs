#!/usr/bin/env node
/**
 * 比邻AI · 端侧鉴权与错误码自检（零依赖）
 *
 *   node tools/test-auth.mjs
 *
 * 守三件事：
 * 1. **每个请求都带上 token**：非流式（request.js）与流式（transport.js）两条路都要带——
 *    只给其中一条加，就会表现成"聊天能流式但历史拉不到"这种莫名其妙的故障
 * 2. **服务端没开鉴权时不带多余的 Authorization 头**（便于排查，也避免误导后端日志）
 * 3. **401 的处理是人话**：老人看到的是"让家里人重新登录一下"，且**不给重试按钮**
 *    （retryable=false 来自服务端错误码表，端侧不再自己猜）
 */

import assert from 'node:assert/strict'
import { register } from 'node:module'
import { finish, group, testAsync } from './test-util.mjs'
import { installUniStub } from './uni-stub.mjs'
import { startMockServer } from './mock-server.mjs'

const { storage } = installUniStub()

register('./node-alias-hook.mjs', import.meta.url)

// ⚠️ token 必须是 ASCII：HTTP 头不能带非 ASCII 字符（fetch 会直接抛 TypeError）
// 踩过一次——中间用了中文，表现成"连不上服务器"，排查起来很费劲
const TOKEN = 'elder-token-9f3c2b71-abcdef'
const mock = await startMockServer({ port: 0, delayMs: 0, authToken: TOKEN })
const baseURL = 'http://127.0.0.1:' + mock.port
const config = await import('../uni-app/api/config.js')
const requestApi = await import('../uni-app/api/request.js')
const plansApi = await import('../uni-app/api/plans.js')
const chatApi = await import('../uni-app/api/chat.js')

config.setBaseURL(baseURL)

group('① token 的读写')

await testAsync('没设 token 时不带 Authorization 头', async () => {
  config.setApiToken('')
  assert.equal(config.getApiToken(), '')
  const headers = config.authHeaders({ Accept: 'application/json' })
  assert.equal(headers.Authorization, undefined)
})

await testAsync('设了 token 之后所有请求都带 Bearer', async () => {
  config.setApiToken(TOKEN)
  assert.equal(config.getApiToken(), TOKEN)
  const headers = config.authHeaders({})
  assert.equal(headers.Authorization, 'Bearer ' + TOKEN)
})

await testAsync('token 会落到本地缓存（下次启动仍然有效）', async () => {
  assert.equal(storage.get('bl_api_token'), TOKEN)
})

group('② 非流式请求（request.js）')

await testAsync('带 token 的 GET 能通过鉴权', async () => {
  const today = await plansApi.fetchTodayPlan({ elderId: 'e_1' })
  assert.ok(today.total >= 0)
  assert.equal(mock.state.lastAuth, 'Bearer ' + TOKEN, '服务端收到的就是 Bearer token')
})

await testAsync('带 token 的 POST 也能通过', async () => {
  const item = (await plansApi.fetchTodayPlan({ elderId: 'e_1' })).items[0]
  const result = await plansApi.submitCheckin({ planItemId: item.id, elderId: 'e_1' })
  assert.equal(result.done, true)
  await plansApi.submitCheckin({ planItemId: item.id, elderId: 'e_1', done: false })
})

await testAsync('没带 token 时：401 + 人话 + 不给重试', async () => {
  config.setApiToken('')
  let error = null
  try {
    await plansApi.fetchTodayPlan({ elderId: 'e_1' })
  } catch (e) {
    error = e
  }
  assert.ok(error, '应该抛错')
  assert.equal(error.code, 'auth_required', '错误码来自服务端错误码表')
  assert.equal(error.statusCode, 401)
  assert.equal(error.retryable, false, '鉴权失败不该给老人重试按钮')
  assert.ok(error.message.length > 0)
  assert.ok(!/[A-Za-z]{6,}/.test(error.message), '提示里不该出现英文异常名：' + error.message)
})

await testAsync('token 不对时：unauthorized（与"没带"区分开）', async () => {
  config.setApiToken('wrong-token')
  let error = null
  try {
    await plansApi.fetchTodayPlan({ elderId: 'e_1' })
  } catch (e) {
    error = e
  }
  assert.equal(error.code, 'unauthorized')
  assert.equal(error.retryable, false)
  config.setApiToken(TOKEN)
})

group('③ 流式请求（transport.js）')

await testAsync('SSE 流式请求同样带 token，且能正常收流', async () => {
  config.setApiToken(TOKEN)
  const events = []
  await new Promise((resolve, reject) => {
    chatApi.chatStream({
      conversationId: 'c_auth',
      text: '妈 在吗',
      clientMsgId: 'm_auth_1',
      onEvent: (event) => events.push(event),
      onError: (err) => reject(new Error(err.message || 'stream error')),
      onDone: () => resolve()
    })
  })
  assert.ok(events.some((event) => event.type === 'token'), '应该收到正文')
  assert.equal(mock.state.lastAuth, 'Bearer ' + TOKEN, '流式请求也要带 token')
})

await testAsync('流式请求没带 token 时给出 401 而不是静默无声', async () => {
  config.setApiToken('')
  let error = null
  await new Promise((resolve) => {
    chatApi.chatStream({
      conversationId: 'c_auth2',
      text: '妈 在吗',
      onEvent: () => {},
      onError: (err) => { error = err; resolve() },
      onDone: () => resolve()
    })
  })
  assert.ok(error, '应该回调 onError')
  assert.equal(error.statusCode, 401)
  assert.ok(error.message.length > 0)
  config.setApiToken(TOKEN)
})

group('④ 错误码表可查（公开接口）')

await testAsync('端侧能拿到错误码表，且不用带 token', async () => {
  config.setApiToken('')
  const body = await requestApi.request({ url: baseURL + '/v1/errors' })
  assert.ok(Array.isArray(body.codes))
  const codes = body.codes.map((row) => row.code)
  assert.ok(codes.includes('auth_required'))
  assert.ok(codes.includes('plan_state'))
  assert.ok(codes.includes('llm_timeout'))
  for (const row of body.codes) {
    assert.equal(typeof row.retryable, 'boolean')
    assert.ok(row.message)
  }
  config.setApiToken(TOKEN)
})

await mock.close()
finish()
