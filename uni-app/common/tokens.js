/**
 * 设计 Token —— 水墨版，与 App.vue 的 page{...}、uni.scss 一一对应。
 * 颜色另有 CSS 变量形态（见 App.vue），这里供 JS 逻辑读取（如 nvue / 原生能力）。
 * 375px 设计稿，1px = 2rpx。
 *
 * 注意：本文件必须与 App.vue 的 page{...} 保持一致，改一处要同步另一处。
 * 对比度已实测，改动色值后请重跑水墨设计稿目录下的 contrast-check.mjs。
 */
export const tokens = {
  color: {
    primary: '#2F5D4E',
    primaryPressed: '#264A3E',
    primarySoft: 'rgba(47, 93, 78, .10)',
    bg: '#F6F3EA',
    surface: '#FFFDF8',
    surface2: '#F4F2E9',
    text: '#1F211D',
    textSecondary: '#6E6A5E',
    textTertiary: '#B9B3A4',
    warm: '#955600',
    danger: '#B23A2E',
    success: '#48714F',
    divider: '#E7E1D2',
    border: '#E7E1D2',
    borderStrong: '#827C6D',
    bubbleMe: '#DDE9DF',
    bubbleAi: '#FFFDF8',
    iconMuted: '#B9B3A4',
    overlay: 'rgba(31, 33, 29, .42)'
  },
  fontSize: {
    caption: 28, body: 32, title: 40, display: 48, huge: 56,
    tab: 26,
    captionLarge: 36, bodyLarge: 40, titleLarge: 48, tabLarge: 34
  },
  spacing: { xs: 8, sm: 16, md: 24, lg: 32, xl: 48, xxl: 64 },
  radius: { bubble: 24, card: 32, pill: 999 },
  size: { touch: 96, row: 112, tabbar: 112, avatar: 104 },
  shadow: {
    card: '0 2rpx 4rpx rgba(31, 33, 29, .05), 0 8rpx 24rpx rgba(31, 33, 29, .07)',
    lift: '0 4rpx 12rpx rgba(31, 33, 29, .08), 0 16rpx 40rpx rgba(31, 33, 29, .10)'
  },
  a11y: { bodyMinPx: 16, bodyMinPxInLargeMode: 20, touchMinPx: 48, contrastMin: 4.5 }
}

/** 适老化字号（rpx），供 <bl-large> 之外的手写样式取值 */
export const fontRpx = (px, large) => (large ? px * 2.2 : px * 2)

export default tokens
