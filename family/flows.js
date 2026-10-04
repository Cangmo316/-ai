/**
 * 比邻AI · 家人端业务流程（不碰 DOM，可在 node 里直接测）
 *
 * 与老人端共用同一份接口客户端（`uni-app/api/plans.js`），所以契约只有一处实现：
 * 家人端一旦跑通，反过来也证明那层 api 是前端无关的。
 *
 * **隐私边界（设计方案 §3.4）**：子女端默认可见的是**计划完成率**，
 * **看不到聊天原文**。所以这里全部流程都只碰计划/打卡/提醒/记忆接口，
 * 一个读会话历史的调用都没有——不是"忘了做"，是刻意不做。
 * 记忆那一层也一样：`source=auto`（从聊天自动整理）的条目默认家属不可见，
 * 家属只能看到"智能体整理出的那句话"并复核，看不到它出自哪段对话。
 */

import {
  confirmPlan,
  createPlanDraft,
  fetchElders,
  fetchPendingPlans,
  fetchPlanHistory,
  fetchPlanSummary,
  fetchTodayPlan,
  rejectPlan
} from '../uni-app/api/plans.js'
import {
  clearMemories,
  createMemory,
  deleteMemory,
  fetchMemories,
  fetchMemorySettings,
  reviewMemory,
  updateMemorySettings
} from '../uni-app/api/memory.js'
import { fetchReminderTasks, fetchSchedulerStatus, tickScheduler } from '../uni-app/api/reminders.js'
import { request } from '../uni-app/api/request.js'
import { ENDPOINTS, resolveURL, setApiToken, setBaseURL } from '../uni-app/api/config.js'
import { installUniShim } from './uni-shim.js'

/**
 * @param {object} options
 * @param {string} [options.baseURL]  后端地址（默认沿用 api/config.js 里的默认值）
 * @param {string} [options.token]    服务端开了鉴权时需要
 */
