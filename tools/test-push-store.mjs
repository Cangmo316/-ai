#!/usr/bin/env node
/**
 * 比邻AI · 推送登记与端侧本地提醒自检（零依赖）
 *
 *   node tools/test-push-store.mjs
 *   BILIN_TEST_BASE_URL=http://127.0.0.1:8000 node tools/test-push-store.mjs
 *
 * 这一段最怕两件事：
 * 1. **能力缺失时把页面搞崩**：`uni.getPushClientId` / `uni.createPushMessage` 在 H5、小程序、
 *    标准 HBuilderX 基座上都不可用，必须静默降级（老人不该看到"推送初始化失败"）
 * 2. **本地通知重复**：每次开 App 都会重排当天提醒，不去重的话，
 *    上午开三次 App、下午的提醒就响三次
 */

import assert from 'node:assert/strict'
import { register } from 'node:module'
import { finish, group, sleep, testAsync } from './test-util.mjs'
import { installUniStub } from './uni-stub.mjs'
import { startMockServer } from './mock-server.mjs'

const stub = installUniStub({ cid: 'cid_test_abcdef123456' })
const { calls } = stub

register('./node-alias-hook.mjs', import.meta.url)

const externalBase = process.env.BILIN_TEST_BASE_URL || ''
const mock = externalBase ? null : await startMockServer({ port: 0, delayMs: 0 })
const baseURL = externalBase || 'http://127.0.0.1:' + mock.port
console.log('联调目标: ' + baseURL + (externalBase ? '（外部后端）' : '（内置 mock）'))

const config = await import('../uni-app/api/config.js')
config.setBaseURL(baseURL)
const pushApi = await import('../uni-app/api/push.js')
const store = await import('../uni-app/stores/push.js')
const { push } = store

group('① 推送标识登记')

await testAsync('拿到 cid 后登记到服务端', async () => {
  const cid = await store.registerPush('e_1')
  assert.equal(cid, 'cid_test_abcdef123456')
  assert.equal(push.state, 'ready', push.lastError)
  assert.equal(push.cidTail, '123456', '对外只留后 6 位')
  assert.ok(push.registeredAt)
  assert.equal(store.cachedCid(), cid, 'cid 要本地留一份，便于排查与重试')
})

await testAsync('服务端看得到这台设备，且不回显完整 cid', async () => {
  const status = await pushApi.fetchPushStatus({ elderId: 'e_1' })
  assert.ok(Array.isArray(status.clients))
  assert.ok(status.clients.length >= 1, '应至少登记了一台设备')
  const client = status.clients[0]
  assert.equal(client.cidTail, '123456')
  assert.ok(client.updatedAt)
})

await testAsync('重复登记是幂等的', async () => {
  const before = (await pushApi.fetchPushStatus({ elderId: 'e_1' })).clients.length
  await store.registerPush('e_1')
  await store.registerPush('e_1')
  const after = (await pushApi.fetchPushStatus({ elderId: 'e_1' })).clients.length
  assert.equal(after, before, '同一 cid 不该重复入库')
})

await testAsync('服务端不可达时：不抛错，记下错误，cid 仍然保留', async () => {
  config.setBaseURL('http://127.0.0.1:1')
  const cid = await store.registerPush('e_1')
  assert.equal(cid, 'cid_test_abcdef123456', '拿 cid 不依赖服务端')
  assert.equal(push.state, 'failed')
  assert.ok(push.lastError)
  assert.equal(store.cachedCid(), cid, 'cid 要留着，下次启动重试登记')
  config.setBaseURL(baseURL)
})

await testAsync('没有 uni-push 能力时（H5/小程序/标准基座）：静默跳过', async () => {
  stub.removeApi('getPushClientId')
  const cid = await store.registerPush('e_1')
  assert.equal(cid, '')
  assert.equal(push.state, 'unsupported')
  assert.equal(push.lastError, '', '能力缺失不是错误，不该给老人看报错')
  // 恢复，后续用例继续
  installUniStub({ cid: 'cid_test_abcdef123456' })
  const restored = await store.registerPush('e_1')
  assert.equal(restored, 'cid_test_abcdef123456')
})

await testAsync('pushFails（未开通 uni-push）：记失败但不抛错', async () => {
  installUniStub({ cid: '', pushFails: true })
  const cid = await store.registerPush('e_1')
  assert.equal(cid, '')
  assert.equal(push.state, 'failed')
  assert.ok(push.lastError.includes('getPushClientId') || push.lastError.includes('推送标识'))
  installUniStub({ cid: 'cid_test_abcdef123456' })
})

