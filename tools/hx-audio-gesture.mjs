#!/usr/bin/env node
/**
 * 比邻AI · 数字人「出声 + 动嘴」真手势行为验收（HBuilderX 内置浏览器）
 *
 * ## 为什么必须是真手势 + 行为断言
 *
 * 1. `tools/hx-cdp.mjs click` 用的是 DOM `element.click()` —— **不受信事件**，不产生
 *    user activation。浏览器自动播放策略拦的正是"没有用户激活就 play()"，
 *    所以那种点法验的是一条**用户走不到的路径**。
 * 2. "嘴有没有动"不能断言"存在非零口型权重"：口型**定格**在一帧时权重也是非零的，
 *    上一版就是这样把"定格"判成了"在动"。真正的判据是**姿态随时间变化**，
 *    且变化必须落在**音频真的在播**的那段时间里。
 *
 * ## 判据（全部为真才算通过）
 *   · 音频起播        stats.audio.played === true（play() 的 Promise 已 resolve）
 *   · 音频推进够久    __blVisionAudioState().pos 增长 >= 1s
 *   · 口型在变化      采样中不同口型姿态数 >= 3
 *   · 音画同窗口      口型变化发生在音频推进期间
 *   · 说完回静止      音频结束后口型回到 vis_silence
 *
 * ⚠️ 音频状态读的是 `__blVisionAudioState()`（H5 原生 <audio> 元素），
 *    不是 uni 的包装层：uni 的封装会把 play() 的失败吞掉，读它等于什么都没验。
 *
 * 用法：node tools/hx-audio-gesture.mjs [--ask "今天天气怎么样"] [--seconds 12]
 * 前置：HBuilderX 内置浏览器已打开通话页（cli.exe launch web --browser Built）
 */

const PORT = Number(process.env.HX_CDP_PORT || 9500)
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function pickTarget() {
  const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()
  const pages = list.filter((i) => i.type === 'page' && !String(i.url).startsWith('devtools://'))
  if (!pages.length) throw new Error('没有可调试页面')
  return pages.find((p) => p.url.includes('vision')) || pages[pages.length - 1]
}

function connect(wsUrl) {
  const socket = new WebSocket(wsUrl)
  const pending = new Map()
  let nextId = 1
  const ready = new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve)
    socket.addEventListener('error', () => reject(new Error('WebSocket 连接失败')))
  })
  socket.addEventListener('message', (event) => {
    const message = JSON.parse(event.data)
    const entry = pending.get(message.id)
    if (!entry) return
    pending.delete(message.id)
    if (message.error) entry.reject(new Error(JSON.stringify(message.error)))
    else entry.resolve(message.result)
  })
  return {
    ready,
    send(method, params = {}) {
      const id = nextId++
      return new Promise((resolve, reject) => {
        pending.set(id, { resolve, reject })
        socket.send(JSON.stringify({ id, method, params }))
        setTimeout(() => { if (pending.delete(id)) reject(new Error('CDP 超时: ' + method)) }, 30000)
      })
    },
    close() { try { socket.close() } catch (e) { void e } },
  }
}

