/**
 * 比邻AI · 家人端页面逻辑
 *
 * 只做四件事，别的都不做（家人端最小版）：
 *   1. 看：待确认的计划（含**依据**）、当前生效计划与打卡、完成率
 *   2. 定：确认 / 驳回 / 生成新计划 / 转入调整
 *   3. 查：提醒到底发出去没有（区分"发了但他没做"与"根本没送到"）
 *   4. 记：记忆（L2 经历 / L3 偏好）的录入、复核、删除、清空与自动整理开关
 *
 * ⚠️ 刻意不读会话历史：默认授权下子女端"可见完成率、不可见聊天原文"（设计方案 §3.4）。
 * 想加"看聊天"，得先有老人授权与 consent 记录，不能顺手加。
 * 记忆区同理：家属能看到"智能体整理出的那句话"（且要复核），但看不到聊天原文。
 */

import {
  createFamilyFlows,
  describeItem,
  describeMemory,
  describeMemorySettings,
  describePlanStatus,
  describeRate,
  describeReviewHint,
  nextReminderAt
} from './flows.js'
import { getApiToken, getBaseURL } from '../uni-app/api/config.js'

const el = (id) => document.getElementById(id)
const esc = (text) =>
  String(text === undefined || text === null ? '' : text).replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[ch]))

let flows = null
let elderId = 'e_1'
let busy = false
/** 老人列表：用来把 elderId 显示成人名——计划接口返回的对象里没有 elderName */
let elders = []

/** elderId → 显示名。查不到才退回 id，绝不把裸 id 当名字展示给家属 */
function elderName(id) {
  const found = elders.find((item) => item.id === id)
  return (found && (found.name || found.id)) || id || ''
}

/* ------------------------------------------------------------------ 连接 */

function prefill() {
  el('base-url').value = getBaseURL()
  el('api-token').value = getApiToken()
}

async function connect() {
  el('conn-hint').textContent = '正在连接…'
  try {
    flows = createFamilyFlows({
      baseURL: el('base-url').value.trim(),
      token: el('api-token').value.trim()
    })
    elders = await flows.listElders()
    const select = el('elder-select')
    select.innerHTML = elders
      .map(
        (elder) =>
          '<option value="' + esc(elder.id) + '">' + esc(elder.name || elder.id) +
          '（' + esc(elder.age || '') + (elder.age ? '岁' : '') + '）</option>'
      )
      .join('')
    if (elders.length) {
      elderId = elders[0].id
      select.value = elderId
    }
    el('conn-hint').textContent = '已连接 ' + getBaseURL() + '，共 ' + elders.length + ' 位老人。'
    await refresh()
  } catch (error) {
    el('conn-hint').textContent = '连接失败：' + (error.message || '未知原因')
  }
}

/* ------------------------------------------------------------------ 刷新 */

async function refresh() {
  if (!flows || busy) return
  busy = true
  try {
    const [pending, today, summary, tasks, scheduler, history, memories, pendingMemories, memorySettings] =
      await Promise.all([
        flows.listPending(elderId).catch(() => []),
        flows.today(elderId).catch(() => null),
        flows.summary(elderId).catch(() => null),
        flows.reminders(elderId).catch(() => []),
        flows.schedulerStatus().catch(() => null),
        flows.history(elderId).catch(() => []),
        flows.listMemories(elderId).catch(() => []),
        flows.pendingMemories(elderId).catch(() => []),
        flows.memorySettings(elderId).catch(() => null)
      ])
    renderPending(pending)
    renderToday(today)
    renderSummary(summary)
    renderReminders(tasks)
    renderHistory(history)
    renderMemories(memories, pendingMemories, memorySettings)
    el('scheduler-hint').textContent = scheduler
      ? '调度器 ' + (scheduler.running ? '运行中' : '未运行') +
        '（这决定了提醒会不会自动投递）'
      : ''
  } finally {
    busy = false
  }
}

/* ------------------------------------------------------------------ 渲染 */

