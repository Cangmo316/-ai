/**
 * 比邻AI · 每周计划（本地存储）
 *
 * 与「日常计划」(stores/daily.js) 同构：老人自己加、存本地、加完立刻生效。
 * 差别只在「什么时候生效」：日常计划每天重复，每周计划只在选中的星期几、且在时间段内重复。
 *
 * 星期编号 1 = 周一 … 7 = 周日（与界面一致）。JS 的 getDay() 换算见 jsWeekday()。
 *
 * 三种关闭与日常计划一一对应，只是「日历选几天」换成了「跳过哪几个星期几」：
 *   · 单次关闭   → closedUntil：这次时间段过完自动恢复
 *   · 跳过某几天 → closedWeekdays：这些星期几不提醒
 *   · 永久关闭   → enabled = false：一直关，直到老人再点一次开关
 *
 * 【为什么所有操作都返回 items】
 * 实测在本项目的 uni-app H5 产物里，本 store 会被内联进页面 chunk 并改名，
 * 导致页面模板里对「模块绑定」的引用变成 undefined（渲染抛错、整页空白）。
 * 因此页面不要直接引用本模块的 reactive 对象，而是使用 xxx() 返回的 items 副本，
 * 放进页面自己的 ref 里渲染。
 */

import { reactive } from 'vue'

const KEY = 'bl_weekly_plans_v1'

export const WEEKDAY_LABELS = ['一', '二', '三', '四', '五', '六', '日']
export const HOURS = Array.from({ length: 24 }, (_, i) => i)
export const MINUTES = Array.from({ length: 12 }, (_, i) => i * 5)

/** 内部状态：不对外暴露给模板 */
const state = reactive({
  items: [],
  ready: false
})

let seq = 0
function newId() {
  seq += 1
  return 'w_' + Date.now().toString(36) + '_' + seq
}

const pad = (n) => String(n).padStart(2, '0')

/** JS 的 getDay()（0 = 周日）→ 本模块的星期编号（1 = 周一 … 7 = 周日） */
export function jsWeekday(date) {
  const d = (date || new Date()).getDay()
  return d === 0 ? 7 : d
}

export function toMinutes(h, m) {
  return h * 60 + m
}

/** 时间段文案：'08:00 — 09:00' */
export function rangeText(item) {
  if (!item) return ''
  return pad(item.fromH) + ':' + pad(item.fromM) + ' — ' + pad(item.toH) + ':' + pad(item.toM)
}

/** 选中星期的展示文案：全选说「每天」，否则「周一、周三」 */
export function daysText(days) {
  const list = normalizeDays(days)
  if (!list.length) return '未选择'
  if (list.length === 7) return '每天'
  return list.map((d) => '周' + WEEKDAY_LABELS[d - 1]).join('、')
}

function normalizeDays(input) {
  const arr = Array.isArray(input) ? input : []
  const set = []
  arr.forEach((v) => {
    const n = Number(v)
    if (n >= 1 && n <= 7 && set.indexOf(n) === -1) set.push(n)
  })
  return set.sort((a, b) => a - b)
}

/** 今天这一轮的时间段是否已经过完 */
function windowPassed(item, now) {
  return toMinutes(now.getHours(), now.getMinutes()) >= toMinutes(item.toH, item.toM)
}



/**
 * 此刻这条计划是否生效。
 * @param {object} item
 * @param {Date} [now]
 */
export function effectiveEnabled(item, now) {
  if (!item) return false
  const at = now || new Date()
  if (!item.enabled) return false
  if (normalizeDays(item.days).indexOf(jsWeekday(at)) === -1) return false
  if (item.closedUntil) {
    if (windowPassed(item, at)) {
      item.closedUntil = ''
      schedulePersist()
      return true
    }
    return false
  }
  const skip = normalizeDays(item.closedWeekdays)
  if (skip.length) return skip.indexOf(jsWeekday(at)) === -1
  return true
}

/** 关闭状态的一句话说明 */
export function closureNote(item, now) {
  if (!item) return ''
  const at = now || new Date()
  if (!item.enabled) return '已永久关闭'
  if (item.closedUntil && !windowPassed(item, at)) return '这次先关掉，时段过后自动打开'
  const skip = normalizeDays(item.closedWeekdays)
  if (skip.length) {
    if (skip.indexOf(jsWeekday(at)) !== -1) return '今天已跳过'
    return '已跳过 ' + skip.length + ' 天'
  }
  return ''
}

/* -------------------------------------------------------------- 生命周期 */

function stamp(date) {
  const d = date || new Date()
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
    ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds())
}

