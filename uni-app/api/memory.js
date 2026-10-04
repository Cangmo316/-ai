/**
 * 比邻AI · 三层记忆接口（P2）
 *
 * 三层里的 L1 是健康档案（`fetchElders`），这里管的是：
 *   L2 经历事件——"2023 年儿子带我去过海南"
 *   L3 兴趣偏好——"爱听戏""喜欢下棋"
 *
 * ⚠️ **端侧只读，不写**。写入只有两条路：
 *   1. 家属在家人端录入（`family/` 那套，用同一份接口）
 *   2. 对话里自动整理，且必须家属先打开开关（`autoExtract`，默认关）
 * 老人端之所以不给写权限：记忆一旦能被 App 直接改，就绕过了"家属确认"这道产品闸门。
 *
 * ⚠️ **默认不展示自动整理出来的记忆**：服务端在 `scope=family` 下只回家属可见的条目，
 * 端侧照默认口径取即可，不要自己拼 `includePending` 去翻待复核内容。
 */

import { ENDPOINTS, resolveURL } from './config.js'
import { request } from './request.js'

/**
 * 记忆列表 / 检索
 * @param {object} [params]
 * @param {string} [params.elderId]
 * @param {string} [params.kind] experience | preference | profile
 * @param {string} [params.q] 有值时走相关性检索（返回带 score）
 * @param {string} [params.scope] family（默认，只看家属可见）| all（老人端自查）
 */
export function fetchMemories(params = {}) {
  const query = []
  query.push('elderId=' + encodeURIComponent(params.elderId || 'e_1'))
  if (params.kind) query.push('kind=' + encodeURIComponent(params.kind))
  if (params.q) query.push('q=' + encodeURIComponent(params.q))
  if (params.scope) query.push('scope=' + encodeURIComponent(params.scope))
  return request({ url: resolveURL(ENDPOINTS.memories) + '?' + query.join('&') })
}

/** L3 用法：这位老人能聊什么（按偏好权重排序），给"今天聊点啥"用 */
export function fetchMemoryTopics(params = {}) {
  return request({
    url:
      resolveURL(ENDPOINTS.memoryTopics) +
      '?elderId=' +
      encodeURIComponent(params.elderId || 'e_1') +
      (params.limit ? '&limit=' + params.limit : '')
  })
}

/** 自动整理的开关状态（默认关。老人端只读展示，改由家人端操作） */
export function fetchMemorySettings(params = {}) {
  return request({
    url: resolveURL(ENDPOINTS.memorySettings) + '?elderId=' + encodeURIComponent(params.elderId || 'e_1')
  })
}

/** 单条删除（方案要求：记忆库支持单条删除，老人/家属都该能删） */
export function deleteMemory(id) {
  return request({
    url: resolveURL(ENDPOINTS.memories) + '/' + encodeURIComponent(id),
    method: 'DELETE'
  })
}

/** 一键清空：把这位老人的记忆全删掉（设置保留） */
export function clearMemories(params = {}) {
  return request({
    url: resolveURL(ENDPOINTS.memoryClear),
    method: 'POST',
    data: { elderId: params.elderId || 'e_1' }
  })
}
