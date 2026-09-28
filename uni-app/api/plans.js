/**
 * 比邻AI · 康养计划接口（P1）
 *
 * 与对话接口分开是有意的：对话是流式、要打字效果；计划是一次性 JSON 请求，
 * 走 `request.js` 那套统一错误处理就够，不必让每个页面自己拼 URL 和错误文案。
 *
 * 契约见 `api/README.md` §六。老人端只会用到 today / checkin 两个，
 * 其余（draft / pending / confirm / reject / summary / adjust）是家属端与运营端的，
 * 二期做家人端时直接复用。
 */

import { ENDPOINTS, resolveURL } from './config.js'
import { request } from './request.js'

/** 今日计划与打卡状态（老人端日程页） */
export function fetchTodayPlan(params = {}) {
  const query = ['elderId=' + encodeURIComponent(params.elderId || 'e_1')]
  if (params.date) query.push('date=' + encodeURIComponent(params.date))
  return request({ url: resolveURL(ENDPOINTS.planToday) + '?' + query.join('&') })
}

/**
 * 打卡 / 取消打卡。
 * @param {object} params
 * @param {string} params.planItemId
 * @param {string} [params.elderId]
 * @param {boolean} [params.done]  false=取消打卡（老人点错了要能改）
 * @param {string} [params.date]
 */
export function submitCheckin(params) {
  return request({
    url: resolveURL(ENDPOINTS.planCheckin),
    method: 'POST',
    data: {
      planItemId: params.planItemId,
      elderId: params.elderId || 'e_1',
      date: params.date,
      done: params.done !== false,
      source: params.source || 'elder'
    }
  })
}

/** 完成率与调整建议（家属端） */
export function fetchPlanSummary(params = {}) {
  const query = ['elderId=' + encodeURIComponent(params.elderId || 'e_1')]
  if (params.days) query.push('days=' + params.days)
  return request({ url: resolveURL(ENDPOINTS.planSummary) + '?' + query.join('&') })
}

/** 待家属确认的计划（家属端） */
export function fetchPendingPlans(params = {}) {
  return request({
    url: resolveURL(ENDPOINTS.planPending) + '?elderId=' + encodeURIComponent(params.elderId || 'e_1')
  })
}

/** 生成计划草稿（家属端 / 康复师端；端侧暂未开放入口） */
export function createPlanDraft(params = {}) {
  return request({
    url: resolveURL(ENDPOINTS.planDraft),
    method: 'POST',
    data: {
      elderId: params.elderId || 'e_1',
      goal: params.goal || '',
      maxItems: params.maxItems,
      polish: params.polish !== false,
      submit: params.submit !== false
    }
  })
}

/** 家属确认 → 计划生效（这一步才结束旧计划） */
export function confirmPlan(params) {
  return request({
    url: resolveURL(ENDPOINTS.planConfirm),
    method: 'POST',
    data: { planId: params.planId, actor: params.actor || '家属' }
  })
}

export function rejectPlan(params) {
  return request({
    url: resolveURL(ENDPOINTS.planReject),
    method: 'POST',
    data: { planId: params.planId, reason: params.reason || '', actor: params.actor || '家属' }
  })
}

export function fetchPlanHistory(params = {}) {
  return request({
    url: resolveURL(ENDPOINTS.planHistory) + '?elderId=' + encodeURIComponent(params.elderId || 'e_1')
  })
}

/** 老人档案（开发期是 3 个模拟档案） */
export function fetchElders() {
  return request({ url: resolveURL(ENDPOINTS.elders) })
}
