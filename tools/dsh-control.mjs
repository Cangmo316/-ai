#!/usr/bin/env node
/**
 * dsh-control — 用脚本控制本机正在运行的 DeepSeek Harness 桌面端。
 *
 * 原理
 * ----
 * 桌面端把 dsh 的 web 服务挂在 127.0.0.1 的一个端口上，鉴权用签名 cookie：
 *
 *     name  = dsh-auth-<base64url(sha256(authority))>
 *     value = v1.<base64url(payload)>.<base64url(hmacSHA256(secret, body))>
 *     payload = { version: 1, authority, issuedAt, expiresAt }
 *
 * 签名密钥持久存放在 ~/.dsh/.credentials.yaml 的
 * `client-connection/browser-session.secret`（32 字节）。因此本工具自己签一个
 * cookie 即可，不依赖 Chromium 的 Cookies 库，也不要求桌面端打开过网页版。
 *
 * RPC 协议
 * --------
 *     POST http://<authority>/api/<namespace>/<method>
 *     body = { type:'client-request', rpcId, method, payload:{ args } }
 *     resp = { type:'server-response', rpcId, result:{ ok, value | error } }
 *
 * 坑：`args` 的键名就是方法签名里的形参名，且各方法不一致 ——
 * session/list 用 `_request`，session/create、session/prompt 用 `request`，
 * session/modelCatalog 无参。写错会被 gateway 以 arguments-invalid 拒绝。
 *
 * 安全提示
 * --------
 * cookie 等价于桌面端登录态。本工具只访问本机回环地址；不要把 cookie 值
 * 外传，也不要把该端口暴露到局域网。
 */

