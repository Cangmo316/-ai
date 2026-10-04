#!/usr/bin/env node
/**
 * 比邻AI · 三层记忆端侧契约自检（零依赖）
 *
 *   node tools/test-memory-store.mjs
 *   BILIN_TEST_BASE_URL=http://127.0.0.1:8000 BILIN_TEST_API_TOKEN=xxx node tools/test-memory-store.mjs
 *
 * 这里守的不是"能取到数据"，而是**取不到不该取的数据**——记忆是最容易越界的一层：

 * 1. **自动整理的记忆不能出现在家人视野**：否则"家人端默认看不到聊天原文"被绕过
 * 2. **待复核的不能出现在默认列表**：低置信内容要先经家属复核
 * 3. **一键清空要真的清空**：老人说"把这些都忘掉"时，必须是删掉而不是标记
 *
 * 真服务与 mock 都要能过这套用例（AGENTS：契约唯一来源是 uni-app/api/README.md）
 */

import assert from 'node:assert/strict'
import { register } from 'node:module'
import { finish, group, testAsync } from './test-util.mjs'
import { installUniStub } from './uni-stub.mjs'
import { startMockServer } from './mock-server.mjs'

installUniStub()
register('./node-alias-hook.mjs', import.meta.url)

const externalBase = process.env.BILIN_TEST_BASE_URL || ''
const mock = externalBase ? null : await startMockServer({ port: 0, delayMs: 0 })
const baseURL = externalBase || 'http://127.0.0.1:' + mock.port
console.log('联调目标: ' + baseURL + (externalBase ? '（外部后端）' : '（内置 mock）'))

const config = await import('../uni-app/api/config.js')
config.setBaseURL(baseURL)
if (process.env.BILIN_TEST_API_TOKEN) config.setApiToken(process.env.BILIN_TEST_API_TOKEN)
const api = await import('../uni-app/api/memory.js')
const raw = await import('../uni-app/api/request.js')

// ⚠️ 用**专用老人 id**，不要用 e_1：
// 这套用例最后一条要验「一键清空」，打真服务时会真的清空这位老人的全部记忆——
// 第一版就是用 e_1 跑的，结果把演示用的两条记忆清掉了（排查了半天"模型怎么不记得"）。
const MEM_ELDER = process.env.BILIN_TEST_ELDER_ID || 'e_mem_test'

function post(path, data) {
  return raw.request({ url: config.resolveURL(path), method: 'POST', data })
}

// 真服务是空库、mock 有种子数据；用例要能在两边重复跑，所以**缺什么补什么**
const seeded = await api.fetchMemories({ elderId: MEM_ELDER })
if (!(seeded.memories || []).some((item) => item.text.includes('海南'))) {
  await post(config.ENDPOINTS.memories, {
    elderId: MEM_ELDER,
    kind: 'experience',
    text: '老人 2023 年跟儿子去过海南',
    tags: ['儿子', '旅行'],
    happenedAt: '2023年'
  })
}
if (!(seeded.memories || []).some((item) => item.source !== 'auto')) {
  await post(config.ENDPOINTS.memories, {
    elderId: MEM_ELDER,
    kind: 'preference',
    text: '老人爱听戏（自检写入）',
    tags: ['戏曲']
  })
}

group('① 列表与可见性')

await testAsync('默认列表只给家属可见的（自动整理的不在其中）', async () => {
  const data = await api.fetchMemories({ elderId: MEM_ELDER })
  assert.ok(Array.isArray(data.memories), 'memories 必须是数组')
  data.memories.forEach((item) => {
    assert.notEqual(item.source, 'auto', '自动整理的记忆不该出现在家人默认视图: ' + item.text)
    assert.notEqual(item.review, 'pending', '待复核的条目不该出现在默认列表: ' + item.text)
    assert.equal(item.visibleToFamily, true)
  })
  assert.ok(data.memories.length >= 1, '至少应有一条家属录入的记忆')
})

await testAsync('老人自查（scope=all）能看到自动整理的那条', async () => {
  const data = await api.fetchMemories({ elderId: MEM_ELDER, scope: 'all' })
  const auto = data.memories.filter((item) => item.source === 'auto')
  if (auto.length) {
    assert.equal(auto[0].visibleToFamily, false, '自动整理的默认家属不可见')
  }
  assert.ok(data.memories.length >= 1)
})

await testAsync('待复核的只有显式要才给（includePending）', async () => {
  const normal = await api.fetchMemories({ elderId: MEM_ELDER, scope: 'all' })
  const withPending = await api.fetchMemories({ elderId: MEM_ELDER, scope: 'all', includePending: true })
  assert.ok(
    withPending.memories.length >= normal.memories.length,
    '要了待复核的，条数不该更少'
  )
})

group('② 检索（按相关性取，不要整库回）')

