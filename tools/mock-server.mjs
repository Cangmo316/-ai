#!/usr/bin/env node
/**
 * 比邻AI · mock agent 服务（零依赖）
 *
 * 用途：uni-app 端还没等到 FastAPI 后端时的联调靶子。它实现的是
 * **真实契约**（见 uni-app/api/README.md），所以端侧代码一行都不用改，
 * 后端就绪后只改 baseURL 即可切换。
 *
 * 接口：
 *   POST /v1/chat/stream    SSE 流式对话（meta / token / sticker / card / done / error）
 *   POST /v1/chat/send      非流式一次性回复（端侧降级路径）
 *   GET  /v1/chat/history   历史消息
 *   GET  /healthz           存活探针
 *
 * 用法：
 *   node tools/mock-server.mjs                 # 默认 127.0.0.1:8787，逐字输出，110ms/字
 *   node tools/mock-server.mjs --port 9000
 *   node tools/mock-server.mjs --delay 0       # 不等待，便于压测/脚本联调
 *   node tools/mock-server.mjs --host 0.0.0.0  # 真机联调（手机与电脑同一局域网）
 *
 * 触发词（用来演示边界，不参与真实业务）：
 *   消息里含 __error  → 走到 error 事件分支（验证端侧错误态与重发）
 *   消息里含 __slow   → 每字放大到 10 倍延迟（验证「停止」按钮）
 */

import { createServer } from 'node:http'
import { pathToFileURL } from 'node:url'

const DEFAULT_PORT = 8787
const DEFAULT_HOST = '127.0.0.1'
const DEFAULT_DELAY_MS = 110

/** 人设：儿子 小明（爽朗、爱开玩笑）——文案遵守「句末不加句号、多句换行」的规范 */
const PERSONA = { id: 'p_son', name: '儿子 小明', relation: '儿子', avatarColor: '#07C160' }

const REPLIES = [
  {
    match: /(药|吃药|服药|降压)/,
    text: '妈 药吃了没\n吃完喝口热水 别空腹',
    sticker: 'pill',
    card: {
      kind: 'plan_item',
      plan: { time: '08:00', title: '用药提醒', desc: '降压药 1 片，饭后温水送服', state: 'todo' }
    }
  },
  { match: /(睡|困|晚安|夜里)/, text: '早点睡 别熬夜\n我把灯给你留着', sticker: 'night' },
  { match: /(想|孤单|没人|闷)/, text: '我也想你们\n晚上我打视频回来', sticker: 'hug' },
  { match: /(吃|饭|菜|盐)/, text: '中午吃点清淡的\n少放盐 多来点青菜', sticker: 'meal' },
  { match: /(天气|冷|热|下雨|风)/, text: '今天降温了\n出门加件外套', sticker: 'sun' },
  { match: /(走|散步|锻炼|运动|腿)/, text: '吃完歇半小时再下去走两圈\n别走太快 扶着点栏杆', sticker: 'walk' },
  { match: /(水|渴)/, text: '喝口水吧\n不渴也得喝 一天七八杯', sticker: 'water' },
  { match: /(疼|难受|血压|头晕)/, text: '妈 别自己扛着\n我一会儿给社区医生打电话 你先把感觉记一下', sticker: 'cheer' }
]

const DEFAULT_REPLY = { text: '妈 我在呢\n今天感觉怎么样', sticker: '' }

/** 每个会话一份内存历史：够端侧首启拉一次即可，不做持久化 */
const histories = new Map()

function conversationOf(id) {
  const key = id || 'c_son'
  if (!histories.has(key)) {
    const now = Date.now()
    histories.set(key, [
      {
        id: key + '_seed_1',
        role: 'agent',
        type: 'text',
        text: '妈 我上班去了\n有事就发消息',
        createdAt: new Date(now - 3600 * 1000).toISOString()
      }
    ])
  }
  return histories.get(key)
}

function replyFor(text) {
  for (const item of REPLIES) {
    if (item.match.test(text)) return item
  }
  return DEFAULT_REPLY
}

