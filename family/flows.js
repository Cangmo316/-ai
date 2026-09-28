/**
 * 比邻AI · 家人端业务流程（不碰 DOM，可在 node 里直接测）
 *
 * 与老人端共用同一份接口客户端（`uni-app/api/plans.js`），所以契约只有一处实现：
 * 家人端一旦跑通，反过来也证明那层 api 是前端无关的。
 *
 * **隐私边界（设计方案 §3.4）**：子女端默认可见的是**计划完成率**，
 * **看不到聊天原文**。所以这里全部流程都只碰计划/打卡/提醒接口，
 * 一个读会话历史的调用都没有——不是"忘了做"，是刻意不做。
 */

import {
  confirmPlan,
  createPlanDraft,
  fetchElders,
  fetchPendingPlans,
  fetchPlanHistory,
  fetchPlanSummary,
  fetchTodayPlan,
  rejectPlan
} from '../uni-app/api/plans.js'
import { fetchReminderTasks, fetchSchedulerStatus, tickScheduler } from '../uni-app/api/reminders.js'
import { request } from '../uni-app/api/request.js'
import { ENDPOINTS, resolveURL, setApiToken, setBaseURL } from '../uni-app/api/config.js'
import { installUniShim } from './uni-shim.js'

/**
 * @param {object} options
 * @param {string} [options.baseURL]  后端地址（默认沿用 api/config.js 里的默认值）
 * @param {string} [options.token]    服务端开了鉴权时需要
 */
export function createFamilyFlows(options = {}) {
  installUniShim()
  if (options.baseURL) setBaseURL(options.baseURL)
  if (options.token !== undefined) setApiToken(options.token || '')

  return {
    /** 老人列表（开发期是 3 个模拟档案） */
    listElders() {
      return fetchElders().then((data) => data.elders || [])
    },

    /** 待确认的计划（家属确认闸门就在这一步） */
    listPending(elderId) {
      return fetchPendingPlans({ elderId }).then((data) => data.plans || [])
    },

    /** 生成计划草稿并提交确认（等同运营/家属"发起一份计划"） */
    createDraft(elderId, extra = {}) {
      return createPlanDraft(Object.assign({ elderId, polish: true }, extra))
    },

    /** 确认 → 生效（旧计划在这一刻结束） */
    confirm(planId, actor = '家人') {
      return confirmPlan({ planId, actor })
    },

    /** 驳回 */
    reject(planId, reason = '', actor = '家人') {
      return rejectPlan({ planId, reason, actor })
    },

    /** 今日计划与打卡状态（老人端看的是同一份数据） */
    today(elderId) {
      return fetchTodayPlan({ elderId })
    },

    /** 完成率与调整建议 */
    summary(elderId, days = 7) {
      return fetchPlanSummary({ elderId, days })
    },

    /** 转入调整（等家属确认后才真的改计划） */
    requestAdjust(planId, reason = '') {
      return request({
        url: resolveURL(ENDPOINTS.planAdjust),
        method: 'POST',
        data: { planId, actor: '家人', reason }
      })
    },

    /** 计划历史（谁在什么时候确认的） */
    history(elderId) {
      return fetchPlanHistory({ elderId }).then((data) => data.plans || [])
    },

    /** 提醒任务（发没发、打没打卡——可追溯，但不含聊天内容） */
    reminders(elderId) {
      return fetchReminderTasks({ elderId }).then((data) => data.tasks || [])
    },

    schedulerStatus() {
      return fetchSchedulerStatus()
    },

    /** 联调用：手动推进调度（生产环境会被服务端关掉） */
    tick(at) {
      return tickScheduler(at)
    }
  }
}

/**
 * 把计划项整理成家人看得懂的一行文案。
 * 依据（来源 + 版本 + 条目 id）必须露出来——设计方案要求"计划项落库时同步存依据，家属端可见"，
 * 家属看到"这条是照哪份指南来的"才会放心点确认。
 */
export function describeItem(item) {
  return {
    time: item.time || '',
    type: item.type || '',
    title: item.title || '',
    detail: item.detail || '',
    freq: item.freq || '',
    strong: !!item.strongRemind,
    done: !!item.done,
    source: (item.basis && (item.basis.sourceName || item.basis.source)) || '',
    basis: (item.basis && item.basis.text) || '',
    boundary: (item.basis && item.basis.boundary) || ''
  }
}

/** 完成率文案（大数字 + 一句人话，别让家属去算百分比） */
export function describeRate(stats) {
  if (!stats) return { percent: 0, text: '还没有数据' }
  const percent = Math.round((stats.rate || 0) * 100)
  let text = '最近 ' + stats.days + ' 天完成了 ' + stats.done + '/' + stats.expected + ' 次'
  if (percent >= 80) text += '，做得挺好'
  else if (percent >= 50) text += '，还行，有空可以提醒两句'
  else text += '，漏得比较多，建议看看是不是提醒时间不合适'
  return { percent, text }
}

/**
 * 计划状态怎么跟家属解释（状态机见 server/app/plan/models.py）。
 *
 * 最容易被误解的一条：**`adjusting` 仍然在执行**——调整期间原计划照旧提醒，
 * 不存在"提醒真空"。不解释清楚，家属会以为点了"需要调整"老人就没人提醒了。
 */
export function describePlanStatus(plan) {
  const status = (plan && plan.status) || ''
  const label = (plan && plan.statusLabel) || ''
  const executing = status === 'active' || status === 'adjusting'
  const hints = {
    draft: '还没提交，老人那边看不到',
    pending_confirm: '还没生效：老人看不到、也收不到任何提醒',
    active: '正在按时间提醒',
    adjusting: '调整期间这份计划**仍然在执行**（不会出现提醒真空），确认新计划后才替换',
    ended: '已结束（被新计划替代）',
    rejected: '家属驳回了，没有生效'
  }
  return { status, label, executing, hint: hints[status] || '' }
}

export default createFamilyFlows