await testAsync('相关的记忆能被检索到，且带 score', async () => {
  const data = await api.fetchMemories({ elderId: MEM_ELDER, q: '你儿子上次带我去海南好玩吗' })
  assert.ok(data.memories.length >= 1, '该检索到海南那条')
  assert.ok(data.memories[0].score > 0, '检索结果要带相关性分数')
  assert.ok(
    data.memories[0].text.includes('海南'),
    '最相关的那条应排在前面，实际: ' + data.memories[0].text
  )
})

await testAsync('无关的话捞不出记忆（避免硬提往事）', async () => {
  const data = await api.fetchMemories({ elderId: MEM_ELDER, q: '今天天气怎么样' })
  assert.equal(data.memories.length, 0, '不相干的问题不该捞出记忆')
})

group('③ 写入、复核与删除')

await testAsync('家人录入一条：直接可用且家属可见', async () => {
  const data = await api.fetchMemories({ elderId: MEM_ELDER })
  const before = data.count
  const request = await import('../uni-app/api/request.js')
  const created = await request.request({
    url: config.resolveURL(config.ENDPOINTS.memories),
    method: 'POST',
    data: { elderId: MEM_ELDER, kind: 'experience', text: '老人 2024 年搬过一次家', tags: ['搬家'] }
  })
  assert.equal(created.memory.visibleToFamily, true)
  assert.equal(created.memory.review, 'approved')
  const after = await api.fetchMemories({ elderId: MEM_ELDER })
  assert.equal(after.count, before + 1, '列表应多一条')
})

await testAsync('空内容被拒（老人不会看到半条记忆）', async () => {
  const request = await import('../uni-app/api/request.js')
  await assert.rejects(
    async () => {
      await request.request({
        url: config.resolveURL(config.ENDPOINTS.memories),
        method: 'POST',
        data: { elderId: MEM_ELDER, text: '   ' }
      })
    },
    // 端侧 reject 的是 { code, statusCode, message, retryable } 对象（不是 Error），
    // 而且 4xx 的 message 会被端侧改写成老人话术——所以断言口径是 code，不是文案
    (err) => {
      assert.equal(err.code, 'memory_empty')
      assert.equal(err.statusCode, 400)
      return true
    },
    '空内容必须报 memory_empty'
  )
})

await testAsync('单条删除生效，再删报"没找到"', async () => {
  const request = await import('../uni-app/api/request.js')
  const created = await request.request({
    url: config.resolveURL(config.ENDPOINTS.memories),
    method: 'POST',
    data: { elderId: MEM_ELDER, text: '这条马上要删掉' }
  })
  const removed = await api.deleteMemory(created.memory.id)
  assert.equal(removed.ok, true)
  await assert.rejects(
    async () => {
      await api.deleteMemory(created.memory.id)
    },
    (err) => {
      assert.equal(err.code, 'memory_not_found')
      assert.equal(err.statusCode, 404)
      assert.equal(err.retryable, false, '没找到就别让端侧给重试按钮')
      return true
    },
    '重复删除必须报 memory_not_found'
  )
})

group('④ 开关（默认关）与一键清空')

await testAsync('自动整理默认关闭，开启后记录同意时间', async () => {
  const before = await api.fetchMemorySettings({ elderId: MEM_ELDER })
  assert.equal(typeof before.settings.autoExtract, 'boolean')
  if (externalBase) {
    assert.equal(before.settings.autoExtract, false, '真服务上默认必须是关的')
  }
  const request = await import('../uni-app/api/request.js')
  const on = await request.request({
    url: config.resolveURL(config.ENDPOINTS.memorySettings),
    method: 'PUT',
    data: { elderId: MEM_ELDER, autoExtract: true }
  })
  assert.equal(on.settings.autoExtract, true)
  assert.ok(on.settings.consentedAt, '开启时该记下同意时间')
  await request.request({
    url: config.resolveURL(config.ENDPOINTS.memorySettings),
    method: 'PUT',
    data: { elderId: MEM_ELDER, autoExtract: false }
  })
})

await testAsync('L3 话题权重（主动关怀用）', async () => {
  const data = await api.fetchMemoryTopics({ elderId: MEM_ELDER, limit: 5 })
  assert.ok(Array.isArray(data.topics))
  if (data.topics.length) {
    assert.ok(data.topics[0].topic, '每个话题要有名字')
    assert.ok(data.topics[0].weight > 0)
  }
})

await testAsync('一键清空：真的清空（老人说忘掉就要忘掉）', async () => {
  const cleared = await api.clearMemories({ elderId: MEM_ELDER })
  assert.ok(cleared.removed >= 1, '至少清掉一条')
  const after = await api.fetchMemories({ elderId: MEM_ELDER, scope: 'all', includePending: true })
  assert.equal(after.count, 0, '清空后不该还有记忆')
})

// 收尾：先关 mock 再 finish（finish 只设 process.exitCode，不强制 exit——
// 强行 process.exit 会在 Windows 上撞 libuv 的 UV_HANDLE_CLOSING 断言）
if (mock) await mock.close()
finish()
