#!/usr/bin/env node
/**
 * 比邻AI · 家人端（最小版）自检（零依赖）
 *
 *   node tools/test-family-flows.mjs
 *   BILIN_TEST_BASE_URL=http://127.0.0.1:8000 BILIN_TEST_API_TOKEN=xxx node tools/test-family-flows.mjs
 *
 * 这里测的是家人端的**业务层**（family/flows.js），不是 DOM：
 * 确认闸门、驳回、调整、完成率文案、依据是否露出。
 *
 * 另外守两条容易被人"顺手改坏"的约束：
 * 1. **隐私边界**：家人端默认不可见聊天原文（设计方案 §3.4）——所以这里有一条
 *    "flows.js 里不许出现任何会话接口"的回归用例。想加"看聊天"，得先有老人授权与 consent 记录
 * 2. **静态托管**：mock/服务端要能把 family/ 与 uni-app/api/ 发出来，
 *    且不能顺着 ../ 把整个仓库读走
 */

import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { register } from 'node:module'
import { finish, group, testAsync } from './test-util.mjs'
import { startMockServer } from './mock-server.mjs'

register('./node-alias-hook.mjs', import.meta.url)

const TOKEN = 'family-console-token-abc123'
const externalBase = process.env.BILIN_TEST_BASE_URL || ''
const externalToken = process.env.BILIN_TEST_API_TOKEN || ''
const mock = externalBase ? null : await startMockServer({ port: 0, delayMs: 0, authToken: TOKEN })
const baseURL = externalBase || 'http://127.0.0.1:' + mock.port
const token = externalBase ? externalToken : TOKEN
console.log('联调目标: ' + baseURL + (externalBase ? '（外部后端）' : '（内置 mock）'))

const family = await import('../family/flows.js')
const flows = family.createFamilyFlows({ baseURL, token })

group('① 待确认 → 确认 → 生效（家属确认闸门）')

await testAsync('老人列表可用', async () => {
  const elders = await flows.listElders()
  assert.ok(elders.length >= 1)
  assert.ok(elders[0].id)
})

await testAsync('生成草稿后出现在待确认里，且带着依据', async () => {
  await flows.createDraft('e_1')
  const pending = await flows.listPending('e_1')
  assert.equal(pending.length, 1, '应该正好有一份待确认计划')
  const plan = pending[0]
  // 状态名以 server/app/plan/models.py 为准：等家里人确认
  assert.equal(plan.status, 'pending_confirm')
  assert.ok(plan.statusLabel)
  assert.ok(plan.items.length >= 1)
  const item = family.describeItem(plan.items[0])
  assert.ok(item.basis, '依据必须露出来：家属要看到这条是照哪份指南来的')
  assert.ok(item.basis.length > 4)
  assert.ok(item.source, '还要能看出依据来自哪份文件')
  assert.ok(item.time && item.title)
  // 状态解释：未确认 = 不产生任何提醒
  const state = family.describePlanStatus(plan)
  assert.equal(state.executing, false)
  assert.match(state.hint, /收不到|没生效/)
})

await testAsync('未确认前不会变成生效计划', async () => {
  const today = await flows.today('e_1')
  const pending = await flows.listPending('e_1')
  assert.notEqual(today.planId, pending[0].id, '草稿不能在确认前生效')
})

await testAsync('确认后立即生效，待确认清空', async () => {
  const pending = await flows.listPending('e_1')
  const planId = pending[0].id
  const result = await flows.confirm(planId, '女儿')
  assert.ok(result.plan)
  assert.equal(result.plan.status, 'active')
  assert.equal(result.plan.confirmedBy, '女儿')
  assert.equal((await flows.listPending('e_1')).length, 0)
  const today = await flows.today('e_1')
  assert.equal(today.planId, planId, '确认的那份应该就是当前生效计划')
  assert.equal(family.describePlanStatus(today).executing, true)
})

