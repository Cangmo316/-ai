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

/**
 * 本地通知的最小提前量（秒）。
 * 与 stores/push.js 的 MIN_LEAD_SECONDS 保持一致：太近的通知系统会直接丢弃，
 * 所以「今天还能不能跳过/关闭」的判定也用同一把尺子——本轮已经开始（含临界）就不许再改。
 */
export const MIN_LEAD_SECONDS = 30

/**
 * 今天这一轮是否**已经开始**（含临界：距开始不足 MIN_LEAD_SECONDS 也算已开始）。
 *
 * 用途：「跳过今天」「关闭今天」必须在本轮开始之前操作——提醒都发出去了，
 * 再跳过/关闭就没有意义了，所以这时不允许选今天。
 *
 * @param {object} item 计划（含 fromH / fromM）
 * @param {Date} [now]
 * @param {number} [leadSeconds] 提前量阈值，默认 MIN_LEAD_SECONDS
 */
export function windowStartedToday(item, now, leadSeconds) {
  if (!item) return false
  const at = now || new Date()
  const lead = typeof leadSeconds === 'number' ? leadSeconds : MIN_LEAD_SECONDS
  const nowSec = at.getHours() * 3600 + at.getMinutes() * 60 + at.getSeconds()
  const startSec = (Number(item.fromH) * 60 + Number(item.fromM)) * 60
  return nowSec >= startSec - lead
}

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
      // 本地计划（日常/每周）到点的提醒：由本次轮询取出来展示，
      // 这样即使定时器回调跑在「另一份模块实例」里也能正常显示
      drainPending()
      pump()
      return reminder.unread
    })
    .catch((error) => {
      // 提醒拉不到就当没有，不打扰老人；下个周期再试
      reminder.lastError = (error && error.message) || ''
      // 服务端拉不到也要把本地提醒放出来（本地计划不依赖网络）
      drainPending()
      pump()
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
    if (current.local) {
      // 本地生成的提醒（开始/结束各一次）：没有服务端 taskId 不需要回执，
      // 但要从待展示列表里去掉，否则刷新页面会重复弹
      removePending(current.id)
    } else {
      markReminderRead({ elderId: reminder.elderId, taskId: current.taskId }).catch(() => {})
    }
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
  clearLocalReminders()
}

/* ------------------------------------------------------------ 本地计划提醒 */
/**
 * 「日常计划」和「每周计划」目前只存本机，不经过服务端提醒队列，
 * 所以这里给它们补一条**本地腿**：到点（开始/结束）把提醒条推上来。
 *
 * 两个刻意的选择：
 * - **一个时间段提醒两次**：开始时说「可以开始了」，结束时说「这一轮结束了」。
 * - **定时器只写本地存储，不直接改 store**：
 *   实测本项目打包后本模块可能被内联进多个 chunk，定时器回调若直接改 store，
 *   写进去的可能是「另一份实例」，页面读不到（表现为到点静默无提醒）。
 *   所以回调只把「待展示提醒」写进本地存储，由页面自己的 poll() 取出来展示——
 *   poll 一定跑在页面自己的实例里，这样跨实例也能生效。
 */

/** 已触发过的键（`日期|计划id|start`），避免同一天重复提醒 */
const firedKeys = {}
/** 当前挂着的定时器 */
let localTimers = []
/** 重新排点时的自增令牌：旧定时器回调据此失效 */
let scheduleToken = 0

/**
 * 待展示的本地提醒：跨实例共享的唯一通道
 */
const PENDING_KEY = 'bl_local_reminders_v1'
/**
 * 「已经提醒过的点」也要落盘。
 *
 * 为什么必须持久化：内存里记的话，**每次刷新/冷启动都会清空**，
 * 而「开始点已过、时段还没走完」会触发补提醒 —— 于是点过「知道了」之后
 * 一刷新又弹一次，老人会被反复打扰。落盘后当天已提醒过的点就真正只提醒一次。
 */
const FIRED_KEY = 'bl_local_fired_v1'
/** 已经推进过队列的待展示提醒 id，避免每次 poll 重复推 */
const shownLocalIds = {}

function readPending() {
  try {
    const raw = uni.getStorageSync(PENDING_KEY)
    const list = raw ? (typeof raw === 'string' ? JSON.parse(raw) : raw) : []
    return Array.isArray(list) ? list : []
  } catch (e) {
    return []
  }
}

function writePending(list) {
  try {
    uni.setStorageSync(PENDING_KEY, JSON.stringify(list))
  } catch (e) {
    // 存储失败不影响其它提醒
  }
}

/* ------------------------------------------------ 「已提醒过」的持久化 */
/**
 * 落盘的格式：{ 日期: { '计划id|start': true, ... } }
 * 每天读一次，读进来之后只保留当天，避免无限增长。
 */
let firedLoaded = false

function loadFired() {
  if (firedLoaded) return
  firedLoaded = true
  const today = dayKeyOf(new Date())
  try {
    const raw = uni.getStorageSync(FIRED_KEY)
    const all = raw ? (typeof raw === 'string' ? JSON.parse(raw) : raw) : {}
    const todayMap = (all && all[today]) || {}
    Object.keys(todayMap).forEach((k) => {
      if (todayMap[k]) firedKeys[today + '|' + k] = true
    })
    // 只保留当天，顺手清掉历史，避免存储越来越大
    writeFired({ [today]: todayMap })
  } catch (e) {
    // 读不到就当作没提醒过
  }
}

function writeFired(map) {
  try {
    uni.setStorageSync(FIRED_KEY, JSON.stringify(map))
  } catch (e) {
    // 存储失败只影响去重，不影响提醒本身
  }
}

/** 标记某个提醒点已提醒过（内存 + 落盘） */
function markFired(key) {
  if (firedKeys[key]) return
  firedKeys[key] = true
  const parts = key.split('|')
  const day = parts[0]
  const slot = parts.slice(1).join('|')
  try {
    const raw = uni.getStorageSync(FIRED_KEY)
    const all = raw ? (typeof raw === 'string' ? JSON.parse(raw) : raw) : {}
    const todayMap = (all && all[day]) || {}
    todayMap[slot] = true
    writeFired({ [day]: todayMap })
  } catch (e) {
    // 忽略
  }
}

/** 定时器到点：只写本地存储，绝不碰 store（原因见本节开头） */
function queueLocalReminder(entry, slot) {
  const item = entry.item
  const timeText = pad2(slot.h) + ':' + pad2(slot.m)
  const id = 'local-' + item.id + '-' + slot.kind + '-' + dayKeyOf(new Date())
  const list = readPending()
  if (list.some((x) => x && x.id === id)) return
  list.push({
    id,
    // 本地提醒没有服务端 taskId，用合成 id 仅作展示（dismiss 时按 local 跳过回执）
    taskId: id,
    planItemId: item.id,
    title: item.name,
    label: timeText + ' · ' + slot.text,
    time: timeText,
    level: 'normal',
    levelLabel: '',
    strong: false,
    local: true,
    queuedAt: Date.now()
  })
  writePending(list)
}

/**
 * 从待展示列表里去掉一条（老人点「知道了」时调用）。
 * 不清掉的话，刷新页面后这条提醒会再弹一次。
 */
function removePending(id) {
  if (!id) return
  const list = readPending()
  const next = list.filter((x) => x && x.id !== id)
  if (next.length !== list.length) writePending(next)
}

/**
 * 把还没展示过的本地提醒推进队列（由 poll 调用）。
 * 超过 2 小时的旧提醒直接丢弃，避免隔天打开 App 弹出一堆过期提醒。
 */
function drainPending() {
  const list = readPending()
  if (!list.length) return
  const now = Date.now()
  const keep = []
  list.forEach((item) => {
    if (!item || !item.id) return
    if (now - (item.queuedAt || 0) > 2 * 3600 * 1000) return // 过期丢弃
    if (!shownLocalIds[item.id]) {
      shownLocalIds[item.id] = true
      reminder.queue.push(item)
      reminder.unread += 1
    }
    keep.push(item)
  })
  if (keep.length !== list.length) writePending(keep)
}

/**
 * 本地提醒的心跳：把到点的本地计划提醒立刻放出来。
 *
 * 为什么不是只靠 poll()：服务端轮询是 **30 秒一次**，而「开始/结束提醒」要求准点；
 * 更麻烦的是**并非每个页面都在轮询**（实测只有对话页和日程页调了 poll），
 * 老人停在日常计划页时提醒就永远不会显示。
 *
 * 所以由 `bl-reminder-bar` 组件自己每秒调一次这个函数——每页最多一个提醒条，
 * 既保证准点、又和当前在哪个页面无关，而且不产生任何网络请求。
 *
 * @returns {number} 这次新放出几条
 */
export function tickLocalReminders() {
  const before = reminder.queue.length
  drainPending()
  if (reminder.queue.length !== before) pump()
  return reminder.queue.length - before
}

const pad2 = (n) => String(n).padStart(2, '0')

function dayKeyOf(d) {
  return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate())
}