import { createHash, createHmac, randomUUID } from 'node:crypto'
import { existsSync, readFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { homedir } from 'node:os'
import { join } from 'node:path'

const COOKIE_PREFIX = 'dsh-auth-'
const SECRET_BYTES = 32
const DEFAULT_COOKIE_DAYS = 30
const DAY_MS = 86_400_000
const DEFAULT_TIMEOUT_SECONDS = 180
const POLL_MS = 1500

// 被 head / Select-Object -First 截断时安静退出，不要抛 EPIPE 崩溃
process.stdout.on('error', () => {})

const HOME = homedir()
const CREDENTIALS_PATH = join(HOME, '.dsh', '.credentials.yaml')

function die(message) {
  console.error('dsh-control: ' + message)
  process.exit(1)
}

// ---------------------------------------------------------------- 参数解析

function parseArgv(argv) {
  const positional = []
  const flags = {}
  for (let i = 0; i < argv.length; i++) {
    const token = argv[i]
    if (!token.startsWith('--')) { positional.push(token); continue }
    const eq = token.indexOf('=')
    if (eq !== -1) { flags[token.slice(2, eq)] = token.slice(eq + 1); continue }
    const key = token.slice(2)
    const next = argv[i + 1]
    if (next === undefined || next.startsWith('--')) flags[key] = true
    else { flags[key] = next; i++ }
  }
  return { positional, flags }
}

// ------------------------------------------------------------------ 凭据

// credentials.yaml 是固定的两层缩进 Map，只需取出 browser-session 块里的 secret，
// 不值得为它引入完整 YAML 依赖。
function readBrowserSessionSecret() {
  if (!existsSync(CREDENTIALS_PATH)) die('找不到凭据文件 ' + CREDENTIALS_PATH)
  const lines = readFileSync(CREDENTIALS_PATH, 'utf8').split(/\r?\n/)
  const start = lines.findIndex(line => /^ {2}client-connection\/browser-session:\s*$/.test(line))
  if (start === -1) die('凭据文件里没有 client-connection/browser-session 记录')
  for (let i = start + 1; i < lines.length; i++) {
    const line = lines[i]
    if (/^ {0,2}\S/.test(line)) break
    const match = /^\s+secret:\s*(\S+)\s*$/.exec(line)
    if (match) return match[1]
  }
  die('browser-session 记录里没有 secret 字段')
}

function decodeSecret(text) {
  const bytes = Buffer.from(text, 'base64url')
  if (bytes.byteLength !== SECRET_BYTES) {
    die('browser-session secret 应为 ' + SECRET_BYTES + ' 字节，实际 ' + bytes.byteLength)
  }
  return bytes
}

// ------------------------------------------------------------------ cookie

function cookieNameFor(authority) {
  return COOKIE_PREFIX + createHash('sha256').update(authority).digest('base64url')
}

function mintCookie(authority, secretText, days) {
  const secret = decodeSecret(secretText)
  const issuedAt = Date.now()
  const payload = { version: 1, authority, issuedAt, expiresAt: issuedAt + days * DAY_MS }
  const body = Buffer.from(JSON.stringify(payload)).toString('base64url')
  const signature = createHmac('sha256', secret).update(body).digest('base64url')
  return { name: cookieNameFor(authority), value: 'v1.' + body + '.' + signature }
}

// ------------------------------------------------------------ 端口发现

function listeningPortsOfHarness() {
  const script = [
    "$procs = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like '*Harness*' -or $_.ProcessName -eq 'dsh' })",
    'if ($procs.Count -eq 0) { "[]"; exit 0 }',
    '$pids = @($procs | Select-Object -ExpandProperty Id)',
    '$ports = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $pids -contains $_.OwningProcess } | Select-Object -ExpandProperty LocalPort)',
    '@($ports | Select-Object -Unique) | ConvertTo-Json -Compress'
  ].join('; ')
  let raw
  try {
    raw = execFileSync('powershell', ['-NoProfile', '-NonInteractive', '-Command', script],
      { encoding: 'utf8', windowsHide: true })
  } catch (error) {
    die('枚举 dsh 进程监听端口失败: ' + error.message)
  }
  const parsed = JSON.parse(raw.trim() || '[]')
  const list = Array.isArray(parsed) ? parsed : [parsed]
  return list.filter(p => Number.isInteger(p) && p > 0)
}

async function discover() {
  const explicit = process.env.DSH_BASE_URL
  const candidates = []
  if (explicit) candidates.push(explicit.replace(/\/+$/, ''))
  else for (const port of listeningPortsOfHarness()) candidates.push('http://127.0.0.1:' + port)
  if (candidates.length === 0) {
    die('没有发现 DeepSeek Harness 的监听端口 —— 桌面端是否在运行？也可用 --base 或 DSH_BASE_URL 指定。')
  }
  const secret = readBrowserSessionSecret()
  const days = DEFAULT_COOKIE_DAYS
  for (const base of candidates) {
    const authority = new URL(base).host
    const cookie = mintCookie(authority, secret, days)
    let response
    try {
      response = await fetch(base + '/', { headers: { cookie: cookie.name + '=' + cookie.value } })
    } catch {
      continue
    }
    if (response.status !== 200) continue
    const body = await response.text()
    if (!/deepseek|dsh/i.test(body)) continue
    return { base, authority, cookie }
  }
  die('端口可达但没有通过鉴权校验。桌面端可能重启过导致 authority 变化，请重试或检查 ~/.dsh/.credentials.yaml。')
}

// -------------------------------------------------------------------- RPC

async function rpc(session, endpoint, args = {}) {
  const rpcId = randomUUID()
  let response
  try {
    response = await fetch(session.base + '/api/' + endpoint, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        cookie: session.cookie.name + '=' + session.cookie.value
      },
      body: JSON.stringify({ type: 'client-request', rpcId, method: endpoint, payload: { args } })
    })
  } catch (error) {
    die('请求 ' + endpoint + ' 失败: ' + error.message)
  }
  const text = await response.text()
  if (!response.ok) die(endpoint + ' 返回 HTTP ' + response.status + ': ' + text.slice(0, 300))
  let full
  try { full = JSON.parse(text) } catch { die(endpoint + ' 响应不是 JSON: ' + text.slice(0, 300)) }
  if (full.rpcId !== rpcId) die(endpoint + ' 的 rpcId 不匹配')
  if (!full.result.ok) die(endpoint + ' 失败: ' + JSON.stringify(full.result.error))
  return full.result.value
}

const api = {
  list: session => rpc(session, 'session/list', { _request: {} }),
  catalog: session => rpc(session, 'session/modelCatalog', {}),
  create: (session, request) => rpc(session, 'session/create', { request }),
  prompt: (session, request) => rpc(session, 'session/prompt', { request }),
  page: (session, request) => rpc(session, 'session/page', { request }),
  rename: (session, request) => rpc(session, 'session/rename', { request }),
  fork: (session, request) => rpc(session, 'session/fork', { request }),
  cancel: (session, request) => rpc(session, 'session/cancel', { request }),
  selectModel: (session, request) => rpc(session, 'session/selectModel', { request }),
  search: (session, request) => rpc(session, 'session/search', { request })
}

