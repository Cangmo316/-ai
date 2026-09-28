/**
 * 比邻AI · 表情包（受控 token 映射）
 *
 * 产品约定（设计方案 §3.1）：**LLM 不能直接输出 URL**，只能输出受控 token
 * （如 `<sticker:love>` → 事件 `sticker` + `{"token":"love"}`），端上再映射成素材。
 * 这样内容安全审核只需要审这一张有限的白名单。
 *
 * 现状：`static/` 还没有素材，先用 emoji 占位。素材库就位后给每条补 `src`
 * （形如 `/static/stickers/love.png`），组件会自动优先用图片——不需要改组件。
 */

export const STICKERS = {
  love: { emoji: '❤️', label: '爱心', src: '', audited: true },
  sun: { emoji: '☀️', label: '太阳', src: '', audited: true },
  hug: { emoji: '🤗', label: '拥抱', src: '', audited: true },
  smile: { emoji: '😊', label: '笑脸', src: '', audited: true },
  meal: { emoji: '🍚', label: '饭菜', src: '', audited: true },
  pill: { emoji: '💊', label: '药丸', src: '', audited: true },
  night: { emoji: '🌙', label: '晚安', src: '', audited: true },
  cheer: { emoji: '💪', label: '加油', src: '', audited: true },
  water: { emoji: '🥛', label: '喝水', src: '', audited: true },
  walk: { emoji: '🚶', label: '散步', src: '', audited: true }
}

/** 兜底表情：服务端发了不在白名单里的 token 时用，绝不渲染未知素材 */
const FALLBACK = { emoji: '🙂', label: '表情', src: '', audited: false }

/**
 * token → 可渲染的素材对象
 * @param {string} token
 * @returns {{token:string, emoji:string, label:string, src:string, audited:boolean}}
 */
export function stickerOf(token) {
  const key = String(token || '').trim()
  const hit = STICKERS[key]
  return Object.assign({ token: key }, hit || FALLBACK)
}

export default STICKERS
