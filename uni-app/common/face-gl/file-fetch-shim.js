/**
 * 比邻AI · App 端 file:// 资源加载垫片（renderjs 专用）
 *
 * ## 为什么需要它
 *
 * uni-app 的 App 端页面跑在 `file://` 协议下（H5 端是 `http://`），
 * 而 three.js 的 `FileLoader` 用的是 **Fetch API**：
 *
 *     const req = new Request(url, {...}); fetch(req)
 *
 * WebView 的 `fetch` **不支持 `file://`**，会抛：
 *
 *     Fetch API cannot load file:///.../static/avatar/QDoctor_60k.glb?v=8
 *     URL scheme "file" is not supported.
 *
 * 而 **XMLHttpRequest 支持 `file://`**。所以只把 `file://` 的请求改成走 XHR，
 * 其它（http/https）**原样交给原生 fetch** —— 不改变任何网络行为。
 *
 * ## 为什么不在 three 里改
 *
 * `libs/three/` 是上游库，改了以后升级会被覆盖，也不好区分"上游代码"和"我们的补丁"。
 * 垫片挂在入口处，作用域清楚。
 *
 * ## 什么时候可以删掉
 *
 * 如果将来资源改用 `plus.io` 或 uni-app 的本地文件 API 读取、不再走 fetch，
 * 这个垫片就没有存在价值了。
 */

const FILE_PREFIX = 'file://'

/** 排障用：垫片调用痕迹（真机上看 console 就能判断装没装、拦没拦到） */
function trace(msg) {
  try {
    if (typeof window === 'undefined') return
    window.__blShimTrace = window.__blShimTrace || []
    if (window.__blShimTrace.length < 40) window.__blShimTrace.push(msg)
  } catch (e) { /* 观测失败不能影响主流程 */ }
}

/** 把 fetch 的入参（string / URL / Request）统一取出 url 字符串 */
function urlOf(input) {
  if (typeof input === 'string') return input
  if (!input) return ''
  if (typeof input.url === 'string') return input.url   // Request 对象
  return String(input)
}

/**
 * 用 XHR 读 `file://`，返回一个"够用"的 Response。
 *
 * 只需要满足 three 的 FileLoader：`response.body` 读流、`response.ok`、
 * `response.status`、`response.arrayBuffer()`。所以不实现完整的 Response。
 */
function xhrAsResponse(url) {
  return new Promise((resolve, reject) => {
    let xhr
    try {
      xhr = new XMLHttpRequest()
    } catch (e) {
      reject(e)
      return
    }
    xhr.open('GET', url, true)
    // 本地文件没有 MIME 信息，给个二进制兜底；GLTFLoader 只看字节
    try { xhr.responseType = 'arraybuffer' } catch (e) { void e }

    xhr.onload = () => {
      const buffer = xhr.response
      if (!buffer) {
        reject(new Error('读取本地资源失败（空内容）：' + url))
        return
      }
      // 尽量贴近 fetch 的 Response 形状
      const body = {
        getReader() {
          let done = false
          return {
            read() {
              if (done) return Promise.resolve({ done: true, value: undefined })
              done = true
              return Promise.resolve({ done: false, value: new Uint8Array(buffer) })
            },
            cancel() { return Promise.resolve() },
            releaseLock() {},
          }
        },
      }
      resolve({
        ok: true,
        status: 200,
        statusText: 'OK',
        url,
        headers: { get: () => null },
        body,
        arrayBuffer: () => Promise.resolve(buffer),
        // 有些调用方会走 text()（比如 .gltf JSON 或 mapper 文件）
        text: () => Promise.resolve(new TextDecoder().decode(new Uint8Array(buffer))),
        json: () => Promise.resolve(JSON.parse(new TextDecoder().decode(new Uint8Array(buffer)))),
      })
    }
    xhr.onerror = () => reject(new Error('读取本地资源失败：' + url))
    xhr.ontimeout = () => reject(new Error('读取本地资源超时：' + url))
    xhr.send()
  })
}

/**
 * 安装垫片。**幂等**：重复调用只装一次。
 *
 * @param {object} [scope] 安装到哪个全局对象上（默认 `window`，renderjs 里就是视图层的 window）
 * @returns {boolean} true = 已安装（或本来就在），false = 环境不支持（无 fetch，例如纯逻辑层）
 */
export function installFileFetchShim(scope) {
  const g = scope || (typeof window !== 'undefined' ? window : null)
  trace('install: g=' + (g ? 'ok' : 'null') + ' fetch=' + (g && typeof g.fetch) + ' already=' + !!(g && g.__blFileFetchShim))
  if (!g || typeof g.fetch !== 'function') return false
  if (g.__blFileFetchShim) return true

  const nativeFetch = g.fetch.bind(g)
  g.fetch = function (input, init) {
    const url = urlOf(input)
    if (url.indexOf(FILE_PREFIX) === 0) {
      trace('hit file:// …' + url.slice(-30))
      return xhrAsResponse(url)
    }
    trace('pass-through ' + url.slice(0, 40))
    return nativeFetch(input, init)
  }
  g.__blFileFetchShim = true
  return true
}

/**
 * 安装 XHR 加载兜底：把 GLTFLoader 的 FileLoader 换成走 XHR 的实现。
 *
 * 为什么还要这一层：垫片改的是 `fetch`，但 three 的 FileLoader 内部
 * 先构造 `new Request(url)` —— 某些 WebView 上 `new Request('file://…')`
 * 本身就会抛（在 fetch 之前）。这一层直接把"读字节"这件事交给 XHR，
 * 绕开 Request 的构造。
 *
 * @param {object} THREE three 命名空间（含 FileLoader）
 */
export function installXhrFileLoader(THREE, scope) {
  const g = scope || (typeof window !== 'undefined' ? window : null)
  if (!THREE || !THREE.FileLoader || !g || g.__blXhrFileLoader) return false
  const Native = THREE.FileLoader

  class XhrFileLoader extends Native {
    load(url, onLoad, onProgress, onError) {
      if (typeof url !== 'string' || url.indexOf(FILE_PREFIX) !== 0) {
        return super.load(url, onLoad, onProgress, onError)
      }
      let settled = false
      const fail = (err) => {
        if (settled) return
        settled = true
        if (onError) onError(err)
        else if (typeof console !== 'undefined') console.error('[file-loader]', err)
      }
      try {
        const xhr = new XMLHttpRequest()
        xhr.open('GET', url, true)
        xhr.responseType = 'arraybuffer'
        xhr.onload = () => {
          if (settled) return
          settled = true
          const buf = xhr.response
          if (!buf) { fail(new Error('空内容：' + url)); return }
          // FileLoader 的回调约定：拿到的是 ArrayBuffer
          if (onLoad) onLoad(buf)
        }
        xhr.onerror = () => fail(new Error('读取失败：' + url))
        xhr.send()
      } catch (e) {
        fail(e)
      }
    }
  }

  THREE.FileLoader = XhrFileLoader
  g.__blXhrFileLoader = true
  return true
}

export default { installFileFetchShim, installXhrFileLoader }