/* ------------------------------------------------------------------ HTTP */

function corsHeaders() {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'content-type, accept',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Max-Age': '86400'
  }
}

function sendJSON(res, statusCode, body) {
  const text = JSON.stringify(body)
  res.writeHead(statusCode, Object.assign({
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(text)
  }, corsHeaders()))
  res.end(text)
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = []
    req.on('data', (chunk) => chunks.push(chunk))
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8')
      if (!raw) { resolve({}); return }
      try {
        resolve(JSON.parse(raw))
      } catch (e) {
        reject(new Error('请求体不是合法 JSON'))
      }
    })
    req.on('error', reject)
  })
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

/* ------------------------------------------------- 康养计划（P1 联调样本） */

/**
 * 一份**已生效**的今日计划，用来联调老人端日程页与打卡。
 *
 * ⚠️ 与真实后端的两点差异（有意为之，避免在 JS 里重写一遍计划引擎）：
 *   1. 这里没有"家属确认"这一步，计划直接是生效态；真实服务端要 draft → pending → active
 *   2. 条目是静态样本，不是按老人档案从知识库匹配出来的
 * 端侧代码不关心这些差异，所以联调效果一致。
 */
const PLAN_ITEMS = [
  {
    id: 'pi_mock_1',
    time: '08:00',
    type: '监测',
    title: '量完血压记一下 下次给医生看',
    detail: '家里的血压计比医院的更接近平时状态',
    freq: '每日',
    strongRemind: false,
    basis: {
      entryId: 'nphis_006',
      source: 'nphis3',
      sourceName: '国家基本公共卫生服务规范（第三版）· 老年人健康管理服务规范',
      version: '第三版',
      boundary: '不根据血压值给出用药或剂量建议',
      text: '国家基本公共卫生服务规范（第三版）· 老年人健康管理服务规范 · 第三版 · §nphis_006'
    }
  },
  {
    id: 'pi_mock_2',
    time: '11:30',
    type: '午餐',
    title: '每天吃盐不超过5克',
    detail: '做菜少放酱油和咸菜',
    freq: '每日',
    strongRemind: true,
    basis: {
      entryId: 'diet_salt_001',
      source: 'diet2022',
      sourceName: '中国居民膳食指南（2022）',
      version: '2022',
      boundary: '不涉及药物与剂量调整',
      text: '中国居民膳食指南（2022） · 2022 · §diet_salt_001'
    }
  },
  {
    id: 'pi_mock_3',
    time: '15:30',
    type: '活动',
    title: '出去走走 回来扶着桌子单脚站一会儿',
    detail: '平衡练习能降低跌倒风险，一定要扶着稳的东西',
    freq: '每日',
    strongRemind: false,
    basis: {
      entryId: 'icope_004',
      source: 'icope',
      sourceName: 'ICOPE 老年人整合照护指南（中文版）',
      version: '2019 中文版',
      boundary: '不替代康复训练处方；跌倒高风险者需康复师指导',
      text: 'ICOPE 老年人整合照护指南（中文版） · 2019 中文版 · §icope_004'
    }
  },
  {
    id: 'pi_mock_4',
    time: '20:00',
    type: '问候',
    title: '这两天心里闷不闷 有事跟我说说',
    detail: '',
    freq: '每日',
    strongRemind: false,
    basis: {
      entryId: 'icope_009',
      source: 'icope',
      sourceName: 'ICOPE 老年人整合照护指南（中文版）',
      version: '2019 中文版',
      boundary: '不做抑郁筛查结论与心理治疗建议；须提示家属或就医',
      text: 'ICOPE 老年人整合照护指南（中文版） · 2019 中文版 · §icope_009'
    }
  }
]

function todayKey() {
  const now = new Date()
  return [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, '0'),
    String(now.getDate()).padStart(2, '0')
  ].join('-')
}