await testAsync('计划历史能看出这份计划什么时候被确认的', async () => {
  const history = await flows.history('e_1')
  assert.ok(history.length >= 1)
  const confirmed = history.find((plan) => plan.status === 'active' || plan.status === 'adjusting')
  assert.ok(confirmed, '历史里应该有已生效的那份')
  assert.ok(confirmed.confirmedAt, '已确认的计划必须有确认时间')
  assert.ok(confirmed.statusLabel)
  assert.ok(confirmed.items >= 1, 'items 是项数（不是数组）')
})

await testAsync('确认不存在的计划：人话错误，不给重试', async () => {
  let error = null
  try {
    await flows.confirm('plan_不存在')
  } catch (e) {
    error = e
  }
  assert.ok(error, '应该抛错')
  assert.equal(error.code, 'plan_not_found')
  assert.equal(error.retryable, false)
  assert.ok(!/[A-Za-z]{6,}/.test(error.message), '提示不该出现英文：' + error.message)
})

group('② 驳回与调整')

await testAsync('驳回：待确认清空，当前计划不变', async () => {
  const before = (await flows.today('e_1')).planId
  await flows.createDraft('e_1')
  const pending = await flows.listPending('e_1')
  await flows.reject(pending[0].id, '时间不合适', '女儿')
  assert.equal((await flows.listPending('e_1')).length, 0)
  assert.equal((await flows.today('e_1')).planId, before, '驳回不该影响正在执行的计划')
})

await testAsync('转入调整：还是同一份计划，且**仍在执行**', async () => {
  const today = await flows.today('e_1')
  const result = await flows.requestAdjust(today.planId, '早上太早，改到 9 点后')
  assert.equal(result.plan.status, 'adjusting')
  // 真实语义：adjusting 不产生新的待确认计划，原计划继续跑（没有提醒真空）
  assert.equal((await flows.listPending('e_1')).length, 0)
  const after = await flows.today('e_1')
  assert.equal(after.planId, today.planId, '调整中还是它，不该换计划')
  assert.equal(after.status, 'adjusting')
  const state = family.describePlanStatus(after)
  assert.equal(state.executing, true, '调整中仍在执行')
  assert.match(state.hint, /仍然在执行/)
})

await testAsync('调整后生成新计划并确认，才替换掉旧计划', async () => {
  await flows.createDraft('e_1')
  const pending = await flows.listPending('e_1')
  const newId = pending[0].id
  await flows.confirm(newId, '女儿')
  const today = await flows.today('e_1')
  assert.equal(today.planId, newId)
  assert.equal(today.status, 'active')
  const history = await flows.history('e_1')
  const old = history.find((plan) => plan.id !== newId && plan.status === 'ended')
  assert.ok(old, '旧计划应该被置为已结束')
})

group('③ 完成率与提醒追溯')

await testAsync('完成率能算出百分比且有人话说明', async () => {
  const summary = await flows.summary('e_1', 7)
  const stats = summary.stats || summary
  const rate = family.describeRate(stats)
  assert.ok(rate.percent >= 0 && rate.percent <= 100)
  assert.match(rate.text, /最近 \d+ 天/)
  assert.ok(!/[A-Za-z]{6,}/.test(rate.text))
})

await testAsync('describeRate 分档措辞（高/中/低）', async () => {
  assert.match(family.describeRate({ days: 7, expected: 10, done: 9, rate: 0.9 }).text, /做得挺好/)
  assert.match(family.describeRate({ days: 7, expected: 10, done: 6, rate: 0.6 }).text, /还行/)
  assert.match(family.describeRate({ days: 7, expected: 10, done: 1, rate: 0.1 }).text, /漏得比较多/)
  assert.equal(family.describeRate(null).percent, 0)
})

await testAsync('计划状态解释覆盖全部六态（避免"调整中还在执行"被误解）', async () => {
  const cases = {
    draft: false,
    pending_confirm: false,
    active: true,
    adjusting: true,
    ended: false,
    rejected: false
  }
  for (const [status, executing] of Object.entries(cases)) {
    const state = family.describePlanStatus({ status, statusLabel: 'x' })
    assert.equal(state.executing, executing, status)
    assert.ok(state.hint, status + ' 应该有解释')
  }
  assert.match(family.describePlanStatus({ status: 'adjusting' }).hint, /仍然在执行/)
})

