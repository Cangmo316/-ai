#!/usr/bin/env node
/**
 * 比邻AI · 家人端（最小版）自检（零依赖）
 *
 *   node tools/test-family-flows.mjs
 *   BILIN_TEST_BASE_URL=http://127.0.0.1:8000 BILIN_TEST_API_TOKEN=xxx node tools/test-family-flows.mjs
 *
 * 这里测的是家人端的**业务层**（family/flows.js），不是 DOM：
 * 确认闸门、驳回、调整、完成率文案、依据是否露出、记忆的录入与复核。
 *
 * 另外守几条容易被人"顺手改坏"的约束：
 * 1. **隐私边界**：家人端默认不可见聊天原文（设计方案 §3.4）——所以这里有一条
 *    "flows.js 里不许出现任何会话接口"的回归用例。想加"看聊天"，得先有老人授权与 consent 记录
 * 2. **记忆的两道闸门**：`source=auto`（从聊天自动整理）默认家属不可见；
 *    待复核（`review=pending`）只进待复核区，不进主列表
 * 3. **静态托管**：mock/服务端要能把 family/ 与 uni-app/api/ 发出来，
 *    且不能顺着 ../ 把整个仓库读走
 *
 * ⚠️ 删/清空类用例**不许用 `e_1`**（AGENTS 硬规则）：打真服务时 `e_1` 很可能是演示数据，
 * 被自检清掉就没了。这里统一用 `MEM_ELDER`（`e_mem_test`），它只属于自检。
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
/** 记忆自检专用老人 id：删除/清空只许动它，别动 e_1 */
const MEM_ELDER = 'e_mem_test'
/**
 * 开关用例专用 id：**每次都换一个从没出现过的老人 id**。
 * 原因：打真服务时 `e_mem_test` 的开关状态是上一轮自检留下的（开启过就会留着同意时间），
 * "默认关 / 没有同意时间"这类断言只有在**全新的 key**上才成立。
 * 这里不可能"清空"设置来复位——契约刻意不给撤回告知的接口（consentedAt 是凭证）。
 */
const SETTINGS_ELDER = 'e_mem_switch_' + Date.now()

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

group('④ 三条硬约束')

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

group('⑤ 记忆（P2 三层记忆的家人侧）')

await testAsync('列表默认只看家属可见的：服务端两道闸门都得生效', async () => {
  const list = await flows.listMemories('e_1')
  for (const item of list) {
    assert.notEqual(item.source, 'auto', '从聊天自动整理的记忆不该出现在家人列表：' + item.text)
    assert.notEqual(item.review, 'pending', '待复核的不该出现在家人列表：' + item.text)
    assert.equal(item.visibleToFamily, true, '家人列表里不允许出现家属不可见的条目')
    const described = family.describeMemory(item)
    assert.ok(described.kindText && described.sourceText, '种类与来源都要有中文标签')
    assert.equal(described.pending, false)
    assert.equal(described.autoExtracted, false)
  }
})

await testAsync('待复核默认只进「待复核区」，不进主列表（仅内置 mock 有种子）', async () => {
  // 契约里**没有"手工造一条待复核条目"的写入口**（这正是刻意的隐私口径：
  // source=auto + pending 只能由对话自动整理产生），真服务上库里可能一条都没有，
  // 所以"必须有"只在 mock 上断言；两种情况下"不得出现在主列表"这条都要成立
  const pending = await flows.pendingMemories('e_1')
  if (mock) assert.ok(pending.length >= 1, 'mock 种子里应有一条待复核的，用来验这条口径')
  const ids = new Set((await flows.listMemories('e_1')).map((item) => item.id))
  for (const item of pending) {
    assert.equal(item.review, 'pending')
    assert.ok(!ids.has(item.id), '待复核的绝不能同时出现在主列表：' + item.text)
    const described = family.describeMemory(item)
    assert.equal(described.pending, true)
    assert.equal(described.source, 'auto', '待复核的必然是自动整理出来的')
  }
})

await testAsync('录入空内容被拦：人话提示，且不白跑一趟服务端', async () => {
  const before = (await flows.listMemories(MEM_ELDER)).length
  let error = null
  try {
    await flows.addMemory(MEM_ELDER, { kind: 'experience', text: '   ' })
  } catch (e) {
    error = e
  }
  assert.ok(error, '空内容必须被拦住')
  assert.equal(error.code, 'memory_empty')
  assert.ok(!/[A-Za-z]{6,}/.test(error.message), '提示不该出现英文：' + error.message)
  assert.match(error.message, /不能是空/)
  assert.equal((await flows.listMemories(MEM_ELDER)).length, before, '空提交不该多出一条')
})

