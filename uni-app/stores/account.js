/**
 * 比邻AI · 账号会话
 *
 * 管三样东西：会话 token、当前账号（名字 + 8 位编号 + 头像）、以及登录态。
 *
 * 【为什么账号数据要落本地存储，而不是只放内存 reactive】
 * 两个原因：
 * 1. **冷启动就有名字和编号可显示**。如果只放内存，App 一启动「我的」页会先空一下，
 *    老人看到自己的名字闪一下才出来，体感很差。
 * 2. **回避打包器的一个坑**。实测本项目的 uni-app H5 产物会把 store 内联进多个 chunk，
 *    导致**页面模板里直接引用 store 的模块绑定会变成 undefined**（整页白屏）。
 *    所以这里复用了本地存储当权威来源：页面通过 readAccount() 取数据放进自己的 ref，
 *    模板不碰模块绑定。
 *
 * token 也一并落盘：老人不该每次打开 App 都重新输密码。
 */

import { reactive } from 'vue'
import { fetchMe, loginAccount, registerAccount, updateAvatar } from '@/api/index.js'

const TOKEN_KEY = 'bl_account_token'
const ACCOUNT_KEY = 'bl_account_profile'

/** 会话状态：token 与账号资料（模板请用 readAccount() 取，不要直接绑模块） */
export const session = reactive({
  token: '',
  account: null,
  ready: false,
  lastError: ''
})

/**
 * 账号变化事件名。
 *
 * 为什么需要它：`initAccount()` 向服务端确认是**异步**的，
 * 而页面（如「我的」页）通常只在 setup 时读一次 readAccount()。
 * 没有这个事件，服务端回来的最新资料（比如换过的头像）就不会反映到界面上
 * ——页面会一直显示冷启动时的那份缓存。
 *
 * 用法：页面 onMounted 里 uni.$on(EVENT_ACCOUNT_CHANGED, handler)，onUnmounted 里 uni.$off。
 */
export const EVENT_ACCOUNT_CHANGED = 'bl:account-changed'

function emitChange(account) {
  try {
    uni.$emit(EVENT_ACCOUNT_CHANGED, account ? Object.assign({}, account) : null)
  } catch (e) {
    // 发不出去不影响主流程
  }
}

/** 账号编号固定 8 位；对外展示时统一走这个格式（别做数值运算） */
export const NUMBER_WIDTH = 8

const pad = (value, width) => String(value == null ? '' : value).padStart(width, '0')

/* ------------------------------------------------------------------ 本地存储 */

function readLocal(key) {
  try {
    const raw = uni.getStorageSync(key)
    return raw || ''
  } catch (e) {
    return ''
  }
}

function writeLocal(key, value) {
  try {
    if (value) uni.setStorageSync(key, value)
    else uni.removeStorageSync(key)
  } catch (e) {
    // 存不上不影响本次使用
  }
}

function parseAccount(raw) {
  if (!raw) return null
  try {
    const data = typeof raw === 'string' ? JSON.parse(raw) : raw
    return data && data.number ? data : null
  } catch (e) {
    return null
  }
}

function persist(token, account) {
  writeLocal(TOKEN_KEY, token || '')
  writeLocal(ACCOUNT_KEY, account ? JSON.stringify(account) : '')
}

/* ------------------------------------------------------------------ 读接口 */

/**
 * 当前账号（副本）。页面请把它放进自己的 ref 渲染。
 * 冷启动时数据来自本地缓存，所以第一次渲染就有名字和编号。
 */
export function readAccount() {
  if (session.account) return Object.assign({}, session.account)
  const cached = parseAccount(readLocal(ACCOUNT_KEY))
  if (cached) session.account = cached
  return cached ? Object.assign({}, cached) : null
}

export function readToken() {
  if (session.token) return session.token
  session.token = readLocal(TOKEN_KEY) || ''
  return session.token
}

export function isLoggedIn() {
  return !!(readToken() && readAccount())
}

/** 编号展示文案：`ID:00000000`（按需求格式） */
export function idText(account) {
  const target = account || readAccount()
  if (!target || !target.number) return ''
  return 'ID:' + pad(target.number, NUMBER_WIDTH)
}

