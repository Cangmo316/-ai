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
    /** 复选框状态：记忆区的"从聊天自动整理"开关要用（真实浏览器里由 checked 决定） */
    checked: false,
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

// confirm/prompt 的返回值可以在用例里改：清空要验"二次确认点取消不生效"
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

// 记忆区的前置：mock 种子里有一条待复核（mem_4），复核用例要指名点它
const pendingMemories = await seed.pendingMemories('e_1')
assert.equal(pendingMemories.length, 1, '前置：mock 种子里应有一条待复核记忆')
const memoryPendingId = pendingMemories[0].id

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

group('③ 记忆区（渲染与点击）')

await testAsync('首屏：记忆列表渲染，且自动整理的（source=auto）一条都不出现', async () => {
  const html = document.getElementById('memory-list').innerHTML
  assert.ok(html.length > 0, '不该是空白')
  assert.match(html, /badge--kind/, '每条要显示种类标签')
  assert.match(html, /badge--source/, '每条要显示来源')
  assert.match(html, /badge--visible/, '每条要显示可见性')
  assert.match(html, /家里人填写|老人自己说的/, '来源要是中文')
  assert.ok(!html.includes('从聊天里整理'), 'i.e. 自动整理的记忆不许出现在家人列表')
  assert.match(html, /data-action="memory-delete"/, '每条要给删除按钮')
  assert.match(document.getElementById('memory-count').textContent, /^[0-9]+$/)
  assert.ok(Number(document.getElementById('memory-count').textContent) >= 2)
})

await testAsync('待复核区：显示复核按钮与说明（默认不进主列表）', async () => {
  const html = document.getElementById('memory-pending-list').innerHTML
  assert.match(html, /data-action="memory-approve"/, '缺通过按钮')
  assert.match(html, /data-action="memory-reject"/, '缺否决按钮')
  assert.match(html, /没经你确认前不会用来主动关心/, '要有一句人话说明为什么扣在这里')
  assert.match(html, /从聊天里整理/, '待复核的必然是自动整理出来的')
  assert.match(document.getElementById('memory-pending-count').textContent, /1/)
  assert.ok(
    !document.getElementById('memory-list').innerHTML.includes('data-action="memory-approve"'),
    '复核按钮只能在待复核区'
  )
})

await testAsync('自动整理开关：渲染成"默认关"，说明里点出要告知老人', async () => {
  assert.equal(document.getElementById('memory-auto-extract').checked, false)
  const hint = document.getElementById('memory-settings-hint').textContent
  assert.match(hint, /默认/)
  assert.match(hint, /告知/)
})

await testAsync('录入空内容：给中文提示，且不多出一条', async () => {
  document.getElementById('memory-text').value = '   '
  const before = Number(document.getElementById('memory-count').textContent)
  document.getElementById('btn-memory-add').listeners.click()
  assert.ok(await waitFor('memory-hint', '不能是空的'), '空内容要有中文提示')
  assert.equal(Number(document.getElementById('memory-count').textContent), before, '空提交不该多出一条')
})

await testAsync('录入提交：列表多一条，表单清空', async () => {
  const before = Number(document.getElementById('memory-count').textContent)
  document.getElementById('memory-kind').value = 'preference'
  document.getElementById('memory-text').value = '老人爱听评剧（界面自检写入）'
  document.getElementById('memory-tags').value = '戏曲, 评剧'
  document.getElementById('memory-happened-at').value = '2023年'
  document.getElementById('btn-memory-add').listeners.click()
  assert.ok(await waitFor('memory-list', '老人爱听评剧'), '提交后应出现在列表里')
  assert.equal(Number(document.getElementById('memory-count').textContent), before + 1)
  const html = document.getElementById('memory-list').innerHTML
  assert.match(html, /喜好/, '种类标签应跟着下拉框走')
  assert.match(html, /戏曲、评剧/, '标签要按中文顿号展示')
  assert.match(html, /2023年/)
  assert.equal(document.getElementById('memory-text').value, '', '提交成功要清空表单')

  // 清掉这条，免得影响后面的计数断言
  const created = (await seed.listMemories('e_1')).find((row) => row.text.includes('评剧（界面自检'))
  assert.ok(created, '应该能在接口里找到刚写进去的那条')
  await seed.deleteMemory(created.id)
  await document.getElementById('btn-refresh').listeners.click()
  assert.ok(await waitFor('memory-count', String(before)), '刷新后计数应回到提交前')
})

await testAsync('点「通过，可以用」→ 待复核少一条', async () => {
  const before = Number(document.getElementById('memory-pending-count').textContent)
  assert.ok(before >= 1, '前置：应有待复核条目')
  document.getElementById('memory-pending-list').listeners.click({
    target: {
      closest: (selector) =>
        selector.includes('button') ? { dataset: { action: 'memory-approve', id: memoryPendingId } } : null
    }
  })
  assert.ok(await waitFor('memory-pending-count', String(before - 1)), '通过后待复核数应减一')
})

