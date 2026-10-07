/**
 * 比邻AI · 健康档案接口
 *
 * 契约见 server/app/api/health.py。要点：
 *  · 测量项定义（要填哪些字段、单位、参考区间）由 `GET /v1/health/types` 下发，
 *    端侧**不写死字段**——加一项新指标（比如尿酸）只改服务端一处
 *  · 数值存在 `values` 字典里，键由类型定义给出（血压是 systolic/diastolic/pulse）
 *  · 服务端是校验的唯一事实来源，端侧的即时校验只是提前反馈
 */

import { ENDPOINTS, resolveURL } from './config.js'
import { request } from './request.js'

function authHeader(token) {
  return token ? { Authorization: 'Bearer ' + token } : {}
}

/** 测量项定义（不需要登录：填表前先渲染表单） */
export function fetchHealthTypes() {
  return request({ url: resolveURL(ENDPOINTS.healthTypes) })
}

/** 我的健康记录（按测量时间倒序） */
export function fetchHealthRecords(token, itemType, limit) {
  const query = ['limit=' + encodeURIComponent(String(limit || 100))]
  if (itemType) query.push('itemType=' + encodeURIComponent(itemType))
  return request({
    url: resolveURL(ENDPOINTS.healthRecords) + '?' + query.join('&'),
    header: authHeader(token)
  })
}

/**
 * 记一条。
 * @param {object} params
 * @param {string} params.itemType 如 'bloodPressure'
 * @param {object} params.values   如 { systolic: 128, diastolic: 82, pulse: 72 }
 * @param {string} [params.measuredAt] 测量时间（不传用服务端当前时间）
 * @param {string} [params.note]
 */
export function addHealthRecord(token, params = {}) {
  return request({
    url: resolveURL(ENDPOINTS.healthRecords),
    method: 'POST',
    header: authHeader(token),
    data: {
      itemType: params.itemType || '',
      values: params.values || {},
      measuredAt: params.measuredAt || '',
      note: params.note || '',
      source: params.source || 'manual'
    }
  })
}

/** 删一条（填错了） */
export function deleteHealthRecord(token, recordId) {
  return request({
    url: resolveURL(ENDPOINTS.healthRecords) + '/' + encodeURIComponent(recordId || ''),
    method: 'DELETE',
    header: authHeader(token)
  })
}

/** 概览：每项最近一条 + 条数（页面顶部卡片用） */
export function fetchHealthSummary(token) {
  return request({
    url: resolveURL(ENDPOINTS.healthSummary),
    header: authHeader(token)
  })
}
