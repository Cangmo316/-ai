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
 *   node tools/mock-server.mjs --auth mytoken  # 模拟"服务端开了鉴权"
 *
 * 顺带托管两段静态文件（省得为看家人端再起一个 http 服务，也避免跨域）：
 *   http://127.0.0.1:8787/family/        家人端最小版（计划确认台）
 *   /uni-app/api/*                       家人端复用的那一层接口客户端
 *
 * 触发词（用来演示边界，不参与真实业务）：
 *   消息里含 __error  → 走到 error 事件分支（验证端侧错误态与重发）
 *   消息里含 __slow   → 每字放大到 10 倍延迟（验证「停止」按钮）
 */

import { readFile } from 'node:fs/promises'
import { createServer } from 'node:http'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

/** 静态托管白名单：前缀 → 仓库内目录（只放这两段，别把整个仓库暴露出去） */
const STATIC_PREFIXES = {
  '/family/': 'family',
  '/uni-app/api/': path.join('uni-app', 'api')
}

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png'
}

/** 返回 true 表示这个请求已被静态托管处理掉 */
async function serveStatic(url, res) {
  for (const [prefix, dir] of Object.entries(STATIC_PREFIXES)) {
    const bare = prefix.slice(0, -1)
    if (url.pathname !== bare && !url.pathname.startsWith(prefix)) continue

    const rel = url.pathname === bare ? 'index.html' : url.pathname.slice(prefix.length)
    const root = path.resolve(REPO_ROOT, dir)
    const target = path.resolve(root, rel || 'index.html')
    // 防目录穿越：解析后必须还在白名单目录里
    if (target !== root && !target.startsWith(root + path.sep)) {
      res.writeHead(403, { 'Content-Type': 'text/plain; charset=utf-8' })
      res.end('forbidden')
      return true
    }
    try {
      const data = await readFile(target)
      res.writeHead(200, {
        'Content-Type': MIME[path.extname(target).toLowerCase()] || 'application/octet-stream',
        // 开发期改完刷新就能看到，别让浏览器缓存捣乱
        'Cache-Control': 'no-store'
      })
      res.end(data)
    } catch (error) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' })
      res.end('not found: ' + rel)
    }
    return true
  }
  return false
}

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
    // Allow-Methods 必须把 PATCH/PUT 列全：浏览器的 CORS 预检是按方法名严格匹配的，
    // 少一个方法，家人端的"改记忆可见性（PATCH）/ 自动整理开关（PUT）"在真浏览器里直接发不出去
    // （node 侧的 fetch 不做预检，所以只有这条会静默漏掉）
    'Access-Control-Allow-Methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
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