/** 本地时间戳（与真实服务端一致：不带时区的 ISO，秒级） */
function localStamp(moment) {
  return [
    moment.getFullYear(),
    String(moment.getMonth() + 1).padStart(2, '0'),
    String(moment.getDate()).padStart(2, '0')
  ].join('-') + 'T' + [
    String(moment.getHours()).padStart(2, '0'),
    String(moment.getMinutes()).padStart(2, '0'),
    String(moment.getSeconds()).padStart(2, '0')
  ].join(':')
}

/** 提醒分级：强提醒来自知识库 strong_remind，问候算弱提醒（与真实服务端同一套规则） */
function levelOf(item) {
  if (item.strongRemind) return 'strong'
  if (item.type === '问候') return 'weak'
  return 'normal'
}

const LEVEL_LABELS = { strong: '强提醒', normal: '普通提醒', weak: '弱提醒' }

function createReminderState() {
  return { delivered: [], readIds: new Set(), ticks: 0, lastTickAt: '', lastSummary: {} }
}

/**
 * 手动推进调度：把「已经到点」的提醒登记为已投递。
 *
 * ⚠️ 简化实现：只做「到点 → 投递」，不含真实的过期宽限、弱提醒时间窗、强提醒重复、错过判定。
 * 那些策略由服务端单测守着（server/tests/test_scheduler.py），这里是给端侧联调用的。
 */
function reminderTick(state, plans, at) {
  const moment = at ? new Date(at) : new Date()
  if (Number.isNaN(moment.getTime())) throw new Error('时间格式不对')
  const stamp = localStamp(moment)
  const summary = { at: stamp, created: 0, sent: 0, skipped: 0, canceled: 0, repeated: 0, missed: 0, failed: 0 }

  for (const item of plans.items) {
    if (plans.doneIds.has(item.id)) continue
    const sendAt = plans.date + 'T' + item.time + ':00'
    if (sendAt > stamp) continue
    if (state.delivered.some((task) => task.planItemId === item.id)) continue
    const level = levelOf(item)
    state.delivered.push({
      id: 'rt_mock_' + item.id,
      planId: plans.planId,
      planItemId: item.id,
      elderId: plans.elderId,
      title: item.title,
      label: item.time + ' ' + item.type,
      detail: item.detail,
      level,
      levelLabel: LEVEL_LABELS[level],
      sendAt,
      sentAt: stamp,
      readAt: '',
      ackAt: '',
      repeatCount: 0,
      status: 'sent',
      channel: 'inbox',
      messageId: '',
      note: ''
    })
    summary.sent += 1
  }

  state.ticks += 1
  state.lastTickAt = stamp
  state.lastSummary = summary
  return summary
}

function reminderPayload(state, plans, task) {
  return Object.assign({}, task, {
    readAt: state.readIds.has(task.id) ? task.readAt || state.lastTickAt : task.readAt,
    ackAt: plans.doneIds.has(task.planItemId) ? task.ackAt || state.lastTickAt : task.ackAt,
    status: plans.doneIds.has(task.planItemId) ? 'acked' : task.status
  })
}

function schedulerStatus(state) {
  const pending = state.delivered.filter((task) => !state.readIds.has(task.id))
  return {
    running: false,
    ticks: state.ticks,
    lastTickAt: state.lastTickAt,
    lastSummary: state.lastSummary,
    tickSeconds: 30,
    manualTickAllowed: true,
    channels: [{ name: 'inbox' }, { name: 'log' }],
    counts: {
      pending: 0,
      sent: state.delivered.length,
      acked: 0,
      missed: 0,
      skipped: 0,
      canceled: 0
    },
    nextSendAt: '',
    graceMinutes: 30,
    repeatMinutes: 5,
    missMinutes: 60,
    weakWindow: ['09:00', '20:00'],
    unread: pending.length
  }
}

function createPlanState() {
  return {
    elderId: 'e_1',
    planId: 'plan_mock_1',
    date: todayKey(),
    doneIds: new Set(),
    items: PLAN_ITEMS.map((item) => Object.assign({}, item))
  }
}

