#!/usr/bin/env node
/**
 * 比邻AI · HBuilderX 内置浏览器的截图/交互工具（零依赖）
 *
 * 为什么需要它：HBuilderX 自带的 `cli.exe screencap web` 只能截"当前那个页面"，
 * 换页要重建运行实例（很慢，而且实测只有第一次生效）。而 HBuilderX 的内置浏览器
 * 在 **9500 端口暴露了完整的 Chrome DevTools Protocol**，于是我们可以自己导航、点击、截图：
 * 想看哪页看哪页，还能截 HBuilderX 管不到的页面（比如家人端 http://127.0.0.1:8787/family/）。
 *
 * 用法：
 *   node tools/hx-cdp.mjs list                          # 列出可调试页面
 *   node tools/hx-cdp.mjs shot <url> <file> [--wait 3000] [--full]
 *   node tools/hx-cdp.mjs click <选择器> [--wait 1500]
 *   node tools/hx-cdp.mjs eval "<js 表达式>"
 *   node tools/hx-cdp.mjs key <Text>                     # 往当前聚焦元素输入文本
 *
 * 环境变量：
 *   HX_CDP_PORT   DevTools 端口（默认 9500；HBuilderX 升级后若变了用 /json/version 试）
 *
 * 前置条件：HBuilderX 正在运行、且已通过 `cli.exe launch web --project <项目名>` 跑起 H5。
 * 注意：这是**内置浏览器**的调试端口，只在本机监听；不要暴露到网络。
 */

const PORT = Number(process.env.HX_CDP_PORT || 9500)
const BASE = `http://127.0.0.1:${PORT}`

function log(...args) {
  console.log(...args)
}

function die(message) {
  console.error('错误: ' + message)
  process.exit(1)
}

/** 拿一个可调试的页面目标（默认挑最后一个非 devtools 的 page） */
async function pickTarget() {
  let list
  try {
    const response = await fetch(`${BASE}/json/list`)
    list = await response.json()
  } catch (error) {
    die(`连不上 DevTools（${BASE}）：${error.message}\n  → HBuilderX 起了吗？H5 跑起来了吗？端口对吗（HX_CDP_PORT）？`)
  }
  const pages = list.filter((item) => item.type === 'page' && !String(item.url).startsWith('devtools://'))
  if (!pages.length) die('没有可调试的页面（先用 cli.exe launch web 把项目跑起来）')
  return pages[pages.length - 1]
}

/** 极简 CDP 客户端：一个 WebSocket + 按 id 收响应 */
function connect(wsUrl) {
  const socket = new WebSocket(wsUrl)
  const pending = new Map()
  let nextId = 1

  const ready = new Promise((resolve, reject) => {
    socket.addEventListener('open', () => resolve())
    socket.addEventListener('error', (event) => reject(new Error('WebSocket 连接失败: ' + (event.message || '未知'))))
  })

  socket.addEventListener('message', (event) => {
    let message
    try {
      message = JSON.parse(event.data)
    } catch (error) {
      return
    }
    if (message.id && pending.has(message.id)) {
      const { resolve, reject } = pending.get(message.id)
      pending.delete(message.id)
      if (message.error) reject(new Error(JSON.stringify(message.error)))
      else resolve(message.result)
    }
  })

  return {
    ready,
    send(method, params = {}) {
      const id = nextId++
      return new Promise((resolve, reject) => {
        pending.set(id, { resolve, reject })
        socket.send(JSON.stringify({ id, method, params }))
        setTimeout(() => {
          if (pending.has(id)) {
            pending.delete(id)
            reject(new Error(`CDP 超时: ${method}`))
          }
        }, 30000)
      })
    },
    close() {
      try {
        socket.close()
      } catch (error) {
        /* 忽略 */
      }
    }
  }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

function parseFlags(argv) {
  const flags = { _: [] }
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i].startsWith('--')) {
      const key = argv[i].slice(2)
      const next = argv[i + 1]
      if (next === undefined || next.startsWith('--')) flags[key] = true
      else {
        flags[key] = next
        i += 1
      }
    } else {
      flags._.push(argv[i])
    }
  }
  return flags
}

