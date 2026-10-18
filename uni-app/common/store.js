import { reactive, watch } from 'vue'

import { AVATAR_ASSET } from './face-gl/assets.js'

/**
 * 全局轻量状态。原型阶段不引入 Pinia，保持零依赖。
 */
export const settings = reactive({
  largeFont: false,
  role: '比邻AI',
  largeFontLabel: '大字体模式',
  /**
   * 当前数字人形象（female / male / qdoctor…）。
   *
   * 为什么放在全局 store：**形象页选完要能带到通话页**。
   * 之前只存在形象页的局部 ref 里，切了等于没换（换页面又回到默认值）。
   * 初始值 `''` 表示"还没选过"，由 `initSettings()` 从本地存储恢复，
   * 再兜底到 `DEFAULT_GENDER`（`face-gl/assets.js` 里定义）。
   */
  gender: '',
  /**
   * 说话方式：智能切换（默认）/ 只用陪伴助手 / 只用健康顾问。
   *
   * 为什么默认是「智能切换」：
   *   老人不一定清楚什么时候该换人设，有人甚至不太会用手机。
   *   默认自动 = 他什么都不用做也不会出错；开关是给会用的人（多为子女）留的接管手段。
   *
   * ⚠️ 无论选哪种，医疗话题的免责声明**都会照补**（合规底线，不能由用户关掉）。
   */
  personaMode: 'auto'
})

/** 三种说话方式（顺序即界面展示顺序，第一项是默认） */
export const PERSONA_MODES = [
  {
    value: 'auto',
    label: '智能切换',
    hint: '平时陪您唠嗑，说到身体和吃药就换个懂行的人答',
    badge: '推荐'
  },
  {
    value: 'chat',
    label: '只用陪伴助手',
    hint: '什么话题都是家常聊天，不会被当成病人',
    badge: ''
  },
  {
    value: 'medical',
    label: '只用健康顾问',
    hint: '什么话题都按健康的口径回答',
    badge: ''
  }
]

/** 只接受三个合法值，其余一律回到 auto（防脏数据把行为弄坏） */
function normalizePersonaMode(value) {
  const v = String(value || '').trim()
  return PERSONA_MODES.some((m) => m.value === v) ? v : 'auto'
}

/** 读当前说话方式 */
export function readPersonaMode() {
  return normalizePersonaMode(settings.personaMode)
}

/**
 * 设置说话方式（同时落本地存储，重启后仍生效）。
 * @returns {string} 实际生效的值
 */
export function setPersonaMode(value) {
  const next = normalizePersonaMode(value)
  settings.personaMode = next
  try {
    uni.setStorageSync('bl_persona_mode', next)
  } catch (e) {
    // 存储失败不影响本次会话
  }
  return next
}

/**
 * 合法形象列表。
 *
 * ⚠️ 以前这里硬编码 `'female'` / `'male'`：形象加到第三个（qdoctor）之后，
 * 白名单会把新形象**静默丢掉**——选了没反应，回到默认值。
 * 改成从资产表推导，以后加形象不用再改这里。
 */
function knownGenders() {
  return Object.keys(AVATAR_ASSET)
}

/** 设置数字人形象（同时落本地存储，重启后仍生效）。 */
export function setGender(value) {
  if (!knownGenders().includes(value)) return settings.gender
  settings.gender = value
  try {
    uni.setStorageSync('bl_gender', value)
  } catch (e) {
    // 存储失败不影响本次会话
  }
  return settings.gender
}

export function setLargeFont(on) {
  settings.largeFont = !!on
  try {
    uni.setStorageSync('bl_large_font', settings.largeFont ? 1 : 0)
  } catch (e) {
    // 存储失败不影响本次会话
  }
}

export function toggleLargeFont() {
  setLargeFont(!settings.largeFont)
  return settings.largeFont
}

export function setRole(name) {
  settings.role = name
}

export function initSettings() {
  try {
    const saved = uni.getStorageSync('bl_large_font')
    if (saved) settings.largeFont = true
  } catch (e) {
    settings.largeFont = false
  }
  // 恢复上次选择的形象（没选过则留空，由页面兜底到 DEFAULT_GENDER）
  try {
    const savedGender = uni.getStorageSync('bl_gender')
    if (knownGenders().includes(savedGender)) {
      settings.gender = savedGender
    } else if (savedGender) {
      // 本地存的是**已下架的形象**（比如旧版本存的 female/male）：
      // 清掉它，否则一直是个无效值，页面上永远显示不出当前形象。
      uni.removeStorageSync('bl_gender')
      settings.gender = ''
    }
  } catch (e) {
    // 忽略：保持空值
  }
  // 恢复说话方式（没存过就是 auto —— 老人开箱即用，不需要任何设置）
  try {
    settings.personaMode = normalizePersonaMode(uni.getStorageSync('bl_persona_mode'))
  } catch (e) {
    settings.personaMode = 'auto'
  }
}

export default settings