function renderPending(plans) {
  el('pending-count').textContent = String(plans.length)
  if (!plans.length) {
    el('pending-list').innerHTML =
      '<p class="empty">没有待确认的计划。当前生效的计划会继续执行，不会因为这里空着就停掉。</p>'
    return
  }
  el('pending-list').innerHTML = plans
    .map((plan) => {
      const items = (plan.items || []).map((raw) => {
        const item = describeItem(raw)
        return (
          '<li class="item">' +
          '<div class="item__head"><span class="item__time">' + esc(item.time) + '</span>' +
          '<span class="item__type">' + esc(item.type) + '</span>' +
          '<span class="item__title">' + esc(item.title) + '</span></div>' +
          (item.detail ? '<div class="item__detail">' + esc(item.detail) + '</div>' : '') +
          (item.freq ? '<div class="item__meta">频率：' + esc(item.freq) + '</div>' : '') +
          (item.basis ? '<div class="item__basis">依据：' + esc(item.basis) + '</div>' : '') +
          (item.boundary ? '<div class="item__boundary">边界：' + esc(item.boundary) + '</div>' : '') +
          '</li>'
        )
      }).join('')

      return (
        '<article class="plan">' +
        '<div class="plan__head">' +
        '<strong>' + esc(plan.elderName || elderName(plan.elderId || elderId)) + '</strong>' +
        '<span class="badge badge--pending">' + esc(plan.statusLabel || '待家属确认') + '</span>' +
        '<span class="plan__time">生成于 ' + esc((plan.createdAt || '').replace('T', ' ').slice(0, 16)) + '</span>' +
        '</div>' +
        (plan.summary ? '<p class="plan__summary">' + esc(plan.summary) + '</p>' : '') +
        '<ul class="items">' + items + '</ul>' +
        '<div class="plan__actions">' +
        '<button class="btn btn--primary" data-action="confirm" data-plan="' + esc(plan.id) + '">确认并开始执行</button>' +
        '<button class="btn" data-action="reject" data-plan="' + esc(plan.id) + '">先不执行（驳回）</button>' +
        '</div>' +
        '<p class="hint">确认后：这份计划立即生效，上一份计划同时结束（不会两份同时提醒）。</p>' +
        '</article>'
      )
    })
    .join('')
}

function renderToday(today) {
  if (!today || !today.planId) {
    el('today-box').innerHTML = '<p class="empty">这位老人目前没有生效的计划。点上面的「按知识库生成一份计划」，确认后就有了。</p>'
    return
  }
  const state = describePlanStatus(today)
  const items = (today.items || [])
    .map((raw) => {
      const item = describeItem(raw)
      return (
        '<li class="item item--today">' +
        '<div class="item__head"><span class="item__time">' + esc(item.time) + '</span>' +
        '<span class="item__type">' + esc(item.type) + '</span>' +
        '<span class="item__title">' + esc(item.title) + '</span>' +
        '<span class="badge ' + (item.done ? 'badge--done' : 'badge--todo') + '">' +
        (item.done ? '已打卡' : '待完成') + '</span></div>' +
        '</li>'
      )
    })
    .join('')
  el('today-box').innerHTML =
    '<p class="box__lead"><strong>' + esc(state.label || '正在执行') + '</strong>（' + esc(today.date) + '）' +
    '· 今天 ' + today.done + '/' + today.total + ' 项已完成</p>' +
    (state.hint ? '<p class="hint">' + esc(state.hint) + '</p>' : '') +
    '<ul class="items">' + items + '</ul>' +
    (state.status === 'active'
      ? '<div class="plan__actions">' +
        '<button class="btn" data-action="adjust" data-plan="' + esc(today.planId) + '">这份计划需要调整</button>' +
        '</div>' +
        '<p class="hint">「需要调整」只是把它标成调整中——**它仍在执行**，等新计划确认后才替换。</p>'
      : state.status === 'adjusting'
        ? '<p class="hint">已转入调整：点上面的「按知识库生成一份计划」，确认后替换掉它（在那之前它一直有效）。</p>'
        : '')
}

function renderHistory(plans) {
  if (!plans.length) {
    el('history-box').innerHTML = '<p class="empty">还没有计划记录。</p>'
    return
  }
  el('history-box').innerHTML =
    '<table class="table"><thead><tr><th>计划</th><th>状态</th><th>生成时间</th><th>确认时间</th><th>项数</th></tr></thead><tbody>' +
    plans
      .map((plan) => {
        const state = describePlanStatus(plan)
        return (
          '<tr><td>' + esc(plan.id) + '</td>' +
          '<td>' + esc(state.label) + '</td>' +
          '<td>' + esc((plan.createdAt || '').replace('T', ' ').slice(0, 16)) + '</td>' +
          '<td>' + esc(plan.confirmedAt ? plan.confirmedAt.replace('T', ' ').slice(0, 16) : '—') + '</td>' +
          '<td>' + esc(plan.items) + '</td></tr>'
        )
      })
      .join('') +
    '</tbody></table>' +
    '<p class="hint">用于核对"这份计划是谁在什么时候定的"。审计详情在每个计划的 history 字段里。</p>'
}