/** 给页面用的读接口：返回普通数组副本，页面放进自己的 ref 渲染 */
export function readItems() {
  return state.items.map((i) => Object.assign({}, i, {
    days: i.days.slice(),
    closedWeekdays: i.closedWeekdays.slice()
  }))
}

export function initWeekly() {
  if (!state.ready) {
    state.ready = true
    try {
      const raw = uni.getStorageSync(KEY)
      const list = raw ? (typeof raw === 'string' ? JSON.parse(raw) : raw) : []
      state.items = Array.isArray(list) ? list.map(normalize).filter(Boolean) : []
    } catch (e) {
      state.items = []
    }
    state.items.forEach((item) => effectiveEnabled(item))
  }
  return readItems()
}

function normalize(item) {
  if (!item || !item.name) return null
  const days = normalizeDays(item.days)
  if (!days.length) return null
  return {
    id: item.id || newId(),
    name: String(item.name),
    days,
    fromH: clampHour(item.fromH, 8),
    fromM: clampMinute(item.fromM, 0),
    toH: clampHour(item.toH, 9),
    toM: clampMinute(item.toM, 0),
    enabled: item.enabled === undefined ? true : !!item.enabled,
    closedUntil: item.closedUntil || '',
    closedWeekdays: normalizeDays(item.closedWeekdays),
    createdAt: item.createdAt || Date.now()
  }
}

function clampHour(v, fallback) {
  const n = Number(v)
  if (!isFinite(n)) return fallback
  return Math.min(23, Math.max(0, Math.floor(n)))
}

function clampMinute(v, fallback) {
  const n = Number(v)
  if (!isFinite(n)) return fallback
  const step = Math.round(n / 5) * 5
  return step >= 60 ? 55 : Math.max(0, step)
}

function persist() {
  try {
    uni.setStorageSync(KEY, JSON.stringify(state.items.map((i) => Object.assign({}, i))))
  } catch (e) {
    // 存储失败不影响本次使用
  }
}

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
 * 新增一条每周计划。
 * @returns {{ok:boolean, reason?:string, items:Array}}
 */
export function addWeeklyPlan(input) {
  const name = String((input && input.name) || '').trim()
  const days = normalizeDays(input && input.days)
  if (!name) return { ok: false, reason: '请先写计划名称', items: readItems() }
  if (name.length > 20) return { ok: false, reason: '名称太长，写短一点', items: readItems() }
  if (!days.length) return { ok: false, reason: '先选一个星期几', items: readItems() }

  state.items.push(normalize({
    id: newId(),
    name,
    days,
    fromH: input.fromH,
    fromM: input.fromM,
    toH: input.toH,
    toM: input.toM,
    enabled: true,
    createdAt: Date.now()
  }))
  persist()
  return { ok: true, items: readItems() }
}

export function removeWeeklyPlan(id) {
  const at = state.items.findIndex((i) => i.id === id)
  if (at !== -1) {
    state.items.splice(at, 1)
    persist()
  }
  return readItems()
}

/* ---------------------------------------------------------------- 三种关闭 */

/** 单次关闭：本时段生效，时段过后自动恢复 */
export function closeOnce(id) {
  const item = state.items.find((i) => i.id === id)
  if (item) {
    item.enabled = true
    item.closedUntil = stamp(new Date())
    persist()
  }
  return readItems()
}

/** 跳过：把这些星期几加入跳过列表 */
export function closeOnWeekdays(id, weekdays) {
  const item = state.items.find((i) => i.id === id)
  if (item) {
    const set = item.closedWeekdays.slice()
    normalizeDays(weekdays).forEach((d) => {
      if (set.indexOf(d) === -1) set.push(d)
    })
    set.sort((a, b) => a - b)
    item.enabled = true
    item.closedUntil = ''
    item.closedWeekdays = set
    persist()
  }
  return readItems()
}

/** 永久关闭：关到老人再点一次开关为止 */
export function closeForever(id) {
  const item = state.items.find((i) => i.id === id)
  if (item) {
    item.enabled = false
    item.closedUntil = ''
    item.closedWeekdays = []
    persist()
  }
  return readItems()
}

/** 重新打开：清掉所有关闭标记 */
export function reopenPlan(id) {
  const item = state.items.find((i) => i.id === id)
  if (item) {
    item.enabled = true
    item.closedUntil = ''
    item.closedWeekdays = []
    persist()
  }
  return readItems()
}

export function clearWeeklyPlans() {
  state.items = []
  try { uni.removeStorageSync(KEY) } catch (e) { /* 忽略 */ }
  return readItems()
}

export default { readItems, initWeekly }