await testAsync('录入一条：进列表、带中文来源与种类', async () => {
  const before = (await flows.listMemories(MEM_ELDER)).length
  const created = await flows.addMemory(MEM_ELDER, {
    kind: 'preference',
    text: '老人爱在下午听评剧（家人端自检写入）',
    tags: ['戏曲', '评剧'],
    happenedAt: '2024年'
  })
  assert.ok(created.memory.id)
  assert.equal(created.memory.source, 'family')
  assert.equal(created.memory.visibleToFamily, true)
  assert.equal(created.memory.review, 'approved', '家人录入的直接可用（不需要复核）')
  const list = await flows.listMemories(MEM_ELDER)
  assert.equal(list.length, before + 1)
  const item = family.describeMemory(list.find((row) => row.id === created.memory.id))
  assert.equal(item.kindText, '喜好')
  assert.equal(item.sourceText, '家里人填写')
  assert.equal(item.happenedAt, '2024年')
  assert.equal(item.tagText, '戏曲、评剧')
  assert.equal(item.pending, false)
  assert.equal(item.autoExtracted, false)
})

await testAsync('describeMemory：服务端没给标签时也不出 undefined / 英文枚举', async () => {
  const full = family.describeMemory({
    id: 'mem_x', kind: 'experience', kindLabel: '经历', text: '去过海南',
    tags: ['儿子'], source: 'elder', sourceLabel: '老人自己说的',
    review: 'approved', visibleToFamily: true, happenedAt: '2023年'
  })
  assert.equal(full.kindText, '经历')
  assert.equal(full.sourceText, '老人自己说的')
  assert.match(full.reviewText, /可用/)

  // 真服务上 source≠auto 的条目可能没有 sourceLabel（mock 有），兜底必须还在
  const bare = family.describeMemory({ id: 'm', kind: 'profile', text: '不吃辣', source: 'elder' })
  assert.equal(bare.kindText, '习惯')
  assert.equal(bare.sourceText, '老人自己说的')
  assert.equal(bare.tagText, '')
  assert.equal(bare.happenedAt, '')
  assert.ok(!JSON.stringify(bare).includes('undefined'), '不能把 undefined 渲染到页面上')
  // 自动整理的要能认出来（页面据此显示"从聊天里整理"）
  assert.equal(family.describeMemory({ source: 'auto' }).autoExtracted, true)
  // 全空也不能炸
  const empty = family.describeMemory(null)
  assert.equal(empty.text, '')
  assert.ok(empty.kindText && empty.sourceText && empty.reviewText)
})

await testAsync('复核通过：可用了，但自动整理的仍然不进家人列表', async () => {
  // 只有 mock 有种子待复核条目 → 放在 mock 分支里断言完整流程
  const pending = await flows.pendingMemories('e_1')
  if (mock) {
    assert.ok(pending.length >= 1, '需要一条待复核的来验复核流程')
    const target = pending[0]
    const before = await flows.pendingMemoryCount('e_1')
    const result = await flows.reviewMemory(target.id, true)
    assert.equal(result.memory.review, 'approved')
    assert.ok(result.notice)
    const after = await flows.pendingMemories('e_1')
    assert.equal(after.length, pending.length - 1, '通过后不该再出现在待复核区')
    assert.equal(await flows.pendingMemoryCount('e_1'), before - 1, '服务端的待复核计数要跟着降')
    assert.ok(
      !(await flows.listMemories('e_1')).some((item) => item.id === target.id),
      'source=auto 的即使复核通过也不进家人列表：家属看到的是"整理出的那句话"，不是聊天原文'
    )
  } else {
    // 真服务：库先清干净，用"复核一条不存在的"验证错误口径（人话、不给重试）
    await flows.clearMemories(MEM_ELDER)
    await assert.rejects(
      () => flows.reviewMemory('mem_不存在', true),
      (error) => {
        assert.equal(error.code, 'memory_not_found')
        assert.equal(error.statusCode, 404)
        assert.equal(error.retryable, false, '没找到就别让端侧给重试按钮')
        assert.ok(!/[A-Za-z]{6,}/.test(error.message), '提示不该出现英文：' + error.message)
        return true
      }
    )
  }
})

