/**
 * 特殊计划（某个具体日期要做的事）
 *
 * ## 与「日常计划」的区别
 *
 *   日常计划：每天都在同一时段提醒，没有日期概念
 *   特殊计划：**只在一个指定日期**提醒（生日、体检、走亲戚……）
 *
 * 需求原话：「布局与日程计划一致，只是上方写的是特殊计划，点击添加计划
 * 相比于添加日常计划多了一个选择具体日期的选项」。
 *
 * ## 为什么单开一个文件而不是改 daily.js
 *
 * 两者的「日期语义」完全不同：
 *   · 日常计划的时间窗是**每天**重复，所以有「日历关闭某些天」的概念
 *   · 特殊计划本身**就绑在一个日期上**，不需要"关闭哪些天"，
 *     只需要"这一次跳过"
 * 硬塞进同一个 store 会让两边都变得难懂（每个函数里都要判断有没有 date）。
 * 与既有做法一致：一种计划一个 store 文件
 * （daily.js / week-plans.js / special.js，各自独立）。
 *
 * 时间与日期的底层工具（clock / dayKey / toMinutes / 时段与分钟换算）
 * 都从 `daily.js` 复用，不重复实现。
 */
import { reactive } from 'vue'
import { dayKey, toMinutes } from '@/stores/daily.js'

/** 本地存储 key（与提醒调度器约定，见 stores/reminder.js 的 readLocalPlans） */
export const SPECIAL_KEY = 'bl_special_plans_v1'

/**
 * 计划名称的字数上限。
 *
 * 导出它是为了让**输入框的 maxlength 与这里的校验用同一个数**——
 * 原来两个数字各写一遍（模板写 20、校验写 > 20），
 * 改一处忘另一处就会变成"能输入但存不进去"，那种 bug 很难查。
 */
export const NAME_MAX = 20

export const special = reactive({
  ready: false,
  items: []
})

const pad2 = (n) => String(n).padStart(2, '0')

function newId() {
  return 'sp_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7)
}

export function clock(h, m) {
  return pad2(Number(h) || 0) + ':' + pad2(Number(m) || 0)
}

/** 时间段的展示文案：'08:00 — 09:00' */
export function rangeText(item) {
  return clock(item.fromH, item.fromM) + ' — ' + clock(item.toH, item.toM)
}

/**
 * 日期的展示文案：'10月8日 周四'
 *
 * 卡片上只写 YYYY-MM-DD 老人读起来费劲，所以转成"几月几日 + 星期几"。
 * 解析失败就把原样返回（不因为格式化失败而丢信息）。
 */
export function dateText(date) {
  const key = String(date || '')
  const parts = key.split('-')
  if (parts.length !== 3) return key
  const y = Number(parts[0])
  const m = Number(parts[1])
  const d = Number(parts[2])
  if (!isFinite(y) || !isFinite(m) || !isFinite(d)) return key
  const at = new Date(y, m - 1, d)
  const week = ['日', '一', '二', '三', '四', '五', '六'][at.getDay()]
  const prefix = y === new Date().getFullYear() ? '' : y + '年'
  return prefix + m + '月' + d + '日 周' + week
}

/** 距今天还有几天：'今天' / '明天' / '还有 3 天' / '已过 2 天' */
export function relativeText(date, now) {
  const key = String(date || '')
  if (!/^\d{4}-\d{2}-\d{2}$/.test(key)) return ''
  const at = now || new Date()
  const today = new Date(at.getFullYear(), at.getMonth(), at.getDate())
  const parts = key.split('-').map(Number)
  const target = new Date(parts[0], parts[1] - 1, parts[2])
  const days = Math.round((target.getTime() - today.getTime()) / 86400000)
  if (days === 0) return '今天'
  if (days === 1) return '明天'
  if (days > 1) return '还有 ' + days + ' 天'
  return '已过 ' + Math.abs(days) + ' 天'
}

/* -------------------------------------------------------------- 生命周期 */

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

/** 校验并规范一个日期键；非法返回 '' */
export function normalizeDate(value) {
  const raw = String(value || '').trim()
  if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return ''
  const parts = raw.split('-').map(Number)
  // 防 2026-02-31 这种"格式对但不存在"的日期：建一次 Date 看会不会被规范化掉
  const at = new Date(parts[0], parts[1] - 1, parts[2])
  if (at.getFullYear() !== parts[0] || at.getMonth() !== parts[1] - 1 || at.getDate() !== parts[2]) {
    return ''
  }
  return raw
}