await testAsync('点「删掉这条」→ 列表少一条', async () => {
  const created = await seed.addMemory('e_1', { text: '界面自检：马上要删掉的一条' })
  await document.getElementById('btn-refresh').listeners.click()
  assert.ok(await waitFor('memory-list', '马上要删掉的一条'), '刷新后应能看到它')
  const before = Number(document.getElementById('memory-count').textContent)
  document.getElementById('memory-list').listeners.click({
    target: {
      closest: (selector) =>
        selector.includes('button') ? { dataset: { action: 'memory-delete', id: created.memory.id } } : null
    }
  })
  assert.ok(await waitFor('memory-count', String(before - 1)), '删除后列表应少一条')
})

await testAsync('一键清空：二次确认点取消 → 不清', async () => {
  const before = Number(document.getElementById('memory-count').textContent)
  assert.ok(before >= 1)
  dialogs.confirm = false
  document.getElementById('btn-memory-clear').listeners.click()
  assert.ok(await waitFor('memory-hint', '已取消'), '取消要有反馈')
  assert.equal(Number(document.getElementById('memory-count').textContent), before, '取消了就不该清')
})

await testAsync('一键清空：确认后列表为空，开关状态不跟着被清', async () => {
  dialogs.confirm = true
  // 先打开开关：清空之后它必须还在（"忘掉内容"≠"撤回告知"）
  await seed.saveMemorySettings('e_1', true)
  await document.getElementById('btn-refresh').listeners.click()
  assert.ok(await waitFor('memory-settings-hint', '已开启'), '前置：开关应是开启状态')

  document.getElementById('btn-memory-clear').listeners.click()
  assert.ok(await waitFor('memory-hint', '已清空'), '清空要有反馈')
  assert.equal(Number(document.getElementById('memory-count').textContent), 0)
  assert.equal(Number(document.getElementById('memory-pending-count').textContent), 0)
  assert.equal(document.getElementById('memory-auto-extract').checked, true, '清空是忘掉内容，不是撤回告知')
  assert.equal((await seed.listMemories('e_1')).length, 0, '服务端也要真的空')
  const settings = await seed.memorySettings('e_1')
  assert.equal(settings.autoExtract, true)
  assert.ok(settings.consentedAt, '同意时间也要留着')
})

await testAsync('自动整理开关：打开会二次确认，并显示"已记录同意时间"', async () => {
  // 上一条用例刚把记忆清空，这里先打开开关（confirm 仍为 true）
  document.getElementById('memory-auto-extract').listeners.change({ target: { checked: true } })
  assert.ok(await waitFor('memory-hint', '已记录同意时间'), '开启要给出同意时间凭证')
  assert.equal(document.getElementById('memory-auto-extract').checked, true)
  assert.match(document.getElementById('memory-settings-hint').textContent, /已开启/)
  const settings = await seed.memorySettings('e_1')
  assert.equal(settings.autoExtract, true)
  assert.ok(settings.consentedAt)

  // 再点一次打开（模拟"关掉又打开"）：确认框点取消 → 开关保持原状，且服务端没被改
  dialogs.confirm = false
  document.getElementById('memory-auto-extract').listeners.change({ target: { checked: true } })
  assert.ok(await waitFor('memory-hint', '已取消这次改动'), '取消开启要有中文反馈')
  assert.equal(document.getElementById('memory-auto-extract').checked, true, '取消后勾选状态要跟着服务端')
  assert.equal((await seed.memorySettings('e_1')).autoExtract, true, '取消不该改服务端')
  dialogs.confirm = true
})

await testAsync('开关已经开着时点取消：不能把界面猜成"关着"', async () => {
  // 服务端是唯一事实来源：取消只取消"这次改动"，不该顺手把已开启的开关显示成关闭
  assert.equal((await seed.memorySettings('e_1')).autoExtract, true, '前置：服务端应还开着')
  dialogs.confirm = false
  document.getElementById('memory-auto-extract').listeners.change({ target: { checked: true } })
  assert.ok(await waitFor('memory-hint', '还是开着的'), '取消后要说清开关的真实状态')
  assert.equal(document.getElementById('memory-auto-extract').checked, true, '已开启的开关不能被取消动作关掉')
  dialogs.confirm = true
  // 收尾：关掉它，避免影响别的用例/别的老人
  await seed.saveMemorySettings('e_1', false)
})

await testAsync('记忆区出错时提示也是人话（不出现 undefined / [object Object]）', async () => {
  const hint = document.getElementById('memory-hint').textContent
  assert.ok(!hint.includes('undefined'), hint)
  assert.ok(!hint.includes('[object Object]'), hint)
  assert.ok(!/[A-Za-z]{6,}/.test(hint), hint)
})

await mock.close()
finish()
