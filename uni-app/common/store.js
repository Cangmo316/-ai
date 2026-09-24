import { reactive, watch } from 'vue'

/**
 * 全局轻量状态。原型阶段不引入 Pinia，保持零依赖。
 */
export const settings = reactive({
  largeFont: false,
  role: '儿子 · 小明',
  largeFontLabel: '大字体模式'
})

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
}

export default settings