/**
 * 比邻AI · 提醒状态（老人端前台）
 *
 * 为什么是"前台轮询 + 顶部提醒条 + 震动"，而不是系统通知：
 * 系统通知需要厂商推送通道（uni-push / 极光 / 个推），**要开发者账号与资质、部分功能收费**，
 * 按仓库约定必须先用确认过才能接。在那之前，App 一打开就让老人看到"该吃药了"，
 * 比"什么都没有"强得多；真接了推送通道之后，这里就是"双保险"的第二条腿。
 *
 * 几个刻意的选择：
 * - **不弹模态框**：老人可能正在看别的东西，弹窗打断体验很差。震动 + 顶部条足够提醒，
 *   而且点一下就跳到日程页打卡
 * - **同一条提醒只震一次**：轮询会反复拉到同一条未读提醒，靠 shownIds 去重，
 *   否则每 30 秒震一下会把人烦死
 * - **拉取失败不打扰老人**：提醒属于"锦上添花"，网络不好时静默重试，不弹错误
 */

import { reactive } from 'vue'
import { fetchReminderInbox, markReminderRead } from '@/api/index.js'

export const DEFAULT_ELDER_ID = 'e_1'
const POLL_SECONDS = 30

export const reminder = reactive({
  elderId: DEFAULT_ELDER_ID,
  /** 当前展示的一条（顶部提醒条） */
  banner: null,
  /** 还没展示的队列 */
  queue: [],
  unread: 0,
  polling: false,
  lastError: '',
  lastPollAt: ''
})

let timer = null
const shownIds = {}
let ticking = false

/** 开启前台轮询（App 启动 / 回到前台时调） */
export function startPolling(elderId) {
  if (elderId) reminder.elderId = elderId
  if (timer) return
  reminder.polling = true
  poll()
  timer = setInterval(poll, POLL_SECONDS * 1000)
}

export function stopPolling() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
  reminder.polling = false
}

/** 立刻拉一次（页面 onShow、或者手动刷新） */
export function poll() {
  if (ticking) return Promise.resolve(reminder.unread)
  ticking = true
  return fetchReminderInbox({ elderId: reminder.elderId })
    .then((data) => {
      const tasks = (data && data.tasks) || []
      reminder.unread = tasks.length
      reminder.lastError = ''
      reminder.lastPollAt = new Date().toISOString()
      for (const task of tasks) {
        if (shownIds[task.id]) continue
        shownIds[task.id] = true
        reminder.queue.push(normalize(task))
      }
      pump()
      return reminder.unread
    })
    .catch((error) => {
      // 提醒拉不到就当没有，不打扰老人；下个周期再试
      reminder.lastError = (error && error.message) || ''
      return reminder.unread
    })
    .then((value) => {
      ticking = false
      return value
    })
}

/** 把队列里的下一条推到提醒条上 */
function pump() {
  if (reminder.banner || !reminder.queue.length) return
  reminder.banner = reminder.queue.shift()
  buzz(reminder.banner)
}

/** 老人点"知道了"：回执已看到，然后展示下一条 */
export function dismissBanner() {
  const current = reminder.banner
  reminder.banner = null
  if (current) {
    markReminderRead({ elderId: reminder.elderId, taskId: current.taskId }).catch(() => {})
    reminder.unread = Math.max(0, reminder.unread - 1)
  }
  pump()
}

/** 老人点提醒条本体：去日程页打卡（顺手回执已看到） */
export function openBanner() {
  const current = reminder.banner
  dismissBanner()
  uni.navigateTo({ url: '/pages/plans/plans' })
  return current
}

export function clearReminders() {
  reminder.banner = null
  reminder.queue = []
  reminder.unread = 0
  Object.keys(shownIds).forEach((key) => { delete shownIds[key] })
}

/* ------------------------------------------------------------------ 内部 */

function normalize(task) {
  const sendAt = String(task.sendAt || '')
  const time = sendAt.length >= 16 ? sendAt.slice(11, 16) : ''
  return {
    taskId: task.id,
    planItemId: task.planItemId,
    title: task.title || '',
    label: task.label || time,
    time,
    level: task.level || 'normal',
    levelLabel: task.levelLabel || '',
    strong: task.level === 'strong'
  }
}

/** 震动提醒（H5 等不支持的环境会静默失败，不影响逻辑） */
function buzz(item) {
  try {
    if (item.strong && typeof uni.vibrateLong === 'function') uni.vibrateLong()
    else if (typeof uni.vibrateShort === 'function') uni.vibrateShort()
  } catch (e) {
    // 震动不可用无所谓
  }
}

export default reminder
