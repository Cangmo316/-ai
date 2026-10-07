/**
 * 比邻AI · agent 接口层出口
 *
 * 页面只从这里 import，不直接摸 transport / sse-parse。
 * 用法示例见 api/README.md。
 */

export {
  DEFAULT_API_TOKEN,
  DEFAULT_BASE_URL,
  ENDPOINTS,
  STORAGE_KEY_API_TOKEN,
  TIMEOUT,
  authHeaders,
  getApiToken,
  getBaseURL,
  resolveURL,
  setApiToken,
  setBaseURL
} from './config.js'

export { request } from './request.js'

export {
  CHAT_EVENT,
  chatStream,
  chatSendOnce,
  chatHistory,
  getModelSetting,
  saveModelSetting,
  testModelSetting
} from './chat.js'

export {
  confirmPlan,
  createPlanDraft,
  fetchElders,
  fetchPendingPlans,
  fetchPlanHistory,
  fetchPlanSummary,
  fetchTodayPlan,
  rejectPlan,
  submitCheckin
} from './plans.js'

export {
  fetchReminderInbox,
  fetchReminderTasks,
  fetchSchedulerStatus,
  markReminderRead,
  tickScheduler
} from './reminders.js'

export {
  fetchPushStatus,
  registerPushClient,
  unregisterPushClient
} from './push.js'

export {
  fetchMe,
  fetchAccountOptions,
  loginAccount,
  lookupAccount,
  registerAccount,
  updateAvatar
} from './accounts.js'

export {
  bindFamily,
  fetchAllBindings,
  fetchBindings,
  fetchConversations,
  fetchFamilyOverview,
  deleteMessage,
  fetchMessages,
  markConversationRead,
  recallMessage,
  requestAutoReply,
  respondBindFamily,
  sendMessage,
  unbindFamily
} from './conversations.js'

export {
  addHealthRecord,
  deleteHealthRecord,
  fetchHealthRecords,
  fetchHealthSummary,
  fetchHealthTypes
} from './health.js'

export {
  addCaseFile,
  caseRawUrl,
  createCase,
  deleteCase,
  deleteCaseFile,
  fetchCase,
  fetchCases,
  fetchCaseTypes,
  fetchVisionStatus,
  updateCase
} from './cases.js'

// ⚠️ 记忆的写接口（createMemory / reviewMemory / updateMemorySettings）
// 只导出给**家人端**用：老人端页面不许调用，否则就绕过了"家属确认"这道闸门。
export {
  clearMemories,
  createMemory,
  deleteMemory,
  fetchMemories,
  fetchMemorySettings,
  fetchMemoryTopics,
  reviewMemory,
  updateMemorySettings
} from './memory.js'

/** 当前运行端与是否具备真流式能力（设置页/自检页展示用） */
export { PLATFORM, CAN_STREAM } from './transport.js'
