/**
 * 比邻AI · 提醒接口（P1）
 *
 * 老人端只用得到两个：拉收件箱、回执已看到。
 * 剩下的（任务追溯、调度器状态、手动 tick）是运营/联调用的，端侧不碰。
 */

import { ENDPOINTS, resolveURL } from './config.js'
import { request } from './request.js'

/**
 * 拉未读提醒（已投递、还没被看到过）。
 * @param {object} params
 * @param {string} [params.elderId]
 */
export function fetchReminderInbox(params = {}) {
  return request({
    url: resolveURL(ENDPOINTS.reminderInbox) + '?elderId=' + encodeURIComponent(params.elderId || 'e_1')
  })
}

/**
 * 回执：老人看到了。不传 taskId 表示整个收件箱都看过了。
 */
export function markReminderRead(params = {}) {
  return request({
    url: resolveURL(ENDPOINTS.reminderRead),
    method: 'POST',
    data: {
      elderId: params.elderId || 'e_1',
      taskId: params.taskId || undefined
    }
  })
}

/** 提醒任务与状态（可追溯：发没发、什么时候发的、老人打没打卡） */
export function fetchReminderTasks(params = {}) {
  const query = ['elderId=' + encodeURIComponent(params.elderId || 'e_1')]
  if (params.date) query.push('date=' + encodeURIComponent(params.date))
  return request({ url: resolveURL(ENDPOINTS.reminderTasks) + '?' + query.join('&') })
}

/** 调度器自检（通道、各状态任务数、下一条提醒时间） */
export function fetchSchedulerStatus() {
  return request({ url: resolveURL(ENDPOINTS.schedulerStatus) })
}

/**
 * 手动推进一次调度（联调/演示用）。服务端可用 SCHEDULER_MANUAL_TICK 关掉。
 * @param {string} [at] ISO 时间，例如 2026-09-24T08:00:00
 */
export function tickScheduler(at) {
  return request({
    url: resolveURL(ENDPOINTS.schedulerTick),
    method: 'POST',
    data: { at: at || undefined }
  })
}
