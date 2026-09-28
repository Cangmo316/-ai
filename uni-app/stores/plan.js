/**
 * 比邻AI · 今日计划状态（老人端日程页）
 *
 * 三条设计取舍，都是"适老化 + 降级可活"逼出来的：
 *
 * 1. **打卡是乐观的**：老人手指粗、网络慢，点一下必须立刻变绿。服务端失败再回滚，
 *    并给一句人话提示——不能出现"点了没反应"，那对老人等于"我不会用这个手机"。
 * 2. **三级兜底**：接口 → 本地缓存 → 内置样例，任何一级都能出内容，绝不白屏。
 *    老人打开日程页看到空白，比看到旧数据糟得多。
 * 3. **不做未读/角标之类的压力元素**：未完成的项就安安静静列着，不用红色数字催。
 */

import { reactive } from 'vue'
import { fetchTodayPlan, submitCheckin } from '@/api/index.js'

export const DEFAULT_ELDER_ID = 'e_1'
const CACHE_KEY = 'bl_plan_today_v1'

/** 接口全挂时的兜底内容（沿用原型基线，改自 prototype 的静态数据） */
const SAMPLE_ITEMS = [
  { id: 'sample_1', time: '08:00', type: '监测', title: '量完血压记一下 下次给医生看', detail: '家里的血压计比医院的更接近平时状态', done: false },
  { id: 'sample_2', time: '11:30', type: '午餐', title: '每天吃盐不超过5克', detail: '做菜少放酱油和咸菜', done: false },
  { id: 'sample_3', time: '15:30', type: '活动', title: '出去走走 回来扶着桌子单脚站一会儿', detail: '平衡练习能降低跌倒风险，一定要扶着稳的东西', done: false },
  { id: 'sample_4', time: '20:00', type: '问候', title: '这两天心里闷不闷 有事跟我说说', detail: '', done: false }
]

export const plan = reactive({
  elderId: DEFAULT_ELDER_ID,
  date: '',
  /** loading | ready | cached | sample */
  source: 'loading',
  status: '',
  statusLabel: '还没有计划',
  planId: '',
  items: [],
  total: 0,
  done: 0,
  rate: 0,
  ready: false,
  lastError: '',
  /** 正在打卡的项 id 集合（用于禁用重复点击） */
  pending: []
})

/** 页面标题那行文案：「9月24日 周四 · 共 4 项，已完成 2 项」 */
export function planHeadline() {
  const parsed = parseDay(plan.date)
  const dateText = parsed ? formatDateText(parsed) : ''
  if (!plan.total) {
    return dateText ? dateText + ' · 今天没有要提醒的事' : '今天没有要提醒的事'
  }
  return dateText + ' · 共 ' + plan.total + ' 项，已完成 ' + plan.done + ' 项'
}

export function initPlan(elderId) {
  if (elderId) plan.elderId = elderId
  return refreshToday()
}

/** 拉今日计划：接口 → 缓存 → 样例 */
export function refreshToday() {
  plan.source = plan.ready ? plan.source : 'loading'
  return fetchTodayPlan({ elderId: plan.elderId })
    .then((data) => {
      applyToday(data, 'ready')
      writeCache(data)
      plan.lastError = ''
      return data
    })
    .catch((error) => {
      plan.lastError = (error && error.message) || '连不上服务器'
      const cached = readCache()
      if (cached) {
        applyToday(cached, 'cached')
        return cached
      }
      applyToday(
        {
          elderId: plan.elderId,
          date: plan.date,
          statusLabel: '还没有计划',
          items: SAMPLE_ITEMS.map((item) => Object.assign({}, item)),
          total: SAMPLE_ITEMS.length,
          done: 0,
          rate: 0
        },
        'sample'
      )
      return null
    })
}

/**
 * 打卡 / 取消打卡（乐观更新）。
 * @param {object} item 计划项（来自 plan.items）
 * @returns {Promise<boolean>} 是否最终成功
 */
