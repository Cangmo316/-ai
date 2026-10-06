/**
 * 音频下发通道的端到端检查（对着 mock 服务跑，不依赖前端与浏览器）。
 *
 * 检查三件事：
 *   ① SSE 流里出现 `audio` 且**在 `lipsync` 之前**（顺序错了端侧就没法用音频时钟驱动口型）
 *   ② 拿事件里的签名 URL 能**真的取到可播放的音频字节**（Content-Type + 非空 + MP3 魔数）
 *   ③ 签名错/篡改 id 一律取不到（否则"任何人拿到 URL 就能反复取老人语音"）
 *
 * 跑法：node tools/test-audio-channel.mjs [baseUrl]
 *
 *   # 默认靶子（蜂鸣音兜底：时长固定 3 秒）
 *   node tools/mock-server.mjs
 *   node tools/test-audio-channel.mjs http://127.0.0.1:8787
 *
 *   # 真语音分支（任何机器/CI 都能跑：用替身代替 Windows 声部）
 *   set BILIN_MOCK_TTS=1 && set BILIN_MOCK_TTS_CMD=node tools/mock-tts-stub.mjs
 *   node tools/mock-server.mjs --port 8791 --tts
 *   node tools/test-audio-channel.mjs http://127.0.0.1:8791
 *
 * 两种模式都要验：**真语音的时长随文本变**，所以「够不够长」这条断言按模式分别判
 * （蜂鸣音固定 3 秒；真语音看「秒/字」是否落在人说话的语速带里）。
 */
const baseUrl = (process.argv[2] || 'http://127.0.0.1:8787').replace(/\/+$/, '')

let passed = 0
const failures = []

function check(name, condition, detail) {
  if (condition) {
    console.log('  ✓ ' + name)
    passed += 1
  } else {
    console.log('  ✗ ' + name + (detail ? '  → ' + detail : ''))
    failures.push(name)
  }
}

/** 拉一次对话流，收集事件（只读前 N 个事件就够，不必等完） */
async function readEvents(limit = 40) {
  const response = await fetch(baseUrl + '/v1/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message: '妈今天药按时吃了没',
      conversationId: 'c_audio_test',
      clientMsgId: 'm_audio_test',
    }),
  })
  if (!response.ok) throw new Error('HTTP ' + response.status)
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const events = []
  while (events.length < limit) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let index = buffer.indexOf('\n\n')
    while (index >= 0 && events.length < limit) {
      const chunk = buffer.slice(0, index)
      buffer = buffer.slice(index + 2)
      const nameLine = chunk.split('\n').find((line) => line.startsWith('event: '))
      const dataLine = chunk.split('\n').find((line) => line.startsWith('data: '))
      if (nameLine && dataLine) {
        events.push({ event: nameLine.slice(7).trim(), data: JSON.parse(dataLine.slice(6)) })
      }
      index = buffer.indexOf('\n\n')
    }
    if (events.some((item) => item.event === 'lipsync')) break
  }
  reader.cancel().catch(() => {})
  return events
}

console.log('音频下发通道检查：' + baseUrl + '\n')

// 先问 mock：现在是「蜂鸣音兜底」还是「真语音」（决定下面按哪种口径判时长）
let voiceOn = false
let voiceMode = 'unknown'
try {
  const health = await (await fetch(baseUrl + '/healthz')).json()
  voiceOn = Boolean(health && health.mockVoice && health.mockVoice.enabled)
  voiceMode = (health && health.mockVoice && health.mockVoice.mode) || (voiceOn ? 'on' : 'off')
} catch (error) {
  void error
}
console.log('  语音模式：' + (voiceOn ? '真语音 ' + voiceMode + '（时长随文本变）' : '蜂鸣音兜底（固定 3 秒）') + '\n')

/**
 * 遍历 RIFF chunk 读 WAV 头（不假设 44 字节固定头）。
 * ⚠️ Windows SAPI 写出的 fmt 块是 18 字节（带 cbSize），真实头长 46；
 *    按固定偏移 44 读 data 长度会读到 'data' 这 4 个字节本身 → 时长算错。
 */