/** 名字首字（没头像时画占位） */
export function initialOf(account) {
  const target = account || readAccount()
  const name = (target && target.name) || ''
  return name ? name.slice(0, 1) : ''
}

/* ------------------------------------------------------------------ 生命周期 */

/**
 * 冷启动：先用本地缓存顶上，再向服务端确认一次。
 * 服务端说会话过期了就清掉登录态（老人会回到「请登录或注册」）。
 */
export function initAccount() {
  const cached = parseAccount(readLocal(ACCOUNT_KEY))
  const token = readLocal(TOKEN_KEY) || ''
  session.token = token
  session.account = cached
  session.ready = true

  if (!token) return Promise.resolve(null)

  return fetchMe(token)
    .then((data) => {
      const account = (data && data.account) || null
      session.account = account
      session.lastError = ''
      persist(token, account)
      // 通知页面：这是服务端确认后的最新资料（页面 setup 时读到的只是本地缓存）
      emitChange(account)
      return account
    })
    .catch((error) => {
      // 401 = 会话真的失效了，清掉；其它错误（网络不通）保留缓存，
      // 否则老人一断网就被登出，得重新输密码
      const status = (error && error.statusCode) || 0
      session.lastError = (error && error.message) || ''
      if (status === 401) {
        // 会话真的失效了：清掉并通知页面回到「请登录或注册」
        signOut()
      }
      return session.account
    })
}

/** 退出登录（清本地与内存） */
export function signOut() {
  session.token = ''
  session.account = null
  persist('', null)
  emitChange(null)
  return true
}

/* ------------------------------------------------------------------ 登录 / 注册 */

/**
 * 登录。
 * @returns {Promise<{ok:boolean, account?:object, message?:string}>}
 */
export function signIn(name, password) {
  return loginAccount({ name, password })
    .then((data) => {
      applySession(data)
      return { ok: true, account: session.account }
    })
    .catch((error) => ({ ok: false, message: friendly(error) }))
}

/**
 * 注册。成功即登录态，并拿到 8 位编号。
 * @returns {Promise<{ok:boolean, account?:object, message?:string}>}
 */
export function signUp(name, password, confirm) {
  return registerAccount({ name, password, confirm })
    .then((data) => {
      applySession(data)
      return { ok: true, account: session.account }
    })
    .catch((error) => ({ ok: false, message: friendly(error) }))
}

function applySession(data) {
  const token = (data && data.token) || ''
  const account = (data && data.account) || null
  session.token = token
  session.account = account
  session.lastError = ''
  persist(token, account)
  emitChange(account)
}

/**
 * 换头像。先本地生效（老人马上看到），再上传；失败就把本地改回去。
 * @returns {Promise<{ok:boolean, message?:string}>}
 */
export function changeAvatar(avatar) {
  const token = readToken()
  if (!token) return Promise.resolve({ ok: false, message: '请先登录' })

  const previous = session.account ? Object.assign({}, session.account) : null
  if (session.account) {
    session.account = Object.assign({}, session.account, { avatar: avatar || '' })
    persist(token, session.account)
  }

  return updateAvatar(token, avatar)
    .then((data) => {
      const account = (data && data.account) || null
      if (account) {
        session.account = account
        persist(token, account)
        emitChange(account)
      }
      return { ok: true, account: session.account }
    })
    .catch((error) => {
      // 上传失败回滚，别让界面显示一个服务端并不认的头像
      if (previous) {
        session.account = previous
        persist(token, previous)
        emitChange(previous)
      }
      return { ok: false, message: friendly(error) }
    })
}

/**
 * 把接口错误翻成给老人看的一句话。
 *
 * `api/request.js` 已经把服务端的 `{error:{code,message}}` 归一成扁平的
 * `{code, statusCode, message}`，且 `message` 就是中文文案（错误码表是唯一事实来源）。
 * 所以这里直接用 `error.message`，只对网络层那两种兜个更口语的说法。
 */
function friendly(error) {
  if (!error) return '出了点问题，再试一次'
  const code = error.code || ''
  if (code === 'network') return '连不上服务器，让家里人看一下'
  if (error.message) {
    if (/timeout|超时/i.test(error.message)) return '网络有点慢，再试一次'
    return error.message
  }
  return '出了点问题，再试一次'
}

export default session