function todayPayload(state) {
  const items = state.items.map((item) =>
    Object.assign({}, item, {
      done: state.doneIds.has(item.id),
      doneAt: state.doneIds.has(item.id) ? new Date().toISOString() : ''
    })
  )
  const done = items.filter((item) => item.done).length
  return {
    elderId: state.elderId,
    date: state.date,
    planId: state.planId,
    status: 'active',
    statusLabel: '正在执行',
    items,
    total: items.length,
    done,
    rate: items.length ? Math.round((done / items.length) * 1000) / 1000 : 0
  }
}

function planSummary(state) {
  const payload = todayPayload(state)
  const rate = payload.rate
  const shouldAdjust = rate < 0.5
  return {
    elderId: state.elderId,
    hasPlan: true,
    planId: state.planId,
    status: 'active',
    statusLabel: '正在执行',
    stats: { days: 7, expected: 28, done: Math.round(rate * 28), rate, strongMissing: {} },
    suggestion: {
      shouldAdjust,
      reasons: shouldAdjust ? ['最近 7 天完成率偏低，提醒安排可能太多或时间不合适'] : [],
      stats: null,
      advice: '建议由家属确认后调整；未确认前计划照旧执行'
    }
  }
}

/**
 * @param {object} [options]
 * @param {number} [options.port]      0 表示随机端口（测试用）
 * @param {string} [options.host]
 * @param {number} [options.delayMs]   每个 token 的间隔
 * @returns {Promise<{server: import('node:http').Server, port: number, host: string, close: () => Promise<void>}>}
 */
