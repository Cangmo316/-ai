/**
 * 比邻AI · 语音输入（按住说话 → 识别成文字）
 *
 * ## 为什么需要它
 *
 * 需求：「需要对每个语音输入功能真正接入语音输入功能」。
 * 之前麦克风按钮只弹一句"长按就能说话（语音在 P3 接入）"——**是占位，不是功能**。
 *
 * ## 两端录音 API 完全不同（主要复杂度）
 *
 * | | App（app-vue） | H5 |
 * |---|---|---|
 * | 录音 | `uni.getRecorderManager()` | `getUserMedia` + `MediaRecorder` |
 * | 产物 | 本地临时文件路径 | `Blob` |
 * | 上传 | `uni.uploadFile`（自带 multipart） | `FormData` + `XMLHttpRequest` |
 *
 * 对外只暴露 `start() / stop() / cancel()`，两端差异全关在本模块里。
 *
 * ## 降级要明确
 * 没权限 / 不支持 / 服务端没配 ASR，每种都给**中文原因**；**老人始终可以打字**。
 */

/** App 端录音参数：mp3、16k 单声道（服务端 _MIME 表已支持，体积也小） */
const APP_RECORD_OPTIONS = {
  format: 'mp3',
  sampleRate: 16000,
  numberOfChannels: 1,
  encodeBitRate: 48000
}

/** 最长录音时长（毫秒），与服务端 60 秒上限对齐 */
export const MAX_RECORD_MS = 60000

/** 当前环境能不能录音 */
export function voiceSupported() {
  // #ifdef APP-PLUS
  return { ok: true, reason: '' }
  // #endif
  // #ifndef APP-PLUS
  if (typeof navigator === 'undefined' || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    return { ok: false, reason: '这个环境不支持录音（需要 HTTPS 或 localhost）' }
  }
  if (typeof MediaRecorder === 'undefined') {
    return { ok: false, reason: '这个浏览器不支持录音' }
  }
  return { ok: true, reason: '' }
  // #endif
}

/**
 * 录音器。**一次录音用一个实例**，用完即弃（不要复用，状态太容易错）。
 *
 * @param {{onError?:(reason:string)=>void}} options
 */
export class VoiceRecorder {
  constructor(options) {
    const opt = options || {}
    this.onError = typeof opt.onError === 'function' ? opt.onError : () => {}
    this.state = 'idle'          // idle | recording | stopping | done
    /** 录音产物：App 端 { filePath, name }，H5 端 { blob, name } */
    this.result = null
    /** 内部：结束录音的收尾函数（把 promise resolve 掉） */
    this._finish = null
    /** 内部：App 端 recorderManager 的 stop 触发函数 */
    this._stopNative = null
  }

  _fail(reason) {
    this.state = 'idle'
    this.onError(reason)
    return { ok: false, reason }
  }

  /** 开始录音（H5 端会请求麦克风权限）。 */
  async start() {
    if (this.state === 'recording') return { ok: true, reason: '' }
    const support = voiceSupported()
    if (!support.ok) return this._fail(support.reason)

    // #ifdef APP-PLUS
    return this._startApp()
    // #endif

    // #ifndef APP-PLUS
    return this._startWeb()
    // #endif
  }

  /** 结束录音，返回 { ok, reason, audio }。audio 形如 {filePath|blob, name}。 */
  async stop() {
    if (this.state !== 'recording') return { ok: false, reason: '还没开始录音' }
    this.state = 'stopping'
    try {
      this._stopNative()
    } catch (e) {
      return this._fail('结束录音失败：' + ((e && e.message) || e))
    }
    if (!this._finish) return this._fail('结束录音失败')
    const outcome = await this._finish
    this.state = 'idle'
    if (!outcome || !outcome.ok) return this._fail((outcome && outcome.reason) || '录音失败')
    this.result = outcome.audio
    return { ok: true, reason: '', audio: outcome.audio }
  }

  /** 放弃这次录音（不上传）。 */
  cancel() {
    try { if (this._stopNative) this._stopNative() } catch (e) { void e }
    this.state = 'idle'
    this.result = null
  }

  /* ------------------------------------------------------------ App 端 */

  // #ifdef APP-PLUS
  _startApp() {
    const manager = uni.getRecorderManager()
    let settle = null
    this._finish = new Promise((resolve) => { settle = resolve })

    // 一次性监听：每次录音都重新绑，避免上一次的回调串进来
    manager.onStop((res) => {
      settle({ ok: true, audio: { filePath: res.tempFilePath, name: 'voice.mp3', size: res.fileSize || 0 } })
    })
    manager.onError((err) => {
      settle({ ok: false, reason: '录音失败：' + ((err && err.errMsg) || '未知原因') })
    })

    // 到点自动停（服务端也有上限，这里先掐住，免得传上去被拒）
    this._autoStopTimer = setTimeout(() => {
      try { manager.stop() } catch (e) { void e }
    }, MAX_RECORD_MS)

    this._stopNative = () => {
      if (this._autoStopTimer) { clearTimeout(this._autoStopTimer); this._autoStopTimer = null }
      manager.stop()
    }

    try {
      manager.start(APP_RECORD_OPTIONS)
    } catch (e) {
      return this._fail('录音启动失败：' + ((e && e.message) || e))
    }
    this.state = 'recording'
    return { ok: true, reason: '' }
  }
  // #endif

