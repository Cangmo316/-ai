/**
 * 比邻AI · 智能体设置（模型选择）
 *
 * 需求：`我的 → 智能体设置` 里第一栏选模型，默认「比邻AI」（= 服务端配置的那个），
 * 也可以选"使用其他模型"，填入 **API URL / API KEY / 模型名称**。
 *
 * ## 为什么服务端要存一份
 *
 * 这三项决定"用哪个大模型回话"，属于**能真的改变行为**的配置，
 * 只有服务端知道怎么用它（见 server/app/llm/resolver.py）。
 * 所以这里不是本地存一份就完事，而是读写服务端；本地只做缓存让界面秒开。
 *
 * ## 密钥怎么处理
 *
 * 端侧**永远拿不到完整 key**：服务端只回 `hasApiKey` 与脱敏值。
 * 所以编辑界面里 key 输入框是空的，占位符显示"已配置（sk-xxx****）"；
 * 用户不重填就提交时，服务端保留原来的 key（见下面的 `apiKey` 处理）。
 */

import { reactive } from 'vue'
import { getModelSetting, saveModelSetting, testModelSetting } from '@/api/index.js'
import { readToken } from '@/stores/account.js'

export const MODEL_MODE_BUILTIN = 'builtin'
export const MODEL_MODE_CUSTOM = 'custom'

/** 内置那一项在界面上的名字（需求：默认为「比邻AI」，也就是自己的模型） */
export const BUILTIN_LABEL = '比邻AI'

/** 本地缓存 key（按账号隔离，避免换账号看到别人的配置） */
function cacheKey() {
  let number = ''
  try {
    const raw = uni.getStorageSync('bl_account_profile')
    const account = raw ? (typeof raw === 'string' ? JSON.parse(raw) : raw) : null
    number = (account && account.number) || ''
  } catch (e) {
    number = ''
  }
  return 'bl_model_setting_' + (number || 'guest')
}

/** 界面上要展示的状态。**模板用它，不要直接引用模块导出**（打包器会把 store 内联进多个 chunk）。 */
export const modelSetting = reactive({
  mode: MODEL_MODE_BUILTIN,
  baseUrl: '',
  model: '',
  hasApiKey: false,
  apiKeyMasked: '',
  /** 服务端当前**实际**在用的模型（可能与设置不一致，比如自定义配置坏了退回内置） */
  activeProvider: '',
  activeModel: '',
  activeCustom: false,
  fallbackReason: '',
  loaded: false,
  lastError: ''
})

/** 读本地缓存（进页面先显示，随后被服务端覆盖） */
export function readCached() {
  try {
    const raw = uni.getStorageSync(cacheKey())
    return raw ? (typeof raw === 'string' ? JSON.parse(raw) : raw) : null
  } catch (e) {
    return null
  }
}

function writeCache(data) {
  try {
    uni.setStorageSync(cacheKey(), JSON.stringify(data))
  } catch (e) {
    // 存不上不影响本次使用
  }
}

/** 把服务端返回写进 store */
function apply(setting, active) {
  const s = setting || {}
  modelSetting.mode = s.mode === MODEL_MODE_CUSTOM ? MODEL_MODE_CUSTOM : MODEL_MODE_BUILTIN
  modelSetting.baseUrl = s.baseUrl || ''
  modelSetting.model = s.model || ''
  modelSetting.hasApiKey = !!s.hasApiKey
  modelSetting.apiKeyMasked = s.apiKeyMasked || ''
  const a = active || {}
  modelSetting.activeProvider = a.provider || ''
  modelSetting.activeModel = a.model || ''
  modelSetting.activeCustom = !!a.custom
  modelSetting.fallbackReason = a.fallbackReason || ''
  modelSetting.loaded = true
  writeCache({
    mode: modelSetting.mode,
    baseUrl: modelSetting.baseUrl,
    model: modelSetting.model,
    hasApiKey: modelSetting.hasApiKey,
    apiKeyMasked: modelSetting.apiKeyMasked
  })
}

/** 从服务端拉设置。失败时保留缓存值，不让界面变空。 */
export function loadModelSetting() {
  const cached = readCached()
  if (cached) apply(cached, null)
  const token = readToken()
  if (!token) return Promise.resolve({ ok: false, reason: '请先登录' })
  return getModelSetting(token)
    .then((data) => {
      apply(data && data.setting, data && data.active)
      return { ok: true }
    })
    .catch((error) => {
      modelSetting.lastError = (error && error.message) || '读不到设置'
      return { ok: false, reason: modelSetting.lastError }
    })
}

/**
 * 保存设置。
 *
 * @param {{mode:string, baseUrl?:string, apiKey?:string, model?:string}} input
 *   `apiKey` 留空 = **保留服务端原来的 key**（因为端侧根本拿不到完整 key）
 */
export function saveModel(input) {
  const token = readToken()
  if (!token) return Promise.resolve({ ok: false, reason: '请先登录' })
  return saveModelSetting(token, input)
    .then((data) => {
      apply(data && data.setting, null)
      return { ok: true }
    })
    .catch((error) => ({ ok: false, reason: (error && error.message) || '存不上' }))
}

/** 连通性测试：用填的三项真发一次请求 */
export function testModel(input) {
  const token = readToken()
  if (!token) return Promise.resolve({ ok: false, reason: '请先登录' })
  return testModelSetting(token, input)
    .then((data) => ({ ok: !!(data && data.ok), reason: (data && data.reason) || '', sample: (data && data.sample) || '' }))
    .catch((error) => ({ ok: false, reason: (error && error.message) || '测试失败' }))
}

/** 侧栏/列表上显示的一行小字：当前用的是哪个模型 */
export function modelLabel() {
  if (modelSetting.mode === MODEL_MODE_CUSTOM) {
    return modelSetting.model || '自定义模型'
  }
  return BUILTIN_LABEL
}