// 与真实服务端 app/schedule/models.py 的 STATUS_LABELS 保持一致：
// 家属端的"提醒有没有送到"那一栏直接展示中文，不该出现英文枚举
const REMINDER_STATUS_LABEL = {
  pending: '还没到点',
  sent: '已送出',
  acked: '已打卡',
  missed: '没见回应',
  skipped: '没发（超出时间窗）',
  canceled: '已作废（计划换了）',
  failed: '发送失败'
}

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
  const plan = currentPlan(plans)
  // 没有生效计划就不该有提醒（"未确认不产生提醒"这条硬规则）
  if (!plan) return summary

  for (const item of plan.items) {
    if (plans.doneIds.has(item.id)) continue
    const sendAt = plans.date + 'T' + item.time + ':00'
    if (sendAt > stamp) continue
    if (state.delivered.some((task) => task.planItemId === item.id)) continue
    const level = levelOf(item)
    state.delivered.push({
      id: 'rt_mock_' + item.id,
      planId: plan.id,
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
      statusLabel: REMINDER_STATUS_LABEL.sent,
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
  const acked = plans.doneIds.has(task.planItemId)
  const status = acked ? 'acked' : task.status
  return Object.assign({}, task, {
    readAt: state.readIds.has(task.id) ? task.readAt || state.lastTickAt : task.readAt,
    ackAt: acked ? task.ackAt || state.lastTickAt : task.ackAt,
    status,
    // 状态跟着变化时标签也要跟着变，否则界面上会出现"已打卡 + 已送出"这种自相矛盾
    statusLabel: REMINDER_STATUS_LABEL[status] || status
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
  const first = makePlan({ id: 'plan_mock_1', status: 'active', kind: 'generate', reason: '' })
  return {
    elderId: 'e_1',
    /** 全部计划（含历史），与真实服务端的 plans_of 一致 */
    list: [first],
    date: todayKey(),
    doneIds: new Set(),
    seq: 1
  }
}

/** 真实服务端的状态与中文标签（app/plan/models.py），mock 必须一模一样，否则端侧会被带偏 */
const PLAN_STATUS_LABEL = {
  draft: '草稿',
  pending_confirm: '等家里人确认',
  active: '正在执行',
  adjusting: '调整中，等家里人确认',
  ended: '已结束',
  rejected: '家里人没同意'
}

function makePlan(options) {
  const status = options.status || 'pending_confirm'
  return {
    id: options.id,
    elderId: 'e_1',
    status,
    statusLabel: PLAN_STATUS_LABEL[status] || status,
    kind: options.kind || 'generate',
    goal: '把每天的监测、饮食、活动和问候安排清楚',
    reason: options.reason || '',
    createdAt: options.createdAt || new Date().toISOString(),
    confirmedAt: '',
    confirmedBy: '',
    rejectedReason: '',
    knowledgeVersion: '2026.09',
    items: PLAN_ITEMS.map((item) => Object.assign({}, item)),
    history: []
  }
}

/** 当前生效计划：active 或 adjusting（**adjusting 期间旧计划仍在执行**，与真实 store.active() 一致） */
function currentPlan(state) {
  return (
    state.list.find((plan) => plan.status === 'active') ||
    state.list.find((plan) => plan.status === 'adjusting') ||
    null
  )
}

function todayPayload(state) {
  const plan = currentPlan(state)
  if (!plan) {
    return {
      elderId: state.elderId,
      date: state.date,
      planId: '',
      status: '',
      statusLabel: '',
      items: [],
      total: 0,
      done: 0,
      rate: 0
    }
  }
  const items = plan.items.map((item) =>
    Object.assign({}, item, {
      done: state.doneIds.has(item.id),
      doneAt: state.doneIds.has(item.id) ? new Date().toISOString() : ''
    })
  )
  const done = items.filter((item) => item.done).length
  return {
    elderId: state.elderId,
    date: state.date,
    planId: plan.id,
    status: plan.status,
    statusLabel: plan.statusLabel,
    items,
    total: items.length,
    done,
    rate: items.length ? Math.round((done / items.length) * 1000) / 1000 : 0
  }
}

function planSummary(state) {
  const plan = currentPlan(state)
  const payload = todayPayload(state)
  const rate = payload.rate
  const shouldAdjust = rate < 0.5
  if (!plan) {
    return {
      elderId: state.elderId,
      hasPlan: false,
      status: '',
      stats: null,
      suggestion: { shouldAdjust: false, reasons: [], stats: null, advice: '' }
    }
  }
  return {
    elderId: state.elderId,
    hasPlan: true,
    planId: plan.id,
    status: plan.status,
    statusLabel: plan.statusLabel,
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
  /** 配了就要求 `Authorization: Bearer <authToken>`，用来测端侧有没有带 token */
  const authToken = String(options.authToken || '')
  const state = { lastAuth: '', requests: 0 }
  const plans = createPlanState()
  const reminders = createReminderState()
  const pushClients = new Map()

// ── 三层记忆（P2）：L2 经历 / L3 偏好 ─────────────────────────────// 种子数据刻意包含一条 source=auto 且待复核的，用来验证端侧与家人端**都看不到它**：
// 这条口径（自动整理的内容默认家属不可见、未复核不进检索）是隐私边界，mock 必须跟真服务一致
/** 中文粗切分：字符二元组。mock 的检索只是"量级近似"，不求与真服务同分 */
function bigrams(text) {
  const clean = String(text || '').replace(/[\s，。！？、,.!?：:；;]/g, '')
  const out = []
  for (let i = 0; i < clean.length - 1; i += 1) out.push(clean.slice(i, i + 2))
  return out.length ? out : [clean]
}

/** 自动整理的置信度门槛，与 server/app/memory/models.py 的 AUTO_MIN_CONFIDENCE 对齐 */
const AUTO_MIN_CONFIDENCE = 0.75

const memoryState = {
  seq: 4,
  // 自动整理的开关与同意时间**按老人各存一份**：真服务是 MemoryStore._settings[elder_id]
  // （server/app/memory/models.py:settings_for）。mock 早先是全局一个 bool，
  // 那会导致"给 e_1 开了开关，e_2 也变成开着"——对隐私开关来说这是错的一侧
  settings: {},
  entries: [
    {
      id: 'mem_1', elderId: 'e_1', kind: 'experience', kindLabel: '经历',
      text: '老人 2023 年跟儿子去过海南', tags: ['儿子', '旅行'],
      source: 'family', sourceLabel: '家里人填写', confidence: 1, review: 'approved',
      visibleToFamily: true, happenedAt: '2023年'
    },
    {
      id: 'mem_2', elderId: 'e_1', kind: 'preference', kindLabel: '喜好',
      text: '老人爱听戏，尤其爱听评剧', tags: ['戏曲', '评剧'],
      source: 'elder', sourceLabel: '老人自己说的', confidence: 0.9, review: 'approved',
      visibleToFamily: true, happenedAt: ''
    },
    {
      id: 'mem_3', elderId: 'e_1', kind: 'preference', kindLabel: '喜好',
      text: '老人喜欢下棋', tags: ['下棋'],
      source: 'auto', sourceLabel: '从聊天里整理', confidence: 0.88, review: 'approved',
      visibleToFamily: false, happenedAt: ''
    },
    {
      id: 'mem_4', elderId: 'e_1', kind: 'experience', kindLabel: '经历',
      text: '老人好像提过老家有座石桥', tags: ['老家'],
      source: 'auto', sourceLabel: '从聊天里整理', confidence: 0.4, review: 'pending',
      visibleToFamily: false, happenedAt: ''
    }
  ]
}

/** 每位老人一份设置（默认关），口径对齐 server/app/memory/models.py 的 settings_for */
function memorySettingsOf(elderId) {
  if (!memoryState.settings[elderId]) {
    memoryState.settings[elderId] = { autoExtract: false, consentedAt: '' }
  }
  return memoryState.settings[elderId]
}

  const server = createServer(async (req, res) => {
    const url = new URL(req.url, 'http://' + (req.headers.host || 'localhost'))
    state.requests += 1
    state.lastAuth = req.headers.authorization || ''

    if (req.method === 'OPTIONS') {
      res.writeHead(204, corsHeaders())
      res.end()
      return
    }

    // 静态托管放在最前面，且**不参与鉴权**：HTML/JS 先拿到手才有机会带 token 调接口
    if (req.method === 'GET' && (await serveStatic(url, res))) return

    // 公开路径与真实服务端保持一致：健康检查、错误码表
    const isPublic =
      url.pathname === '/healthz' || url.pathname === '/v1/errors' || url.pathname === '/debug/state'
    if (authToken && !isPublic) {
      const provided = String(state.lastAuth).replace(/^Bearer\s+/i, '').trim()
      if (provided !== authToken) {
        sendJSON(res, 401, {
          error: {
            code: provided ? 'unauthorized' : 'auth_required',
            message: provided ? '登录已过期，让家里人重新登录一下' : '需要先登录，让家里人帮你看一下',
            retryable: false
          }
        })
        return
      }
    }

    if (url.pathname === '/v1/errors' && req.method === 'GET') {
      // 与真实服务端同构：公开、只暴露 code/status/message/retryable
      sendJSON(res, 200, {
        codes: [
          { code: 'auth_required', status: 401, message: '需要先登录，让家里人帮你看一下', retryable: false },
          { code: 'unauthorized', status: 401, message: '登录已过期，让家里人重新登录一下', retryable: false },
          { code: 'not_found', status: 404, message: '没有这个接口', retryable: false },
          { code: 'plan_state', status: 409, message: '这份计划现在不能这么做', retryable: false },
          { code: 'llm_timeout', status: 504, message: '等我一下 我这边有点慢', retryable: true },
          { code: 'internal', status: 500, message: '服务器开小差了，一会儿再试', retryable: true }
        ],
        note: 'mock 只列常用码；完整表见 server/app/errors.py 与 uni-app/api/README.md'
      })
      return
    }

    if (url.pathname === '/debug/state' && req.method === 'GET') {
      sendJSON(res, 200, { lastAuth: state.lastAuth, requests: state.requests })
      return
    }

    if (url.pathname === '/healthz') {
      sendJSON(res, 200, {
        ok: true,
        service: 'bilin-mock-agent',
        delayMs,
        auth: { required: Boolean(authToken) },
        // 与后端 /healthz 的 voice 字段同形状：让端侧与验收脚本用同一套判据
        voice: { tts: 'MockTts', aligner: '（mock 自带字级时间戳）', ttsReady: true, alignReady: true }
      })
      return
    }

    // ── 合成音频（短期签名 URL，**播放器带不了 Authorization 头**，故靠签名自证）──
    if (url.pathname.startsWith('/v1/audio/') && req.method === 'GET') {
      const audioId = decodeURIComponent(url.pathname.slice('/v1/audio/'.length))
      const expires = Number(url.searchParams.get('expires') || 0)
      const signature = url.searchParams.get('sig') || ''
      const expired = !expires || expires * 1000 < Date.now()
      const badSignature = signature !== mockAudioSignature(audioId, expires)
      // 403/404 用同一句话，避免通过错误差异探测 id 是否存在（与后端一致）
      if (expired || badSignature || !mockAudioIds.has(audioId)) {
        sendJSON(res, 403, { code: 'audio_forbidden', message: '音频链接无效或已过期' })
        return
      }
      res.writeHead(200, Object.assign({
        // 与真实实现一致地**如实**声明类型：mock 发的是 WAV（静音可精确控制），
        // 真后端发的是百炼的 MP3。两者都合法，端侧按 Content-Type 都能放。
        'Content-Type': 'audio/wav',
        'Content-Length': MOCK_AUDIO_BYTES.length,
        'Cache-Control': 'private, max-age=300'
      }, corsHeaders()))
      res.end(MOCK_AUDIO_BYTES)
      return
    }

    // ── 康养计划 ──────────────────────────────────────────────
    if (url.pathname === '/v1/plans/today' && req.method === 'GET') {
      sendJSON(res, 200, todayPayload(plans))
      return
    }

    if (url.pathname === '/v1/plans/checkin' && req.method === 'POST') {
      readBody(req).then((body) => {
        const plan = currentPlan(plans)
        const itemId = String((body && body.planItemId) || '')
        if (!plan) {
          sendJSON(res, 409, { error: { code: 'plan_not_active', message: '还没有生效的计划，先让家里人确认', retryable: false } })
          return
        }
        if (!plan.items.some((item) => item.id === itemId)) {
          sendJSON(res, 404, { error: { code: 'plan_item_not_found', message: '没找到这一项', retryable: false } })
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

    // ── 康养计划：家属端（生成 → 确认 → 生效 / 驳回 / 调整）──
    if (url.pathname === '/v1/plans/pending' && req.method === 'GET') {
      sendJSON(res, 200, {
        elderId: plans.elderId,
        plans: plans.list.filter((plan) => plan.status === 'pending_confirm')
      })
      return
    }

    if (url.pathname === '/v1/plans/draft' && req.method === 'POST') {
      readBody(req).then((body) => {
        plans.seq += 1
        const draft = makePlan({
          id: 'plan_mock_draft_' + plans.seq,
          status: 'pending_confirm',
          kind: 'generate',
          reason: (body && body.reason) || ''
        })
        draft.history.push({ at: new Date().toISOString(), action: 'draft', detail: '按知识库生成', actor: 'agent' })
        plans.list.push(draft)
        sendJSON(res, 200, {
          plan: draft,
          reused: false,
          // 形状与真实服务端一致：{asked, polished, fallback, reasons}
          polish: { asked: draft.items.length, polished: 0, fallback: draft.items.length, reasons: ['mock 不做话术润色'] }
        })
      }).catch((err) => sendJSON(res, 400, { error: { code: 'bad_request', message: err.message } }))
      return
    }

    if (url.pathname === '/v1/plans/confirm' && req.method === 'POST') {
      readBody(req).then((body) => {
        const planId = String((body && body.planId) || '')
        const plan = plans.list.find((item) => item.id === planId)
        if (!plan) {
          sendJSON(res, 404, { error: { code: 'plan_not_found', message: '没找到这份计划', retryable: false } })
          return
        }
        if (plan.status !== 'pending_confirm') {
          sendJSON(res, 409, {
            error: { code: 'plan_state', message: '这份计划现在不能确认（当前是「' + plan.statusLabel + '」）', retryable: false }
          })
          return
        }
        // 确认的这一刻才结束旧计划（过渡期旧计划继续执行，避免提醒真空）
        const previous = currentPlan(plans)
        const previousPlanId = previous && previous.id !== plan.id ? previous.id : ''
        if (previousPlanId) {
          previous.status = 'ended'
          previous.statusLabel = PLAN_STATUS_LABEL.ended
          previous.history.push({ at: new Date().toISOString(), action: 'ended', detail: '新计划已确认', actor: 'system' })
        }
        plan.status = 'active'
        plan.statusLabel = PLAN_STATUS_LABEL.active
        plan.confirmedAt = new Date().toISOString()
        plan.confirmedBy = (body && body.actor) || '家属'
        plan.history.push({ at: plan.confirmedAt, action: 'confirm', detail: '家属确认', actor: plan.confirmedBy })
        sendJSON(res, 200, { plan, previousPlanId, notice: '计划已生效，开始按时间提醒' })
      }).catch((err) => sendJSON(res, 400, { error: { code: 'bad_request', message: err.message } }))
      return
    }

    if (url.pathname === '/v1/plans/reject' && req.method === 'POST') {
      readBody(req).then((body) => {
        const planId = String((body && body.planId) || '')
        const plan = plans.list.find((item) => item.id === planId)
        if (!plan) {
          sendJSON(res, 404, { error: { code: 'plan_not_found', message: '没找到这份计划', retryable: false } })
          return
        }
        if (plan.status !== 'pending_confirm') {
          sendJSON(res, 409, {
            error: { code: 'plan_state', message: '这份计划现在不能驳回（当前是「' + plan.statusLabel + '」）', retryable: false }
          })
          return
        }
        plan.status = 'rejected'
        plan.statusLabel = PLAN_STATUS_LABEL.rejected
        plan.rejectedReason = (body && body.reason) || ''
        plan.history.push({
          at: new Date().toISOString(),
          action: 'reject',
          detail: plan.rejectedReason,
          actor: (body && body.actor) || '家属'
        })
        sendJSON(res, 200, { plan, notice: '已驳回，这份计划不会生效' })
      }).catch((err) => sendJSON(res, 400, { error: { code: 'bad_request', message: err.message } }))
      return
    }

    if (url.pathname === '/v1/plans/adjust' && req.method === 'POST') {
      readBody(req).then((body) => {
        const planId = String((body && body.planId) || '')
        const plan = plans.list.find((item) => item.id === planId)
        if (!plan) {
          sendJSON(res, 404, { error: { code: 'plan_not_found', message: '没找到这份计划', retryable: false } })
          return
        }
        if (plan.status !== 'active') {
          sendJSON(res, 409, {
            error: { code: 'plan_state', message: '只有正在执行的计划能转入调整（当前是「' + plan.statusLabel + '」）', retryable: false }
          })
          return
        }
        // 真实语义：**还是这份计划**，只是进入 adjusting；它仍在执行（store.active 认 active+adjusting）
        plan.status = 'adjusting'
        plan.statusLabel = PLAN_STATUS_LABEL.adjusting
        plan.reason = (body && body.reason) || '家属发起调整'
        plan.history.push({ at: new Date().toISOString(), action: 'adjusting', detail: plan.reason, actor: (body && body.actor) || '家属' })
        sendJSON(res, 200, {
          plan,
          suggestion: { shouldAdjust: true, reasons: [plan.reason], stats: null, advice: '改完由家属确认后生效' },
          notice: '已转入调整，等家里人确认'
        })
      }).catch((err) => sendJSON(res, 400, { error: { code: 'bad_request', message: err.message } }))
      return
    }

    if (url.pathname === '/v1/plans/history' && req.method === 'GET') {
      // 真实服务端返回的是**计划列表摘要**，不是审计流水（审计在每个计划的 history 字段里）
      sendJSON(res, 200, {
        elderId: plans.elderId,
        plans: plans.list.map((plan) => ({
          id: plan.id,
          status: plan.status,
          statusLabel: plan.statusLabel,
          createdAt: plan.createdAt,
          confirmedAt: plan.confirmedAt,
          items: plan.items.length,
          knowledgeVersion: plan.knowledgeVersion
        }))
      })
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

    // ── 三层记忆（P2）──────────────────────────────────────────────
    // 与真服务同一份口径：默认只回家属可见的；待复核的默认不出现也不参与检索
    if (url.pathname === '/v1/memories' && req.method === 'GET') {
      const elderId = url.searchParams.get('elderId') || 'e_1'
      const kind = url.searchParams.get('kind')
      const q = url.searchParams.get('q')
      const scope = url.searchParams.get('scope') || 'family'
      const includePending = url.searchParams.get('includePending') === 'true'
      const limit = Number(url.searchParams.get('limit') || 50)

      const mine = memoryState.entries.filter((entry) => entry.elderId === elderId)
      const pendingCount = mine.filter((entry) => entry.review === 'pending').length

      if (q) {
        // mock 用"字符二元组命中数"近似真服务的相关性检索，只求量级一致，不求同分
        const grams = bigrams(q)
        const ranked = mine
          .filter((entry) => entry.review === 'approved')
          .map((entry) => {
            const hay = entry.text + ' ' + (entry.tags || []).join(' ')
            let hits = 0
            grams.forEach((gram) => { if (hay.includes(gram)) hits += 1 })
            return { entry, score: hits ? Number((hits / Math.max(1, grams.length)).toFixed(3)) : 0 }
          })
          .filter((row) => row.score > 0)
          .sort((a, b) => b.score - a.score)
          .slice(0, limit)
        sendJSON(res, 200, {
          elderId, query: q, scope, count: ranked.length,
          memories: ranked.map((row) => Object.assign({}, row.entry, { score: row.score }))
        })
        return
      }

      let entries =
        scope === 'all'
          ? mine.slice()
          : mine.filter((entry) => entry.review === 'approved' && entry.visibleToFamily)
      if (!includePending) entries = entries.filter((entry) => entry.review !== 'pending')
      if (kind) entries = entries.filter((entry) => entry.kind === kind)
      sendJSON(res, 200, {
        elderId, scope, count: entries.slice(0, limit).length,
        memories: entries.slice(0, limit),
        pendingCount
      })
      return
    }

    if (url.pathname === '/v1/memories' && req.method === 'POST') {
      readBody(req).then((body) => {
        const text = String((body && body.text) || '').trim()
        if (!text) {
          sendJSON(res, 400, { error: { code: 'memory_empty', message: '要记的内容不能是空的', retryable: false } })
          return
        }
        const kind = (body && body.kind) || 'experience'
        if (!['experience', 'preference', 'profile'].includes(kind)) {
          sendJSON(res, 422, { error: { code: 'invalid_request', message: '记忆种类不合法', retryable: false } })
          return
        }
        const source = (body && body.source) || 'family'
        // 与真服务同口径：**不许客户端声明 source=auto**（见 server/app/api/memories.py）。
        // 否则客户端能把"从聊天整理"的内容标成 visibleToFamily=true，从接口层绕开
        // "家人端默认看不到聊天原文"（真服务上实测过这个洞，已堵）
        if (source !== 'family' && source !== 'elder') {
          sendJSON(res, 422, {
            error: {
              code: 'invalid_request',
              message: 'source 只能是 family 或 elder；从聊天自动整理的记忆由服务端生成，不能手工声明',
              retryable: false
            }
          })
          return
        }
        // 复核状态与家属可见性**不写死**：真服务在 MemoryStore.add 里按 source/confidence 推导
        //   confidence < 0.75 → review=pending（source=auto 时 auto 由服务端生成，接口发不出来）
        // mock 早先一律 approved + visible，于是"自动整理的低置信内容会被当成可用且家属可见"，
        // 这正是两条隐私硬约束要拦的东西。推导口径必须跟 server/app/memory/models.py 一致
        const confidence =
          body && typeof body.confidence === 'number' ? body.confidence : 1
        const entry = {
          id: 'mem_' + (++memoryState.seq),
          elderId: (body && body.elderId) || 'e_1',
          kind,
          kindLabel: { experience: '经历', preference: '喜好', profile: '习惯' }[kind],
          text,
          tags: Array.isArray(body && body.tags) ? body.tags : [],
          source,
          sourceLabel: { family: '家里人填写', elder: '老人自己说的', auto: '从聊天里整理' }[source] || source,
          confidence,
          review:
            body && body.review
              ? body.review
              : confidence < AUTO_MIN_CONFIDENCE
                ? 'pending'
                : 'approved',
          visibleToFamily:
            body && body.visibleToFamily !== undefined ? !!body.visibleToFamily : true,
          happenedAt: (body && body.happenedAt) || ''
        }
        memoryState.entries.push(entry)
        sendJSON(res, 200, { memory: entry, notice: '已记住，之后对话里会自然用到' })
      }).catch((err) => sendJSON(res, 400, { error: { code: 'bad_request', message: err.message } }))
      return
    }

    if (url.pathname.startsWith('/v1/memories/') && req.method === 'DELETE') {
      const id = decodeURIComponent(url.pathname.replace('/v1/memories/', ''))
      const index = memoryState.entries.findIndex((entry) => entry.id === id)
      if (index < 0) {
        sendJSON(res, 404, { error: { code: 'memory_not_found', message: '没找到这条记忆', retryable: false } })
        return
      }
      memoryState.entries.splice(index, 1)
      sendJSON(res, 200, { ok: true, notice: '已删除，对话里不会再提到它' })
      return
    }

    if (url.pathname === '/v1/memories/clear' && req.method === 'POST') {
      readBody(req).then((body) => {
        const elderId = (body && body.elderId) || 'e_1'
        const before = memoryState.entries.length
        memoryState.entries = memoryState.entries.filter((entry) => entry.elderId !== elderId)
        sendJSON(res, 200, { ok: true, removed: before - memoryState.entries.length, notice: '这位老人的记忆已清空' })
      }).catch((err) => sendJSON(res, 400, { error: { code: 'bad_request', message: err.message } }))
      return
    }

    if (url.pathname === '/v1/memories/review' && req.method === 'POST') {
      readBody(req).then((body) => {
        const entry = memoryState.entries.find((row) => row.id === ((body && body.id) || ''))
        if (!entry) {
          sendJSON(res, 404, { error: { code: 'memory_not_found', message: '没找到这条记忆', retryable: false } })
          return
        }
        const approve = !(body && body.approve === false)
        entry.review = approve ? 'approved' : 'rejected'
        sendJSON(res, 200, {
          memory: entry,
          notice: approve ? '已通过，之后可以用它主动关心' : '已否决，不会再使用'
        })
      }).catch((err) => sendJSON(res, 400, { error: { code: 'bad_request', message: err.message } }))
      return
    }

    if (url.pathname === '/v1/memories/settings' && req.method === 'GET') {
      const elderId = url.searchParams.get('elderId') || 'e_1'
      const settings = memorySettingsOf(elderId)
      sendJSON(res, 200, {
        settings: {
          elderId,
          autoExtract: settings.autoExtract,
          consentedAt: settings.consentedAt,
          notice: '从聊天自动整理记忆需要先明确告知本人并在这里开启；关闭后不再新增，已入库的仍可单条删除或一键清空'
        }
      })
      return
    }

    if (url.pathname === '/v1/memories/settings' && req.method === 'PUT') {
      readBody(req).then((body) => {
        const elderId = (body && body.elderId) || 'e_1'
        const settings = memorySettingsOf(elderId)
        if (body && body.autoExtract !== undefined) {
          settings.autoExtract = !!body.autoExtract
          // 同意时间只在**第一次开启**时记，且关掉也不清（它是"曾明确告知过"的凭证）
          if (settings.autoExtract && !settings.consentedAt) settings.consentedAt = localStamp(new Date())
        }
        sendJSON(res, 200, {
          settings: {
            elderId,
            autoExtract: settings.autoExtract,
            consentedAt: settings.consentedAt
          }
        })
      }).catch((err) => sendJSON(res, 400, { error: { code: 'bad_request', message: err.message } }))
      return
    }

    if (url.pathname === '/v1/memories/topics' && req.method === 'GET') {
      const elderId = url.searchParams.get('elderId') || 'e_1'
      const limit = Number(url.searchParams.get('limit') || 5)
      const weights = new Map()
      memoryState.entries
        .filter((entry) => entry.elderId === elderId && entry.review === 'approved')
        .forEach((entry) => {
          const boost = (entry.source !== 'auto' ? 1 : 0.7) + (entry.kind === 'preference' ? 0.3 : 0)
          ;(entry.tags.length ? entry.tags : [entry.text.slice(0, 8)]).forEach((tag) => {
            const row = weights.get(tag) || { topic: tag, weight: 0, from: [] }
            row.weight = Number((row.weight + boost).toFixed(2))
            if (row.from.length < 3) row.from.push(entry.text)
            weights.set(tag, row)
          })
        })
      const topics = Array.from(weights.values()).sort((a, b) => b.weight - a.weight).slice(0, limit)
      sendJSON(res, 200, { elderId, topics })
      return
    }

    // ⚠️ 路径参数路由（`/v1/memories/{id}`）必须放在所有**字面量路径**之后：
    // FastAPI 是按注册顺序匹配的，字面量先注册；mock 早先把它放在前面，
    // 于是 `PATCH /v1/memories/settings` 会被当成"改 id 叫 settings 的记忆"→ 404 没找到这条记忆
    if (url.pathname.startsWith('/v1/memories/') && req.method === 'PATCH') {
      const id = decodeURIComponent(url.pathname.replace('/v1/memories/', ''))
      readBody(req).then((body) => {
        const entry = memoryState.entries.find((row) => row.id === id)
        if (!entry) {
          sendJSON(res, 404, { error: { code: 'memory_not_found', message: '没找到这条记忆', retryable: false } })
          return
        }
        const text = body && body.text !== undefined ? String(body.text).trim() : null
        if (text !== null && !text) {
          sendJSON(res, 400, { error: { code: 'memory_empty', message: '要记的内容不能是空的', retryable: false } })
          return
        }
        if (text) entry.text = text
        if (body && Array.isArray(body.tags)) entry.tags = body.tags
        if (body && body.visibleToFamily !== undefined) entry.visibleToFamily = !!body.visibleToFamily
        if (body && body.happenedAt !== undefined) entry.happenedAt = body.happenedAt
        sendJSON(res, 200, { memory: entry })
      }).catch((err) => sendJSON(res, 400, { error: { code: 'bad_request', message: err.message } }))
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
        }),
        /** 测试用：最后一次请求的 Authorization 头与请求计数 */
        state
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

/* ------------------------------------------------------- 音频（合成结果） */

/**
 * 一段**真实可播放的静音音频**（WAV，默认 3 秒），运行时生成。
 *
 * ⚠️ 踩坑记录：第一版用"两帧静音 MP3"（417 字节 × 2），
 * 浏览器实测 `duration = 0.052125` —— **只有 52 毫秒**，等于没声音，
 * 口型也一闪而过。当时我用"字节像 MP3"这种形状断言就以为验过了，**是假验证**。
 * 改成 WAV：静音时长可以精确控制，任何浏览器都能解码，且不需要编码器。
 *
 * 为什么 mock 要真发音频：端侧 `innerAudioContext` / `<audio>` 的播放链路
 * 只有拿到**能解码、且够长**的字节才算验证过。
 */
function buildSilentWav(seconds = 3, sampleRate = 16000) {
  const frames = Math.round(seconds * sampleRate)
  const dataBytes = frames * 2                      // 16bit 单声道
  const buffer = Buffer.alloc(44 + dataBytes)       // 44 字节是标准 WAV 头
  buffer.write('RIFF', 0)
  buffer.writeUInt32LE(36 + dataBytes, 4)
  buffer.write('WAVE', 8)
  buffer.write('fmt ', 12)
  buffer.writeUInt32LE(16, 16)                      // fmt 块长度
  buffer.writeUInt16LE(1, 20)                       // PCM
  buffer.writeUInt16LE(1, 22)                       // 声道数
  buffer.writeUInt32LE(sampleRate, 24)
  buffer.writeUInt32LE(sampleRate * 2, 28)          // 字节率
  buffer.writeUInt16LE(2, 32)                       // 块对齐
  buffer.writeUInt16LE(16, 34)                      // 位深
  buffer.write('data', 36)
  buffer.writeUInt32LE(dataBytes, 40)
  // 负载全 0 = 静音
  return buffer
}
const MOCK_AUDIO_SECONDS = 3
const MOCK_AUDIO_BYTES = buildSilentWav(MOCK_AUDIO_SECONDS)
/**
 * 已"发放"的音频 id 集合：只有发过音频事件的 id 才允许取。
 * 这样 mock 也能验证"**没发过的 id 取不到**"这条约束（而不是任何 id 都给音频）。
 */
const mockAudioIds = new Set()
/**
 * mock 的音频签名：与真实现**同形状**（`expires` + `sig` 查询参数）但不共用密钥。
 * 端侧只关心"这个 URL 能取到音频"，签名算法细节由各自服务端决定。
 * 用简单哈希而不是 HMAC：mock 不引入 crypto 依赖，且它不承载真实数据。
 */
const MOCK_AUDIO_SECRET = 'mock-audio-secret'
function mockAudioSignature(id, expires) {
  const text = id + '.' + expires + '.' + MOCK_AUDIO_SECRET
  let hash = 0
  for (let i = 0; i < text.length; i += 1) {
    hash = (hash * 31 + text.charCodeAt(i)) | 0
  }
  return (hash >>> 0).toString(16).padStart(8, '0')
}
function buildMockAudioUrl(id, ttlSeconds = 600) {
  const expires = Math.floor(Date.now() / 1000) + ttlSeconds
  return '/v1/audio/' + id + '?expires=' + expires + '&sig=' + mockAudioSignature(id, expires)
}

/* --------------------------------------------------------------- 口型关键帧 */

/**
 * 文字 → 口型关键帧（viseme cues）。
 *
 * ⚠️ 这是**后端 `server/app/avatar/visemes.py` 的等价实现**，两者必须给出**同样的口径**
 * （字段名、时间单位、最多 2 个 viseme）。改动任一侧都要同步另一侧 + 契约文档。
 *
 * 这里是**精简版**：只收录日常对话高频字的拼音，未收录的回退 `vis_AA`（开口）。
 * 真实现（后端那份）收录更全；mock 的作用只是把「契约 + 端侧驱动」这条链跑通。
 *
 * 时间轴按字数估算（与 mock 逐字吐字的节奏一致：默认 110ms/字），
 * **不是真实语音对齐** —— 真 TTS 就绪后这个字段会由真时间戳取代。
 */
const VISEME_INITIALS = {
  b: 'vis_MBP', p: 'vis_MBP', m: 'vis_MBP', f: 'vis_FV',
  d: 'vis_L', t: 'vis_L', n: 'vis_NN', l: 'vis_L',
  g: 'vis_KK', k: 'vis_KK', h: 'vis_KK',
  j: 'vis_SS', q: 'vis_SS', x: 'vis_SS',
  zh: 'vis_SS', ch: 'vis_SS', sh: 'vis_SS', r: 'vis_RR',
  z: 'vis_SS', c: 'vis_SS', s: 'vis_SS', y: 'vis_I', w: 'vis_WQ'
}
const VISEME_FINALS = {
  a: ['vis_AA'], o: ['vis_O'], e: ['vis_E'], i: ['vis_I'], u: ['vis_U'], v: ['vis_U'],
  er: ['vis_RR'],
  ai: ['vis_AA', 'vis_I'], ei: ['vis_E', 'vis_I'], ao: ['vis_AA', 'vis_O'], ou: ['vis_O', 'vis_U'],
  an: ['vis_AA'], en: ['vis_E'], ang: ['vis_AA'], eng: ['vis_E'], ong: ['vis_O'],
  ia: ['vis_I', 'vis_AA'], ie: ['vis_I', 'vis_E'], iao: ['vis_I', 'vis_AA', 'vis_O'],
  iu: ['vis_I', 'vis_U'], ian: ['vis_I'], in: ['vis_I'], iang: ['vis_I'], ing: ['vis_I'],
  iong: ['vis_I'], ua: ['vis_U', 'vis_AA'], uo: ['vis_U', 'vis_O'],
  uai: ['vis_U', 'vis_AA', 'vis_I'], ui: ['vis_U', 'vis_I'], uan: ['vis_U'], un: ['vis_U'],
  uang: ['vis_U'], ueng: ['vis_U'], ve: ['vis_U', 'vis_E'], van: ['vis_U'], vn: ['vis_U']
}
/** 常用字 → 无声调拼音（与后端表同口径，仅收录高频字） */
const PINYIN = {
  妈: 'ma', 爸: 'ba', 你: 'ni', 我: 'wo', 他: 'ta', 她: 'ta', 们: 'men', 的: 'de',
  了: 'le', 是: 'shi', 在: 'zai', 有: 'you', 不: 'bu', 和: 'he', 就: 'jiu', 都: 'dou',
  也: 'ye', 还: 'hai', 要: 'yao', 会: 'hui', 能: 'neng', 可: 'ke', 以: 'yi', 好: 'hao',
  很: 'hen', 这: 'zhe', 那: 'na', 个: 'ge', 什: 'shen', 么: 'me', 样: 'yang', 谁: 'shui',
  哪: 'na', 里: 'li', 吃: 'chi', 喝: 'he', 睡: 'shui', 觉: 'jiao', 走: 'zou', 来: 'lai',
  去: 'qu', 回: 'hui', 到: 'dao', 看: 'kan', 听: 'ting', 说: 'shuo', 做: 'zuo', 给: 'gei',
  拿: 'na', 放: 'fang', 开: 'kai', 关: 'guan', 今: 'jin', 天: 'tian', 明: 'ming', 昨: 'zuo',
  早: 'zao', 晚: 'wan', 上: 'shang', 下: 'xia', 中: 'zhong', 午: 'wu', 点: 'dian', 分: 'fen',
  年: 'nian', 月: 'yue', 日: 'ri', 号: 'hao', 星: 'xing', 期: 'qi', 药: 'yao', 医: 'yi',
  生: 'sheng', 院: 'yuan', 病: 'bing', 身: 'shen', 体: 'ti', 血: 'xue', 压: 'ya', 糖: 'tang',
  心: 'xin', 脏: 'zang', 头: 'tou', 疼: 'teng', 痛: 'tong', 舒: 'shu', 服: 'fu', 饭: 'fan',
  菜: 'cai', 水: 'shui', 汤: 'tang', 果: 'guo', 茶: 'cha', 子: 'zi', 女: 'nv', 儿: 'er',
  孙: 'sun', 家: 'jia', 人: 'ren', 老: 'lao', 太: 'tai', 爷: 'ye', 奶: 'nai', 姨: 'yi',
  叔: 'shu', 朋: 'peng', 友: 'you', 邻: 'lin', 居: 'ju', 行: 'xing', 对: 'dui', 没: 'mei',
  事: 'shi', 别: 'bie', 请: 'qing', 谢: 'xie', 再: 'zai', 见: 'jian', 您: 'nin', 一: 'yi',
  二: 'er', 三: 'san', 四: 'si', 五: 'wu', 六: 'liu', 七: 'qi', 八: 'ba', 九: 'jiu',
  十: 'shi', 百: 'bai', 千: 'qian', 坐: 'zuo', 站: 'zhan', 起: 'qi', 躺: 'tang', 慢: 'man',
  快: 'kuai', 多: 'duo', 少: 'shao', 大: 'da', 小: 'xiao', 高: 'gao', 低: 'di', 冷: 'leng',
  热: 're', 暖: 'nuan', 凉: 'liang', 风: 'feng', 雨: 'yu', 雪: 'xue', 晴: 'qing', 阴: 'yin',
  记: 'ji', 得: 'de', 忘: 'wang', 想: 'xiang', 念: 'nian', 喜: 'xi', 欢: 'huan', 爱: 'ai',
  怕: 'pa', 累: 'lei', 忙: 'mang', 闲: 'xian', 帮: 'bang', 等: 'deng', 着: 'zhe', 先: 'xian',
  后: 'hou', 现: 'xian', 已: 'yi', 经: 'jing', 刚: 'gang', 才: 'cai', 正: 'zheng', 马: 'ma',
  挺: 'ting', 真: 'zhen', 特: 'te', 问: 'wen', 题: 'ti', 办: 'ban', 法: 'fa', 需: 'xu',
  准: 'zhun', 备: 'bei', 完: 'wan', 成: 'cheng', 始: 'shi', 电: 'dian', 话: 'hua', 视: 'shi',
  频: 'pin', 聊: 'liao', 通: 'tong', 照: 'zhao', 片: 'pian'
}
const VISEME_DEFAULT = 'vis_AA'
const VISEME_SILENCE = 'vis_silence'

function visemesForChar(ch) {
  const syllable = PINYIN[ch]
  if (!syllable) return [VISEME_DEFAULT]
  let initial = ''
  let rest = syllable
  if (VISEME_INITIALS[syllable.slice(0, 2)]) {
    initial = syllable.slice(0, 2)
    rest = syllable.slice(2)
  } else if (VISEME_INITIALS[syllable.slice(0, 1)]) {
    initial = syllable.slice(0, 1)
    rest = syllable.slice(1)
  }
  const out = []
  if (initial) out.push(VISEME_INITIALS[initial])
  const finals = VISEME_FINALS[rest] || VISEME_FINALS[rest.slice(0, 2)] || [VISEME_DEFAULT]
  out.push(...finals)
  const deduped = out.filter((v, i) => i === 0 || out[i - 1] !== v)
  return deduped.slice(0, 2)
}

/** 生成 SSE `lipsync` 的 payload（字段与后端 build_lipsync_payload 一致） */
function buildLipsyncPayload(text, assistantMsgId, charMs) {
  const perChar = Number.isFinite(charMs) && charMs > 0 ? charMs : 110
  const cues = []
  let cursor = 0
  for (const ch of Array.from(text || '')) {
    if (/\s/.test(ch)) { cursor += 40; continue }
    if ('。！？!?…'.includes(ch)) { cursor += 380; continue }
    if ('，,、；;：:'.includes(ch)) { cursor += 220; continue }
    const isCjk = /[\u4e00-\u9fff]/.test(ch)
    const visemes = isCjk ? visemesForChar(ch) : [VISEME_DEFAULT]
    const start = cursor
    cursor += perChar
    cues.push({ c: ch, b: start, e: cursor, v: visemes })
  }
  if (cursor > 0) cues.push({ c: '', b: cursor, e: cursor + 120, v: [VISEME_SILENCE] })
  return {
    assistantMsgId: assistantMsgId || '',
    durationMs: cursor + 120,
    cues,
    version: 1,
    source: 'estimated'
  }
}

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

    // 音频 + 口型关键帧：都在 done 之前发，**顺序是 audio → lipsync**
    // （与后端一致：端侧要先把音频下载并起播，才能用音频时刻驱动口型，否则音画漂移）。
    if ((turn.text || '').trim()) {
      const audioId = 'aud_' + turn.assistantMsgId
      mockAudioIds.add(audioId)
      write('audio', {
        assistantMsgId: turn.assistantMsgId,
        url: buildMockAudioUrl(audioId),
        durationMs: MOCK_AUDIO_SECONDS * 1000,   // 与 MOCK_AUDIO_BYTES 的静音时长严格对应
        format: 'wav',
        bytes: MOCK_AUDIO_BYTES.length
      })
      await wait(60)
      write('lipsync', buildLipsyncPayload(turn.text, turn.assistantMsgId, perCharDelay))
      await wait(60)
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
  // --auth <token>：模拟"服务端开了鉴权"，用来验证端侧有没有带 Authorization
  const authToken = typeof flags.auth === 'string' ? flags.auth : ''

  startMockServer({ host, port, delayMs, authToken }).then((instance) => {
    console.log('比邻AI mock agent 已启动')
    console.log('  地址   : http://' + host + ':' + instance.port)
    console.log('  每字延迟: ' + delayMs + 'ms（--delay 0 可关闭）')
    console.log('  鉴权   : ' + (authToken ? '要求 Authorization: Bearer <token>' : '关闭（--auth <token> 可打开）'))
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