export function createFamilyFlows(options = {}) {
  installUniShim()
  if (options.baseURL) setBaseURL(options.baseURL)
  if (options.token !== undefined) setApiToken(options.token || '')

  return {
    /** 老人列表（开发期是 3 个模拟档案） */
    listElders() {
      return fetchElders().then((data) => data.elders || [])
    },

    /** 待确认的计划（家属确认闸门就在这一步） */
    listPending(elderId) {
      return fetchPendingPlans({ elderId }).then((data) => data.plans || [])
    },

    /** 生成计划草稿并提交确认（等同运营/家属"发起一份计划"） */
    createDraft(elderId, extra = {}) {
      return createPlanDraft(Object.assign({ elderId, polish: true }, extra))
    },

    /** 确认 → 生效（旧计划在这一刻结束） */
    confirm(planId, actor = '家人') {
      return confirmPlan({ planId, actor })
    },

    /** 驳回 */
    reject(planId, reason = '', actor = '家人') {
      return rejectPlan({ planId, reason, actor })
    },

    /** 今日计划与打卡状态（老人端看的是同一份数据） */
    today(elderId) {
      return fetchTodayPlan({ elderId })
    },

    /** 完成率与调整建议 */
    summary(elderId, days = 7) {
      return fetchPlanSummary({ elderId, days })
    },

    /** 转入调整（等家属确认后才真的改计划） */
    requestAdjust(planId, reason = '') {
      return request({
        url: resolveURL(ENDPOINTS.planAdjust),
        method: 'POST',
        data: { planId, actor: '家人', reason }
      })
    },

    /** 计划历史（谁在什么时候确认的） */
    history(elderId) {
      return fetchPlanHistory({ elderId }).then((data) => data.plans || [])
    },

    /** 提醒任务（发没发、打没打卡——可追溯，但不含聊天内容） */
    reminders(elderId) {
      return fetchReminderTasks({ elderId }).then((data) => data.tasks || [])
    },

    schedulerStatus() {
      return fetchSchedulerStatus()
    },

    /** 联调用：手动推进调度（生产环境会被服务端关掉） */
    tick(at) {
      return tickScheduler(at)
    },

    /* ---------------------------------------------------------- 记忆（P2 三层记忆的家人侧） */

    /**
     * 记忆列表：默认口径（scope=family）**只看家属可见的**。
     *
     * 服务端在这一层就把两道闸门收紧了，端侧不许自己放宽（见 server/app/memory/models.py）：
     *   1. 从聊天自动整理出来的（`source=auto`）默认 `visibleToFamily=false`
     *   2. 待复核的（`review=pending`）不出现——它们只该进下面的「待复核区」
     * 所以这里不传 `includePending`、也不传 `scope=all`。
     */
    listMemories(elderId, params = {}) {
      return fetchMemories(Object.assign({ elderId, scope: 'family' }, params)).then(
        (data) => data.memories || []
      )
    },

    /**
     * 待复核区：家属要能看到"智能体自己想记但没把握的东西"，否则复核这道关没法过。
     *
     * ⚠️ 这里**必须** `scope=all` + `includePending=true`，而且只能在复核区用：
     * `scope=family` 走的是 `family_view()`（只含"已复核且家属可见"），
     * 在那儿加 `includePending` 是无效的——待复核的照样一条都不出。
     *
     * 家属看到的是"自动整理出的那句话"本身，而不是聊天原文（原文仍然不出这个页面）。
     */
    pendingMemories(elderId) {
      return fetchMemories({ elderId, scope: 'all', includePending: true }).then((data) =>
        (data.memories || []).filter((item) => item.review === 'pending')
      )
    },

    /**
     * 待复核条数（服务端顺带返回的 `pendingCount`，不用再拉一遍列表）。
     * 页面顶部要显示"有几条等你判断"——单独一个 HTTP 请求只为了一个数字不划算。
     */
    pendingMemoryCount(elderId) {
      return fetchMemories({ elderId, scope: 'family' }).then((data) => data.pendingCount || 0)
    },

    /** 家人端按老人分别取开关（默认关；`consentedAt` 是第一次开启时记下的同意时间） */
    memorySettings(elderId) {
      return fetchMemorySettings({ elderId }).then((data) => data.settings || {})
    },

    /**
     * 录入一条记忆。
     *
     * 服务端会拦空内容（`memory_empty`），但这里**先拦一道**：家属写了个空就点提交，
     * 等一个来回才被告知"不能为空"太钝了。端侧的拦法只为人话提示，口径仍以服务端为准。
     */
    addMemory(elderId, payload = {}) {
      const text = String(payload.text || '').trim()
      if (!text) {
        // 返回 rejected promise（而不是 throw）：调用方统一用 try/catch 处理
        return Promise.reject({
          code: 'memory_empty',
          statusCode: 400,
          message: '要记的内容不能是空的，写一句再提交',
          retryable: false
        })
      }
      return createMemory({
        elderId,
        kind: payload.kind || 'experience',
        text,
        tags: payload.tags || [],
        happenedAt: payload.happenedAt || ''
      })
    },

    /** 复核自动整理出来的条目：通过 → 可用；否决 → 保留痕迹但不再使用 */
    reviewMemory(id, approve) {
      return reviewMemory(id, approve)
    },

    /** 单条删除（方案要求：记忆库支持单条删除） */
    deleteMemory(id) {
      return deleteMemory(id)
    },

    /** 一键清空（页面侧要二次确认；这里只负责把动作发出去） */
    clearMemories(elderId) {
      return clearMemories({ elderId })
    },

    /**
     * 读写"从聊天里自动整理"的开关。默认关；开启即视为已明确告知本人，
     * 服务端会记 `consentedAt`——页面要把这个时间显示出来，作为"确实告知过"的凭证。
     */
    saveMemorySettings(elderId, autoExtract) {
      return updateMemorySettings({ elderId, autoExtract: !!autoExtract }).then(
        (data) => data.settings || {}
      )
    }
  }
}

/**
 * 把计划项整理成家人看得懂的一行文案。
 * 依据（来源 + 版本 + 条目 id）必须露出来——设计方案要求"计划项落库时同步存依据，家属端可见"，
 * 家属看到"这条是照哪份指南来的"才会放心点确认。
 */
export function describeItem(item) {
  return {
    time: item.time || '',
    type: item.type || '',
    title: item.title || '',
    detail: item.detail || '',
    freq: item.freq || '',
    strong: !!item.strongRemind,
    done: !!item.done,
    source: (item.basis && (item.basis.sourceName || item.basis.source)) || '',
    basis: (item.basis && item.basis.text) || '',
    boundary: (item.basis && item.basis.boundary) || ''
  }
}