function normalize(item) {
  if (!item || !item.name) return null
  const date = normalizeDate(item.date)
  // 没有有效日期的特殊计划没有意义（它就是为了"某一天"存在的）
  if (!date) return null
  return {
    id: item.id || newId(),
    name: String(item.name),
    date,
    fromH: clampHour(item.fromH),
    fromM: clampMinute(item.fromM),
    toH: clampHour(item.toH),
    toM: clampMinute(item.toM),
    // 永久开关：默认开启。特殊计划**只有这一个关闭状态**
    // （没有 closedDates / skipped，理由见 effectiveEnabled 的说明）
    enabled: item.enabled === undefined ? true : !!item.enabled,
    createdAt: item.createdAt || Date.now()
  }
}

/** 排序：日期近的在前；同一天按开始时间 */
function sortItems() {
  special.items.sort((a, b) => {
    if (a.date !== b.date) return a.date < b.date ? -1 : 1
    return toMinutes(a.fromH, a.fromM) - toMinutes(b.fromH, b.fromM)
  })
}

function persist() {
  try {
    uni.setStorageSync(SPECIAL_KEY, JSON.stringify(special.items.map((i) => Object.assign({}, i))))
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

export function initSpecial() {
  if (special.ready) return
  special.ready = true
  try {
    const raw = uni.getStorageSync(SPECIAL_KEY)
    const list = raw ? (typeof raw === 'string' ? JSON.parse(raw) : raw) : []
    special.items = Array.isArray(list) ? list.map(normalize).filter(Boolean) : []
  } catch (e) {
    special.items = []
  }
  sortItems()
}

/* -------------------------------------------------------------------- 生效 */

/**
 * 此刻这条特殊计划是否生效。
 *
 * 与日常计划的差别：
 *   · 日常计划的 `enabled` 只表示"要不要开"，还要另外判断今天是不是关闭日
 *   · 特殊计划**没有"部分关闭"**——它只落在一个日期上，所以关闭只有一种
 *     （`enabled = false`），不需要 closedDates / skipped 那一套。
 *
 * 曾经做过"跳过这一次"，后来去掉：一条只落一天的计划，
 * "这次不提醒"与"以后都不提醒"结果**完全相同**，
 * 给老人两个结果一样的选项只会让他犹豫。
 */
export function effectiveEnabled(item) {
  return !!item.enabled
}

/** 是不是"就是今天"（卡片上要突出显示） */
export function isToday(item, now) {
  return item.date === dayKey(now || new Date())
}

/** 关闭状态的一句话说明，给卡片做副标题 */
export function closureNote(item) {
  return item.enabled ? '' : '已关掉提醒，想开就点右边的开关'
}

/* -------------------------------------------------------------------- 增删 */

/**
 * 新增一条特殊计划。
 * @returns {{ok:boolean, reason?:string, item?:object}}
 */
export function addSpecialPlan(input) {
  const name = String((input && input.name) || '').trim()
  if (!name) return { ok: false, reason: '请先写计划名称' }
  if (name.length > NAME_MAX) return { ok: false, reason: '名称太长，写短一点' }

  const date = normalizeDate(input && input.date)
  if (!date) return { ok: false, reason: '请选择具体日期' }

  const item = normalize({
    id: newId(),
    name,
    date,
    fromH: input.fromH,
    fromM: input.fromM,
    toH: input.toH,
    toM: input.toM,
    enabled: true,
    createdAt: Date.now()
  })
  if (!item) return { ok: false, reason: '这条计划的数据不对，再填一次' }
  special.items.push(item)
  sortItems()
  persist()
  return { ok: true, item }
}

export function removeSpecialPlan(id) {
  const at = special.items.findIndex((i) => i.id === id)
  if (at === -1) return false
  special.items.splice(at, 1)
  persist()
  return true
}

/* -------------------------------------------------------------------- 开关 */

/**
 * 打开：恢复提醒。
 *
 * 只有 `enabled` 一个开关，没有别的状态要清
 * （曾经的"跳过标记"已去掉，见 effectiveEnabled 的说明）。
 */
export function reopenSpecial(id) {
  const item = special.items.find((i) => i.id === id)
  if (!item) return false
  item.enabled = true
  persist()
  return true
}

/** 关掉提醒。想再开就再调 reopenSpecial（页面上的开关就是这两个动作） */
export function closeSpecialForever(id) {
  const item = special.items.find((i) => i.id === id)
  if (!item) return false
  item.enabled = false
  persist()
  return true
}

export function clearSpecialPlans() {
  special.items = []
  persist()
}

export default special