group('② 端侧本地提醒（第二条腿）')

const today = new Date()
const hhmm = (date) => String(date.getHours()).padStart(2, '0') + ':' + String(date.getMinutes()).padStart(2, '0')
const plusMinutes = (base, minutes) => new Date(base.getTime() + minutes * 60000)

await testAsync('只排未来 12 小时内的项，过去的不排', async () => {
  const now = new Date(today.getTime())
  const items = [
    { id: 'a', time: hhmm(plusMinutes(now, 30)), title: '该吃药了', type: '用药', done: false },
    { id: 'b', time: hhmm(plusMinutes(now, -30)), title: '早就过了', type: '活动', done: false },
    { id: 'c', time: hhmm(plusMinutes(now, 20 * 60)), title: '太远了', type: '问候', done: false },
    { id: 'd', time: hhmm(plusMinutes(now, 60)), title: '已经做完', type: '监测', done: true }
  ]
  calls.localNotify.length = 0
  const count = store.scheduleLocalNotifications(items, now)
  assert.equal(count, 1, '只应排 30 分钟后那条')
  assert.equal(calls.localNotify.length, 1)
  const scheduled = calls.localNotify[0]
  assert.equal(scheduled.content, '该吃药了')
  assert.ok(scheduled.title.includes(':'), '标题应带时间')
  assert.ok(scheduled.delay > 0 && scheduled.delay <= 12 * 3600)
  assert.equal(scheduled.payload.type, 'local-reminder')
})

await testAsync('同一天重复排程不会重复通知（开三次 App 不该响三次）', async () => {
  const now = new Date(today.getTime())
  const items = [{ id: 'repeat-1', time: hhmm(plusMinutes(now, 45)), title: '散步', type: '活动', done: false }]
  calls.localNotify.length = 0
  assert.equal(store.scheduleLocalNotifications(items, now), 1)
  assert.equal(store.scheduleLocalNotifications(items, now), 0, '第二次不该再排')
  assert.equal(store.scheduleLocalNotifications(items, now), 0)
  assert.equal(calls.localNotify.length, 1)
})

await testAsync('打卡后不再排（已完成的事不该再提醒）', async () => {
  const now = new Date(today.getTime())
  const items = [{ id: 'repeat-1', time: hhmm(plusMinutes(now, 45)), title: '散步', type: '活动', done: true }]
  calls.localNotify.length = 0
  assert.equal(store.scheduleLocalNotifications(items, now), 0)
})

await testAsync('跨天会重置排程记账（昨天的记录不该挡住今天）', async () => {
  const tomorrow = new Date(today.getTime() + 24 * 3600 * 1000)
  const items = [{ id: 'repeat-1', time: hhmm(plusMinutes(tomorrow, 45)), title: '散步', type: '活动', done: false }]
  calls.localNotify.length = 0
  assert.equal(store.scheduleLocalNotifications(items, tomorrow), 1, '新的一天应重新排')
})

await testAsync('没有本地通知能力时返回 0（H5/小程序）', async () => {
  const basic = installUniStub({ cid: 'cid_test_abcdef123456' })
  basic.removeApi('createPushMessage')
  const now = new Date(today.getTime())
  const items = [{ id: 'no-api', time: hhmm(plusMinutes(now, 20)), title: '喝水', type: '问候', done: false }]
  assert.equal(store.scheduleLocalNotifications(items, now), 0)
  assert.equal(store.localNotifySupported(), false)
})

group('③ 推送消息监听')

await testAsync('收到推送会刷新提醒；点通知栏则跳到日程页', async () => {
  const fresh = installUniStub({ cid: 'cid_test_abcdef123456' })
  let received = null
  store.listenPushMessages({
    onMessage(info) {
      received = info
    }
  })
  fresh.emitPush({ type: 'receive', data: { type: 'reminder', taskId: 'rt_x' } })
  assert.ok(received, '监听应被触发')
  assert.equal(received.type, 'receive')
  assert.equal(received.payload.taskId, 'rt_x')
  assert.equal(store.pushAction(received), 'refresh', '在线收到不该跳页')
})

await testAsync('点通知栏（click）才跳日程页', async () => {
  assert.equal(store.pushAction({ type: 'click', payload: {} }), 'open-plans')
  assert.equal(store.pushAction({ type: '', payload: {} }), 'refresh')
  assert.equal(store.pushAction(null), 'refresh')
  assert.equal(store.listenPushMessages(null), true, '不传 handler 也不该抛错')
})

/* ------------------------------------------------------------------ 收尾 */

if (mock) await mock.close()
finish()
