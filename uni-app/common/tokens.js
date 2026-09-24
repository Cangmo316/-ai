/**
 * 设计 Token —— 与 prototype/tokens.json 一一对应。
 * 颜色另有 CSS 变量形态（见 App.vue），这里供 JS 逻辑读取（如 nvue / 原生能力）。
 * 375px 设计稿，1px = 2rpx。
 */
export const tokens = {
  color: {
    primary: '#07C160',
    primaryPressed: '#06AD56',
    bg: '#EDEDED',
    surface: '#FFFFFF',
    text: '#1A1A1A',
    textSecondary: '#8C8C8C',
    warm: '#F5A623',
    danger: '#E64340',
    divider: '#E5E5E5',
    bubbleMe: '#95EC69',
    iconMuted: '#C4C4C4'
  },
  fontSize: {
    caption: 28, body: 32, title: 40, display: 48, huge: 56,
    captionLarge: 36, bodyLarge: 40, titleLarge: 48
  },
  spacing: { xs: 8, sm: 16, md: 24, lg: 32, xl: 48, xxl: 64 },
  radius: { bubble: 24, card: 32, pill: 999 },
  size: { touch: 96, row: 112, tabbar: 112, avatar: 104 },
  a11y: { bodyMinPx: 16, bodyMinPxLargeMode: 20, touchMinPx: 48, contrastMin: 4.5 }
}

/** 适老化字号（rpx），供 <bl-large> 之外的场景手写样式时取用 */
export const fontRpx = (px, large) => (large ? px * 2.2 : px * 2)

export default tokens