/** 完成率文案（大数字 + 一句人话，别让家属去算百分比） */
export function describeRate(stats) {
  if (!stats) return { percent: 0, text: '还没有数据' }
  const percent = Math.round((stats.rate || 0) * 100)
  let text = '最近 ' + stats.days + ' 天完成了 ' + stats.done + '/' + stats.expected + ' 次'
  if (percent >= 80) text += '，做得挺好'
  else if (percent >= 50) text += '，还行，有空可以提醒两句'
  else text += '，漏得比较多，建议看看是不是提醒时间不合适'
  return { percent, text }
}

/**
 * 计划状态怎么跟家属解释（状态机见 server/app/plan/models.py）。
 *
 * 最容易被误解的一条：**`adjusting` 仍然在执行**——调整期间原计划照旧提醒，
 * 不存在"提醒真空"。不解释清楚，家属会以为点了"需要调整"老人就没人提醒了。
 */
export function describePlanStatus(plan) {
  const status = (plan && plan.status) || ''
  const label = (plan && plan.statusLabel) || ''
  const executing = status === 'active' || status === 'adjusting'
  const hints = {
    draft: '还没提交，老人那边看不到',
    pending_confirm: '还没生效：老人看不到、也收不到任何提醒',
    active: '正在按时间提醒',
    adjusting: '调整期间这份计划**仍然在执行**（不会出现提醒真空），确认新计划后才替换',
    ended: '已结束（被新计划替代）',
    rejected: '家属驳回了，没有生效'
  }
  return { status, label, executing, hint: hints[status] || '' }
}

/**
 * 下一个该提醒的时刻（用于"手动推进调度"的默认值）。
 *
 * 为什么需要它：演示/验收时直接推"当前时间"往往会得到 0 条提醒
 * （计划项都在 08:00 之后，而现在可能是凌晨），看起来像坏了。
 * 这里挑出今天**还没到点**的最早一项；都过完了就顺延到明天第一项。
 *
 * @param {object} today  GET /v1/plans/today 的返回
 * @param {Date} [now]
 * @returns {string} 本地时间字符串 `YYYY-MM-DDTHH:mm:ss`（调度器接受这个格式）
 */
export function nextReminderAt(today, now) {
  const moment = now || new Date()
  const items = ((today && today.items) || [])
    .filter((item) => !item.done && /^\d{2}:\d{2}$/.test(item.time || ''))
    .sort((a, b) => (a.time < b.time ? -1 : 1))
  const day = today && today.date ? today.date : localDay(moment)
  const future = items.find((item) => atLocal(day, item.time).getTime() > moment.getTime())
  const picked = future || items[0]
  if (!picked) return localStamp(moment)
  const target = future ? atLocal(day, picked.time) : atLocal(addDay(day), picked.time)
  return localStamp(target)
}

function atLocal(day, hhmm) {
  const parts = String(day).split('-').map(Number)
  const hm = String(hhmm).split(':').map(Number)
  return new Date(parts[0], parts[1] - 1, parts[2], hm[0], hm[1], 0, 0)
}

function addDay(day) {
  const parts = String(day).split('-').map(Number)
  const next = new Date(parts[0], parts[1] - 1, parts[2] + 1)
  return localDay(next)
}

function localDay(moment) {
  const pad = (n) => String(n).padStart(2, '0')
  return moment.getFullYear() + '-' + pad(moment.getMonth() + 1) + '-' + pad(moment.getDate())
}

/** 调度器要的是不带时区的本地时间串（和它自己的 clock 语义一致） */
function localStamp(moment) {
  const pad = (n) => String(n).padStart(2, '0')
  return (
    localDay(moment) +
    'T' +
    pad(moment.getHours()) + ':' + pad(moment.getMinutes()) + ':' + pad(moment.getSeconds())
  )
}

/* -------------------------------------------------------------------- 记忆文案 */

/** 种类：memory.kind 的取值见 server/app/memory/models.py 的 KIND_LABELS */
const KIND_TEXT = {
  experience: '经历',
  preference: '喜好',
  profile: '习惯'
}