export function startMockServer(options = {}) {
  const host = options.host || DEFAULT_HOST
  const delayMs = options.delayMs === undefined ? DEFAULT_DELAY_MS : options.delayMs
  const plans = createPlanState()
  const reminders = createReminderState()
  const pushClients = new Map()

  const server = createServer((req, res) => {
    const url = new URL(req.url, 'http://' + (req.headers.host || 'localhost'))

    if (req.method === 'OPTIONS') {
      res.writeHead(204, corsHeaders())
      res.end()
      return
    }

    if (url.pathname === '/healthz') {
      sendJSON(res, 200, { ok: true, service: 'bilin-mock-agent', delayMs })
      return
    }

    // ── 康养计划 ──────────────────────────────────────────────
    if (url.pathname === '/v1/plans/today' && req.method === 'GET') {
      sendJSON(res, 200, todayPayload(plans))
      return
    }

    if (url.pathname === '/v1/plans/checkin' && req.method === 'POST') {
      readBody(req).then((body) => {
        const itemId = String((body && body.planItemId) || '')
        if (!plans.items.some((item) => item.id === itemId)) {
          sendJSON(res, 404, { error: { code: 'plan_item_not_found', message: '没找到这一项' } })
          return
        }
        // 同一天同一项幂等，与真实服务端一致
        const wanted = !(body && body.done === false)
        if (wanted) plans.doneIds.add(itemId)
        else plans.doneIds.delete(itemId)
        const payload = todayPayload(plans)
        sendJSON(res, 200, {
          elderId: plans.elderId,
          date: plans.date,
          planItemId: itemId,
          done: wanted,
          checkin: wanted ? { planItemId: itemId, date: plans.date } : null,
          total: payload.total,
          completed: payload.done,
          rate: payload.rate
        })
      }).catch((err) => sendJSON(res, 400, { error: { code: 'bad_request', message: err.message } }))
      return
    }

    if (url.pathname === '/v1/plans/summary' && req.method === 'GET') {
      sendJSON(res, 200, planSummary(plans))
      return
    }

    if (url.pathname === '/v1/plans/pending' && req.method === 'GET') {
      // mock 里计划已经是生效态，没有待确认草稿（真实服务端会有）
      sendJSON(res, 200, { elderId: plans.elderId, plans: [] })
      return
    }

    if (url.pathname === '/v1/reminders/inbox' && req.method === 'GET') {
      const tasks = reminders.delivered
        .filter((task) => !reminders.readIds.has(task.id))
        .sort((a, b) => (a.sendAt < b.sendAt ? -1 : 1))
        .map((task) => reminderPayload(reminders, plans, task))
      sendJSON(res, 200, { elderId: plans.elderId, tasks, count: tasks.length })
      return
    }

    if (url.pathname === '/v1/reminders/read' && req.method === 'POST') {
      readBody(req).then((body) => {
        const taskId = body && body.taskId
        let marked = 0
        for (const task of reminders.delivered) {
          if (taskId && task.id !== taskId) continue
          if (reminders.readIds.has(task.id)) continue
          task.readAt = reminders.lastTickAt || localStamp(new Date())
          reminders.readIds.add(task.id)
          marked += 1
        }
        sendJSON(res, 200, { elderId: plans.elderId, marked })
      }).catch((err) => sendJSON(res, 400, { error: { code: 'bad_request', message: err.message } }))
      return
    }

    if (url.pathname === '/v1/reminders/tasks' && req.method === 'GET') {
      const day = url.searchParams.get('date') || plans.date
      const tasks = reminders.delivered
        .filter((task) => task.sendAt.startsWith(day))
        .map((task) => reminderPayload(reminders, plans, task))
      sendJSON(res, 200, { elderId: plans.elderId, date: day, tasks })
      return
    }

    if (url.pathname === '/v1/scheduler/status' && req.method === 'GET') {
      sendJSON(res, 200, schedulerStatus(reminders))
      return
    }

    if (url.pathname === '/v1/scheduler/tick' && req.method === 'POST') {
      readBody(req).then((body) => {
        const summary = reminderTick(reminders, plans, body && body.at)
        sendJSON(res, 200, { summary, status: schedulerStatus(reminders) })
      }).catch((err) => sendJSON(res, 400, { error: { code: 'bad_request', message: err.message } }))
      return
    }

    if (url.pathname === '/v1/push/register' && req.method === 'POST') {
      readBody(req).then((body) => {
        const cid = String((body && body.cid) || '').trim()
        if (!cid) {
          sendJSON(res, 400, { error: { code: 'invalid_cid', message: '推送标识不能为空' } })
          return
        }
        pushClients.set(cid, {
          cid,
          elderId: (body && body.elderId) || plans.elderId,
          platform: (body && body.platform) || '',
          updatedAt: localStamp(new Date())
        })
        sendJSON(res, 200, {
          ok: true,
          elderId: (body && body.elderId) || plans.elderId,
          cidTail: cid.slice(-6),
          notice: '提醒会同时走站内消息与系统通知'
        })
      }).catch((err) => sendJSON(res, 400, { error: { code: 'bad_request', message: err.message } }))
      return
    }

    if (url.pathname === '/v1/push/unregister' && req.method === 'POST') {
      readBody(req).then((body) => {
        const removed = pushClients.delete(String((body && body.cid) || '').trim())
        sendJSON(res, 200, { ok: removed })
      }).catch((err) => sendJSON(res, 400, { error: { code: 'bad_request', message: err.message } }))
      return
    }

    if (url.pathname === '/v1/push/status' && req.method === 'GET') {
      const elderId = url.searchParams.get('elderId') || plans.elderId
      const clients = Array.from(pushClients.values()).filter((client) => client.elderId === elderId)
      sendJSON(res, 200, {
        elderId,
        channels: [{ name: 'inbox' }, { name: 'unipush', configured: false }, { name: 'log' }],
        unipushConfigured: false,
        forceNotification: true,
        clients: clients.map((client) => Object.assign({}, client, { cidTail: client.cid.slice(-6) })),
        totals: { clients: pushClients.size, enabled: pushClients.size, elders: clients.length ? 1 : 0 },
        note: 'mock 只登记 cid，不真的发推送'
      })
      return
    }

    if (url.pathname === '/v1/elders' && req.method === 'GET') {      sendJSON(res, 200, {
        elders: [{ id: 'e_1', name: '张桂兰', address: '妈', age: 71, chronic: ['高血压'], careLevel: '居家' }],
        demo: true,
        note: '开发期模拟档案，不是真实病例，也不构成医学建议'
      })
      return
    }

    if (url.pathname === '/v1/chat/history' && req.method === 'GET') {
      const conversationId = url.searchParams.get('conversationId') || 'c_son'
      sendJSON(res, 200, { conversationId, messages: conversationOf(conversationId) })
      return
    }

    if (url.pathname === '/v1/chat/send' && req.method === 'POST') {
      readBody(req).then((body) => {
        const echo = buildTurn(body)
        appendHistory(body, echo)
        sendJSON(res, 200, echo.full)
      }).catch((err) => sendJSON(res, 400, { error: { code: 'bad_request', message: err.message } }))
      return
    }

    if (url.pathname === '/v1/chat/stream' && req.method === 'POST') {
      readBody(req).then((body) => streamTurn(req, res, body, delayMs)).catch((err) => {
        sendJSON(res, 400, { error: { code: 'bad_request', message: err.message } })
      })
      return
    }

    sendJSON(res, 404, { error: { code: 'not_found', message: '没有这个接口：' + url.pathname } })
  })

  return new Promise((resolve) => {
    server.listen(options.port === undefined ? DEFAULT_PORT : options.port, host, () => {
      const address = server.address()
      resolve({
        server,
        host,
        port: typeof address === 'object' && address ? address.port : 0,
        close: () => new Promise((done) => {
          // fetch/undici 会复用 keep-alive 连接，只调 close() 会一直等连接释放；先全部掐掉
          if (typeof server.closeAllConnections === 'function') server.closeAllConnections()
          server.close(() => done())
        })
      })
    })
  })
}