// ------------------------------------------------------------------ 渲染

function messageText(node) {
  if (!node || !Array.isArray(node.content)) return ''
  return node.content
    .filter(part => part && part.type === 'text' && typeof part.text === 'string')
    .map(part => part.text)
    .join('\n')
}

function describeEvent(event, full) {
  const data = event.data || {}
  const message = data.message || data
  if (event.type === 'user/message') {
    const kind = data.source && data.source.kind
    if (!full && kind !== 'user') return { skip: true }
    return { role: '用户', text: messageText(message) }
  }
  if (event.type === 'assistant/message') return { role: '助理', text: messageText(message) }
  return undefined
}

function printHistoryPage(page, full) {
  const assistantOnly = page.records.filter(record => record.type === 'event')
  for (const record of assistantOnly) {
    const described = describeEvent(record.event, full)
    if (described && described.skip) continue
    if (described) {
      console.log('[' + described.role + '] ' + described.text)
      console.log('')
      continue
    }
    if (record.event.type === 'assistant/attempt') {
      const stream = record.event.data && record.event.data.stream
      const finish = Array.isArray(stream) ? stream.find(item => item.chunk && item.chunk.type === 'finish') : undefined
      const failure = finish && finish.chunk.reason && finish.chunk.reason.failure
      if (failure) console.log('[失败] ' + failure.message)
      continue
    }
    if (record.event.type === 'turn/end') {
      const reason = record.event.data && record.event.data.reason
      if (reason && reason.kind === 'error' && reason.error) console.log('[失败] ' + reason.error.message)
      continue
    }
    if (record.event.type === 'session/title') console.log('[标题] ' + record.event.data.title)
  }
}

// ------------------------------------------------------------------ 等待

async function findSession(session, sessionId) {
  const list = await api.list(session)
  return list.items.find(item => item.sessionId === sessionId)
}

async function snapshot(session, sessionId) {
  const item = await findSession(session, sessionId)
  if (!item) die('会话不存在: ' + sessionId)
  const values = item.projections.values
  return {
    outline: (values.turnOutline || []).length,
    turns: values.sessionStats.turns,
    running: item.running
  }
}

// baseline 必须在发送「之前」取：否则这一轮的 outline 条目已经出现，
// 增长判定永远不成立，会一直空等到超时。
async function waitForTurn(session, sessionId, timeoutSeconds, baseline) {
  const deadline = Date.now() + timeoutSeconds * 1000
  const start = baseline || { outline: -1, turns: -1 }
  const startDeadline = Date.now() + 20000
  let previous = ''
  while (Date.now() < deadline) {
    const item = await findSession(session, sessionId)
    if (!item) die('会话不存在: ' + sessionId)
    const values = item.projections.values
    const outline = values.turnOutline || []
    const tail = outline[outline.length - 1]
    const signature = outline.length + '|' + (tail ? tail.response.length : -1) + '|' + item.running
    if (signature !== previous) {
      console.log('  … 轮次=' + values.sessionStats.turns + ' 步=' + values.sessionStats.steps +
        ' tokens=' + JSON.stringify(values.tokenUsage))
      previous = signature
    }
    const grew = outline.length > start.outline || values.sessionStats.turns > start.turns
    if (grew && !item.running) return tail || { prompt: '', response: '' }
    if (!grew && !item.running && Date.now() > startDeadline) {
      die('这一轮没有开始（轮次仍为 ' + values.sessionStats.turns + '）—— 请检查默认模型与账号额度')
    }
    await new Promise(resolve => setTimeout(resolve, POLL_MS))
  }
  die('等待回复超时（' + timeoutSeconds + 's）')
}

// ------------------------------------------------------------------ 命令

function requireFlag(flags, name) {
  const value = flags[name]
  if (typeof value !== 'string' || value.length === 0) die('缺少 --' + name + ' 参数')
  return value
}

function textOf(positional, flags) {
  if (typeof flags.text === 'string') return flags.text
  const text = positional.join(' ').trim()
  if (text.length === 0) die('缺少要发送的文本')
  return text
}

async function connect(flags) {
  if (typeof flags.base === 'string') process.env.DSH_BASE_URL = flags.base
  return discover()
}

