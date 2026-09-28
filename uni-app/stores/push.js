/**
 * 比邻AI · 推送登记与「端侧本地提醒」（App 端第二条腿）
 *
 * 提醒要送达老人，靠三条腿，这条文件负责后两条：
 *   ① 站内消息 —— 服务端写进会话，端侧轮询拉（App 前台一定收得到，已在 reminder.js 实现）
 *   ② **系统推送** —— 服务端 → uniCloud 云函数 → uni-push → 手机通知栏（老人不开 App 也能收到）
 *   ③ **端侧本地通知** —— App 端用 `uni.createPushMessage({delay})` 预排当天的提醒，
 *      断网、推送挂了也照样响（这就是设计方案里的"端侧本地提醒兜底"）
 *
 * 关键取舍：
 * - **只做能力探测，不做假设**：`uni.getPushClientId` / `uni.createPushMessage` 在 H5、小程序、
 *   标准 HBuilderX 基座上都不可用，全部走 `typeof === 'function'` 判断 + 静默降级，
 *   绝不让"推送不可用"变成页面报错
 * - **本地通知要防重复**：每次开 App 都会重排当天的提醒，如果不去重，
 *   老人上午开三次 App，下午的提醒就会响三次。所以按 `${日期}|${计划项 id}` 记账（本地存储，跨天自动失效）
 * - 只排**未来 12 小时内**且**还没打卡**的项：太远的排了没意义（跨天后计划可能变），
 *   已经过时的排了会立刻弹一条，反而添乱
 */

import { reactive } from 'vue'
import { fetchPushStatus, registerPushClient } from '@/api/index.js'

const CID_KEY = 'bl_push_cid'
const SCHEDULE_KEY = 'bl_local_notify_v1'
/** 只排未来这么多秒内的提醒（12 小时） */
const MAX_LOOKAHEAD_SECONDS = 12 * 3600
/** 太近的就别排了（否则本地通知和页面提醒条会同时弹） */
const MIN_LEAD_SECONDS = 30

export const push = reactive({
  elderId: 'e_1',
  cid: '',
  cidTail: '',
  /** unsupported | ready | failed | empty */
  state: 'unsupported',
  lastError: '',
  scheduled: 0,
  registeredAt: ''
})

/** 系统推送是否可用（App 端 + 开通 uni-push 的基座） */
export function pushSupported() {
  return typeof uni !== 'undefined' && typeof uni.getPushClientId === 'function'
}

/** 端侧本地通知是否可用（只有 App 端有） */
export function localNotifySupported() {
  return typeof uni !== 'undefined' && typeof uni.createPushMessage === 'function'
}

/**
 * 登记推送标识（App 启动 / 回到前台时调用；幂等）
 * @returns {Promise<string>} cid（拿不到返回空串）
 */
export function registerPush(elderId) {
  if (elderId) push.elderId = elderId
  if (!pushSupported()) {
    // 能力缺失（H5/小程序/标准基座）不是错误：清掉上次的失败，别让老人看到没意义的报错
    push.state = 'unsupported'
    push.lastError = ''
    return Promise.resolve('')
  }
  return new Promise((resolve) => {
    uni.getPushClientId({
      success(res) {
        const cid = (res && res.cid) || ''
        if (!cid) {
          push.state = 'empty'
          resolve('')
          return
        }
        push.cid = cid
        push.cidTail = cid.slice(-6)
        writeLocal(CID_KEY, cid)
        registerPushClient({
          cid,
          elderId: push.elderId,
          platform: platformName(),
          appVersion: appVersion()
        })
          .then(() => {
            push.state = 'ready'
            push.lastError = ''
            push.registeredAt = new Date().toISOString()
            resolve(cid)
          })
          .catch((error) => {
            // 登记失败不影响提醒的其它两条腿，先记下来下次再报
            push.state = 'failed'
            push.lastError = (error && error.message) || '登记失败'
            resolve(cid)
          })
      },
      fail(err) {
        push.state = 'failed'
        push.lastError = (err && err.errMsg) || '拿不到推送标识'
        resolve('')
      }
    })
  })
}

/** 上一次成功登记的 cid（排查用） */
export function cachedCid() {
  return readLocal(CID_KEY) || ''
}

/**
 * 预排当天的本地通知（在日程页拿到今日计划后调用）
 *
 * @param {Array} items 今日计划项（来自 stores/plan.js）
 * @param {Date} [now]
 * @returns {number} 本次新排了几条
 */