/* --------------------------------------------------------------- 回复生成 */

/** 把一次回复拆成「事件序列」，流式与非流式共用同一份数据 */
function buildTurn(body) {
  const raw = String((body && body.text) || '').trim()
  const conversationId = (body && body.conversationId) || 'c_son'
  const wantsError = raw.indexOf('__error') !== -1
  const wantsSlow = raw.indexOf('__slow') !== -1

  const reply = replyFor(raw.replace(/__\w+/g, ''))
  const assistantMsgId = conversationId + '_a_' + Date.now().toString(36)

  const base = {
    conversationId,
    assistantMsgId,
    persona: PERSONA,
    text: reply.text,
    sticker: reply.sticker || '',
    card: reply.card || null,
    slow: wantsSlow,
    full: {
      conversationId,
      assistantMsgId,
      persona: PERSONA,
      text: reply.text,
      sticker: reply.sticker || '',
      card: reply.card || null,
      finishReason: 'stop'
    }
  }

  if (wantsError) {
    return Object.assign(base, {
      text: '',
      sticker: '',
      card: null,
      error: { code: 'server_error', message: '服务器开小差了，一会儿再试', retryable: true }
    })
  }

  return Object.assign(base, { error: null })
}

function appendHistory(body, turn) {
  const list = conversationOf(turn.conversationId || (body && body.conversationId))
  if (body && body.text) {
    list.push({
      id: turn.assistantMsgId + '_u',
      role: 'elder',
      type: 'text',
      text: String(body.text),
      createdAt: new Date().toISOString()
    })
  }
  if (turn.text) {
    list.push({
      id: turn.assistantMsgId,
      role: 'agent',
      type: 'text',
      text: turn.text,
      createdAt: new Date().toISOString()
    })
  }
}

/* ------------------------------------------------------------------- SSE */