const commands = {
  async doctor(session, flags) {
    console.log('base       : ' + session.base)
    console.log('authority  : ' + session.authority)
    console.log('cookie     : ' + session.cookie.name)
    console.log('credential : ' + CREDENTIALS_PATH)
    const list = await api.list(session)
    console.log('sessions   : ' + list.items.length)
    const catalog = await api.catalog(session)
    console.log('default    : ' + JSON.stringify(catalog.default))
    console.log('providers  : ' + (catalog.routableProviders || []).join(', '))
    console.log('OK — 控制通道可用')
  },

  async list(session, flags) {
    const list = await api.list(session)
    if (flags.json) { console.log(JSON.stringify(list, null, 2)); return }
    for (const item of list.items) {
      const values = item.projections.values
      const outline = values.turnOutline || []
      const tail = outline[outline.length - 1]
      console.log((item.running ? '* ' : '  ') + item.sessionId)
      console.log('    标题   : ' + (values.title || '(未命名)'))
      console.log('    目录   : ' + item.cwd)
      console.log('    轮次   : ' + values.sessionStats.turns + '  更新: ' + new Date(item.updatedAt).toLocaleString())
      if (tail && tail.prompt) console.log('    最近问 : ' + tail.prompt.slice(0, 70).replace(/\n/g, ' '))
      if (tail && tail.response) console.log('    最近答 : ' + tail.response.slice(0, 70).replace(/\n/g, ' '))
      console.log('')
    }
  },

  async models(session, flags) {
    const catalog = await api.catalog(session)
    if (flags.json) { console.log(JSON.stringify(catalog, null, 2)); return }
    console.log('默认: ' + JSON.stringify(catalog.default))
    for (const group of catalog.groups || []) {
      console.log('- ' + group.id + ' (' + group.name + '): ' + (group.models || []).map(m => m.id).join(', '))
    }
    if (catalog.failures && catalog.failures.length) console.log('失败: ' + JSON.stringify(catalog.failures))
  },

  async new(session, flags) {
    const request = {}
    if (typeof flags['workspace-id'] === 'string') request.workspaceId = flags['workspace-id']
    else if (typeof flags.cwd === 'string') request.cwd = flags.cwd
    if (typeof flags.preset === 'string') request.agentPreset = flags.preset
    const created = await api.create(session, request)
    if (flags.json) { console.log(JSON.stringify(created, null, 2)); return }
    console.log('已创建会话: ' + created.sessionId)
    if (created.agentPreset) console.log('agentPreset: ' + created.agentPreset)
  },

  async prompt(session, flags) {
    const sessionId = requireFlag(flags, 'session')
    const request = {
      requestId: randomUUID(),
      sessionId,
      mode: 'queue',
      content: [{ type: 'text', text: textOf(flags._, flags) }],
      clientTimeZone: Intl.DateTimeFormat().resolvedOptions().timeZone
    }
    const baseline = await snapshot(session, sessionId)
    await api.prompt(session, request)
    console.log('已发送到 ' + sessionId)
    if (flags.wait) {
      const tail = await waitForTurn(session, sessionId, Number(flags.timeout) || DEFAULT_TIMEOUT_SECONDS, baseline)
      console.log('')
      console.log('[回复] ' + tail.response)
    }
  },

  async send(session, flags) {
    const request = {}
    if (typeof flags['workspace-id'] === 'string') request.workspaceId = flags['workspace-id']
    else if (typeof flags.cwd === 'string') request.cwd = flags.cwd
    const created = await api.create(session, request)
    console.log('已创建会话: ' + created.sessionId)
    const baseline = { outline: 0, turns: 0 }
    await api.prompt(session, {
      requestId: randomUUID(),
      sessionId: created.sessionId,
      mode: 'queue',
      content: [{ type: 'text', text: textOf(flags._, flags) }],
      clientTimeZone: Intl.DateTimeFormat().resolvedOptions().timeZone
    })
    console.log('已发送')
    if (flags.wait) {
      const tail = await waitForTurn(session, created.sessionId, Number(flags.timeout) || DEFAULT_TIMEOUT_SECONDS, baseline)
      console.log('')
      console.log('[回复] ' + tail.response)
    }
  },

  async wait(session, flags) {
    const sessionId = requireFlag(flags, 'session')
    const tail = await waitForTurn(session, sessionId, Number(flags.timeout) || DEFAULT_TIMEOUT_SECONDS)
    console.log('')
    console.log('[回复] ' + tail.response)
  },

  async history(session, flags) {
    const sessionId = requireFlag(flags, 'session')
    const item = await findSession(session, sessionId)
    if (!item) die('会话不存在: ' + sessionId)
    const throughSeq = item.projections.asOfSeq
    const limit = Number(flags.limit) || 200
    const page = await api.page(session, {
      address: { kind: 'session', sessionId },
      throughSeq,
      maxMessages: limit
    })
    if (flags.json) { console.log(JSON.stringify(page, null, 2)); return }
    console.log('会话 ' + sessionId + '（asOfSeq=' + throughSeq + '，hasMore=' + page.hasMore + '）')
    console.log('')
    printHistoryPage(page, flags.full)
  },

  async search(session, flags) {
    const query = textOf(flags._, flags)
    const result = await api.search(session, { query })
    if (flags.json) { console.log(JSON.stringify(result, null, 2)); return }
    console.log(JSON.stringify(result, null, 2))
  },

  async 'select-model'(session, flags) {
    const request = {
      sessionId: requireFlag(flags, 'session'),
      provider: requireFlag(flags, 'provider'),
      model: requireFlag(flags, 'model')
    }
    if (typeof flags.effort === 'string') request.reasoningEffort = flags.effort
    const result = await api.selectModel(session, request)
    if (flags.json) { console.log(JSON.stringify(result, null, 2)); return }
    console.log('已选择: ' + JSON.stringify(result.selected))
    console.log('（已持久化为桌面端默认模型）')
  },

  async rename(session, flags) {
    const sessionId = requireFlag(flags, 'session')
    const title = textOf(flags._, flags)
    const result = await api.rename(session, { sessionId, title })
    console.log('标题已改为「' + result.title + '」(seq ' + result.seq + ')')
  },

  async fork(session, flags) {
    const request = { sessionId: requireFlag(flags, 'session') }
    if (flags['at-seq'] !== undefined) request.atSeq = Number(flags['at-seq'])
    const result = await api.fork(session, request)
    console.log('已分叉出新会话: ' + result.sessionId)
  },

  async cancel(session, flags) {
    const sessionId = requireFlag(flags, 'session')
    const result = await api.cancel(session, { sessionId })
    console.log('已请求取消: ' + JSON.stringify(result))
  }
}

