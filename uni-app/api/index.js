/**
 * 比邻AI · agent 接口层出口
 *
 * 页面只从这里 import，不直接摸 transport / sse-parse。
 * 用法示例见 api/README.md。
 */

export {
  DEFAULT_BASE_URL,
  ENDPOINTS,
  TIMEOUT,
  getBaseURL,
  setBaseURL,
  resolveURL
} from './config.js'

export { request } from './request.js'

export {
  CHAT_EVENT,
  chatStream,
  chatSendOnce,
  chatHistory
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

/** 当前运行端与是否具备真流式能力（设置页/自检页展示用） */
export { PLATFORM, CAN_STREAM } from './transport.js'
