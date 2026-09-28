#!/usr/bin/env node
/**
 * 比邻AI · node 侧的 `uni` 运行时桩（给 tools/ 下的端侧测试用）
 *
 * 端侧代码调的是 `uni.request` / `uni.getStorageSync`，裸 node 里没有这些全局对象。
 * 这个桩要尽量**像真的 uni.request**，否则测试会骗自己——踩过的坑：
 * `uni.request` 默认 content-type 就是 application/json，桩里漏了这一条，
 * 服务端收到的是 text/plain，pydantic 直接把整个 body 当 bytes，报 422。
 * 后来改成"只在调用方没给 content-type 时补默认值"（大小写不敏感），
 * 避免同一请求里出现两个 content-type 头。
 */

/* eslint-disable no-undef */

/**
 * 调用记录与本地存储在整个进程内共享：
 * 真实设备上 `uni` 只有一个、storage 也只有一份，如果每次 installUniStub() 都换新对象，
 * 测试里提前解构出来的 `calls` 就会变成"旧对象"，断言永远看不到新调用（踩过这个坑）。
 * 需要干净起点时用返回的 `reset()`。
 */
const calls = { navigate: [], vibrate: [], toast: [], localNotify: [] }
const storage = new Map()

export function installUniStub(options = {}) {
  const pushListeners = []
  const cid = options.cid === undefined ? 'cid_test_000047d1' : options.cid
  const pushFails = options.pushFails === true
  const platform = options.platform || 'android'

  globalThis.uni = {
    getStorageSync(key) {
      return storage.has(key) ? storage.get(key) : ''
    },
    setStorageSync(key, value) {
      storage.set(key, value)
    },
    removeStorageSync(key) {
      storage.delete(key)
    },
    navigateTo(options) {
      calls.navigate.push((options && options.url) || '')
    },
    switchTab(options) {
      calls.navigate.push((options && options.url) || '')
    },
    reLaunch(options) {
      calls.navigate.push((options && options.url) || '')
    },
    vibrateLong() {
      calls.vibrate.push('long')
    },
    vibrateShort() {
      calls.vibrate.push('short')
    },
    showToast(options) {
      calls.toast.push((options && options.title) || '')
    },
    getSystemInfoSync() {
      return { platform, osName: platform, appVersion: '1.0.0-test' }
    },
    /** uni-push：拿客户端推送标识（cid）。options.pushFails=true 模拟"没开通/标准基座" */
    getPushClientId(handlers = {}) {
      if (pushFails || !cid) {
        if (handlers.fail) handlers.fail({ errMsg: 'getPushClientId:fail register fail' })
        return
      }
      if (handlers.success) handlers.success({ cid, errMsg: 'getPushClientId:ok' })
    },
    /** 创建本地通知栏消息（App 端专属，支持 delay 秒） */
    createPushMessage(opts = {}) {
      calls.localNotify.push(Object.assign({}, opts))
      if (opts.success) opts.success({})
    },
    /** 监听推送消息；测试用 stub.emitPush() 模拟收到 */
    onPushMessage(callback) {
      pushListeners.push(callback)
    },
    offPushMessage(callback) {
      const at = pushListeners.indexOf(callback)
      if (at !== -1) pushListeners.splice(at, 1)
    },
    /** 非流式请求走这里（流式走 fetch，见 transport.js 的 H5 分支） */
    request(options) {
      const method = options.method || 'GET'
      const provided = options.header || {}
      const hasContentType = Object.keys(provided).some(
        (key) => key.toLowerCase() === 'content-type'
      )
      const headers = Object.assign({}, provided)
      if (!hasContentType) headers['content-type'] = 'application/json'

      const init = { method, headers }
      if (options.data !== undefined && method !== 'GET') {
        init.body = JSON.stringify(options.data)
      }

      fetch(options.url, init)
        .then(async (res) => {
          const text = await res.text()
          let data = text
          try {
            data = JSON.parse(text)
          } catch (e) {
            // 保留原文，交给调用方判断
          }
          if (options.success) options.success({ statusCode: res.status, data, header: {} })
          if (options.complete) options.complete()
        })
        .catch((error) => {
          if (options.fail) options.fail({ errMsg: 'request:fail ' + error.message })
          if (options.complete) options.complete()
        })
      return { abort() {} }
    }
  }

  return {
    storage,
    calls,
    /** 模拟收到一条推送（type: 'receive' 在线收到 / 'click' 点了通知栏） */
    emitPush(message) {
      for (const listener of pushListeners.slice()) listener(message)
    },
    /** 去掉某个 API，模拟 H5/小程序/标准基座的能力缺失 */
    removeApi(name) {
      delete globalThis.uni[name]
    },
    /** 清空调用记录与本地存储（需要干净起点的用例自己调） */
    reset() {
      calls.navigate.length = 0
      calls.vibrate.length = 0
      calls.toast.length = 0
      calls.localNotify.length = 0
      storage.clear()
      pushListeners.length = 0
    }
  }
}

export default installUniStub
