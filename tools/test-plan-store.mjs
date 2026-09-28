#!/usr/bin/env node
/**
 * 比邻AI · 老人端「今日计划 + 打卡」状态自检（零依赖）
 *
 *   node tools/test-plan-store.mjs
 *   BILIN_TEST_BASE_URL=http://127.0.0.1:8000 node tools/test-plan-store.mjs   # 打真实后端
 *
 * 重点守两件事：
 * 1. **打卡是乐观的**：点一下立刻变绿，服务端失败要回滚并给人话提示
 *    （老人手指粗、网慢，出现"点了没反应"等于告诉他"我不会用"）
 * 2. **永不白屏**：接口 → 缓存 → 内置样例，三级都断不了
 */

import assert from 'node:assert/strict'
import { register } from 'node:module'
import { finish, group, testAsync } from './test-util.mjs'
import { installUniStub } from './uni-stub.mjs'
import { startMockServer } from './mock-server.mjs'

/* -------------------------------------------------- 内存版 uni 运行时 */

const storage = installUniStub()

register('./node-alias-hook.mjs', import.meta.url)

const externalBase = process.env.BILIN_TEST_BASE_URL || ''
const mock = externalBase ? null : await startMockServer({ port: 0, delayMs: 0 })
const baseURL = externalBase || 'http://127.0.0.1:' + mock.port
console.log('联调目标: ' + baseURL + (externalBase ? '（外部后端）' : '（内置 mock）'))

const config = await import('../uni-app/api/config.js')
config.setBaseURL(baseURL)
const plansApi = await import('../uni-app/api/plans.js')

// 真实后端有「家属确认」闸门：没有生效计划时今日计划就是空的（这正是它该有的行为）。
// 所以打外部后端时先走一遍「生成 → 家属确认」，模拟家里人的操作。
if (externalBase) {
  const today = await plansApi.fetchTodayPlan({ elderId: 'e_1' })
  if (!today.total) {
    const draft = await plansApi.createPlanDraft({ elderId: 'e_1', polish: false })
    await plansApi.confirmPlan({ planId: draft.plan.id, actor: '测试家属' })
    console.log('已先为真实后端生成并确认一份计划：' + draft.plan.id)
  }
}

const store = await import('../uni-app/stores/plan.js')
const { plan } = store

group('① 今日计划加载')

await testAsync('拉到今日计划：条目、计数、标题都对', async () => {
  await store.initPlan()
  assert.equal(plan.source, 'ready', '应走接口成功分支')
  assert.ok(plan.items.length > 0, '计划项不能为空')
  assert.equal(plan.total, plan.items.length)
  assert.equal(plan.done, 0)
  for (const item of plan.items) {
    assert.ok(item.id, '每项都要有 id（打卡要用）')
    assert.match(item.time, /^\d{2}:\d{2}$/)
    assert.ok(item.title)
    assert.equal(typeof item.done, 'boolean')
  }
  const headline = store.planHeadline()
  assert.ok(headline.includes('共 ' + plan.total + ' 项'), '标题应显示总项数：' + headline)
  assert.ok(headline.includes('周一') || /\d+月\d+日/.test(headline), '标题应带日期：' + headline)
})

await testAsync('状态文案是人话，不是英文枚举', async () => {
  assert.ok(plan.statusLabel)
  assert.ok(!/[a-z_]{4,}/i.test(plan.statusLabel), '不该出现 status 原文：' + plan.statusLabel)
})

group('② 打卡')

await testAsync('打卡：乐观更新 + 服务端确认', async () => {
  const item = plan.items[0]
  const before = plan.done
  const ok = await store.toggleCheckin(item)
  assert.equal(ok, true)
  assert.equal(item.done, true, '界面应立刻变绿')
  assert.equal(plan.done, before + 1)

  const fresh = await (await import('../uni-app/api/plans.js')).fetchTodayPlan({ elderId: plan.elderId })
  const serverItem = fresh.items.find((entry) => entry.id === item.id)
  assert.equal(serverItem.done, true, '服务端也要记下来')
  assert.equal(fresh.done, before + 1)
})

await testAsync('取消打卡：能改回来（老人点错了）', async () => {
  const item = plan.items[0]
  const ok = await store.toggleCheckin(item)
  assert.equal(ok, true)
  assert.equal(item.done, false)
  assert.equal(plan.done, 0)
})

await testAsync('连点两下不会来回抖（同项进行中直接拒绝）', async () => {
  const item = plan.items[1]
  const first = store.toggleCheckin(item)
  const second = store.toggleCheckin(item)
  const results = await Promise.all([first, second])
  assert.equal(results[1], false, '第二次点击应被挡掉')
  assert.equal(results[0], true)
  assert.equal(item.done, true)
  assert.equal(plan.pending.length, 0, '结束后 pending 要清空')
  await store.toggleCheckin(item) // 还原
  assert.equal(item.done, false)
})

await testAsync('未知项打卡：服务端 404 时不静默成功', async () => {
  const ghost = { id: 'pi_not_exist', done: false }
  const ok = await store.toggleCheckin(ghost)
  assert.equal(ok, false)
  assert.equal(ghost.done, false, '失败要回滚')
  assert.ok(plan.lastError, '要给老人一句提示')
})

group('③ 降级：绝不白屏')

await testAsync('接口挂了但有缓存：显示缓存并提示', async () => {
  const cachedCount = plan.items.length
  config.setBaseURL('http://127.0.0.1:1')
  await store.refreshToday()
  assert.equal(plan.source, 'cached')
  assert.equal(plan.items.length, cachedCount, '缓存内容应与上次一致')
  assert.ok(plan.lastError)
})

await testAsync('接口挂了且没缓存：用内置样例兜底', async () => {
  store.clearPlanCache()
  await store.refreshToday()
  assert.equal(plan.source, 'sample')
  assert.ok(plan.items.length > 0, '样例兜底不能为空')
  assert.equal(plan.done, 0)
})

await testAsync('样例数据下打卡：本地有反馈，但不假装保存成功', async () => {
  const item = plan.items[0]
  const ok = await store.toggleCheckin(item)
  assert.equal(ok, false, '样例数据不该报告成功')
  assert.equal(item.done, true, '本地仍要给老人反馈')
  assert.ok(plan.lastError, '要说明现在连不上')
})

await testAsync('恢复连接后回到正常数据', async () => {
  config.setBaseURL(baseURL)
  store.clearPlanCache()
  await store.refreshToday()
  assert.equal(plan.source, 'ready')
  assert.equal(plan.done, 0, '服务端状态为准（样例里的勾选不该带过来）')
})

/* ------------------------------------------------------------------ 收尾 */

if (mock) await mock.close()
finish()