export function scheduleLocalNotifications(items, now) {
  if (!localNotifySupported() || !Array.isArray(items) || !items.length) return 0
  const moment = now || new Date()
  const day = dayKey(moment)
  const state = loadSchedule(day)
  let scheduled = 0

  for (const item of items) {
    if (!item || !item.id || item.done) continue
    if (!/^\d{2}:\d{2}$/.test(item.time || '')) continue
    const key = day + '|' + item.id
    if (state.scheduled[key]) continue

    const at = momentWithTime(moment, item.time)
    const delay = Math.round((at.getTime() - moment.getTime()) / 1000)
    if (delay < MIN_LEAD_SECONDS || delay > MAX_LOOKAHEAD_SECONDS) continue

    try {
      uni.createPushMessage({
        title: (item.time || '') + ' ' + (item.type || '提醒'),
        content: item.title || '该做今天这件事了',
        delay,
        sound: 'system',
        payload: { type: 'local-reminder', planItemId: item.id, time: item.time }
      })
      state.scheduled[key] = true
      scheduled += 1
    } catch (e) {
      // 单条排不上不影响其它条
      push.lastError = '本地提醒排不上：' + ((e && e.message) || e)
    }
  }

  if (scheduled) {
    saveSchedule(state)
    push.scheduled = Object.keys(state.scheduled).length
  }
  return scheduled
}

/** 监听推送消息（在 App.vue 的 onLaunch 里调用，必须在收到消息之前注册） */
export function listenPushMessages(handlers) {
  if (typeof uni === 'undefined' || typeof uni.onPushMessage !== 'function') return false
  uni.onPushMessage((res) => {
    const payload = (res && res.data) || {}
    if (handlers && typeof handlers.onMessage === 'function') {
      handlers.onMessage({ type: (res && res.type) || '', payload })
    }
  })
  return true
}

/**
 * 一条推送消息该做什么（纯函数，便于测试）：见 uni-push 文档的两个 type
 * - `receive` 应用在线直接收到 → 只刷新提醒，别跳页（老人可能正在看别的）
 * - `click`   老人点了通知栏消息 → 说明他就是来处理这件事的，进日程页打卡
 */
export function pushAction(info) {
  const type = (info && info.type) || ''
  return type === 'click' ? 'open-plans' : 'refresh'
}

/** 推送状态（含服务端是否配好云函数） */
export function fetchStatus(elderId) {
  return fetchPushStatus({ elderId: elderId || push.elderId }).catch(() => null)
}

/** 打开系统的通知设置页（老人/家属排查"收不到提醒"时用） */
export function openNotificationSettings() {
  try {
    if (typeof plus !== 'undefined' && plus.runtime && plus.runtime.openURL) {
      // Android 各厂商跳转不同，这里只做"尽力而为"，失败不影响其它功能
      plus.runtime.openURL('app-settings:')
    } else {
      uni.showToast({ title: '请在手机设置里打开通知', icon: 'none' })
    }
  } catch (e) {
    uni.showToast({ title: '请在手机设置里打开通知', icon: 'none' })
  }
}

/* ------------------------------------------------------------------ 内部 */

function loadSchedule(day) {
  const raw = readLocal(SCHEDULE_KEY)
  let state = null
  try {
    state = raw ? JSON.parse(raw) : null
  } catch (e) {
    state = null
  }
  if (!state || state.day !== day || typeof state.scheduled !== 'object') {
    // 跨天就整体重置：昨天的排程没必要留着，也避免存储无限增长
    state = { day, scheduled: {} }
  }
  return state
}

function saveSchedule(state) {
  writeLocal(SCHEDULE_KEY, JSON.stringify(state))
}

function momentWithTime(day, hhmm) {
  const parts = hhmm.split(':')
  const at = new Date(day.getTime())
  at.setHours(Number(parts[0]), Number(parts[1]), 0, 0)
  return at
}

function dayKey(moment) {
  return [
    moment.getFullYear(),
    String(moment.getMonth() + 1).padStart(2, '0'),
    String(moment.getDate()).padStart(2, '0')
  ].join('-')
}

function platformName() {
  try {
    // uni.getSystemInfoSync 在 App 端返回 platform: android / ios
    const info = uni.getSystemInfoSync ? uni.getSystemInfoSync() : null
    return (info && (info.platform || info.osName)) || ''
  } catch (e) {
    return ''
  }
}

function appVersion() {
  try {
    const info = uni.getSystemInfoSync ? uni.getSystemInfoSync() : null
    return (info && info.appVersion) || ''
  } catch (e) {
    return ''
  }
}

function readLocal(key) {
  try {
    return uni.getStorageSync(key) || ''
  } catch (e) {
    return ''
  }
}

function writeLocal(key, value) {
  try {
    uni.setStorageSync(key, value)
  } catch (e) {
    // 存储失败不影响本次会话
  }
}

export default push