const USAGE = [
  'dsh-control — 控制本机 DeepSeek Harness 桌面端',
  '',
  '用法: node tools/dsh-control.mjs <命令> [参数]',
  '',
  '命令:',
  '  doctor                              自检：发现端口、鉴权、列出能力',
  '  list                                列出会话',
  '  models                              查看模型目录',
  '  new [--workspace-id X] [--cwd P]    新建会话，打印 sessionId',
  '  send <文本> [--wait]                新建会话并发送（--wait 等回复）',
  '  prompt --session S <文本> [--wait]  向已有会话发送',
  '  wait --session S [--timeout 秒]     等待当前轮结束并打印回复',
  '  history --session S [--limit N] [--full]  打印会话历史（--full 含系统注入消息）',
  '  search <关键词>                     搜索会话内容（需部署开启 session-query 索引，否则报错）',
  '  select-model --session S --provider P --model M [--effort E]',
  '  rename --session S <新标题>',
  '  fork --session S [--at-seq N]       分叉会话',
  '  cancel --session S                  取消当前轮',
  '',
  '通用参数:',
  '  --base <url>   覆盖自动发现的地址（默认扫 Harness 进程的监听端口）',
  '  --json         输出原始 JSON',
  '',
  '示例:',
  '  node tools/dsh-control.mjs doctor',
  '  node tools/dsh-control.mjs send "你好" --wait',
  ''
].join('\n')

async function main() {
  const { positional, flags } = parseArgv(process.argv.slice(2))
  const name = positional.shift()
  if (!name || name === 'help' || flags.help) { console.log(USAGE); return }
  const command = commands[name]
  if (!command) die('未知命令 ' + JSON.stringify(name) + '，用 --help 查看用法')
  flags._ = positional
  const session = await connect(flags)
  await command(session, flags)
}

main().catch(error => {
  console.error('dsh-control: ' + (error && error.stack ? error.stack : String(error)))
  process.exit(1)
})