async function main() {
  const args = process.argv.slice(2)
  const askIndex = args.indexOf('--ask')
  const askText = askIndex >= 0 ? args[askIndex + 1] : '今天天气怎么样'
  const secIndex = args.indexOf('--seconds')
  const seconds = secIndex >= 0 ? Number(args[secIndex + 1]) : 12
  const noReload = args.includes('--no-reload')

  const target = await pickTarget()
  const client = connect(target.webSocketDebuggerUrl)
  await client.ready
  await client.send('Page.enable')

  // 打开**焦点模拟**并把页面提到前台。
  // 这台机器的 HBuilderX 主窗口拿不到前台（MainWindowHandle=0，进程枚举里也看不到窗口），
  // 渲染进程会认为自己"没被聚焦"；打开焦点模拟让它按"已聚焦"处理输入。
  // （真正导致"点了没反应"的是坐标尺度问题，见下面 realClick 的说明，不是这一项。）
  try {
    await client.send('Emulation.setFocusEmulationEnabled', { enabled: true })
    await client.send('Page.bringToFront')
  } catch (error) {
    console.log('警告：打开焦点模拟失败（' + error.message + '）')
  }

  const evaluate = async (expression) => {
    const result = await client.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
    if (result.exceptionDetails) throw new Error('页面抛错: ' + JSON.stringify(result.exceptionDetails).slice(0, 300))
    return result.result && result.result.value
  }

  if (!noReload) {
    await client.send('Page.navigate', { url: target.url })
    await sleep(4000)
    // 等通话页的钩子挂上（3D 舞台挂载是异步的）
    for (let i = 0; i < 40; i += 1) {
      const ok = await evaluate('typeof window.__blVisionAskStats === "function" && !!document.getElementById("blVisionStage")')
      if (ok) break
      await sleep(500)
    }
  }

  // 仪表：抓 uni 创建的音频上下文 + 记录 play() 的成败与用户激活状态
  await evaluate(`(() => {
    window.__diag = { ctxMeta: [], playLog: [], events: [] }
    if (!window.__diagHooked) {
      window.__diagHooked = true
      const origCreate = uni.createInnerAudioContext
      uni.createInnerAudioContext = function () {
        const ctx = origCreate.apply(this, arguments)
        window.__diag.ctx = ctx
        window.__diag.ctxMeta.push({ at: Date.now(), active: navigator.userActivation ? navigator.userActivation.isActive : null, ever: navigator.userActivation ? navigator.userActivation.hasBeenActive : null })
        const origPlay = ctx.play
        ctx.play = function () { window.__diag.events.push({ at: Date.now(), what: 'play()', act: navigator.userActivation ? navigator.userActivation.isActive : null }); return origPlay.apply(this, arguments) }
        const origStop = ctx.stop
        ctx.stop = function () { window.__diag.events.push({ at: Date.now(), what: 'stop()' }); return origStop.apply(this, arguments) }
        const origDestroy = ctx.destroy
        ctx.destroy = function () { window.__diag.events.push({ at: Date.now(), what: 'destroy()' }); return origDestroy.apply(this, arguments) }
        ctx.onPlay(() => window.__diag.events.push({ at: Date.now(), what: 'onPlay' }))
        return ctx
      }
      const origHtmlPlay = HTMLMediaElement.prototype.play
      HTMLMediaElement.prototype.play = function () {
        const rec = { at: Date.now(), what: 'html.play', readyState: this.readyState, networkState: this.networkState, muted: this.muted, volume: this.volume }
        window.__diag.playLog.push(rec)
        const p = origHtmlPlay.apply(this, arguments)
        if (p && typeof p.then === 'function') p.then(() => { rec.result = 'resolved' }).catch((e) => { rec.result = e.name + ': ' + e.message })
        return p
      }
    }
    return 'ok'
  })()`)

  // 真手势：点输入框 → 键入 → 点「问一句」
  //
  // ⚠️ 必须先 `scrollIntoView`：通话页是**可滚动**的，输入框与按钮常常在视口下方
  //    （实测内置浏览器视口只有 399×423，输入框在 y≈537）。
  //    不在视口内 → `elementFromPoint` 返回 null → CDP 的鼠标事件落到 BODY，
  //    表现为"点了没反应 / 输入框拿不到字"，很容易被误判成产品 bug。
  // 同时加**命中校验**：点之前先确认该点确实落在目标元素上，点空就直接报错，
  //    不再让"点空"伪装成"通过/失败"。
  /** 点击坐标换算系数：本环境 CEF 按物理像素解释 CDP 鼠标坐标（见 realClick 的说明） */
  const dpr = Number(await evaluate('window.devicePixelRatio || 1')) || 1
  const rectOf = async (selector) => {
    await evaluate(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); if (el && el.scrollIntoView) el.scrollIntoView({ block: 'center', inline: 'center' }) })()`)
    await sleep(250)
    const geo = JSON.parse(await evaluate(`(() => {
      const el = document.querySelector(${JSON.stringify(selector)})
      const r = el.getBoundingClientRect()
      const x = r.x + r.width / 2
      const y = r.y + r.height / 2
      const hit = document.elementFromPoint(x, y)
      return JSON.stringify({
        x, y,
        inView: x >= 0 && y >= 0 && x <= window.innerWidth && y <= window.innerHeight,
        hitTarget: !!(hit && (hit === el || el.contains(hit) || hit.contains(el)))
      })
    })()`))
    if (!geo.inView || !geo.hitTarget) throw new Error('点击目标不可点（' + selector + '）→ ' + JSON.stringify(geo))
    return geo
  }
  // ⚠️ 坐标必须**乘 devicePixelRatio**：
  //    这一版 CEF 把 `Input.dispatchMouseEvent` 的坐标当**物理像素**解释，
  //    渲染层再除以 dpr 换成 CSS 坐标
  //    （实测：发 (112.0, 288.9) → 页面收到 clientX=112, clientY=289 之前先变成 56, 144）。
  //    不乘就会**整体点偏一半**：点输入框落到旁边空白、点按钮落到别处 ——
  //    而鼠标事件确实送达了（`navigator.userActivation` 都会变成 true、pointerdown 监听器也会触发），
  //    所以看起来像"点了没反应"，极难排查。
  const realClick = async (x, y) => {
    const deviceX = x * dpr
    const deviceY = y * dpr
    await client.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: deviceX, y: deviceY })
    await client.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: deviceX, y: deviceY, button: 'left', buttons: 1, clickCount: 1 })
    await client.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: deviceX, y: deviceY, button: 'left', buttons: 0, clickCount: 1 })
  }

  // 填值必须用**真实按键事件**：
  //   · 直接改 input.value + 派发 input 事件看起来"填进去了"（DOM value 对），
  //     但 uni-app H5 的 v-model 不一定吃这个合成事件，结果 question 仍是空
  //     → 点按钮只弹"没有内容"，被误读成"点了没反应"（实测踩到两次）。
  //   · `Input.dispatchKeyEvent {type:'char'}` 是受信的键盘事件，和真人打字一致。
  const input = await rectOf('.bl-vision__ask-input input, .bl-vision__ask-input')
  await realClick(input.x, input.y)
  await sleep(300)

  // ⚠️ 先清空旧值：同一个输入框里可能还留着上一轮打的字，
  //    直接追加会变成"今天天气怎么样今天天气怎么样"，答非所问（实测踩过）。
  //    用键盘全选 + 退格清，同样只走**受信**按键事件。
  const key = async (type, extra) => client.send('Input.dispatchKeyEvent', Object.assign({ type }, extra))
  const pressKey = async (key0, code, vk) => {
    await key('keyDown', { key: key0, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk })
    await key('keyUp', { key: key0, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk })
  }
  const ctrlA = async () => {
    await key('keyDown', { modifiers: 2, key: 'a', code: 'KeyA', windowsVirtualKeyCode: 65, nativeVirtualKeyCode: 65 })
    await key('keyUp', { modifiers: 2, key: 'a', code: 'KeyA', windowsVirtualKeyCode: 65, nativeVirtualKeyCode: 65 })
  }
  const readInput = () => evaluate("(document.querySelector('.bl-vision__ask-input input')||{}).value")
  await ctrlA()
  await pressKey('Backspace', 'Backspace', 8)
  await sleep(200)
  for (let i = 0; i < 40 && (await readInput()); i += 1) await pressKey('Backspace', 'Backspace', 8)
  const leftover = await readInput()
  if (leftover) throw new Error('输入框没清空（还剩 ' + JSON.stringify(leftover) + '），先手动清一下再跑')

  for (const ch of askText) {
    await client.send('Input.dispatchKeyEvent', { type: 'char', text: ch })
    await sleep(30)
  }
  await sleep(300)
  console.log('输入框内容 =', JSON.stringify(await readInput()),
    '｜激活 =', await evaluate('JSON.stringify({ active: navigator.userActivation.isActive, ever: navigator.userActivation.hasBeenActive })'))
  await evaluate('window.__blVisionProbeStart()')
  const btn = await rectOf('.bl-vision__ask-btn')
  await realClick(btn.x, btn.y)

  // 采样
  const rows = []
  const startedAt = Date.now()
  while (Date.now() - startedAt < seconds * 1000) {
    await sleep(250)
    const raw = await evaluate(`(() => {
      const s = window.__blVisionAskStats()
      const st = window.__blVisionAudioState ? window.__blVisionAudioState() : null
      return JSON.stringify({
        played: !!(s.audio && s.audio.played), dur: s.audio ? s.audio.duration : 0, err: s.audio ? s.audio.error : '',
        pos: st ? st.pos : -1, paused: st ? st.paused : null, ready: st ? st.readyState : null,
        clock: s.lipsync.clockSource, lip: s.lipsync.elapsedMs, lipOn: s.lipsync.playing,
        morph: s.morph ? [s.morph.vis_silence, s.morph.vis_AA, s.morph.vis_I, s.morph.vis_MBP, s.morph.vis_L] : null
      })
    })()`)
    const row = Object.assign({ at: Math.round((Date.now() - startedAt) / 100) / 10 }, JSON.parse(raw))
    rows.push(row)
    console.log(
      String(row.at).padStart(4) + 's  起播=' + String(row.played).padEnd(5) + ' 音频=' + row.pos.toFixed(2).padStart(5) +
      ' 暂停=' + String(row.paused).padEnd(5) + ' 时钟=' + String(row.clock).padEnd(5) + ' 口型ms=' + String(row.lip).padStart(4) +
      ' 口型跑=' + String(row.lipOn).padEnd(5) + ' 姿态=' + JSON.stringify(row.morph) + (row.err ? '  错误=' + row.err : '')
    )
  }

  const diag = JSON.parse(await evaluate('JSON.stringify(window.__diag)'))
  const probe = JSON.parse(await evaluate('JSON.stringify(window.__blVisionProbeResult())'))

  const poses = new Set(rows.filter((r) => r.morph).map((r) => r.morph.join(',')))
  const advanced = rows.filter((r) => r.pos > 0).length
  const maxPos = rows.reduce((m, r) => Math.max(m, r.pos), 0)
  const mouthWhilePlaying = rows.filter((r) => r.pos > 0 && r.morph && new Set(r.morph).size > 1 && r.morph[0] < 0.9).length
  const ended = rows[rows.length - 1]
  const lastPlay = diag.playLog[diag.playLog.length - 1] || {}
  const verdict = {
    音频起播: probe.played,
    音频推进秒数: Number(maxPos.toFixed(2)),
    音频推进够久: maxPos >= 1,
    口型姿态种类: poses.size,
    口型在变化: poses.size >= 3,
    变化落在播放期间: mouthWhilePlaying >= 2,
    说完回静止: !!(ended && ended.morph && ended.morph[0] > 0.9),
    起播Promise: lastPlay.result || '(无记录)',
  }
  console.log('\n诊断事件 =', JSON.stringify(diag.events.slice(0, 12)))
  console.log('play() 记录 =', JSON.stringify(diag.playLog))
  console.log('上下文创建时的用户激活 =', JSON.stringify(diag.ctxMeta))
  console.log('probe =', JSON.stringify(probe))
  console.log('\n判定 =', JSON.stringify(verdict, null, 2))
  const failed = Object.entries(verdict).filter(([k, v]) => (typeof v === 'boolean' ? !v : false))
  console.log(failed.length ? '\n结果：未通过 —— ' + failed.map(([k]) => k).join('、') : '\n结果：通过（听到声音 + 看到口型随时间变化）')
  client.close()
}

main().catch((error) => { console.error('错误:', error.message); process.exit(1) })
