#!/usr/bin/env node
/**
 * 比邻AI · 家人端页面渲染冒烟测试（零依赖，自带极简 DOM 垫片）
 *
 *   node tools/test-family-ui.mjs
 *
 * 为什么要有这个：家人端是浏览器页面，我没有浏览器可以截图，
 * 于是给它一个几十行的 DOM 垫片，把真实渲染路径跑一遍。
 * 它能抓住的是最实际的一类 bug：**渲染函数里的拼写错误、读到 undefined 的字段、
 * 事件委托的 data-action 写错**——这些在浏览器里就是白屏或点了没反应，很难靠读代码发现。
 *
 * ⚠️ 它不替代真机/真浏览器验收：样式、布局、点击手感的最终确认还得靠人看。
 */

import assert from 'node:assert/strict'
import { finish, group, sleep, testAsync } from './test-util.mjs'
import { startMockServer } from './mock-server.mjs'
import { installUniShim } from '../family/uni-shim.js'

/* ------------------------------------------------------------ 极简 DOM 垫片 */

function makeElement(id) {
  return {
    id,
    innerHTML: '',
    textContent: '',
    value: '',
    dataset: {},
    listeners: {},
    addEventListener(type, handler) {
      this.listeners[type] = handler
    },
    /** 事件委托用：让 button[data-action] 选择器能匹配到自己 */
    closest(selector) {
      return selector.includes('button') && this.dataset && this.dataset.action ? this : null
    }
  }
}

const elements = new Map()
const document = {
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, makeElement(id))
    return elements.get(id)
  }
}

const dialogs = { confirm: true, prompt: '早上太早' }
const window = {
  confirm: () => dialogs.confirm,
  prompt: () => dialogs.prompt
}

globalThis.document = document
globalThis.window = window

/** 等某个元素的内容出现关键字（渲染是异步的；提示语写在 textContent，列表写在 innerHTML） */
async function waitFor(id, needle, timeoutMs = 4000) {
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    const node = document.getElementById(id)
    if (node.innerHTML.includes(needle) || String(node.textContent).includes(needle)) return true
    await sleep(30)
  }
  return false
}

/* ------------------------------------------------------------ 环境 */

// uni 垫片必须在 app.js 之前装好：它启动时就会读 baseURL 与 token
installUniShim()
const TOKEN = 'family-ui-token-abc123'
const mock = await startMockServer({ port: 0, delayMs: 0, authToken: TOKEN })
const baseURL = 'http://127.0.0.1:' + mock.port
console.log('联调目标: ' + baseURL + '（内置 mock）')

// 预置好连接信息：app.js 启动时会自动连接
const { setApiToken, setBaseURL } = await import('../uni-app/api/config.js')
setBaseURL(baseURL)
setApiToken(TOKEN)

// 预置一份待确认计划（点"生成"那条路也顺便验证过了）
const { createFamilyFlows } = await import('../family/flows.js')
const seed = createFamilyFlows({ baseURL, token: TOKEN })
await seed.createDraft('e_1')
const pendingBefore = await seed.listPending('e_1')
assert.equal(pendingBefore.length, 1, '前置：应该有一份待确认计划')
const pendingId = pendingBefore[0].id

// 真正加载页面脚本（会自己 connect + 首次渲染）
await import('../family/app.js')
assert.ok(await waitFor('conn-hint', '已连接'), '页面应该自动连上并刷新：' + document.getElementById('conn-hint').textContent)

/* ------------------------------------------------------------ 断言 */

group('① 首屏渲染（真实渲染路径）')

await testAsync('待确认计划：标题、依据、两个操作按钮都在', async () => {
  const html = document.getElementById('pending-list').innerHTML
  assert.match(html, /等家里人确认/, '状态标签应展示')
  assert.match(html, /依据：/, '依据必须渲染出来')
  assert.match(html, /国家基本公共卫生服务规范|中国居民膳食指南|ICOPE/, '依据里应有来源名')
  assert.match(html, /data-action="confirm"/, '缺确认按钮')
  assert.match(html, /data-action="reject"/, '缺驳回按钮')
  assert.match(document.getElementById('pending-count').textContent, /1/)
})

await testAsync('当前生效计划：状态、今日完成数、调整入口', async () => {
  const html = document.getElementById('today-box').innerHTML
  assert.match(html, /今天 \d+\/\d+ 项已完成/)
  assert.match(html, /正在执行/)
  assert.match(html, /data-action="adjust"/, '生效计划应能发起调整')
})

await testAsync('完成率：百分比与建议都渲染出来（suggestion 是对象，不能渲染成 [object Object]）', async () => {
  const html = document.getElementById('summary-box').innerHTML
  assert.match(html, /%/)
  assert.ok(!html.includes('[object Object]'), '对象没被正确取值')
  assert.match(html, /建议：|最近 \d+ 天/)
})

await testAsync('计划历史有表格行，且已确认的计划显示确认时间', async () => {
  const html = document.getElementById('history-box').innerHTML
  assert.match(html, /<table/)
  assert.match(html, /plan_mock_1/)
})

await testAsync('提醒追溯表能渲染（没有记录时给出解释而不是空白）', async () => {
  const html = document.getElementById('reminder-box').innerHTML
  assert.ok(html.length > 0, '不该是空白')
  assert.ok(html.includes('<table') || html.includes('还没有提醒记录'))
})

group('② 事件委托真的能点')

await testAsync('点「确认并开始执行」→ 计划生效，列表清空', async () => {
  const list = document.getElementById('pending-list')
  const handler = list.listeners.click
  assert.ok(handler, '待确认列表必须绑定了 click')
  handler({
    target: {
      closest: (selector) => (selector.includes('button') ? { dataset: { action: 'confirm', plan: pendingId } } : null)
    }
  })
  assert.ok(await waitFor('pending-count', '0'), '确认后待确认数量应变成 0')
  const today = await seed.today('e_1')
  assert.equal(today.planId, pendingId, '确认的计划应该生效')
})

await testAsync('点「这份计划需要调整」→ 转入调整中，按钮消失', async () => {
  // 重新渲染一次拿到最新的 today-box（含 adjust 按钮）
  await seed.createDraft('e_1')
  const draft = (await seed.listPending('e_1'))[0]
  await seed.confirm(draft.id, '女儿')
  await document.getElementById('btn-refresh').listeners.click()
  assert.ok(await waitFor('today-box', 'data-action="adjust"'), '刷新后应有调整按钮')

  const box = document.getElementById('today-box')
  box.listeners.click({
    target: { closest: (selector) => (selector.includes('button') ? { dataset: { action: 'adjust', plan: draft.id } } : null) }
  })
  assert.ok(await waitFor('today-box', '已转入调整'), '调整后应出现调整中的说明')
  const today = await seed.today('e_1')
  assert.equal(today.status, 'adjusting')
  assert.equal(today.planId, draft.id, '调整中仍是同一份计划')
})

await testAsync('出错时提示是人话（不是 undefined / [object Object]）', async () => {
  const hint = document.getElementById('conn-hint').textContent
  assert.ok(!hint.includes('undefined'), hint)
  assert.ok(!hint.includes('[object Object]'), hint)
})

await mock.close()
finish()
