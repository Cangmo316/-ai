/**
 * 比邻AI · 家人端（浏览器）的 uni 运行时垫片
 *
 * 为什么需要它：`uni-app/api/` 那一层是围绕 `uni.request` / `uni.getStorageSync` 写的。
 * 家人端跑在浏览器里，没有这些对象，但我们**不想为它再写一套接口客户端**——
 * 那就等于契约有两份实现，迟早不一致。
 *
 * 所以这里补一个最小垫片，让家人端直接 import 端侧那套 `api/plans.js`：
 * 同一份契约实现，两个前端（老人端 App + 家人端浏览器）。
 * 顺带得到一个好处：家人端一旦跑通，就证明这层 api 是"前端无关"的。
 */

const memory = new Map()

function storageGet(key) {
  try {
    if (typeof localStorage !== 'undefined') return localStorage.getItem(key) || ''
  } catch (e) {
    // 隐私模式等场景下 localStorage 可能不可用，退回内存
  }
  return memory.has(key) ? memory.get(key) : ''
}

function storageSet(key, value) {
  memory.set(key, value)
  try {
    if (typeof localStorage !== 'undefined') localStorage.setItem(key, value)
  } catch (e) {
    // 忽略：内存里也有一份
  }
}

function storageRemove(key) {
  memory.delete(key)
  try {
    if (typeof localStorage !== 'undefined') localStorage.removeItem(key)
  } catch (e) {
    // 忽略
  }
}

/** 安装 globalThis.uni（重复调用幂等） */
export function installUniShim() {
  if (globalThis.uni && globalThis.uni.__familyShim) return globalThis.uni

  globalThis.uni = {
    __familyShim: true,
    getStorageSync: storageGet,
    setStorageSync: storageSet,
    removeStorageSync: storageRemove,
    showToast(options) {
      // 家人端不需要 uni 的 toast，控制台留痕即可
      if (typeof console !== 'undefined') console.info('[toast]', (options && options.title) || '')
    },
    request(options) {
      const method = options.method || 'GET'
      const provided = options.header || {}
      const hasContentType = Object.keys(provided).some(
        (key) => key.toLowerCase() === 'content-type'
      )
      const headers = Object.assign({}, provided)
      if (!hasContentType) headers['content-type'] = 'application/json'

      const init = { method, headers }
      if (options.data !== undefined && method !== 'GET') init.body = JSON.stringify(options.data)

      fetch(options.url, init)
        .then(async (res) => {
          const text = await res.text()
          let data = text
          try {
            data = JSON.parse(text)
          } catch (e) {
            // 保留原文
          }
          if (options.success) options.success({ statusCode: res.status, data, header: {} })
          if (options.complete) options.complete()
        })
        .catch((error) => {
          if (options.fail) options.fail({ errMsg: 'request:fail ' + (error && error.message) })
          if (options.complete) options.complete()
        })

      return { abort() {} }
    }
  }

  return globalThis.uni
}

export default installUniShim