await testAsync('提醒任务可追溯（发了/没发/通道），且状态是中文', async () => {
  const tasks = await flows.reminders('e_1')
  assert.ok(Array.isArray(tasks))
  // 推进到下一个提醒时间，逼出一条真实任务
  const today = await flows.today('e_1')
  if (today.planId) {
    await flows.tick(family.nextReminderAt(today))
    const after = await flows.reminders('e_1')
    assert.ok(after.length >= 1, '推进后应该有提醒任务了')
    for (const task of after) {
      assert.ok(task.statusLabel, '家属端要直接展示中文状态：' + JSON.stringify(task))
      assert.match(task.statusLabel, /[\u4e00-\u9fff]/)
      assert.ok(task.sendAt && task.title)
    }
    assert.ok(
      after.some((task) => task.status === 'sent'),
      '应该有已送出的任务'
    )
  }
})

await testAsync('nextReminderAt：默认推进到下一个提醒时间（演示时不会推成 0 条）', async () => {
  const today = await flows.today('e_1')
  assert.ok(today.items.length >= 1)
  const first = today.items.slice().sort((a, b) => (a.time < b.time ? -1 : 1))[0]
  // 定在"今天 00:01"，那第一个时间点一定还在未来
  const earlyMorning = new Date(today.date + 'T00:01:00')
  const next = family.nextReminderAt(today, earlyMorning)
  assert.equal(next, today.date + 'T' + first.time + ':00')
  // 时间点都过完时顺延到明天第一项，而不是回到过去
  const lateNight = new Date(today.date + 'T23:59:00')
  const tomorrow = family.nextReminderAt(today, lateNight)
  assert.ok(tomorrow > lateNight.toISOString().slice(0, 19).replace('T', 'T'), tomorrow)
  assert.match(tomorrow, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00$/)
})

group('④ 两条硬约束')

await testAsync('隐私：家人端流程里没有任何会话接口（默认看不到聊天原文）', async () => {
  const source = await readFile(new URL('../family/flows.js', import.meta.url), 'utf8')
  const code = source
    .split('\n')
    .filter((line) => {
      const trimmed = line.trim()
      return !trimmed.startsWith('*') && !trimmed.startsWith('//') && !trimmed.startsWith('/*')
    })
    .join('\n')
  assert.ok(!/chat/i.test(code), 'flows.js 里出现了会话相关代码：家人端默认不可见聊天原文')
  const keys = Object.keys(flows)
  assert.ok(!keys.some((key) => /chat|history\($/.test(key) && /chat/i.test(key)), keys.join(','))
})

await testAsync('静态托管可用，且挡得住目录穿越', async () => {
  const html = await fetch(baseURL + '/family/')
  assert.equal(html.status, 200)
  assert.match(await html.text(), /家人端/)

  const module = await fetch(baseURL + '/uni-app/api/plans.js')
  assert.equal(module.status, 200, '家人端 import 的 api 模块必须能取到')
  assert.match(await module.text(), /fetchTodayPlan/)

  const escape = await fetch(baseURL + '/family/..%2f..%2fAGENTS.md')
  assert.ok(escape.status === 403 || escape.status === 404, '不该把仓库文件读出去：' + escape.status)
})

if (mock) {
  await testAsync('鉴权：没带 token 时错误是人话且不给重试', async () => {
    const noToken = family.createFamilyFlows({ baseURL, token: '' })
    let error = null
    try {
      await noToken.listPending('e_1')
    } catch (e) {
      error = e
    }
    assert.ok(error, '应该抛错')
    assert.equal(error.statusCode, 401)
    assert.equal(error.retryable, false)
    assert.ok(!/[A-Za-z]{6,}/.test(error.message))
  })
  await mock.close()
}

finish()