function renderSummary(summary) {
  if (!summary) {
    el('summary-box').innerHTML = '<p class="empty">还没有完成情况的数据。</p>'
    return
  }
  const stats = summary.stats || summary
  const { percent, text } = describeRate(stats)
  const byType = (summary.byType || summary.by_type || [])
    .map((row) => esc(row.type) + ' ' + row.done + '/' + row.expected)
    .join(' · ')
  // 服务端返回的 suggestion 是对象（shouldAdjust / reasons / advice），不是字符串
  const suggestion = summary.suggestion || {}
  const advice = typeof suggestion === 'string' ? suggestion : suggestion.advice || ''
  const reasons = (suggestion.reasons || []).map((item) => '<li>' + esc(item) + '</li>').join('')
  el('summary-box').innerHTML =
    '<div class="rate"><span class="rate__num">' + percent + '%</span>' +
    '<span class="rate__text">' + esc(text) + '</span></div>' +
    (byType ? '<p class="hint">分类：' + byType + '</p>' : '') +
    (reasons ? '<ul class="reasons">' + reasons + '</ul>' : '') +
    (advice ? '<p class="box__lead">建议：' + esc(advice) + '</p>' : '')
}

function renderReminders(tasks) {
  if (!tasks.length) {
    el('reminder-box').innerHTML = '<p class="empty">今天还没有提醒记录。可能是没到时间，也可能是调度器没开。</p>'
    return
  }
  el('reminder-box').innerHTML =
    '<table class="table"><thead><tr><th>时间</th><th>内容</th><th>级别</th><th>状态</th><th>通道</th></tr></thead><tbody>' +
    tasks
      .map((task) =>
        '<tr><td>' + esc(task.sendAt ? task.sendAt.slice(11, 16) : '') +
        '</td><td>' + esc(task.title || '') +
        '</td><td>' + esc(task.levelLabel || task.level || '') +
        '</td><td>' + esc(task.statusLabel || task.status || '') +
        '</td><td>' + esc(task.channel || '-') + '</td></tr>'
      )
      .join('') +
    '</tbody></table>'
}

/* ------------------------------------------------------------------ 记忆渲染 */

/**
 * 记忆区一次渲染三块：主列表、待复核区、自动整理开关。
 *
 * 三个块的口径都不一样，所以拿到数据的人是调用方，不是这里：
 *   主列表 = `scope=family`（服务端已保证"家属可见 + 已复核"）
 *   待复核 = `scope=all&includePending=true` 再筛 `review=pending`
 * 这个区别是隐私边界本身（自动整理的默认家属不可见），不能在两处混用。
 */
function renderMemories(memories, pendingMemories, settings) {
  el('memory-count').textContent = String(memories.length)
  if (!memories.length) {
    el('memory-list').innerHTML =
      '<p class="empty">还没有家属可见的记忆。你可以在下面录一条（比如"2023 年去过海南""爱听评剧"），' +
      '智能体之后就会在合适的时候自然用上。</p>'
  } else {
    el('memory-list').innerHTML = memories
      .map((raw) => {
        const item = describeMemory(raw)
        return (
          '<article class="memory">' +
          '<div class="memory__head">' +
          '<span class="badge badge--kind">' + esc(item.kindText) + '</span>' +
          '<span class="badge badge--source">' + esc(item.sourceText) + '</span>' +
          '<span class="badge badge--visible">' +
          (item.visibleToFamily ? '家里人可见' : '仅老人自己可见') + '</span>' +
          (item.happenedAt ? '<span class="memory__when">' + esc(item.happenedAt) + '</span>' : '') +
          '</div>' +
          '<p class="memory__text">' + esc(item.text) + '</p>' +
          (item.tagText ? '<p class="memory__tags">标签：' + esc(item.tagText) + '</p>' : '') +
          '<div class="memory__actions">' +
          '<button class="btn btn--danger" data-action="memory-delete" data-id="' + esc(item.id) +
          '">删掉这条</button>' +
          '</div>' +
          '<p class="hint">' + esc(item.reviewText) +
          (item.createdText ? ' · 记于 ' + esc(item.createdText) : '') + '</p>' +
          '</article>'
        )
      })
      .join('')
  }

  el('memory-pending-count').textContent = String(pendingMemories.length)
  if (!pendingMemories.length) {
    el('memory-pending-list').innerHTML =
      '<p class="empty">没有待复核的记忆。' +
      '（自动整理默认是关的；就算开着，智能体没把握的内容才会进这里等你判断。）</p>'
  } else {
    el('memory-pending-list').innerHTML = pendingMemories
      .map((raw) => {
        const item = describeMemory(raw)
        const review = describeReviewHint(raw)
        return (
          '<article class="memory memory--pending">' +
          '<div class="memory__head">' +
          '<span class="badge badge--pending">' + esc(item.reviewText) + '</span>' +
          '<span class="badge badge--kind">' + esc(item.kindText) + '</span>' +
          '<span class="badge badge--source">' + esc(item.sourceText) + '</span>' +
          '</div>' +
          '<p class="memory__text">' + esc(review.text) + '</p>' +
          (item.tagText ? '<p class="memory__tags">标签：' + esc(item.tagText) + '</p>' : '') +
          '<p class="hint">' + esc(review.hint) + '</p>' +
          '<div class="memory__actions">' +
          '<button class="btn btn--primary" data-action="memory-approve" data-id="' + esc(item.id) +
          '">通过，可以用</button>' +
          '<button class="btn" data-action="memory-reject" data-id="' + esc(item.id) +
          '">否决，别用</button>' +
          '</div>' +
          '</article>'
        )
      })
      .join('')
  }

  const state = describeMemorySettings(settings)
  const checkbox = el('memory-auto-extract')
  // 服务端是唯一事实来源：勾选状态跟着它走（否则"界面显示开着、服务端其实关着"最误导人）
  if (checkbox) checkbox.checked = state.autoExtract
  el('memory-settings-hint').textContent = state.label + '：' + state.hint
}

