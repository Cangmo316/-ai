#!/usr/bin/env node
/**
 * 比邻AI · 老人端「到点提醒」自检（零依赖）
 *
 *   node tools/test-reminder-store.mjs
 *   BILIN_TEST_BASE_URL=http://127.0.0.1:8000 node tools/test-reminder-store.mjs
 *
 * ⚠️ 打真实后端时请用 `SCHEDULER_ENABLED=false` 起服务：本脚本靠"手动把时间推到 12:00"来驱动，
 * 后台调度循环如果也在跑，会按真实时间抢先投递/判过期，两边就打架了。
 *
 * 守三件事：
 * 1. 到点的提醒能被端侧看到（顶部提醒条 + 震动），强提醒震得更重
 * 2. **同一条提醒只震一次**：轮询会反复拉到同一条未读提醒，不去重就会每 30 秒震一下
 * 3. 拉取失败静默：提醒是"锦上添花"，网络不好时不能弹错误吓老人
 */

import assert from 'node:assert/strict'
import { register } from 'node:module'
import { finish, group, sleep, testAsync } from './test-util.mjs'
import { installUniStub } from './uni-stub.mjs'
import { startMockServer } from './mock-server.mjs'

const { storage, calls } = installUniStub()

register('./node-alias-hook.mjs', import.meta.url)

const externalBase = process.env.BILIN_TEST_BASE_URL || ''
const mock = externalBase ? null : await startMockServer({ port: 0, delayMs: 0 })
const baseURL = externalBase || 'http://127.0.0.1:' + mock.port
console.log('联调目标: ' + baseURL + (externalBase ? '（外部后端）' : '（内置 mock）'))

const config = await import('../uni-app/api/config.js')
config.setBaseURL(baseURL)
const remindersApi = await import('../uni-app/api/reminders.js')
const plansApi = await import('../uni-app/api/plans.js')

/** 本机今天某时刻（提醒时间是按"今天"排的，只有真实今天才对得上） */
function todayAt(hour, minute = 0) {
  const now = new Date()
  const pad = (value) => String(value).padStart(2, '0')
  return (
    now.getFullYear() + '-' + pad(now.getMonth() + 1) + '-' + pad(now.getDate()) +
    'T' + pad(hour) + ':' + pad(minute) + ':00'
  )
}

// 真实后端要先有生效计划；mock 自带一份
if (externalBase) {
  const today = await plansApi.fetchTodayPlan({ elderId: 'e_1' })
  if (!today.total) {
    const draft = await plansApi.createPlanDraft({ elderId: 'e_1', polish: false })
    await plansApi.confirmPlan({ planId: draft.plan.id, actor: '测试家属' })
  }
}

// 推进调度到 12:00：08:00 与 11:30 的提醒该到点了
const tick = await remindersApi.tickScheduler(todayAt(12))
assert.ok(tick && tick.summary, '手动推进调度应返回 summary')

const store = await import('../uni-app/stores/reminder.js')
const { reminder } = store

group('① 拉取与展示')

await testAsync('拉到未读提醒：进提醒条，队列里排好', async () => {
  const unread = await store.poll()
  assert.ok(unread >= 1, '12:00 时应有已投递的提醒')
  assert.ok(reminder.banner, '应有一条推到提醒条上')
  assert.ok(reminder.banner.taskId)
  assert.ok(reminder.banner.title, '提醒要有正文')
  assert.match(reminder.banner.time, /^\d{2}:\d{2}$/)
  assert.equal(reminder.unread, unread, '未读数应等于服务端返回的条数')
})

await testAsync('提醒条文案是人话', async () => {
  const banner = reminder.banner
  assert.ok(banner.label.includes(':') || banner.label.includes(' '), '要有时间或类型')
  assert.ok(['强提醒', '普通提醒', '弱提醒'].includes(banner.levelLabel), banner.levelLabel)
})

await testAsync('新提醒会震动（普通级轻震）', async () => {
  assert.ok(calls.vibrate.length >= 1, '新提醒应触发震动')
  assert.ok(calls.vibrate.includes('short') || calls.vibrate.includes('long'))
})

group('② 强提醒')

await testAsync('点「知道了」后强提醒上屏，并且长震', async () => {
  const first = reminder.banner
  const before = calls.vibrate.length
  if (reminder.queue.length) {
    assert.equal(first.strong, false, '第一条应该是普通级（08:00 监测）')
    store.dismissBanner()
    await sleep(30)
    assert.ok(reminder.banner, '队列里还有一条')
    assert.equal(reminder.banner.strong, true, '下一条应是强提醒（11:30 午餐）')
    assert.equal(reminder.banner.levelLabel, '强提醒')
    assert.ok(calls.vibrate.slice(before).includes('long'), '强提醒要长震')
  } else {
    console.log('      （服务端只投递了一条提醒，跳过强提醒用例）')
  }
})

group('③ 去重与回执')

await testAsync('反复轮询不会重复震动', async () => {
  const before = calls.vibrate.length
  await store.poll()
  await store.poll()
  assert.equal(calls.vibrate.length, before, '同一条未读提醒不该反复震动')
})

await testAsync('回执：已读的提醒不再出现在收件箱', async () => {
  const current = reminder.banner
  assert.ok(current, '此时提醒条上应该有内容')
  const unreadBefore = reminder.unread
  store.dismissBanner()
  await sleep(40)
  assert.equal(reminder.unread, Math.max(0, unreadBefore - 1))
  const inbox = await remindersApi.fetchReminderInbox({ elderId: 'e_1' })
  assert.ok(
    !(inbox.tasks || []).some((task) => task.id === current.taskId),
    '已读的提醒不该再出现：' + current.taskId
  )
})

await testAsync('点提醒条本体：跳日程页打卡', async () => {
  // 先把时间推到 16:00，让 15:30 那条提醒到点，保证这一步有东西可点
  await remindersApi.tickScheduler(todayAt(16))
  store.clearReminders()
  await store.poll()
  assert.ok(reminder.banner, '应有一条新的未读提醒')
  const before = calls.navigate.length
  store.openBanner()
  await sleep(30)
  assert.ok(calls.navigate.length > before, '应触发页面跳转')
  assert.ok(calls.navigate[calls.navigate.length - 1].includes('/pages/plans/plans'))
  assert.equal(reminder.banner, null, '点过之后提醒条应消失')
})

group('④ 降级与开关')

await testAsync('拉取失败静默：不抛错、不吓老人、已有提醒不丢', async () => {
  store.dismissBanner()
  const bannerBefore = reminder.banner
  config.setBaseURL('http://127.0.0.1:1')
  const unread = await store.poll()
  assert.equal(typeof unread, 'number', '失败也要正常返回')
  assert.ok(reminder.lastError, '内部记下错误即可')
  assert.deepEqual(reminder.banner, bannerBefore, '已经展示的提醒不该被清掉')
  config.setBaseURL(baseURL)
})

await testAsync('轮询开关可控（退到后台要停）', async () => {
  store.stopPolling()
  assert.equal(reminder.polling, false)
  store.startPolling('e_1')
  assert.equal(reminder.polling, true)
  await sleep(50)
  store.stopPolling()
  assert.equal(reminder.polling, false)
})

await testAsync('调度器状态可查（通道与任务数）', async () => {
  const status = await remindersApi.fetchSchedulerStatus()
  assert.ok(Array.isArray(status.channels))
  assert.ok(status.channels.some((channel) => channel.name === 'inbox'))
  assert.ok(status.counts)
  assert.ok(Array.isArray(status.weakWindow))
})

/* ------------------------------------------------------------------ 收尾 */

if (mock) await mock.close()
finish()
