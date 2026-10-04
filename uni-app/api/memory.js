/**
 * 比邻AI · 三层记忆接口（P2）
 *
 * 三层里的 L1 是健康档案（`fetchElders`），这里管的是：
 *   L2 经历事件——"2023 年儿子带我去过海南"
 *   L3 兴趣偏好——"爱听戏""喜欢下棋"
 *
 * ⚠️ **老人端页面（`uni-app/pages/**`）只读，写接口仅供家人端**。
 * 本文里的 `createMemory` / `reviewMemory` / `updateMemorySettings` / `deleteMemory` /
 * `clearMemories` 都**不许在老人端页面调用**——写入只有两条路：
 *   1. 家属在家人端录入（`family/flows.js` 走同一份接口）
 *   2. 对话里自动整理，且必须家属先打开开关（`autoExtract`，默认关）
 * 老人端之所以不给写权限：记忆一旦能被 App 直接改，就绕过了"家属确认"这道产品闸门。
 *
 * ⚠️ **默认不展示自动整理出来的记忆**：服务端在 `scope=family` 下只回家属可见的条目，
 * 端侧照默认口径取即可。家人端要看待复核的那几条（`scope=all` + `includePending=true`）
 * 只允许用在**复核区**那一处，别顺手拿它填主列表。
 */

import { ENDPOINTS, resolveURL } from './config.js'
import { request } from './request.js'

/**
 * 记忆列表 / 检索
 * @param {object} [params]
 * @param {string} [params.elderId]
 * @param {string} [params.kind] experience | preference | profile
 * @param {string} [params.q] 有值时走相关性检索（返回带 score）
 * @param {string} [params.scope] family（默认，只看家属可见）| all（老人端自查 / 家人端复核区）
 * @param {boolean} [params.includePending] 是否连待复核的一起返回。
 *   ⚠️ 在 `scope=family` 下**不起作用**：服务端的家属视图只含"已复核且家属可见"，
 *   所以看待复核必须配 `scope=all`（见 server/app/memory/models.py 的 `family_view`）
 */
export function fetchMemories(params = {}) {
  const query = []
  query.push('elderId=' + encodeURIComponent(params.elderId || 'e_1'))
  if (params.kind) query.push('kind=' + encodeURIComponent(params.kind))
  if (params.q) query.push('q=' + encodeURIComponent(params.q))
  if (params.scope) query.push('scope=' + encodeURIComponent(params.scope))
  // 只在显式要的时候才带上：多带一个参数就多一份"待复核内容被误用"的机会
  if (params.includePending) query.push('includePending=true')
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

/**
 * 自动整理的开关状态（默认关）
 *
 * `settings.consentedAt` 是**第一次开启**时服务端记下的同意时间；
 * 之后再关开关这个时间不会清掉——它是"曾经明确告知过本人"的凭证，将来要落 consent_record。
 * 老人端只读展示，改由家人端操作（见下方 updateMemorySettings 的注释）。
 */
export function fetchMemorySettings(params = {}) {
  return request({
    url: resolveURL(ENDPOINTS.memorySettings) + '?elderId=' + encodeURIComponent(params.elderId || 'e_1')
  })
}

/* ------------------------------------------------------------------ 以下只给家人端 */

/**
 * 录入一条记忆（**仅供家人端**，老人端 `uni-app/pages/**` 不许调用）
 *
 * 空内容必须由服务端拦住（`memory_empty`）；端侧也提前拦一道，
 * 但那只是体验优化，真正的口径以服务端为准。
 *
 * @param {object} params
 * @param {string} params.elderId
 * @param {string} params.kind    experience | preference | profile
 * @param {string} params.text    记忆正文
 * @param {string[]} [params.tags]
 * @param {string} [params.happenedAt] 事情发生的时间（"2023年""去年"这类模糊说法也照存）
 * @returns {Promise<{memory: object, notice: string}>}
 */
export function createMemory(params = {}) {
  return request({
    url: resolveURL(ENDPOINTS.memories),
    method: 'POST',
    data: {
      elderId: params.elderId || 'e_1',
      kind: params.kind || 'experience',
      text: params.text || '',
      tags: params.tags || [],
      happenedAt: params.happenedAt || ''
    }
  })
}

/**
 * 复核一条自动整理出来的记忆（**仅供家人端**）
 *
 * 为什么必须有这个动作：置信度低于 0.75 的自动整理结果会以 `review=pending` 入库，
 * 它们**不参与检索、不用于主动话题**，只等家属判断"这条记对了没有"。
 * 通过 → 可用（自动整理的仍然 `visibleToFamily=false`，家属看不到正文本身）；
 * 否决 → 保留痕迹但不再使用。
 *
 * @param {string} id
 * @param {boolean} approve true=通过，false=否决
 * @returns {Promise<{memory: object, notice: string}>}
 */
export function reviewMemory(id, approve = true) {
  return request({
    url: resolveURL(ENDPOINTS.memoryReview),
    method: 'POST',
    data: { id, approve: !!approve }
  })
}

/**
 * 改"从聊天里自动整理记忆"的开关（**仅供家人端**）
 *
 * 默认关。开启即视为**已明确告知本人**，服务端据此记 `consentedAt`
 * （设计方案原文："需明确告知并允许关闭"——默认开启就是没告知）。
 * 关闭只影响新增，已入库的仍可单条删除或一键清空。
 *
 * @param {object} params
 * @param {string} params.elderId
 * @param {boolean} params.autoExtract
 * @returns {Promise<{settings: object}>}
 */
export function updateMemorySettings(params = {}) {
  return request({
    url: resolveURL(ENDPOINTS.memorySettings),
    method: 'PUT',
    data: {
      elderId: params.elderId || 'e_1',
      autoExtract: !!params.autoExtract
    }
  })
}

/**
 * 单条删除（方案要求：记忆库支持单条删除，老人/家属都该能删）
 *
 * 端侧有意不区分调用方：老人端"忘掉这条"与家人端"删掉这条"是同一个动作，
 * 多一层角色判断反而容易漏。
 */
export function deleteMemory(id) {
  return request({
    url: resolveURL(ENDPOINTS.memories) + '/' + encodeURIComponent(id),
    method: 'DELETE'
  })
}

/**
 * 一键清空：把这位老人的记忆全删掉（设置保留，见 server/app/memory/models.py 的 `clear`）
 *
 * 保留设置是刻意的：清空是"忘掉内容"，不是"撤回告知"。
 */
export function clearMemories(params = {}) {
  return request({
    url: resolveURL(ENDPOINTS.memoryClear),
    method: 'POST',
    data: { elderId: params.elderId || 'e_1' }
  })
}