/* ------------------------------------------------------------------ 动作 */

async function confirmPlan(planId) {
  if (!window.confirm('确认这份计划开始执行？老人会按上面的时间收到提醒。')) return
  await act(() => flows.confirm(planId), '已确认，计划开始执行。')
}

async function rejectPlan(planId) {
  const reason = window.prompt('驳回原因（会记在计划历史上，可以留空）：', '')
  if (reason === null) return
  await act(() => flows.reject(planId, reason), '已驳回，老人那边继续沿用原计划。')
}

async function createDraft() {
  await act(async () => {
    const result = await flows.createDraft(elderId)
    const plan = result.plan || result
    return '已生成草稿（' + (plan.items ? plan.items.length : 0) + ' 项），请在下面确认。'
  }, null)
}

async function requestAdjust(planId) {
  const reason = window.prompt('哪里不合适？（例如"早上太早，改到 9 点后"）', '')
  if (reason === null) return
  await act(
    () => flows.requestAdjust(planId, reason),
    '已转入调整中——这份计划仍在执行，生成并确认新计划后才会替换。'
  )
}

async function tick() {
  // 默认推进到"下一个提醒时间"：直接推当前时间往往会得到 0 条提醒，看起来像坏了
  const today = await flows.today(elderId).catch(() => null)
  const suggestion = nextReminderAt(today)
  const at = window.prompt(
    '推进到哪个时间？（计划项都是整天的时间点，推到下一项才能真正看到提醒）\n格式：2026-09-29T08:00:00',
    suggestion
  )
  if (at === null) return
  await act(
    () => flows.tick(at.trim() || suggestion),
    '已推进到 ' + (at.trim() || suggestion) + '（仅联调用，生产环境这个接口会被关掉）。'
  )
}

/* ------------------------------------------------------------------ 记忆动作 */

/** 标签输入：逗号/顿号/空格/分号都当分隔符——家属不会照着提示只打英文逗号 */
function parseTags(raw) {
  return String(raw || '')
    .split(/[,，、;；\s]+/)
    .map((tag) => tag.trim())
    .filter(Boolean)
}

/** 录入一条。空内容在 flows 层就被拦下（给的是人话提示），这里只负责把提示显示出来 */
async function addMemory() {
  const text = el('memory-text').value
  const payload = {
    kind: el('memory-kind').value,
    text,
    tags: parseTags(el('memory-tags').value),
    happenedAt: el('memory-happened-at').value.trim()
  }
  if (!String(text).trim()) {
    // 不跑一趟服务端：本地就能看出是空的，来回一趟才报错太钝
    el('memory-hint').textContent = '要记的内容不能是空的，写一句再提交'
    return
  }
  await act(async () => {
    const result = await flows.addMemory(elderId, payload)
    // 提交成功才清表单：失败时把家属刚写的东西留着，否则得重打一遍
    el('memory-text').value = ''
    el('memory-tags').value = ''
    el('memory-happened-at').value = ''
    return (result && result.notice) || '已记下来，之后对话里会自然用到'
  }, null, 'memory-hint')
}

async function approveMemory(id) {
  await act(() => flows.reviewMemory(id, true), '已通过，之后可以用它主动关心老人。', 'memory-hint')
}

async function rejectMemory(id) {
  await act(
    () => flows.reviewMemory(id, false),
    '已否决，智能体不会再使用这条（条目还留着，可以删掉）。',
    'memory-hint'
  )
}