/** JS 的 getDay()（0=周日）→ 1..7（1=周一） */
function isoWeekday(d) {
  const w = d.getDay()
  return w === 0 ? 7 : w
}

function atTime(base, h, m) {
  const d = new Date(base.getFullYear(), base.getMonth(), base.getDate(), h, m, 0, 0)
  return d
}

/** 读取本地计划（解析失败就当作没有，不打断提醒链路） */
function readLocalPlans() {
  const out = []
  const read = (key, kind) => {
    try {
      const raw = uni.getStorageSync(key)
      const list = raw ? (typeof raw === 'string' ? JSON.parse(raw) : raw) : []
      if (!Array.isArray(list)) return
      list.forEach((item) => {
        if (!item || !item.id || !item.name) return
        if (!item.enabled) return
        out.push({ kind, item })
      })
    } catch (e) {
      // 忽略：本地存储读不到就不排提醒
    }
  }
  read('bl_daily_plans_v1', 'daily')
  read('bl_weekly_plans_v1', 'weekly')
  return out
}

/** 今天这条计划是否该提醒（跟页面 effectiveEnabled 同一套语义，但只读不写） */
function activeToday(entry, now) {
  const { kind, item } = entry
  const h = Number(item.fromH)
  const m = Number(item.fromM)
  const th = Number(item.toH)
  const tm = Number(item.toM)
  if (![h, m, th, tm].every((v) => isFinite(v))) return null

  if (kind === 'weekly') {
    const days = Array.isArray(item.days) ? item.days.map(Number) : []
    if (days.indexOf(isoWeekday(now)) === -1) return null
  }
  // 单次关闭：时间段过完就自动恢复，所以只在本轮还没过完时算「关着」
  const nowMin = now.getHours() * 60 + now.getMinutes()
  const endMin = th * 60 + tm
  const startMin = h * 60 + m
  if (item.closedUntil && nowMin < endMin) return null
  // 跳过 / 日历关闭
  const skipWeek = Array.isArray(item.closedWeekdays) ? item.closedWeekdays.map(Number) : []
  if (skipWeek.indexOf(isoWeekday(now)) !== -1) return null
  const skipDates = Array.isArray(item.closedDates) ? item.closedDates : []
  if (skipDates.indexOf(dayKeyOf(now)) !== -1) return null

  return { startH: h, startM: m, endH: th, endM: tm, startMin, endMin }
}

