/**
 * 比邻AI · 日常计划（本地存储）
 *
 * 一期把「日常计划」存本地：老人自己加的事不需要等网络，加完立刻生效。
 *
 * 关闭（关闭提醒）分三种语义，状态字段各自独立，互不干扰：
 *   · 单次关闭   → closedUntil：一次时间段过完就自动恢复
 *   · 日历关闭   → closedDates：只在选中的那几天关，过了这天的时段自动恢复
 *   · 永久关闭   → enabled = false：一直关着，直到老人再点一次开关
 *
 * effectiveEnabled() 是唯一判定「此刻到底开没开」的出口，
 * 界面只读它，不要直接读 enabled。
 */

import { reactive } from 'vue'

const KEY = 'bl_daily_plans_v1'

/** 一天 24 小时，分钟固定 5 分钟一档：老人滑起来省力，也不会滑半天 */
export const HOURS = Array.from({ length: 24 }, (_, i) => i)
export const MINUTES = Array.from({ length: 12 }, (_, i) => i * 5)

export const daily = reactive({
  items: [],
  ready: false
})

/** 毫秒时间戳 + 自增序号，保证同一毫秒内多次添加也不撞 id */
let seq = 0
function newId() {
  seq += 1
  return 'd_' + Date.now().toString(36) + '_' + seq
}

const pad = (n) => String(n).padStart(2, '0')

/** 12 → '12:00' */
export function clock(h, m) {
  return pad(h) + ':' + pad(m)
}

/** 时间段的展示文案：'08:00 — 09:00' */
export function rangeText(item) {
  return clock(item.fromH, item.fromM) + ' — ' + clock(item.toH, item.toM)
}

export function toMinutes(h, m) {
  return h * 60 + m
}

/** 本地日期键 'YYYY-MM-DD'（不用 toISOString，避免时区偏移） */
export function dayKey(date) {
  const d = date || new Date()
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
}

/* ------------------------------------------------------------------ 时间窗 */

/** 今天这个计划的时间窗是否已经过完（用于「单次关闭」的到期判断） */
function windowPassed(item, now) {
  return toMinutes(now.getHours(), now.getMinutes()) >= toMinutes(item.toH, item.toM)
}

/**
 * 此刻这条计划是否生效。
 * @param {object} item
 * @param {Date} [now]
 */
export function effectiveEnabled(item, now) {
  const at = now || new Date()
  // 永久关闭
  if (!item.enabled) return false
  // 单次关闭：时间窗过完就自动恢复（读的时候顺手清掉标记）
  if (item.closedUntil) {
    if (windowPassed(item, at)) {
      item.closedUntil = ''
      schedulePersist()
      return true
    }
    return false
  }
  // 日历关闭：只在选中的日期里关
  if (item.closedDates && item.closedDates.length) {
    return item.closedDates.indexOf(dayKey(at)) === -1
  }
  return true
}

/** 关闭状态的一句话说明，给卡片做副标题用 */
export function closureNote(item, now) {
  const at = now || new Date()
  if (!item.enabled) return '已永久关闭'
  if (item.closedUntil && !windowPassed(item, at)) return '这次先关掉，时段过后自动打开'
  if (item.closedDates && item.closedDates.length) {
    const today = dayKey(at)
    if (item.closedDates.indexOf(today) !== -1) return '今天已关闭'
    return '已关 ' + item.closedDates.length + ' 天'
  }
  return ''
}

/* -------------------------------------------------------------- 生命周期 */

const pad2 = (n) => String(n).padStart(2, '0')
function stamp(date) {
  return date.getFullYear() + '-' + pad2(date.getMonth() + 1) + '-' + pad2(date.getDate()) +
    ' ' + pad2(date.getHours()) + ':' + pad2(date.getMinutes()) + ':' + pad2(date.getSeconds())
}

export function initDaily() {
  if (daily.ready) return
  daily.ready = true
  try {
    const raw = uni.getStorageSync(KEY)
    const list = raw ? (typeof raw === 'string' ? JSON.parse(raw) : raw) : []
    daily.items = Array.isArray(list) ? list.map(normalize).filter(Boolean) : []
  } catch (e) {
    daily.items = []
  }
  sortItems()
  // 顺手结算一次：单次关闭到期的直接恢复
  daily.items.forEach((item) => effectiveEnabled(item))
}

