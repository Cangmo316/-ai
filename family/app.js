/**
 * 比邻AI · 家人端页面逻辑
 *
 * 只做三件事，别的都不做（家人端最小版）：
 *   1. 看：待确认的计划（含**依据**）、当前生效计划与打卡、完成率
 *   2. 定：确认 / 驳回 / 生成新计划 / 转入调整
 *   3. 查：提醒到底发出去没有（区分"发了但他没做"与"根本没送到"）
 *
 * ⚠️ 刻意不读会话历史：默认授权下子女端"可见完成率、不可见聊天原文"（设计方案 §3.4）。
 * 想加"看聊天"，得先有老人授权与 consent 记录，不能顺手加。
 */

import { createFamilyFlows, describeItem, describePlanStatus, describeRate } from './flows.js'
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
    const elders = await flows.listElders()
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
    const [pending, today, summary, tasks, scheduler, history] = await Promise.all([
      flows.listPending(elderId).catch(() => []),
      flows.today(elderId).catch(() => null),
      flows.summary(elderId).catch(() => null),
      flows.reminders(elderId).catch(() => []),
      flows.schedulerStatus().catch(() => null),
      flows.history(elderId).catch(() => [])
    ])
    renderPending(pending)
    renderToday(today)
    renderSummary(summary)
    renderReminders(tasks)
    renderHistory(history)
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
        '<strong>' + esc(plan.elderName || elderId) + '</strong>' +
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
  await act(
    () => flows.tick(new Date().toISOString().slice(0, 19)),
    '已手动推进一次调度（仅联调用，生产环境这个接口会被关掉）。'
  )
}

async function act(run, successText) {
  const hint = el('conn-hint')
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

prefill()
connect()