  /* ------------------------------------------------------------- H5 端 */

  // #ifndef APP-PLUS
  async _startWeb() {
    let stream = null
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (e) {
      const name = (e && e.name) || ''
      if (name === 'NotAllowedError') return this._fail('没拿到麦克风权限，请在浏览器/系统设置里允许')
      if (name === 'NotFoundError') return this._fail('没找到麦克风')
      return this._fail('录音启动失败：' + ((e && e.message) || e))
    }

    let settle = null
    this._finish = new Promise((resolve) => { settle = resolve })

    const chunks = []
    const mime = pickWebMime()
    let recorder = null
    try {
      recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
    } catch (e) {
      try { stream.getTracks().forEach((t) => t.stop()) } catch (e2) { void e2 }
      return this._fail('录音启动失败：' + ((e && e.message) || e))
    }

    recorder.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data) }
    recorder.onstop = () => {
      try { stream.getTracks().forEach((t) => t.stop()) } catch (e) { void e }
      const type = recorder.mimeType || 'audio/webm'
      const blob = new Blob(chunks, { type })
      if (!blob.size) { settle({ ok: false, reason: '没录到声音' }); return }
      settle({ ok: true, audio: { blob, name: 'voice' + suffixOf(type), size: blob.size } })
    }
    recorder.onerror = (e) => {
      try { stream.getTracks().forEach((t) => t.stop()) } catch (e2) { void e2 }
      settle({ ok: false, reason: '录音出错：' + ((e && e.error && e.error.name) || '未知') })
    }

    this._autoStopTimer = setTimeout(() => {
      try { if (recorder.state === 'recording') recorder.stop() } catch (e) { void e }
    }, MAX_RECORD_MS)

    this._stopNative = () => {
      if (this._autoStopTimer) { clearTimeout(this._autoStopTimer); this._autoStopTimer = null }
      if (recorder.state === 'recording') recorder.stop()
      else settle({ ok: false, reason: '录音已经结束了' })
    }

    try {
      recorder.start()
    } catch (e) {
      return this._fail('录音启动失败：' + ((e && e.message) || e))
    }
    this.state = 'recording'
    return { ok: true, reason: '' }
  }
  // #endif
}

/**
 * 把录音上传到 `/v1/asr/transcribe`，拿回文字。
 *
 * 两端各走各的上传：App 用 `uni.uploadFile`（原生 multipart，弱网更稳），
 * H5 用 `XMLHttpRequest` + `FormData`。
 *
 * @returns {Promise<{ok:boolean, text:string, reason:string}>}
 */
export function transcribeAudio(audio, options) {
  const opt = options || {}
  const base = String(opt.baseUrl || '').replace(/\/+$/, '')
  const token = String(opt.token || '')
  const url = base + '/v1/asr/transcribe'
  if (!audio) return Promise.resolve({ ok: false, text: '', reason: '没有录音' })

  // #ifdef APP-PLUS
  return new Promise((resolve) => {
    uni.uploadFile({
      url,
      filePath: audio.filePath,
      name: 'file',
      header: token ? { Authorization: 'Bearer ' + token } : {},
      success: (res) => resolve(parseAsrBody(res && res.data)),
      fail: (err) => resolve({ ok: false, text: '', reason: (err && err.errMsg) || '上传失败' })
    })
  })
  // #endif

  // #ifndef APP-PLUS
  return new Promise((resolve) => {
    try {
      const form = new FormData()
      form.append('file', audio.blob, audio.name || 'voice.webm')
      const xhr = new XMLHttpRequest()
      xhr.open('POST', url, true)
      if (token) xhr.setRequestHeader('Authorization', 'Bearer ' + token)
      xhr.timeout = 120000
      xhr.onload = () => resolve(parseAsrBody(xhr.responseText))
      xhr.onerror = () => resolve({ ok: false, text: '', reason: '上传失败，检查网络' })
      xhr.ontimeout = () => resolve({ ok: false, text: '', reason: '上传超时，再说一次试试' })
      xhr.send(form)
    } catch (e) {
      resolve({ ok: false, text: '', reason: '上传失败：' + ((e && e.message) || e) })
    }
  })
  // #endif
}

/** 解析服务端返回（两端共用）。服务端失败也返回 200 + ok:false，见 main.py 说明。 */
function parseAsrBody(raw) {
  let data = raw
  if (typeof raw === 'string') {
    try { data = JSON.parse(raw) } catch (e) { return { ok: false, text: '', reason: '识别服务返回异常' } }
  }
  if (!data || typeof data !== 'object') return { ok: false, text: '', reason: '识别服务返回异常' }
  return {
    ok: !!data.ok,
    text: String(data.text || ''),
    reason: String(data.reason || (data.ok ? '' : '没听清，再说一次试试'))
  }
}

/** H5：挑一个浏览器支持的音频 MIME */
function pickWebMime() {
  const cands = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus']
  for (const m of cands) {
    try { if (MediaRecorder.isTypeSupported(m)) return m } catch (e) { void e }
  }
  return ''
}

function suffixOf(mime) {
  const m = String(mime || '')
  if (m.indexOf('mp4') >= 0) return '.m4a'
  if (m.indexOf('ogg') >= 0) return '.ogg'
  if (m.indexOf('wav') >= 0) return '.wav'
  return '.webm'
}
