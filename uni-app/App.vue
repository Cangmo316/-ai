<script>
import { initSettings } from './common/store.js'
import { startPolling, stopPolling } from './stores/reminder.js'

export default {
  onLaunch() {
    // 把「大字体模式」的本地缓存读回内存
    initSettings()
    // 提醒只在 App 前台轮询：到点后顶部提醒条 + 震动（系统通知要等厂商推送通道，见 stores/reminder.js）
    startPolling()
  },
  onShow() {
    startPolling()
  },
  onHide() {
    // 退到后台就停掉，别白耗电
    stopPolling()
  }
}
</script>

<style>
/* ==========================================================================
   比邻AI · 设计 Token（唯一数据源）
   与 prototype/tokens.json 保持一一对应
   375px 设计稿 → 750rpx，换算系数 2
   ========================================================================== */
page {
  /* 色彩 */
  --bl-primary: #07C160;
  --bl-primary-pressed: #06AD56;
  --bl-bg: #EDEDED;
  --bl-surface: #FFFFFF;
  --bl-text: #1A1A1A;
  --bl-text-2: #8C8C8C;
  --bl-warm: #F5A623;
  --bl-danger: #E64340;
  --bl-divider: #E5E5E5;
  --bl-bubble-me: #95EC69;
  --bl-icon-muted: #C4C4C4;

  /* 字号（标准模式） */
  --bl-font-caption: 28rpx;
  --bl-font-body: 32rpx;
  --bl-font-title: 40rpx;
  --bl-font-display: 48rpx;
  --bl-font-huge: 56rpx;

  /* 间距 8pt 栅格 */
  --bl-space-xs: 8rpx;
  --bl-space-sm: 16rpx;
  --bl-space-md: 24rpx;
  --bl-space-lg: 32rpx;
  --bl-space-xl: 48rpx;

  /* 圆角 */
  --bl-radius-bubble: 24rpx;
  --bl-radius-card: 32rpx;
  --bl-radius-pill: 999rpx;

  /* 触控尺寸 */
  --bl-touch: 96rpx;
  --bl-row: 112rpx;
  --bl-tabbar: 112rpx;
  --bl-avatar: 104rpx;

  --bl-shadow-card: 0 2rpx 4rpx rgba(0, 0, 0, .05);

  background-color: var(--bl-bg);
  font-family: "Noto Sans SC", "PingFang SC", "Microsoft YaHei", -apple-system, sans-serif;
  color: var(--bl-text);
}

/* 大字体模式 —— 对应规范里的「+ 大字体变体」 */
page,
.bl-large {
  /* 占位：真正的覆盖在下面 .bl-large 里 */
}
.bl-large {
  --bl-font-caption: 36rpx;
  --bl-font-body: 40rpx;
  --bl-font-title: 48rpx;
  --bl-font-display: 60rpx;
  --bl-font-huge: 68rpx;
  --bl-touch: 112rpx;
  --bl-row: 128rpx;
  --bl-tabbar: 128rpx;
  --bl-avatar: 120rpx;
}

/* ==========================================================================
   布局
   ========================================================================== */
.bl-page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background-color: var(--bl-bg);
  box-sizing: border-box;
}

.bl-body {
  flex: 1;
  min-height: 0;
}

/* 安全区：非全面屏手动兜底，全面屏交给 env() */
.bl-safe-top { height: calc(env(safe-area-inset-top) + 20rpx); }
.bl-safe-bottom { height: env(safe-area-inset-bottom); }

/* ==========================================================================
   基础组件样式
   ========================================================================== */
.bl-card {
  background-color: var(--bl-surface);
  border-radius: var(--bl-radius-card);
  box-shadow: var(--bl-shadow-card);
}

.bl-group {
  background-color: var(--bl-surface);
  border-radius: var(--bl-radius-card);
  overflow: hidden;
  margin: 0 var(--bl-space-lg) var(--bl-space-lg);
}

.bl-section-title {
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  padding: var(--bl-space-lg) var(--bl-space-lg) var(--bl-space-sm);
}

/* 按钮 */
.bl-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: var(--bl-touch);
  padding: 0 var(--bl-space-xl);
  border-radius: var(--bl-radius-pill);
  font-size: var(--bl-font-body);
  font-weight: 600;
  border: none;
  line-height: 1.2;
}
.bl-btn--primary { background-color: var(--bl-primary); color: #FFFFFF; }
.bl-btn--primary:active { background-color: var(--bl-primary-pressed); }
.bl-btn--ghost {
  background-color: var(--bl-surface);
  color: var(--bl-primary);
  border: 3rpx solid var(--bl-primary);
}
.bl-btn--block { width: 100%; }
.bl-btn__text { font-size: var(--bl-font-body); font-weight: 600; line-height: 1.2; }

/* 页面底部按钮区 */
.bl-page-footer { padding: 0 var(--bl-space-lg) var(--bl-space-xl); }
.bl-page-footer__text {
  font-size: var(--bl-font-body);
  font-weight: 600;
  color: var(--bl-primary);
  line-height: 1.2;
}
.bl-page-footer__text--on { color: #FFFFFF; }

/* 列表行 */
.bl-row {
  display: flex;
  align-items: center;
  min-height: var(--bl-row);
  padding: var(--bl-space-md) var(--bl-space-lg);
  background-color: var(--bl-surface);
  position: relative;
  box-sizing: border-box;
}
.bl-row + .bl-row::before {
  content: '';
  position: absolute;
  left: 120rpx;
  right: 0;
  top: 0;
  height: 1rpx;
  background-color: var(--bl-divider);
}
.bl-row:active { background-color: #F7F7F7; }
.bl-row__icon {
  width: 80rpx;
  height: 80rpx;
  border-radius: 22rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: #EAF9F1;
  margin-right: var(--bl-space-md);
  flex: none;
}
.bl-row__label { flex: 1; font-size: var(--bl-font-body); color: var(--bl-text); }
.bl-row__value { font-size: var(--bl-font-caption); color: var(--bl-text-2); margin-right: var(--bl-space-xs); }

/* 头像 */
.bl-avatar {
  width: var(--bl-avatar);
  height: var(--bl-avatar);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
}

/* 未读角标 */
.bl-badge {
  min-width: 40rpx;
  height: 40rpx;
  padding: 0 12rpx;
  border-radius: 20rpx;
  background-color: var(--bl-danger);
  color: #FFFFFF;
  font-size: 24rpx;
  font-weight: 700;
  line-height: 40rpx;
  text-align: center;
  box-sizing: border-box;
}

/* 空态 */
.bl-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 160rpx var(--bl-space-xl);
  text-align: center;
}
.bl-empty__title { font-size: var(--bl-font-body); color: var(--bl-text); margin-top: var(--bl-space-md); }
.bl-empty__desc { font-size: var(--bl-font-caption); color: var(--bl-text-2); margin-top: var(--bl-space-sm); }
</style>