async function streamTurn(req, res, body, serverDelayMs) {
  const turn = buildTurn(body)
  // 逐字吐字的速度：默认按启动参数，__slow 触发词放大到 700ms/字，便于手动验证「停止」
  const perCharDelay = turn.slow ? Math.max(serverDelayMs, 700) : serverDelayMs

  res.writeHead(200, Object.assign({
    'Content-Type': 'text/event-stream; charset=utf-8',
    'Cache-Control': 'no-cache, no-transform',
    Connection: 'keep-alive',
    // 关掉反向代理的缓冲（真上了 nginx 少这一行会变成「一次性吐完」）
    'X-Accel-Buffering': 'no'
  }, corsHeaders()))
  res.flushHeaders()
  if (res.socket && res.socket.setNoDelay) res.socket.setNoDelay(true)

  let closed = false
  // 用 res 的 close 而不是 req 的：req 的 close 在请求体读完时也会触发，
  // 会把「客户端还在收」误判成断开，结果一个字都发不出去
  res.on('close', () => { closed = true })

  // 心跳：注释行，端侧解析器会忽略；用来防中间层掐掉空闲连接
  const heartbeat = setInterval(() => {
    if (!closed) res.write(': ping\n\n')
  }, 15000)

  const write = (event, payload) => {
    if (closed) return
    res.write('event: ' + event + '\ndata: ' + JSON.stringify(payload) + '\n\n')
  }

  const wait = (ms) => (closed ? Promise.resolve() : sleep(ms))

  try {
    write('meta', {
      conversationId: turn.conversationId,
      assistantMsgId: turn.assistantMsgId,
      persona: PERSONA
    })
    await wait(perCharDelay)

    if (turn.error) {
      write('error', turn.error)
      return
    }

    const chars = Array.from(turn.text)
    for (let i = 0; i < chars.length; i += 1) {
      write('token', { t: chars[i] })
      await wait(perCharDelay)
    }

    // 先说完话，再补一个表情/卡片——顺序与真人聊天一致，端上呈现也更自然
    if (turn.sticker) {
      write('sticker', { token: turn.sticker })
      await wait(perCharDelay)
    }

    if (turn.card) {
      write('card', { card: turn.card })
      await wait(perCharDelay)
    }

    write('done', { assistantMsgId: turn.assistantMsgId, finishReason: 'stop' })
    appendHistory(body, turn)
  } catch (e) {
    write('error', { code: 'internal', message: 'mock 服务出错了', retryable: false })
  } finally {
    clearInterval(heartbeat)
    if (!closed) res.end()
  }
}

/* -------------------------------------------------------------------- CLI */

function parseArgs(argv) {
  const flags = {}
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i]
    if (!token.startsWith('--')) continue
    const eq = token.indexOf('=')
    if (eq !== -1) { flags[token.slice(2, eq)] = token.slice(eq + 1); continue }
    const key = token.slice(2)
    const next = argv[i + 1]
    if (next === undefined || next.startsWith('--')) flags[key] = true
    else { flags[key] = next; i += 1 }
  }
  return flags
}

const isDirectRun = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href

if (isDirectRun) {
  const flags = parseArgs(process.argv.slice(2))
  const host = typeof flags.host === 'string' ? flags.host : DEFAULT_HOST
  const port = flags.port !== undefined ? Number(flags.port) : DEFAULT_PORT
  const delayMs = flags.delay !== undefined ? Number(flags.delay) : DEFAULT_DELAY_MS

  startMockServer({ host, port, delayMs }).then((instance) => {
    console.log('比邻AI mock agent 已启动')
    console.log('  地址   : http://' + host + ':' + instance.port)
    console.log('  每字延迟: ' + delayMs + 'ms（--delay 0 可关闭）')
    console.log('  接口   : POST /v1/chat/stream · POST /v1/chat/send · GET /v1/chat/history')
    console.log('')
    console.log('  端侧联调：uni-app/api/config.js 里把 DEFAULT_BASE_URL 指向这个地址')
    console.log('  真机联调：加 --host 0.0.0.0，并把 baseURL 改成电脑的局域网 IP')
    console.log('  自检     : node tools/test-chat-api.mjs')
    console.log('')
    console.log('  Ctrl+C 退出')
  }).catch((error) => {
    console.error('启动失败：' + error.message)
    process.exit(1)
  })
}