function readWavHeader(bytes) {
  if (bytes.length < 12) return null
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  const ascii = (start) =>
    String.fromCharCode(bytes[start], bytes[start + 1], bytes[start + 2], bytes[start + 3])
  if (ascii(0) !== 'RIFF' || ascii(8) !== 'WAVE') return null
  let offset = 12
  let fmt = null
  let data = null
  while (offset + 8 <= bytes.length) {
    const id = ascii(offset)
    const size = view.getUint32(offset + 4, true)
    const body = offset + 8
    if (id === 'fmt ' && size >= 16 && body + 16 <= bytes.length) {
      fmt = {
        channels: view.getUint16(body + 2, true),
        sampleRate: view.getUint32(body + 4, true),
        bits: view.getUint16(body + 14, true),
      }
    } else if (id === 'data') {
      data = { start: body, bytes: Math.min(size, Math.max(0, bytes.length - body)) }
    }
    offset = body + size + (size % 2)
  }
  if (!fmt || !data || !fmt.channels || !fmt.sampleRate || !fmt.bits) return null
  return {
    sampleRate: fmt.sampleRate,
    channels: fmt.channels,
    bits: fmt.bits,
    dataStart: data.start,
    dataBytes: data.bytes,
  }
}

const events = await readEvents()
const names = events.map((item) => item.event)
// 这一轮回答的字数：真语音模式下用来算「秒/字」
const replyText = events
  .filter((item) => item.event === 'token')
  .map((item) => item.data.t || item.data.text || '')
  .join('')
const replyChars = Array.from(replyText.replace(/\s/g, '')).length
const audioEvent = events.find((item) => item.event === 'audio')
const lipsyncEvent = events.find((item) => item.event === 'lipsync')

check('流里出现 audio 事件', !!audioEvent, '实际事件：' + names.join(','))
check('流里出现 lipsync 事件', !!lipsyncEvent)
check('audio 在 lipsync 之前（否则端侧无法用音频时钟驱动口型）',
  names.indexOf('audio') >= 0 && names.indexOf('audio') < names.indexOf('lipsync'),
  '顺序：' + names.join(','))

