/**
 * 语音识别（老人端「按住说话」）
 *
 * 把"录音 → 上传 → 识别文本"封装成一次调用，通话页只管拿到文本去提问。
 *
 * ## 为什么录音分两套实现
 * 各端录音 API **完全不通用**，没有第二选择：
 *   · H5   ：必须用浏览器原生 `MediaRecorder` + `getUserMedia`
 *            （`uni.getRecorderManager()` 在 H5 上是空壳）
 *   · App  ：用 `uni.getRecorderManager()`（原生录音，不依赖浏览器权限模型）
 * 所以这里按平台分支，但**对外只暴露同一组 `start()/stop()`**。
 *
 * ## ⚠️ 隐私
 * · 录音**只在内存/临时路径**存在，上传成功后**立即废弃**，不留档
 * · **不写日志、不上报到任何第三方** —— 音频只发往本项目自己的后端
 *   （后端 `app/asr/privacy.py` 保证用完即删、不记日志）
 * · 失败时明确告知，让老人知道"没听清"，而不是猜
 *
 * ## 浏览器限制（H5）
 * `getUserMedia` 只在 **HTTPS 或 localhost** 下可用。真机联调走 http 内网地址时
 * H5 录音会被浏览器拒绝，此时应改用 App 端（`uni.getRecorderManager()`）或配 https。
 * 这个限制没法绕过，所以错误信息里直接说清楚。
 */

import { resolveURL, authHeaders, ENDPOINTS, getApiToken } from './config.js'

/** 单次录音上限（秒）：后端限 8MB，16kHz 单声道 wav 约 1.9MB/60s，60 秒足够一句话 */
export const MAX_RECORD_SECONDS = 60

/** 当前环境能否录音（用于按钮置灰，而不是点下去才报错） */
export function canRecord() {
  // #ifdef H5
  const ok = typeof navigator !== 'undefined'
    && navigator.mediaDevices
    && typeof navigator.mediaDevices.getUserMedia === 'function'
    && typeof window !== 'undefined'
    && typeof window.MediaRecorder === 'function'
  return !!ok
  // #endif
  // #ifndef H5
  return typeof uni !== 'undefined' && typeof uni.getRecorderManager === 'function'
  // #endif
}

/** H5 的录音实现（MediaRecorder）。返回 { stop } */
function createH5Recorder() {
  let recorder = null
  let chunks = []
  let stream = null

  const start = () => new Promise((resolve, reject) => {
    if (!canRecord()) {
      reject(new Error('这个浏览器不支持录音（需要 HTTPS 或 localhost）'))
      return
    }
    navigator.mediaDevices.getUserMedia({ audio: true }).then((mediaStream) => {
      stream = mediaStream
      chunks = []
      // 不指定 mimeType：各浏览器支持的格式不同（Chrome 偏 webm/opus、Safari 只有 mp4/aac），
      // 让浏览器自己选，上传时按真实 mimeType 报给后端（后端按它推断扩展名）。
      recorder = new window.MediaRecorder(mediaStream)
      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) chunks.push(event.data)
      }
      recorder.start()
      resolve()
    }).catch((error) => {
      // 权限被拒 / 没有麦克风：给老人能看懂的话，别抛原始英文
      const name = error && error.name
      if (name === 'NotAllowedError') reject(new Error('没有麦克风权限，请在浏览器里允许'))
      else if (name === 'NotFoundError') reject(new Error('没找到麦克风'))
      else reject(new Error('打不开麦克风'))
    })
  })

  const stop = () => new Promise((resolve) => {
    if (!recorder || recorder.state === 'inactive') {
      resolve(null)
      return
    }
    recorder.onstop = () => {
      const type = recorder.mimeType || 'audio/webm'
      const blob = new Blob(chunks, { type })
      // 用完立刻关掉音轨：麦克风指示灯不该一直亮着（老人会以为在被偷听）
      if (stream) {
        stream.getTracks().forEach((track) => track.stop())
        stream = null
      }
      recorder = null
      chunks = []
      resolve({ blob, mimeType: type, extension: extensionOf(type) })
    }
    recorder.stop()
  })

  return { start, stop }
}

/** App 的录音实现（uni.getRecorderManager） */
function createAppRecorder() {
  const manager = uni.getRecorderManager()
  let resolveStop = null
  let rejected = null

  // 一次性绑定回调（manager 是单例，不能每次 start 都绑，否则重复触发）
  manager.onStop((res) => {
    if (resolveStop) {
      resolveStop({ path: res.tempFilePath, duration: res.duration })
      resolveStop = null
    }
  })
  manager.onError((error) => {
    if (rejected) {
      rejected(new Error((error && error.errMsg) || '录音出错了'))
      rejected = null
    }
  })

  const start = () => new Promise((resolve, reject) => {
    if (!canRecord()) {
      reject(new Error('这个设备不支持录音'))
      return
    }
    try {
      manager.start({
        duration: MAX_RECORD_SECONDS * 1000,
        sampleRate: 16000,
        numberOfChannels: 1,
        // 16k 单声道 wav：体积小、ASR 引擎普遍直接支持，后端不必转码
        format: 'wav',
      })
      resolve()
    } catch (error) {
      reject(new Error('打不开麦克风'))
    }
  })

  const stop = () => new Promise((resolve, reject) => {
    resolveStop = resolve
    rejected = reject
    try {
      manager.stop()
    } catch (error) {
      reject(new Error('停止录音失败'))
    }
  })

  return { start, stop }
}

