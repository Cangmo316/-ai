import { base64Encode } from './base64.js'

/**
 * 图标集：24×24 线性图标，`{c}` 为颜色占位符。
 * 运行时按需把 {c} 替换成实际颜色，再编码成 SVG data URI，
 * 这样同一个图标可以随主题/状态变色，不需要准备多套切图。
 */
export const ICONS = {
  // 对话 / 日程 / 我的 三个图标已改为水墨版，定义在文件末尾的「水墨图标」区（见下方）
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
  /* 密码显隐：眼睛睁开 = 显示明文，加斜杠 = 隐藏（与其它图标同为 24×24 纯描边） */
  eye: '<path d="M2 12c2.4-4 5.8-6 10-6s7.6 2 10 6c-2.4 4-5.8 6-10 6s-7.6-2-10-6z" fill="none" stroke="{c}" stroke-width="2" stroke-linejoin="round"/><circle cx="12" cy="12" r="2.8" fill="none" stroke="{c}" stroke-width="2"/>',
  eyeoff: '<path d="M2 12c2.4-4 5.8-6 10-6s7.6 2 10 6c-2.4 4-5.8 6-10 6s-7.6-2-10-6z" fill="none" stroke="{c}" stroke-width="2" stroke-linejoin="round"/><circle cx="12" cy="12" r="2.8" fill="none" stroke="{c}" stroke-width="2"/><path d="M4 20L20 4" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round"/>',
  empty: '<circle cx="12" cy="12" r="9" fill="none" stroke="{c}" stroke-width="2"/><path d="M8.5 15a4.5 4.5 0 0 0 7 0" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round"/><circle cx="9" cy="10" r="1.2" fill="{c}"/><circle cx="15" cy="10" r="1.2" fill="{c}"/>',
  palette: '<path d="M12 3.5c-4.7 0-8.5 3.4-8.5 7.6 0 4.2 3.8 7.6 8.5 7.6h1.6c1.1 0 1.9-.8 1.9-1.8 0-.5-.2-.9-.5-1.2-.3-.3-.5-.7-.5-1.1 0-1 .8-1.8 1.9-1.8h1.9c2 0 3.7-1.5 3.7-3.4 0-3.3-3.9-5.9-10-5.9z" fill="none" stroke="{c}" stroke-width="2" stroke-linejoin="round"/><circle cx="7.6" cy="12.4" r="1.1" fill="{c}"/><circle cx="9.6" cy="8.4" r="1.1" fill="{c}"/><circle cx="14" cy="7.6" r="1.1" fill="{c}"/>',

  /* ===== 水墨图标（TabBar 三个入口 + 品牌印记） =====
     设计约束（勿随意改笔画比例，否则 26px 实际尺寸下会糊）：
     1. 描边宽度 1.5–1.9（24 单位制）；「重」的部分用填充色块（笔锋 / 卷轴轴头 / 印框）
     2. 关键元素间距 ≥1.2 单位
     3. 三者形状必须互斥：毛笔 / 卷轴 / 墨印 */

  // 对话 · 毛笔（笔杆 + 笔箍 + 笔锋 + 滴墨）
  chat: '<rect x="10" y="3" width="4" height="8" rx="1.7" fill="none" stroke="{c}" stroke-width="1.5"/><path d="M9.2 11.1h5.6" fill="none" stroke="{c}" stroke-width="1.9" stroke-linecap="round"/><path d="M9.5 12.7h5c-.7 3.7-1.7 6-2.5 7.1-.8-1.1-1.8-3.4-2.5-7.1z" fill="{c}"/><circle cx="17.9" cy="19.7" r="1.4" fill="{c}" opacity=".8"/>',

  // 日程 · 卷轴（双轴头 + 内页 + 时间折线）
  cal: '<rect x="4.4" y="7" width="15.2" height="13" rx="1.4" fill="none" stroke="{c}" stroke-width="1.5"/><rect x="3.4" y="4.4" width="17.2" height="2.6" rx="1.3" fill="{c}"/><rect x="3.4" y="19.8" width="17.2" height="2.6" rx="1.3" fill="{c}"/><path d="M7 16.6l2-3.4 1.7 2.1 2-2.7 2 1.7 1.7-2.4" fill="none" stroke="{c}" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round"/><circle cx="8" cy="10.8" r="1.05" fill="{c}"/>',

  // 我的 · 墨印（方印框 + 印中人字 + 朱砂点，朱砂为固定色不随主题变）
  me: '<path d="M3.2 3.2h17.6v17.6H3.2z" fill="none" stroke="{c}" stroke-width="2"/><path d="M13.5 7.4c-1.3 3.6-3.2 6.7-5.7 9.2" fill="none" stroke="{c}" stroke-width="1.9" stroke-linecap="round"/><path d="M13.7 7.5c.9 3.2 2.1 5.9 3.8 8.1" fill="none" stroke="{c}" stroke-width="1.7" stroke-linecap="round"/><circle cx="19.1" cy="5.3" r="1.5" fill="#B23A2E"/>',

  // 日历 · 卷轴（导航栏右侧用；与「日程」的卷轴同源，含水波纹与日期点）
  calmonth: '<rect x="4" y="8" width="16" height="11.6" rx="1.4" fill="none" stroke="{c}" stroke-width="1.5"/><rect x="3" y="4.4" width="18" height="3.6" rx="1.8" fill="{c}"/><rect x="3" y="19.4" width="18" height="3.6" rx="1.8" fill="{c}"/><path d="M7.4 16.6c2.4-1.6 4.6 1 6.8-.6" fill="none" stroke="{c}" stroke-width="1.3" stroke-linecap="round"/><circle cx="16.8" cy="11" r="1.35" fill="{c}"/>'
}

/**
 * 品牌印记：比邻印章（两笔交叉，取「比」字两笔相并之意 + 天涯若比邻）
 * 32×32 viewBox，与图标集尺寸不同，需用 iconSrcOf(INK_BRAND, color, 32)
 */
export const INK_BRAND =
  '<rect x="2.6" y="2.6" width="26.8" height="26.8" rx="6" fill="none" stroke="{c}" stroke-width="2.5"/>' +
  '<path d="M16.6 9.4c-4.6 3.4-8.4 8-10.6 13.6" fill="none" stroke="{c}" stroke-width="3.1" stroke-linecap="round"/>' +
  '<path d="M15.2 9.4c4.8 3.2 8.8 7.8 11 13.4" fill="none" stroke="{c}" stroke-width="3.1" stroke-linecap="round"/>'

/** 生成 SVG 的 data URI（base64，三端通用） */
export function iconSrc(name, color = '#1F211D') {
  const body = ICONS[name]
  if (!body) return ''
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">' +
    body.replace(/\{c\}/g, color) + '</svg>'
  return 'data:image/svg+xml;base64,' + base64Encode(svg)
}

/**
 * 任意 SVG body 转 data URI，支持自定义 viewBox 尺寸。
 * 用于品牌印记（32×32）以及后续更大的图标位（48×48 空态插图等）。
 *   iconSrcOf(INK_BRAND, tokens.color.primary, 32)
 */
export function iconSrcOf(body, color = '#1F211D', box = 24) {
  if (!body) return ''
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${box}" height="${box}" viewBox="0 0 ${box} ${box}">` +
    body.replace(/\{c\}/g, color) + '</svg>'
  return 'data:image/svg+xml;base64,' + base64Encode(svg)
}

export default iconSrc