async function removeMemory(id) {
  if (!window.confirm('删掉这条记忆？智能体之后不会再提到它。')) {
    el('memory-hint').textContent = '已取消，没有删。'
    return
  }
  await act(
    async () => {
      const result = await flows.deleteMemory(id)
      return (result && result.notice) || '已删除，对话里不会再提到它'
    },
    null,
    'memory-hint'
  )
}

async function clearAllMemories() {
  // 二次确认（产品要求）：一键清空是最不可逆的动作，必须让家属再看一眼要删多少条
  const total = el('memory-count').textContent
  const pending = el('memory-pending-count').textContent
  if (!window.confirm('清空这位老人的全部记忆（当前列表 ' + total + ' 条、待复核 ' + pending + ' 条）？删掉就没了。')) {
    el('memory-hint').textContent = '已取消，没有清空。'
    return
  }
  await act(
    async () => {
      const result = await flows.clearMemories(elderId)
      return '已清空 ' + ((result && result.removed) || 0) + ' 条记忆（自动整理开关保持原样）。'
    },
    null,
    'memory-hint'
  )
}

/**
 * 自动整理开关。
 *
 * 开启前必须让家属知道"这是在告诉老人我们要记录聊天内容"——这是产品红线（设计方案 §3.4），
 * 所以开启走一次确认；服务端会记下同意时间，页面把时间显示出来当凭证。
 */
async function toggleAutoExtract(event) {
  const on = !!(event && event.target && event.target.checked)
  if (on && !window.confirm('开启后智能体会从聊天里整理记忆，并且需要先明确告知老人（他随时可以让你关掉）。确认开启？')) {
    // 取消时**回服务端取真值**再回填勾选状态：服务端才是唯一事实来源，
    // 不能凭本地猜"取消 = 关着"（万一原本就是开的，猜错会让界面跟服务端不一致）
    const settings = await flows.memorySettings(elderId).catch(() => null)
    const stillOn = !!(settings && settings.autoExtract)
    el('memory-auto-extract').checked = stillOn
    el('memory-hint').textContent = stillOn
      ? '已取消这次改动，开关还是开着的。'
      : '已取消，开关保持关闭。'
    return
  }
  await act(
    async () => {
      const settings = await flows.saveMemorySettings(elderId, on)
      const state = describeMemorySettings(settings)
      return on
        ? '已开启' + (state.consentedAt ? '，已记录同意时间 ' + state.consentedAt : '，已记录同意时间')
        : '已关闭：不再新增，已入库的仍可单条删除或一键清空。'
    },
    null,
    'memory-hint'
  )
}

async function act(run, successText, hintId) {
  const hint = el(hintId || 'conn-hint')
  try {
    const result = await run()
    hint.textContent = successText || (typeof result === 'string' ? result : '完成。')
    await refresh()
  } catch (error) {
    // 服务端错误码表里的 message 就是给家属/老人看的人话，直接用
    hint.textContent = '操作失败：' + (error.message || '未知原因') +
      (error.retryable ? '（可以再试一次）' : '')
  }
}

/* ------------------------------------------------------------------ 绑定 */

el('btn-connect').addEventListener('click', connect)
el('btn-refresh').addEventListener('click', refresh)
el('btn-draft').addEventListener('click', createDraft)
el('btn-tick').addEventListener('click', tick)
el('elder-select').addEventListener('change', (event) => {
  elderId = event.target.value
  refresh()
})
el('pending-list').addEventListener('click', (event) => {
  const button = event.target.closest('button[data-action]')
  if (!button) return
  if (button.dataset.action === 'confirm') confirmPlan(button.dataset.plan)
  if (button.dataset.action === 'reject') rejectPlan(button.dataset.plan)
})
el('today-box').addEventListener('click', (event) => {
  const button = event.target.closest('button[data-action="adjust"]')
  if (button) requestAdjust(button.dataset.plan)
})
el('btn-memory-add').addEventListener('click', addMemory)
el('btn-memory-clear').addEventListener('click', clearAllMemories)
el('memory-auto-extract').addEventListener('change', toggleAutoExtract)
el('memory-list').addEventListener('click', (event) => {
  const button = event.target.closest('button[data-action="memory-delete"]')
  if (button) removeMemory(button.dataset.id)
})
el('memory-pending-list').addEventListener('click', (event) => {
  const button = event.target.closest('button[data-action]')
  if (!button) return
  if (button.dataset.action === 'memory-approve') approveMemory(button.dataset.id)
  if (button.dataset.action === 'memory-reject') rejectMemory(button.dataset.id)
})

prefill()
connect()
