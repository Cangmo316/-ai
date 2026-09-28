/**
 * 比邻AI · 非流式请求封装（历史消息、打卡、计划等常规接口用）
 *
 * 统一三件事，避免每个页面各写一遍：
 *   1) header / baseURL 拼接
 *   2) 失败原因归一化成 { code, message, statusCode, retryable }
 *   3) 把中文错误提示翻译成老人看得懂的话（不要说「网络异常 -1」这种）
 */

import { TIMEOUT } from './config.js'

/**
 * @param {object} options
 * @param {string} options.url            完整 URL
 * @param {string} [options.method]       GET / POST / PUT / PATCH / DELETE
 * @param {object} [options.data]
 * @param {object} [options.header]
 * @param {number} [options.timeout]
 * @returns {Promise<any>} 解析后的响应体（JSON 优先）
 */
export function request(options) {
  const method = options.method || 'GET'
  const header = Object.assign({ Accept: 'application/json' }, options.header || {})
  // uni.request 默认就是 application/json，这里显式写出来：小程序端、以及联调用的 Node 桩
  // 都不会因为"平台默认值不同"而把 JSON 当纯文本发（服务端会直接 422）
  if (options.data !== undefined && method !== 'GET') {
    const hasType = header['Content-Type'] || header['content-type']
    if (!hasType) header['Content-Type'] = 'application/json'
  }

  return new Promise((resolve, reject) => {
    uni.request({
      url: options.url,
      method,
      data: options.data,
      header,
      timeout: options.timeout || TIMEOUT.total,
      success(res) {
        const body = parseBody(res.data)
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(body)
          return
        }
        reject({
          code: 'http',
          statusCode: res.statusCode,
          message: messageOf(res.statusCode, body),
          retryable: res.statusCode >= 500 || res.statusCode === 429
        })
      },
      fail(err) {
        reject({
          code: 'network',
          message: '连不上服务器',
          retryable: true,
          detail: (err && err.errMsg) || String(err)
        })
      }
    })
  })
}

/** uni.request 在 dataType=json 时已自动解析；这里只兜住「content-type 不对」的情况 */
export function parseBody(data) {
  if (typeof data !== 'string') return data
  const text = data.trim()
  if (!text) return null
  if (text.charAt(0) !== '{' && text.charAt(0) !== '[') return data
  try {
    return JSON.parse(text)
  } catch (e) {
    return data
  }
}

/** 服务端错误体约定：{ error: { code, message } } */
function messageOf(statusCode, body) {
  if (body && body.error && body.error.message) return body.error.message
  if (statusCode === 401 || statusCode === 403) return '登录已过期，让家里人重新登录一下'
  if (statusCode === 404) return '这个功能还没上线'
  if (statusCode === 429) return '说得太快了，歇一会儿再说'
  if (statusCode >= 500) return '服务器开小差了，一会儿再试'
  return '请求失败（' + statusCode + '）'
}