function extensionOf(mimeType) {
  const text = String(mimeType || '').toLowerCase()
  if (text.includes('webm')) return 'webm'
  if (text.includes('ogg')) return 'ogg'
  if (text.includes('mp4') || text.includes('aac') || text.includes('m4a')) return 'm4a'
  if (text.includes('wav')) return 'wav'
  if (text.includes('mpeg') || text.includes('mp3')) return 'mp3'
  return 'webm'
}

/**
 * 一个"按住说话"会话。
 *
 * 用法::
 *     const session = createRecordingSession()
 *     await session.start()          // 按下
 *     const result = await session.finish()   // 松手 → 上传 → 拿到文本
 *     if (result.ok) ask(result.text)
 */
export function createRecordingSession() {
  let recorder = null
  let startedAt = 0

  return {
    get recording() { return !!recorder },

    async start() {
      // #ifdef H5
      recorder = createH5Recorder()
      // #endif
      // #ifndef H5
      recorder = createAppRecorder()
      // #endif
      await recorder.start()
      startedAt = Date.now()
      return { ok: true }
    },

    /**
     * 松手：停止录音并上传识别。
     *
     * @returns {Promise<{ok:boolean, text?:string, reason?:string, durationMs?:number}>}
     *          失败**不抛异常**，统一返回 `ok:false` + `reason`——
     *          调用方（适老页面）需要的是"给一句人话"，不是错误栈。
     */
    async finish() {
      if (!recorder) return { ok: false, reason: '没有在录音' }
      const current = recorder
      recorder = null                 // 先置空：避免连点导致重复上传
      const durationMs = Date.now() - startedAt
      // 太短（<400ms）基本是误触，不必浪费一次上传与一次计费
      if (durationMs < 400) {
        try { await current.stop() } catch (error) { void error }
        return { ok: false, reason: '说话时间太短了' }
      }
      let payload = null
      try {
        payload = await current.stop()
      } catch (error) {
        return { ok: false, reason: '录音出错了' }
      }
      if (!payload) return { ok: false, reason: '没有录到声音' }

      // #ifdef H5
      return uploadBlob(payload.blob, payload.extension, payload.mimeType, durationMs)
      // #endif
      // #ifndef H5
      return uploadFile(payload.path, 'wav', durationMs)
      // #endif
    },

    /** 放弃这次录音（老人中途反悔 / 页面离开） */
    async cancel() {
      if (!recorder) return
      const current = recorder
      recorder = null
      try { await current.stop() } catch (error) { void error }
    },
  }
}

/* ------------------------------------------------------------------ 上传 */

/** 统一把后端的业务响应翻译成 `{ok, text, reason}`（失败不抛，交给页面提示） */
function interpret(body) {
  if (!body || typeof body !== 'object') return { ok: false, reason: '没听清，再说一次' }
  if (body.ok && body.text) return { ok: true, text: String(body.text).trim() }
  // 后端的 reason 是给部署方看的中文说明，可以直接展示
  return { ok: false, reason: body.reason || '没听清，再说一次' }
}

/** H5：直接 POST 二进制（用 FormData 让浏览器自己生成 multipart 边界） */
function uploadBlob(blob, extension, mimeType, durationMs) {
  return new Promise((resolve) => {
    const url = resolveURL(ENDPOINTS.asrTranscribe)
    const form = new FormData()
    form.append('file', blob, 'speech.' + (extension || 'webm'))
    // 不手动设 Content-Type：必须让浏览器带 boundary，否则后端解不出来
    const xhr = new XMLHttpRequest()
    xhr.open('POST', url, true)
    // 鉴权头必须手动带（XHR 不会自动加）；`authHeaders()` 是和 request/transport 共用的那一份
    const header = authHeaders({})
    if (header.Authorization) xhr.setRequestHeader('Authorization', header.Authorization)
    xhr.onload = () => {
      let body = null
      try { body = JSON.parse(xhr.responseText) } catch (error) { body = null }
      const result = interpret(body)
      resolve(Object.assign({ durationMs, mimeType }, result))
    }
    xhr.onerror = () => resolve({ ok: false, reason: '网络不太好，再试一次', durationMs })
    xhr.ontimeout = () => resolve({ ok: false, reason: '识别太慢了，再试一次', durationMs })
    xhr.timeout = 20000
    xhr.send(form)
  })
}

/** App：用 uni.uploadFile 传本地临时文件 */
function uploadFile(path, extension, durationMs) {
  return new Promise((resolve) => {
    uni.uploadFile({
      url: resolveURL(ENDPOINTS.asrTranscribe),
      // 只传 files 不传 filePath：两者同时给时 H5 会重复发一次（见 api/cases.js 的说明）
      files: [{ name: 'file', uri: path }],
      name: 'file',
      header: authHeaders({}),
      success(res) {
        let body = res.data
        if (typeof body === 'string') {
          try { body = JSON.parse(body) } catch (error) { body = null }
        }
        resolve(Object.assign({ durationMs }, interpret(body)))
      },
      fail() {
        resolve({ ok: false, reason: '网络不太好，再试一次', durationMs })
      },
    })
  })
}