/**
 * 来源：**必须显示给家属**。
 *
 * 家属在一眼扫列表时要知道"这条是家里人写的 / 老人自己说的 / 智能体从聊天里整理的"，
 * 可信度完全不同（`source=auto` 的家属本来也看不到正文，见 visibleToFamily）。
 */
const SOURCE_TEXT = {
  family: '家里人填写',
  elder: '老人自己说的',
  auto: '从聊天里整理'
}

const REVIEW_TEXT = {
  approved: '已复核可用',
  pending: '待家里人复核',
  rejected: '已否决，不会再用'
}

/**
 * 把一条记忆整理成家人看得懂的一行文案。
 *
 * 为什么要单独有这个函数：**来源与复核状态必须露出来**。
 * 记忆是"智能体对老人的了解"，家属看不到来源就无从判断"这条到底靠不靠谱"，
 * 更没法决定要不要复核——这跟计划项必须露出依据是同一个道理。
 *
 * 缺字段一律退回中文兜底（"其他"），**绝不把 undefined 或英文枚举值甩到页面上**。
 */
export function describeMemory(item) {
  const entry = item || {}
  const tags = Array.isArray(entry.tags) ? entry.tags.filter((tag) => String(tag || '').trim()) : []
  const review = entry.review || 'approved'
  return {
    id: entry.id || '',
    kind: entry.kind || '',
    // 服务端给了 kindLabel 就用它（将来加种类时端侧不必跟着改）；没给才用本地表
    kindText: entry.kindLabel || KIND_TEXT[entry.kind] || '其他',
    text: entry.text || '',
    tags,
    tagText: tags.join('、'),
    source: entry.source || '',
    sourceText: entry.sourceLabel || SOURCE_TEXT[entry.source] || '来源不明',
    // 自动整理出来的记忆家属默认看不到正文；这里如实说明"为什么看不到"。
    // 字段名刻意不叫 fromChat：`tools/test-family-flows.mjs` 有一条扫源码的隐私回归用例，
    // 会连同标识符一起扫（出现会话相关英文词就失败），改名字比放宽用例更安全
    autoExtracted: entry.source === 'auto',
    review,
    reviewText: REVIEW_TEXT[review] || '状态不明',
    pending: review === 'pending',
    visibleToFamily: entry.visibleToFamily !== false,
    happenedAt: entry.happenedAt || '',
    // 没有发生时间时，退到入库时间（家属问"这是什么时候记的"也要有答案）
    createdAt: entry.createdAt || '',
    createdText: entry.createdAt ? String(entry.createdAt).replace('T', ' ').slice(0, 16) : ''
  }
}

/**
 * 自动整理开关怎么跟家属解释。
 *
 * 默认关是**产品红线**（设计方案 §3.4：从聊天里自动整理需明确告知并允许关闭），
 * 所以文案不能只说"开/关"，得说清楚开启意味着什么、以及"同意时间已被记录"。
 */
export function describeMemorySettings(settings) {
  const value = settings || {}
  const on = !!value.autoExtract
  const consentedAt = value.consentedAt ? String(value.consentedAt).replace('T', ' ').slice(0, 16) : ''
  return {
    autoExtract: on,
    consentedAt,
    label: on ? '已开启' : '已关闭（默认）',
    hint: on
      ? '智能体会把聊天里提到的经历和喜好记下来' +
        (consentedAt ? '，已记录同意时间 ' + consentedAt : '，已记录同意时间') +
        '；没把握的先放进待复核，由你决定用不用'
      : '现在不会从聊天里整理任何东西。开启前请先明确告知老人，并让他知道随时可以关掉'
  }
}

/**
 * 一条待复核条目的复核建议（页面上每条给一句人话，别只丢两个按钮）。
 * 置信度低不代表记错了，只代表"智能体自己没把握"，所以要家属看一眼再定。
 */
export function describeReviewHint(item) {
  const entry = describeMemory(item)
  const confidence = typeof (item && item.confidence) === 'number' ? item.confidence : null
  const percent = confidence === null ? '' : '（整理时的把握 ' + Math.round(confidence * 100) + '%）'
  return {
    text: entry.text,
    hint: '这条是智能体从聊天里自己整理出来的' + percent +
      '，没经你确认前不会用来主动关心老人。内容对就通过，不对就否决。'
  }
}

export default createFamilyFlows