if (audioEvent) {
  const payload = audioEvent.data
  check('audio payload 有 url/durationMs/format',
    typeof payload.url === 'string' && payload.url.length > 0
    && typeof payload.durationMs === 'number' && typeof payload.format === 'string',
    JSON.stringify(payload))
  check('url 带签名与有效期（expires + sig）',
    payload.url.includes('expires=') && payload.url.includes('sig='), payload.url)

  // ② 真的取到音频
  const audioResponse = await fetch(baseUrl + payload.url)
  const contentType = audioResponse.headers.get('content-type') || ''
  const bytes = new Uint8Array(await audioResponse.arrayBuffer())
  check('签名 URL 能取到音频（HTTP 200）', audioResponse.status === 200, 'HTTP ' + audioResponse.status)
  check('Content-Type 是音频', /audio\//.test(contentType), contentType)
  check('返回了非空音频字节', bytes.length > 100, bytes.length + ' bytes')

  // ⚠️ 这里原本是**形状断言**（"字节像 MP3"）——它放过了两个真 bug：
  //    ① mock 的音频实际只有 0.052 秒（形状对、时长错）→ 用户"听不到声音"
  //    ② 口型在音频就绪前就演完 → 用户"看不到唇形同步"
  //    所以现在改成**行为断言**：字节要与声明格式一致 + 时长要与字节数对得上。
  const declaredFormat = String(payload.format || '').toLowerCase()
  const looksWav = bytes.length > 12
    && bytes[0] === 0x52 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x46
  const looksMp3 = bytes.length > 2 && bytes[0] === 0xFF && (bytes[1] & 0xE0) === 0xE0
  check('字节与声明的格式一致（' + declaredFormat + '）',
    declaredFormat === 'wav' ? looksWav : looksMp3,
    'content-type=' + contentType + ' bytes0-3=' + bytes.slice(0, 4).join(','))

  if (looksWav) {
    // WAV 头里有采样率/声道/位深/数据长度 → 可以**精确算出**时长。
    // ⚠️ 必须按 chunk 遍历，不能用固定 44 字节头的偏移：
    //    SAPI 的 fmt 块是 18 字节（带 cbSize），真实头长 46，
    //    view.getUint32(40) 读到的是 'data' 这四个字节本身 → 时长算错。
    const wav = readWavHeader(bytes)
    const sampleRate = wav.sampleRate
    const channels = wav.channels
    const bits = wav.bits
    const dataBytes = wav.dataBytes
    const seconds = dataBytes / (sampleRate * channels * (bits / 8))
    if (voiceOn) {
      // 真语音：时长由文本长度决定，不能要求固定秒数（固定秒数是蜂鸣音时代的判据）
      check('音频不是畸形短音（≥ 0.3 秒）', seconds >= 0.3, seconds.toFixed(3) + 's')
      const perChar = replyChars ? seconds / replyChars : 0
      check('时长与文本同量级（人语速 0.05~0.5 秒/字）',
        replyChars > 0 && perChar >= 0.05 && perChar <= 0.5,
        perChar.toFixed(3) + ' 秒/字（' + replyChars + ' 字 → ' + seconds.toFixed(2) + 's）')
    } else {
      check('音频实际时长 ≥ 2 秒（防「看起来像音频但只有几十毫秒」）', seconds >= 2, seconds.toFixed(3) + 's')
    }
    check('durationMs 与字节算出的时长一致（±0.2s）',
      Math.abs(seconds - payload.durationMs / 1000) <= 0.2,
      '声明 ' + (payload.durationMs / 1000).toFixed(3) + 's / 实际 ' + seconds.toFixed(3) + 's')

    // ⚠️ 这里必须再加一层**行为断言**：能解码 + 够长 ≠ 有声。
    //    mock 的第二版就是"3.000s、字节数正确、还能解码"的**全零静音** ——
    //    端侧表现与"播放链路坏了"一模一样（都没声音），靠形状断言分辨不出来。
    //    静音的峰值恰好是 0，所以用峰值 + RMS 判"到底有没有声音"最直接。
    if (bits === 16) {
      const pcmLength = Math.min(dataBytes, bytes.byteLength - wav.dataStart)
      const pcm = new DataView(bytes.buffer, bytes.byteOffset + wav.dataStart, pcmLength)
      let peak = 0
      let sumSquares = 0
      let sampleCount = 0
      for (let offset = 0; offset + 1 < pcmLength; offset += 2) {
        const value = pcm.getInt16(offset, true) / 32768
        const magnitude = Math.abs(value)
        if (magnitude > peak) peak = magnitude
        sumSquares += value * value
        sampleCount += 1
      }
      const rms = sampleCount ? Math.sqrt(sumSquares / sampleCount) : 0
      check('音频**不是静音**（峰值 ≥ 5% 满量程）', peak >= 0.05, 'peak=' + peak.toFixed(4))
      check('音频电平有效（RMS ≥ 1% 满量程）', rms >= 0.01, 'rms=' + rms.toFixed(4))
    }
  } else if (looksMp3) {
    check('durationMs 合理（> 0）', payload.durationMs > 0, String(payload.durationMs))
  }

  // ④ 口型时间轴必须**盖到音频结束**（"音画同长"）
  // ⚠️ 这同样是一条行为断言，而不是形状断言：
  //    mock 的音频固定 3 秒，而按字数估算出来的口型轴只有 1~2 秒 ——
  //    直接发出去就会「嘴先停、声音还在响」，用户看到的现象就是"唇形不同步"。
  //    真后端的时间轴来自 TTS 对齐（天然等于音频长度）；mock 靠缩放对齐到音频时长。
  if (lipsyncEvent) {
    const cues = Array.isArray(lipsyncEvent.data.cues) ? lipsyncEvent.data.cues : []
    const lastCueEnd = cues.reduce((max, cue) => Math.max(max, Number(cue.e) || 0), 0)
    const audioMs = Number(payload.durationMs) || 0
    check('口型关键帧盖到音频结束（不出现「嘴停声还在响」）',
      cues.length > 0 && lastCueEnd >= audioMs - 200,
      '最后口型 ' + lastCueEnd + 'ms / 音频 ' + audioMs + 'ms')
    check('lipsync 的 durationMs 与音频时长一致（±0.3s）',
      Math.abs((Number(lipsyncEvent.data.durationMs) || 0) - audioMs) <= 300,
      'lipsync ' + (Number(lipsyncEvent.data.durationMs) || 0) + 'ms / 音频 ' + audioMs + 'ms')
  }

  // ③ 篡改一律取不到
  const tamperedSig = await fetch(baseUrl + payload.url.replace(/sig=[0-9a-f]+/, 'sig=deadbeef'))
  check('签名错误取不到（403）', tamperedSig.status === 403, 'HTTP ' + tamperedSig.status)
  const tamperedId = await fetch(baseUrl + payload.url.replace('/v1/audio/aud_', '/v1/audio/xxx_'))
  check('篡改 id 取不到（403）', tamperedId.status === 403, 'HTTP ' + tamperedId.status)
  const noSignature = await fetch(baseUrl + payload.url.split('?')[0])
  check('不带签名取不到（403）', noSignature.status === 403, 'HTTP ' + noSignature.status)
  const expired = await fetch(baseUrl + payload.url.replace(/expires=\d+/, 'expires=1'))
  check('过期签名取不到（403）', expired.status === 403, 'HTTP ' + expired.status)
}

console.log('\n通过 ' + passed + ' 项，失败 ' + failures.length + ' 项')
if (failures.length) process.exitCode = 1