await testAsync('复核否决：待复核区不再出现，也不会被检索用上', async () => {
  if (mock) {
    // 上一条用例把种子里的待复核条目消费掉了，而契约刻意不给"手工造一条 pending"的写入口
    // （source=auto + pending 只能由对话自动整理产生），所以这里先断言"待复核区已经干净"，
    // 再用一条不存在的 id 验证否决的失败口径：绝不能被当成"否决成功"
    assert.equal((await flows.pendingMemories('e_1')).length, 0)
  }
  await assert.rejects(
    () => flows.reviewMemory('mem_不存在', false),
    (error) => {
      assert.equal(error.code, 'memory_not_found')
      assert.equal(error.statusCode, 404)
      assert.equal(error.retryable, false, '没找到就别让端侧给重试按钮')
      assert.ok(!/[A-Za-z]{6,}/.test(error.message), '提示不该出现英文：' + error.message)
      return true
    }
  )
})

await testAsync('开关默认关，开启后记录同意时间', async () => {
  // 用全新老人 id（见 SETTINGS_ELDER 的注释：老 id 上可能留着上一轮的同意时间）
  const off = await flows.memorySettings(SETTINGS_ELDER)
  assert.equal(off.autoExtract, false, '默认必须是关的')
  assert.equal(off.consentedAt, '', '没开启过就不该有同意时间')
  const state = family.describeMemorySettings(off)
  assert.equal(state.autoExtract, false)
  assert.match(state.label, /关闭/)
  assert.match(state.hint, /告知/)

  const on = await flows.saveMemorySettings(SETTINGS_ELDER, true)
  assert.equal(on.autoExtract, true)
  assert.ok(on.consentedAt, '开启时该记下同意时间')
  const onState = family.describeMemorySettings(on)
  assert.equal(onState.autoExtract, true)
  assert.match(onState.hint, /已记录同意时间/)

  // 关掉只影响新增，同意时间作为"曾明确告知过"的凭证保留
  const back = await flows.saveMemorySettings(SETTINGS_ELDER, false)
  assert.equal(back.autoExtract, false)
  assert.ok(back.consentedAt, '关掉不该抹掉同意记录')
  assert.match(family.describeMemorySettings(back).label, /关闭/)
})

await testAsync('开关按老人各存一份（别把一位老人的同意算到另一位头上）', async () => {
  // 开关是隐私开关：给一位老人开了，绝不等于另一位也同意过。
  // 同样用全新 id，否则打真服务时会撞上"上一条用例刚把开关改过"的残留状态
  const other = await flows.memorySettings('e_mem_other_' + Date.now())
  assert.equal(other.autoExtract, false, '没开过就必须是关的')
  assert.equal(other.consentedAt, '', '不该继承别人的同意时间')
})

await testAsync('单条删除', async () => {
  const created = await flows.addMemory(MEM_ELDER, { text: '这条马上要删掉（家人端自检）' })
  const id = created.memory.id
  assert.ok((await flows.listMemories(MEM_ELDER)).some((item) => item.id === id))
  const removed = await flows.deleteMemory(id)
  assert.equal(removed.ok, true)
  assert.ok(!(await flows.listMemories(MEM_ELDER)).some((item) => item.id === id), '删掉就不该还在列表里')
})

await testAsync('一键清空：列表与待复核区都空，设置保留', async () => {
  // 先确保有内容可清（用例可以单独重跑，不依赖别的用例留下的痕迹）
  await flows.addMemory(MEM_ELDER, { text: '清空前先放一条（家人端自检）' })
  // 并确保"同意时间"确实存在：它是"清空≠撤回告知"这条断言的依据，
  // 不能指望别的用例先把它设上（用例顺序会变，打真服务时还可能是上一轮的残留）
  const beforeClear = await flows.saveMemorySettings(MEM_ELDER, true)
  assert.ok(beforeClear.consentedAt, '前置：开启后应有同意时间')

  const cleared = await flows.clearMemories(MEM_ELDER)
  assert.ok(cleared.removed >= 1, '至少清掉一条')
  assert.equal((await flows.listMemories(MEM_ELDER)).length, 0)
  assert.equal((await flows.pendingMemories(MEM_ELDER)).length, 0)
  assert.ok(
    !(await flows.listMemories(MEM_ELDER)).some((item) => item.text.includes('清空前先放一条')),
    '清空之后正文不该还留在库里'
  )
  const settings = await flows.memorySettings(MEM_ELDER)
  assert.equal(settings.autoExtract, true, '清空是"忘掉内容"，不是"改开关"')
  assert.ok(settings.consentedAt, '同意时间当初记下了就该留着')
  // 清空之后录入仍然可用：不能把"清空"做成一次性状态
  const again = await flows.addMemory(MEM_ELDER, { text: '清空后重新记一条（家人端自检）' })
  assert.equal((await flows.listMemories(MEM_ELDER)).length, 1)
  await flows.deleteMemory(again.memory.id)
  // 收尾：开关关回去（同意时间按契约保留，这正是它的意义）
  await flows.saveMemorySettings(MEM_ELDER, false)
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
