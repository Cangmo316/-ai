/**
 * 音频下发通道的端到端检查（对着 mock 服务跑，不依赖前端与浏览器）。
 *
 * 检查三件事：
 *   ① SSE 流里出现 `audio` 且**在 `lipsync` 之前**（顺序错了端侧就没法用音频时钟驱动口型）
 *   ② 拿事件里的签名 URL 能**真的取到可播放的音频字节**（Content-Type + 非空 + MP3 魔数）
 *   ③ 签名错/篡改 id 一律取不到（否则"任何人拿到 URL 就能反复取老人语音"）
 *
 * 跑法：node tools/test-audio-channel.mjs [baseUrl]
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

const events = await readEvents()
const names = events.map((item) => item.event)
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
  // MP3 帧头：0xFF 0xEx/0xFx
  check('字节像 MP3（帧同步字 0xFF 0xF?）',
    bytes.length > 2 && bytes[0] === 0xFF && (bytes[1] & 0xE0) === 0xE0,
    bytes.slice(0, 4).join(','))

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
