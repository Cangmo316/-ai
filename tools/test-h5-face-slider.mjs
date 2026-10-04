// 捏脸页滑杆是否真的驱动模型（只比 3D 预览区像素，固定视口）
// 背景：§7 记录过一个未解决的现象——`applyCommands` 后 stage 像素不变。
import { execFileSync } from 'node:child_process'
import { readFileSync, writeFileSync } from 'node:fs'

const PORT = Number(process.env.HX_CDP_PORT || 9500)
const BASE = `http://127.0.0.1:${PORT}`

async function target() {
  const list = await (await fetch(`${BASE}/json/list`)).json()
  const pages = list.filter((p) => p.type === 'page' && !String(p.url).startsWith('devtools://'))
  const face = pages.find((p) => p.url.includes('face')) || pages[pages.length - 1]
  return face.webSocketDebuggerUrl
}

let id = 0
function send(ws, method, params = {}) {
  return new Promise((resolve) => {
    const current = ++id
    const onMessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.id === current) {
        ws.removeEventListener('message', onMessage)
        resolve(data.result)
      }
    }
    ws.addEventListener('message', onMessage)
    ws.send(JSON.stringify({ id: current, method, params }))
  })
}

async function evaluate(ws, expression) {
  const result = await send(ws, 'Runtime.evaluate', {
    expression, returnByValue: true, awaitPromise: true,
  })
  return result?.result?.value
}

/** 只裁 3D 预览区（canvas 的 boundingBox），避免滑杆文字干扰 */
async function regionHash(ws) {
  const box = await evaluate(ws, `(() => {
    const c = document.querySelector('canvas')
    if (!c) return null
    const r = c.getBoundingClientRect()
    return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) }
  })()`)
  if (!box) throw new Error('页面上没有 canvas')
  const shot = await send(ws, 'Page.captureScreenshot', {
    format: 'png',
    clip: { x: box.x, y: box.y, width: box.w, height: box.h, scale: 1 },
  })
  const buffer = Buffer.from(shot.data, 'base64')
  writeFileSync(process.env.TMP_SHOT || 'E:\\比邻AI\\_shots\\_slider-probe.png', buffer)
  // 简单哈希（不使用 crypto 之外的东西）
  let hash = 0
  for (const byte of buffer) hash = (hash * 31 + byte) >>> 0
  return { hash, size: buffer.length, box }
}

const wsUrl = await target()
const ws = new WebSocket(wsUrl)
await new Promise((resolve) => ws.addEventListener('open', resolve, { once: true }))
await send(ws, 'Page.enable')
await send(ws, 'Runtime.enable')

const baseline = await evaluate(ws, 'window.__blFaceStage ? window.__blFaceStage.stats().triangles : -1')
console.log('stage triangles =', baseline)

const before = await regionHash(ws)
console.log('before hash', before.hash, 'size', before.size, before.box)

// 1) 只改相机（对照：应该变）
await evaluate(ws, 'window.__blFaceStage.rotate(0.35, 0)')
await new Promise((r) => setTimeout(r, 900))
const rotated = await regionHash(ws)
console.log('rotated hash', rotated.hash, rotated === before.hash ? '（未变 ✗）' : '（变了 ✓）')
await evaluate(ws, 'window.__blFaceStage.rotate(-0.35, 0)')
await new Promise((r) => setTimeout(r, 900))
const back = await regionHash(ws)
console.log('back hash', back.hash, back.hash === before.hash ? '（回到基线 ✓）' : '（未回到基线）')

// 2) 只改 morph（关键验证）
const applied = await evaluate(ws, `(() => {
  const stage = window.__blFaceStage
  if (!stage) return 'no stage'
  const before = stage.stats()
  stage.applyCommands({ morphs: { shape_face_width_up: 1, shape_cheekbone_width_up: 1 } })
  const after = stage.stats()
  return JSON.stringify({ beforeWarnings: before.warnings, afterWarnings: after.warnings })
})()`)
console.log('applyCommands →', applied)
await new Promise((r) => setTimeout(r, 1200))
const morphed = await regionHash(ws)
console.log('morph hash', morphed.hash, morphed.hash === back.hash ? '（没变 ✗ 复现了 §7）' : '（变了 ✓）')

// 3) 恢复
await evaluate(ws, 'window.__blFaceStage.applyCommands({ morphs: { shape_face_width_up: 0, shape_cheekbone_width_up: 0 } })')
await new Promise((r) => setTimeout(r, 1200))
const restored = await regionHash(ws)
console.log('restore hash', restored.hash, restored.hash === back.hash ? '（已复原 ✓）' : '（未复原）')

console.log(`\n结论：相机 ${rotated.hash !== before.hash ? '生效' : '不生效'} / morph ${morphed.hash !== back.hash ? '生效' : '不生效'}`)
ws.close()
