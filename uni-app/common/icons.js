import { base64Encode } from './base64.js'

/**
 * 图标集：24×24 线性图标，`{c}` 为颜色占位符。
 * 运行时按需把 {c} 替换成实际颜色，再编码成 SVG data URI，
 * 这样同一个图标可以随主题/状态变色，不需要准备多套切图。
 */
export const ICONS = {
  chat: '<path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  cal: '<rect x="3" y="5" width="18" height="16" rx="3" fill="none" stroke="{c}" stroke-width="2"/><path d="M3 10h18M8 3v4M16 3v4" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round"/>',
  me: '<circle cx="12" cy="8" r="4" fill="none" stroke="{c}" stroke-width="2"/><path d="M4.5 20.5c0-3.8 3.4-6 7.5-6s7.5 2.2 7.5 6" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round"/>',
  person: '<circle cx="12" cy="8.5" r="4.2" fill="{c}"/><path d="M3.6 21c0-4.2 3.8-6.8 8.4-6.8s8.4 2.6 8.4 6.8z" fill="{c}"/>',
  back: '<path d="M15 5l-7 7 7 7" fill="none" stroke="{c}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>',
  chev: '<path d="M9 5l7 7-7 7" fill="none" stroke="{c}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>',
  video: '<rect x="2" y="6" width="13" height="12" rx="3.5" fill="none" stroke="{c}" stroke-width="2"/><path d="M15 11l6.2-3.6v9.2L15 13z" fill="{c}"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3" fill="none" stroke="{c}" stroke-width="2"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round"/>',
  emoji: '<circle cx="12" cy="12" r="9" fill="none" stroke="{c}" stroke-width="2"/><path d="M8.5 14.5a4.5 4.5 0 0 0 7 0" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round"/><circle cx="9" cy="10" r="1.2" fill="{c}"/><circle cx="15" cy="10" r="1.2" fill="{c}"/>',
  plus: '<path d="M12 5v14M5 12h14" fill="none" stroke="{c}" stroke-width="2.2" stroke-linecap="round"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5" fill="none" stroke="{c}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>',
  clock: '<circle cx="12" cy="12" r="9" fill="none" stroke="{c}" stroke-width="2"/><path d="M12 7v5.2l3.4 2" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  heart: '<path d="M12 20.5S4.5 15.7 4.5 10.6A4.7 4.7 0 0 1 12 7.3a4.7 4.7 0 0 1 7.5 3.3c0 5.1-7.5 9.9-7.5 9.9z" fill="{c}"/>',
  role: '<circle cx="9" cy="8" r="3.4" fill="none" stroke="{c}" stroke-width="2"/><path d="M2.5 20c0-3.4 3-5.4 6.5-5.4s6.5 2 6.5 5.4" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round"/><path d="M17 5.5l1.6 1.6L22 3.5" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  face: '<circle cx="12" cy="9" r="5" fill="none" stroke="{c}" stroke-width="2"/><circle cx="10" cy="8.5" r="1" fill="{c}"/><circle cx="14" cy="8.5" r="1" fill="{c}"/><path d="M4 21c0-4.2 3.6-6.6 8-6.6s8 2.4 8 6.6" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round"/>',
  family: '<circle cx="8" cy="8" r="3.4" fill="none" stroke="{c}" stroke-width="2"/><circle cx="16.5" cy="9.5" r="2.6" fill="none" stroke="{c}" stroke-width="2"/><path d="M2 19.5c0-3 2.8-4.7 6-4.7s6 1.7 6 4.7M15 19.5c0-2.4 1.8-3.7 4-3.7" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round"/>',
  health: '<path d="M3 12.5h4l2-5.5 3 11 2.5-6.5 1.5 3h5" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  settings: '<circle cx="12" cy="12" r="3.2" fill="none" stroke="{c}" stroke-width="2"/><path d="M12 3v2.2M12 18.8V21M3 12h2.2M18.8 12H21M5.6 5.6l1.6 1.6M16.8 16.8l1.6 1.6M18.4 5.6l-1.6 1.6M7.2 16.8l-1.6 1.6" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round"/>',
  privacy: '<path d="M12 3l7 3v6c0 4.4-3 7.6-7 9-4-1.4-7-4.6-7-9V6z" fill="none" stroke="{c}" stroke-width="2" stroke-linejoin="round"/><path d="M9.2 12.2l2 2 3.6-4" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  hangup: '<path d="M12 9.5c-3.6 0-6.9 1-9.2 2.8v3.2c0 .8.7 1.5 1.5 1.5h2.3c.8 0 1.5-.7 1.5-1.5v-1.6c1.2-.4 2.5-.6 3.9-.6s2.7.2 3.9.6v1.6c0 .8.7 1.5 1.5 1.5h2.3c.8 0 1.5-.7 1.5-1.5v-3.2c-2.3-1.8-5.6-2.8-9.2-2.8z" fill="{c}" transform="rotate(135 12 12)"/>',
  speaker: '<path d="M11 5L7 8.5H4v7h3l6 4.5V5z" fill="{c}"/><path d="M15.5 9a4.2 4.2 0 0 1 0 6M18.2 6.4a7.6 7.6 0 0 1 0 11.2" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round"/>',
  muted: '<path d="M11 5L7 8.5H4v7h3l6 4.5V5z" fill="{c}"/><path d="M15.5 9.5l5 5M20.5 9.5l-5 5" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round"/>',
  shuffle: '<path d="M4 7h3.6l9 10H20M4 17h3.6l2.6-2.9M17 4l3 3-3 3M17 14l3 3-3 3" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  save: '<path d="M5 4h11l3 3v13H5z" fill="none" stroke="{c}" stroke-width="2" stroke-linejoin="round"/><path d="M9 4v5h6V4M9 15h6" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round"/>',
  empty: '<circle cx="12" cy="12" r="9" fill="none" stroke="{c}" stroke-width="2"/><path d="M8.5 15a4.5 4.5 0 0 0 7 0" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round"/><circle cx="9" cy="10" r="1.2" fill="{c}"/><circle cx="15" cy="10" r="1.2" fill="{c}"/>',
  palette: '<path d="M12 3.5c-4.7 0-8.5 3.4-8.5 7.6 0 4.2 3.8 7.6 8.5 7.6h1.6c1.1 0 1.9-.8 1.9-1.8 0-.5-.2-.9-.5-1.2-.3-.3-.5-.7-.5-1.1 0-1 .8-1.8 1.9-1.8h1.9c2 0 3.7-1.5 3.7-3.4 0-3.3-3.9-5.9-10-5.9z" fill="none" stroke="{c}" stroke-width="2" stroke-linejoin="round"/><circle cx="7.6" cy="12.4" r="1.1" fill="{c}"/><circle cx="9.6" cy="8.4" r="1.1" fill="{c}"/><circle cx="14" cy="7.6" r="1.1" fill="{c}"/>'
}

/** 生成 SVG 的 data URI（base64，三端通用） */
export function iconSrc(name, color = '#1A1A1A') {
  const body = ICONS[name]
  if (!body) return ''
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">' +
    body.replace(/\{c\}/g, color) + '</svg>'
  return 'data:image/svg+xml;base64,' + base64Encode(svg)
}

export default iconSrc