export function toggleCheckin(item) {
  if (!item || !item.id) return Promise.resolve(false)
  if (plan.pending.indexOf(item.id) !== -1) return Promise.resolve(false)
  if (String(item.id).indexOf('sample_') === 0) {
    // 样例数据（服务端不可用）：允许本地勾选，让老人有反馈，但不假装保存成功
    item.done = !item.done
    recount()
    plan.lastError = '现在连不上，等有网了会自动同步'
    return Promise.resolve(false)
  }

  const wanted = !item.done
  const before = item.done
  item.done = wanted
  recount()
  plan.pending.push(item.id)

  return submitCheckin({
    planItemId: item.id,
    elderId: plan.elderId,
    date: plan.date || undefined,
    done: wanted
  })
    .then((data) => {
      // 以服务端返回的计数为准（可能同时有别的端在打卡）
      if (data && typeof data.completed === 'number') {
        plan.done = data.completed
        plan.total = typeof data.total === 'number' ? data.total : plan.total
        plan.rate = typeof data.rate === 'number' ? data.rate : plan.rate
      }
      plan.lastError = ''
      writeCache(todaySnapshot())
      return true
    })
    .catch((error) => {
      item.done = before
      recount()
      plan.lastError = (error && error.message) || '打卡没成功，一会儿再试'
      return false
    })
    .then((result) => {
      const at = plan.pending.indexOf(item.id)
      if (at !== -1) plan.pending.splice(at, 1)
      return result
    })
}

export function clearPlanCache() {
  try { uni.removeStorageSync(CACHE_KEY) } catch (e) { /* 忽略 */ }
}

/* ------------------------------------------------------------------ 内部 */

function applyToday(data, source) {
  const payload = data || {}
  plan.date = payload.date || plan.date || todayKey()
  plan.status = payload.status || ''
  plan.statusLabel = payload.statusLabel || '还没有计划'
  plan.planId = payload.planId || ''
  plan.items = (payload.items || []).map((item) => ({
    id: item.id,
    time: item.time,
    type: item.type,
    title: item.title,
    detail: item.detail || '',
    freq: item.freq || '',
    strongRemind: !!item.strongRemind,
    done: !!item.done,
    doneAt: item.doneAt || '',
    basis: item.basis || null
  }))
  plan.total = typeof payload.total === 'number' ? payload.total : plan.items.length
  plan.done = typeof payload.done === 'number' ? payload.done : countDone()
  plan.rate = typeof payload.rate === 'number' ? payload.rate : 0
  plan.source = source
  plan.ready = true
}

function recount() {
  plan.done = countDone()
  plan.total = plan.items.length
  plan.rate = plan.total ? Math.round((plan.done / plan.total) * 1000) / 1000 : 0
}

function countDone() {
  return plan.items.filter((item) => item.done).length
}

function todaySnapshot() {
  return {
    elderId: plan.elderId,
    date: plan.date,
    status: plan.status,
    statusLabel: plan.statusLabel,
    planId: plan.planId,
    items: plan.items.map((item) => Object.assign({}, item)),
    total: plan.total,
    done: plan.done,
    rate: plan.rate
  }
}

function writeCache(data) {
  try {
    uni.setStorageSync(CACHE_KEY, JSON.stringify(data))
  } catch (e) {
    // 存储失败不影响本次展示
  }
}

function readCache() {
  try {
    const raw = uni.getStorageSync(CACHE_KEY)
    if (!raw) return null
    const data = typeof raw === 'string' ? JSON.parse(raw) : raw
    if (!data || !Array.isArray(data.items)) return null
    return data
  } catch (e) {
    return null
  }
}

function todayKey() {
  const now = new Date()
  return [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, '0'),
    String(now.getDate()).padStart(2, '0')
  ].join('-')
}

function parseDay(text) {
  if (!text) return null
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text)
  if (!match) return null
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
}

function formatDateText(day) {
  const week = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][day.getDay()]
  return day.getMonth() + 1 + '月' + day.getDate() + '日 ' + week
}

export default plan