async function withClient(fn) {
  const target = await pickTarget()
  const client = connect(target.webSocketDebuggerUrl)
  await client.ready
  try {
    return await fn(client, target)
  } finally {
    client.close()
  }
}

async function main() {
  const flags = parseFlags(process.argv.slice(2))
  const command = flags._[0]

  if (!command || command === 'help') {
    log('用法: node tools/hx-cdp.mjs <list|shot|click|eval|key> [...]')
    log('  list                              列出可调试页面')
    log('  shot <url> <file> [--wait ms] [--full]')
    log('  click <css 选择器>|text:<文本> [--wait ms]')
    log('  eval "<js>"')
    log('  key <文本>                         往当前聚焦元素输入')
    return
  }

  if (command === 'list') {
    const response = await fetch(`${BASE}/json/list`)
    const list = await response.json()
    list.forEach((item) => log(`  [${item.type}] ${item.url}`))
    return
  }

  if (command === 'shot') {
    const url = flags._[1]
    const file = flags._[2]
    if (!file) die('shot 需要 <url> <file>')
    const wait = Number(flags.wait || 3500)
    const { writeFile } = await import('node:fs/promises')
    await withClient(async (client) => {
      await client.send('Page.enable')
      if (url && url !== '-') {
        await client.send('Page.navigate', { url })
        await sleep(wait)
      }
      // 窗口不可见时合成器可能不出帧，先强制一个固定视口把渲染逼出来
      if (flags.phone) {
        const [w, h] = String(flags.phone).split('x').map(Number)
        await client.send('Emulation.setDeviceMetricsOverride', {
          width: w || 430,
          height: h || 932,
          deviceScaleFactor: 2,
          mobile: true
        })
        await sleep(600)
      }
      const attempt = async (params) => {
        try {
          return await client.send('Page.captureScreenshot', params)
        } catch (error) {
          return null
        }
      }
      const shot =
        (await attempt({ format: 'png', fromSurface: false, captureBeyondViewport: Boolean(flags.full) })) ||
        (await attempt({ format: 'png', fromSurface: true, captureBeyondViewport: Boolean(flags.full) })) ||
        (await attempt({ format: 'png', captureBeyondViewport: true }))
      if (!shot) die('三种截图方式都失败：内置浏览器窗口可能被最小化/遮挡，先把它切到前台再试')
      await writeFile(file, Buffer.from(shot.data, 'base64'))
      log(`  已保存 ${file}`)
    })
    return
  }

  if (command === 'eval') {
    const expression = flags._[1]
    if (!expression) die('eval 需要一段表达式')
    await withClient(async (client) => {
      const result = await client.send('Runtime.evaluate', {
        expression,
        returnByValue: true,
        awaitPromise: true
      })
      log(JSON.stringify(result.result?.value ?? result.result, null, 2))
    })
    return
  }

  if (command === 'click') {
    const selector = flags._[1]
    if (!selector) die('click 需要 <css 选择器>，或用 text:<文本> 按文字点')
    const wait = Number(flags.wait || 1500)
    await withClient(async (client) => {
      const script = selector.startsWith('text:')
        ? `(() => {
             const want = ${JSON.stringify(selector.slice(5))};
             const nodes = [...document.querySelectorAll('*')].filter(
               (n) => n.children.length === 0 && (n.textContent || '').trim().includes(want)
             );
             const target = nodes[0];
             if (!target) return 'not-found';
             target.click();
             return 'clicked:' + (target.textContent || '').trim().slice(0, 20);
           })()`
        : `(() => {
             const target = document.querySelector(${JSON.stringify(selector)});
             if (!target) return 'not-found';
             target.click();
             return 'clicked:' + (target.textContent || '').trim().slice(0, 20);
           })()`
      const result = await client.send('Runtime.evaluate', { expression: script, returnByValue: true })
      log('  ' + JSON.stringify(result.result?.value))
      await sleep(wait)
    })
    return
  }

  if (command === 'key') {
    const text = flags._[1] || ''
    await withClient(async (client) => {
      for (const ch of text) {
        await client.send('Input.dispatchKeyEvent', { type: 'char', text: ch })
      }
      log('  已输入 ' + text.length + ' 个字符')
    })
    return
  }

  die('未知命令: ' + command)
}

main().catch((error) => die(error.message))