function normalize(item) {
  if (!item || !item.name) return null
  return {
    id: item.id || newId(),
    name: String(item.name),
    fromH: clampHour(item.fromH),
    fromM: clampMinute(item.fromM),
    toH: clampHour(item.toH),
    toM: clampMinute(item.toM),
    // 永久开关：默认开启
    enabled: item.enabled === undefined ? true : !!item.enabled,
    // 单次关闭的时间戳（到期自动清空）
    closedUntil: item.closedUntil || '',
    // 日历关闭的日期数组 ['YYYY-MM-DD']
    closedDates: Array.isArray(item.closedDates) ? item.closedDates.slice() : [],
    createdAt: item.createdAt || Date.now()
  }
}

function clampHour(v) {
  const n = Number(v)
  if (!isFinite(n)) return 8
  return Math.min(23, Math.max(0, Math.floor(n)))
}

function clampMinute(v) {
  const n = Number(v)
  if (!isFinite(n)) return 0
  const step = Math.round(n / 5) * 5
  return step >= 60 ? 55 : Math.max(0, step)
}

function sortItems() {
  daily.items.sort((a, b) => toMinutes(a.fromH, a.fromM) - toMinutes(b.fromH, b.fromM))
}

function persist() {
  try {
    uni.setStorageSync(KEY, JSON.stringify(daily.items.map((i) => Object.assign({}, i))))
  } catch (e) {
    // 存储失败不影响本次使用
  }
}

/** 读的时候清理过期标记，不要每次都写盘 */
let persistTimer = null
function schedulePersist() {
  if (persistTimer) return
  persistTimer = setTimeout(() => {
    persistTimer = null
    persist()
  }, 60)
}

/* -------------------------------------------------------------------- 增删 */

/**
 * 新增一条日常计划。
 * @returns {{ok:boolean, reason?:string, item?:object}}
 */
export function addDailyPlan(input) {
  const name = String((input && input.name) || '').trim()
  if (!name) return { ok: false, reason: '请先写计划名称' }
  if (name.length > 20) return { ok: false, reason: '名称太长，写短一点' }

  const item = normalize({
    id: newId(),
    name,
    fromH: input.fromH,
    fromM: input.fromM,
    toH: input.toH,
    toM: input.toM,
    enabled: true,
    createdAt: Date.now()
  })
  daily.items.push(item)
  sortItems()
  persist()
  return { ok: true, item }
}

export function removeDailyPlan(id) {
  const at = daily.items.findIndex((i) => i.id === id)
  if (at === -1) return false
  daily.items.splice(at, 1)
  persist()
  return true
}

/* ---------------------------------------------------------------- 三种关闭 */

/** 单次关闭：本时段生效，时段过后自动恢复 */
export function closeOnce(id) {
  const item = daily.items.find((i) => i.id === id)
  if (!item) return false
  item.enabled = true
  item.closedUntil = stamp(new Date())
  persist()
  return true
}

/** 日历关闭：把这些日期加进关闭列表（重复点同一天不会重复加） */
export function closeOnDates(id, dates) {
  const item = daily.items.find((i) => i.id === id)
  if (!item) return false
  const set = item.closedDates.slice()
  ;(dates || []).forEach((d) => {
    if (set.indexOf(d) === -1) set.push(d)
  })
  set.sort()
  item.enabled = true
  item.closedUntil = ''
  item.closedDates = set
  persist()
  return true
}

/** 永久关闭：关到老人再点一次开关为止 */
export function closeForever(id) {
  const item = daily.items.find((i) => i.id === id)
  if (!item) return false
  item.enabled = false
  item.closedUntil = ''
  item.closedDates = []
  persist()
  return true
}

/** 重新打开：清掉所有关闭标记 */
export function reopenPlan(id) {
  const item = daily.items.find((i) => i.id === id)
  if (!item) return false
  item.enabled = true
  item.closedUntil = ''
  item.closedDates = []
  persist()
  return true
}

/** 撤销日历关闭里的某一天 */
export function reopenDate(id, date) {
  const item = daily.items.find((i) => i.id === id)
  if (!item) return false
  const at = item.closedDates.indexOf(date)
  if (at !== -1) item.closedDates.splice(at, 1)
  persist()
  return true
}

export function clearDailyPlans() {
  daily.items = []
  try { uni.removeStorageSync(KEY) } catch (e) { /* 忽略 */ }
}

export default daily