/** 清掉所有本地定时器 */
export function clearLocalReminders() {
  scheduleToken += 1
  localTimers.forEach((t) => clearTimeout(t))
  localTimers = []
}

/**
 * 排查「到点没提醒」用的观测点：
 *   localTimerCount()   当前挂着的定时器数量
 *   firedCallbackInfo() 定时器回调真正执行的次数（到点应 +1）
 *   firedKeysInfo()     已触发过的提醒键（`日期|计划id|start|end`）
 */
export function localTimerCount() {
  return localTimers.length
}
export function firedKeysInfo() {
  return Object.keys(firedKeys)
}
let firedCallbackCount = 0
export function firedCallbackInfo() {
  return firedCallbackCount
}

/**
 * 算出某条计划今天该提醒的时间点（纯函数，便于单独验证）。
 * @returns {null|{startH:number,startM:number,endH:number,endM:number,startMin:number,endMin:number}}
 */
export function todayWindow(entry, now) {
  return activeToday(entry, now || new Date())
}

/** 读取本地计划（排查用，返回解析到的条目） */
export function readLocalPlanEntries() {
  return readLocalPlans()
}

/**
 * 按当前本地计划重新排点（页面增删/开关计划后调用）。
 * @param {Array} [planSources] 计划来源，默认读本地存储
 * @returns {number} 排了几条
 */
export function rescheduleLocalReminders(now) {
  clearLocalReminders()
  // 先把「今天已经提醒过的点」读回来，否则刷新后会重复补提醒
  loadFired()
  const moment = now || new Date()
  const day = dayKeyOf(moment)
  const token = scheduleToken
  let count = 0

  readLocalPlans().forEach((entry) => {
    const win = activeToday(entry, moment)
    if (!win) return

    const slots = [
      { kind: 'start', h: win.startH, m: win.startM, text: '可以开始了' },
      { kind: 'end', h: win.endH, m: win.endM, text: '这一轮结束了' }
    ]

    slots.forEach((slot) => {
      const key = day + '|' + entry.item.id + '|' + slot.kind
      if (firedKeys[key]) return
      const at = atTime(moment, slot.h, slot.m)
      const delay = at.getTime() - moment.getTime()

      if (delay <= 0) {
        // 已经过了这个点：只在「本轮的时段还没走完」时补一次开始提醒
        // （例如 App 当时没开着）。结束点已经过了就说明这轮早结束，不必再补。
        const nowMin = moment.getHours() * 60 + moment.getMinutes()
        if (slot.kind === 'start' && nowMin < win.endMin) {
          markFired(key)
          queueLocalReminder(entry, slot)
          count += 1
        }
        return
      }

      const timer = setTimeout(() => {
        firedCallbackCount += 1
        // 期间重新排过点，这个定时器就作废
        if (token !== scheduleToken) return
        markFired(key)
        // 只写本地存储，由页面自己的 poll() 取出来展示（见本节开头说明）
        queueLocalReminder(entry, slot)
      }, delay)
      localTimers.push(timer)
      count += 1
    })
  })

  return count
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
