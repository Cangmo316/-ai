/**
 * 比邻AI · agent 接口层配置
 *
 * 纯 JS，无平台条件编译，可被 node 直接 import（供 tools/ 下的测试与工具复用）。
 */

/**
 * 默认后端地址。
 *
 * 端口与后端 `server/.env` 的 `PORT`（8000）保持一致。之前这里写的是 8787，
 * 而后端实际监听 8000——两者不一致会导致端侧所有接口「连不上服务器」。
 * 改端口时**两处一起改**：server/.env 的 PORT 与本常量。
 *
 * ⚠️ 三端各自的「本机」不是同一台机器，联调时按下面改：
 *   - HBuilderX 运行到浏览器（H5）：127.0.0.1 就是本机，默认值可直接用
 *   - 运行到 Android 模拟器：模拟器里的 127.0.0.1 指模拟器自身，需改 10.0.2.2
 *   - 运行到真机 / 微信开发者工具真机预览：需改成开发机局域网 IP，如 http://192.168.1.5:8000
 *   - 微信开发者工具：需在「详情 → 本地设置」勾选「不校验合法域名」
 *
 * 改法有两种，优先级从高到低：
 *   1) 运行期：setBaseURL('http://192.168.x.x:8000')（写入本地缓存，不用重新编译）
 *   2) 源码：直接改这个常量
 */
export const DEFAULT_BASE_URL = 'http://127.0.0.1:8000'

/** 本地缓存 key：运行期覆盖 baseURL 用 */
export const STORAGE_KEY_BASE_URL = 'bl_api_base'

/** 本地缓存 key：访问 token（服务端开了鉴权就必须配上） */
export const STORAGE_KEY_API_TOKEN = 'bl_api_token'

/** 接口路径（与《比邻AI_项目设计方案.md》§4.3 的契约一致） */
export const ENDPOINTS = {
  chatStream: '/v1/chat/stream',
  chatSend: '/v1/chat/send',
  chatHistory: '/v1/chat/history',
  // 康养计划（P1）：生成 → 家属确认 → 今日计划 → 打卡
  planDraft: '/v1/plans/draft',
  planPending: '/v1/plans/pending',
  planConfirm: '/v1/plans/confirm',
  planReject: '/v1/plans/reject',
  planToday: '/v1/plans/today',
  planCheckin: '/v1/plans/checkin',
  planSummary: '/v1/plans/summary',
  planAdjust: '/v1/plans/adjust',
  planHistory: '/v1/plans/history',
  elders: '/v1/elders',
  // 提醒投递（P1）：调度器到点投递，端侧拉取后展示
  reminderInbox: '/v1/reminders/inbox',
  reminderRead: '/v1/reminders/read',
  reminderTasks: '/v1/reminders/tasks',
  schedulerStatus: '/v1/scheduler/status',
  schedulerTick: '/v1/scheduler/tick',
  // 推送标识登记（uni-push 2.0）：端侧把 cid 报给服务端，服务端才知道提醒发到哪台设备
  pushRegister: '/v1/push/register',
  pushUnregister: '/v1/push/unregister',
  pushStatus: '/v1/push/status',
  // 三层记忆（P2）：L2 经历 / L3 偏好。老人端只读，写入由家人端或对话自动整理
  memories: '/v1/memories',
  memoryClear: '/v1/memories/clear',
  memoryReview: '/v1/memories/review',
  memorySettings: '/v1/memories/settings',
  memoryTopics: '/v1/memories/topics',
  // 账号（注册 / 登录 / 编号 / 头像）：注册后拿到 8 位编号作为对外身份
  accountRegister: '/v1/accounts/register',
  accountLogin: '/v1/accounts/login',
  accountMe: '/v1/accounts/me',
  accountAvatar: '/v1/accounts/avatar',
  accountOptions: '/v1/accounts/options',
  accountLookup: '/v1/accounts/lookup',
  // 会话与消息（含跨账号共享会话）：家人绑定后双方能看到同一份聊天记录
  conversations: '/v1/conversations',
  conversationMessages: '/v1/conversations/messages',
  conversationRead: '/v1/conversations/read',
  conversationBindings: '/v1/conversations/bindings',
  // 家人查看管理（只有互相绑定的家人能取）
  familyOverview: '/v1/family/overview',
  // 健康档案（血压/血糖/体重…）：作为智能体主动关心的依据
  healthTypes: '/v1/health/types',
  healthRecords: '/v1/health/records',
  healthSummary: '/v1/health/summary',
  // 病例病史（医院单据图片/PDF）：自动解析后给智能体当背景知识
  caseTypes: '/v1/cases/types',
  cases: '/v1/cases',
  visionStatus: '/v1/cases/vision/status'
}

/** 超时（ms）：首字节超时用看门狗实现，总超时只作用于非流式接口 */
export const TIMEOUT = {
  firstByte: 20000,
  total: 60000
}

/** 读取当前 baseURL（去掉结尾斜杠） */
export function getBaseURL() {
  let base = ''
  try {
    base = uni.getStorageSync(STORAGE_KEY_BASE_URL) || ''
  } catch (e) {
    base = ''
  }
  return String(base || DEFAULT_BASE_URL).replace(/\/+$/, '')
}

/** 运行期切换 baseURL（写本地缓存，下次启动仍生效） */
export function setBaseURL(url) {
  const value = String(url || '').replace(/\/+$/, '')
  try {
    if (value) uni.setStorageSync(STORAGE_KEY_BASE_URL, value)
    else uni.removeStorageSync(STORAGE_KEY_BASE_URL)
  } catch (e) {
    // 存储失败不影响本次会话，下次启动会回到默认值
  }
  return value || DEFAULT_BASE_URL
}

/** 拼接完整 URL：path 以 / 开头 */
export function resolveURL(path) {
  return getBaseURL() + path
}

/**
 * 访问 token（服务端开了鉴权就必须带上，否则所有 /v1 接口一律 401）。
 *
 * 设置方式，优先级从高到低：
 *   1. 运行期：`setApiToken('...')`（写本地缓存，下次启动仍生效）
 *   2. 源码：改下面的 `DEFAULT_API_TOKEN`（本机联调图省事用，**真 token 不要提交进仓库**）
 *   3. 都不设：服务端没开鉴权时不带这个头
 */
export const DEFAULT_API_TOKEN = ''

export function getApiToken() {
  let token = ''
  try {
    token = uni.getStorageSync(STORAGE_KEY_API_TOKEN) || ''
  } catch (e) {
    token = ''
  }
  return String(token || DEFAULT_API_TOKEN || '').trim()
}

export function setApiToken(token) {
  const value = String(token || '').trim()
  try {
    if (value) uni.setStorageSync(STORAGE_KEY_API_TOKEN, value)
    else uni.removeStorageSync(STORAGE_KEY_API_TOKEN)
  } catch (e) {
    // 存储失败不影响本次会话
  }
  return value
}

/**
 * 给请求头补上鉴别信息。
 * request.js（非流式）与 transport.js（流式）共用，避免两处各写一遍导致"某个接口漏带 token"。
 */
export function authHeaders(headers) {
  const merged = Object.assign({}, headers || {})
  const token = getApiToken()
  if (token && !merged.Authorization && !merged.authorization) {
    merged.Authorization = 'Bearer ' + token
  }
  return merged
}
