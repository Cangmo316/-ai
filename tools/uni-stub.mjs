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

export function installUniStub() {
  const storage = new Map()
  /** 记录端侧调用，便于断言（导航、震动、toast） */
  const calls = { navigate: [], vibrate: [], toast: [] }

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

  return { storage, calls }
}

export default installUniStub
