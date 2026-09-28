/**
 * 比邻AI · 推送标识登记接口
 *
 * 端侧拿到 cid（`uni.getPushClientId`）后报给服务端，服务端才知道提醒发到哪台设备。
 * 没有登记 cid 的老人，提醒只能靠站内消息（App 打开着才收得到）。
 */

import { ENDPOINTS, resolveURL } from './config.js'
import { request } from './request.js'

/**
 * 登记推送标识（同一 cid 重复登记是幂等的）
 * @param {object} params
 * @param {string} params.cid
 * @param {string} [params.elderId]
 * @param {string} [params.platform]
 * @param {string} [params.appVersion]
 */
export function registerPushClient(params) {
  return request({
    url: resolveURL(ENDPOINTS.pushRegister),
    method: 'POST',
    data: {
      cid: params.cid,
      elderId: params.elderId || 'e_1',
      platform: params.platform || '',
      appVersion: params.appVersion || ''
    }
  })
}

/** 注销（老人关掉推送 / 换设备时调用） */
export function unregisterPushClient(params) {
  return request({
    url: resolveURL(ENDPOINTS.pushUnregister),
    method: 'POST',
    data: { cid: params.cid }
  })
}

/** 推送通道自检：是否配好了云函数、这位老人登记了几台设备 */
export function fetchPushStatus(params = {}) {
  return request({
    url: resolveURL(ENDPOINTS.pushStatus) + '?elderId=' + encodeURIComponent(params.elderId || 'e_1')
  })
}
