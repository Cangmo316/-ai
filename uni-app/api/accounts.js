/**
 * 比邻AI · 账号接口（注册 / 登录 / 我的资料 / 换头像）
 *
 * 契约见 server/app/api/accounts.py。三件事值得记住：
 *
 * 1. **注册成功即登录态**：注册返回 token，端侧不用再登一次。
 * 2. **编号是 8 位字符串**（`"00000000"`），不是数字——别做数值运算，直接当字符串显示。
 * 3. **鉴权走 `Authorization: Bearer <token>`**，与服务端的接口级 token 是两个概念：
 *    那个答"谁能访问服务"，这个答"你是哪个账号"。
 */

import { ENDPOINTS, resolveURL } from './config.js'
import { request } from './request.js'

/** 带会话 token 的请求头 */
function authHeader(token) {
  return token ? { Authorization: 'Bearer ' + token } : {}
}

/**
 * 注册。
 * @param {object} params
 * @param {string} params.name      账号名称
 * @param {string} params.password  密码（8–16 位数字或字母）
 * @param {string} params.confirm   再次输入的密码
 * @returns {Promise<{token:string, expiresAt:string, account:object}>}
 */
export function registerAccount(params = {}) {
  return request({
    url: resolveURL(ENDPOINTS.accountRegister),
    method: 'POST',
    data: {
      name: params.name || '',
      password: params.password || '',
      confirm: params.confirm || ''
    }
  })
}

/**
 * 登录。
 * @returns {Promise<{token:string, expiresAt:string, account:object}>}
 */
export function loginAccount(params = {}) {
  return request({
    url: resolveURL(ENDPOINTS.accountLogin),
    method: 'POST',
    data: {
      name: params.name || '',
      password: params.password || ''
    }
  })
}

/** 我的资料（冷启动用它确认会话还有效） */
export function fetchMe(token) {
  return request({
    url: resolveURL(ENDPOINTS.accountMe),
    header: authHeader(token)
  })
}

/**
 * 换头像。
 * @param {string} avatar 预设名（`grandma`）或 data URI（`data:image/png;base64,...`）
 */
export function updateAvatar(token, avatar) {
  return request({
    url: resolveURL(ENDPOINTS.accountAvatar),
    method: 'POST',
    header: authHeader(token),
    data: { avatar: avatar || '' }
  })
}

/** 注册/换头像的固定选项（预设头像名等），端侧不用写死 */
export function fetchAccountOptions() {
  return request({ url: resolveURL(ENDPOINTS.accountOptions) })
}

/**
 * 按 8 位编号查账号（用于「绑定家人」时确认绑的是谁）。
 * @returns {Promise<{found:boolean, account:object|null}>}
 */
export function lookupAccount(number) {
  return request({
    url: resolveURL(ENDPOINTS.accountLookup) + '?number=' + encodeURIComponent(number || '')
  })
}