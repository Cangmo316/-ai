<script>
import { initSettings } from './common/store.js'
import { initAccount } from './stores/account.js'
import { poll, rescheduleLocalReminders, startPolling, stopPolling } from './stores/reminder.js'
import { listenPushMessages, pushAction, registerPush } from './stores/push.js'

export default {
  onLaunch() {
    // 把「大字体模式」的本地缓存读回内存
    initSettings()
    // 账号会话：先用本地缓存立即可渲染，再向服务端确认一次
    // （服务端确认结果通过 EVENT_ACCOUNT_CHANGED 通知页面；重复调用是幂等的）
    initAccount()
    // 提醒有四条腿：站内消息（前台轮询）、系统推送（uni-push）、
    // 端侧本地通知，以及本地计划（日常/每周）的「开始/结束」两次提醒
    startPolling()
    // 本地计划的时间点按当前时间重排：冷启动和每次回前台都要来一次，
    // 否则「结束提醒」会在后台期间错过
    rescheduleLocalReminders()
    // 登记推送标识：拿到 cid 才可能收到系统通知（H5/小程序/标准基座会静默跳过）
    registerPush()
    // 必须在收到消息之前注册监听：点通知栏消息进来时刷新提醒
    listenPushMessages({
      onMessage(info) {
        poll()
        if (pushAction(info) === 'open-plans') {
          // 冷启动时页面栈还没建好，立刻跳页会被首屏覆盖，等一拍再跳
          setTimeout(() => {
            uni.navigateTo({ url: '/pages/plans/plans' })
          }, 300)
        }
      }
    })
  },
  onShow() {
    startPolling()
    // 回到前台：按当前时间重排本地提醒点（后台期间错过的开始点会补提醒）
    rescheduleLocalReminders()
    // cid 可能变（重装/清数据），每次回前台补一次登记（服务端按 cid 幂等）
    registerPush()
  },
  onHide() {
    // 退到后台就停掉轮询，别白耗电
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
  /* 色彩 —— 水墨版（宣纸 + 墨 + 松烟墨绿 + 朱砂）
     对比度已实测，改动后请重跑水墨设计稿目录下的 contrast-check.mjs */
  --bl-primary: #2F5D4E;
  --bl-primary-pressed: #264A3E;
  --bl-primary-soft: rgba(47, 93, 78, .10);
  --bl-bg: #F6F3EA;
  --bl-surface: #FFFDF8;
  --bl-surface-2: #F4F2E9;
  --bl-text: #1F211D;
  --bl-text-2: #6E6A5E;
  --bl-text-3: #B9B3A4;
  --bl-warm: #955600;
  --bl-danger: #B23A2E;
  --bl-success: #48714F;
  --bl-divider: #E7E1D2;
  --bl-border: #E7E1D2;
  --bl-border-strong: #827C6D;
  --bl-bubble-me: #DDE9DF;
  --bl-bubble-ai: #FFFDF8;
  --bl-icon-muted: #B9B3A4;
  --bl-overlay: rgba(31, 33, 29, .42);

  /* 日历选日（观感按需求：绿底 + 白字 / 今日红字 / 点选后白底黑字）
     注：红字压在绿底上对比度天然不足（红绿亮度接近，实测最深绿也只有 3.17:1），
     所以「今天」用浅绿底 + 深红字，既保住红字又达到 4.5:1。 */
  --bl-cal-on: #16794B;          /* 可点日期绿底；白字 on 它 5.43:1 ✓ */
  --bl-cal-on-today: #E6F4EC;    /* 今日浅绿底 */
  --bl-cal-today: #C81E1E;       /* 今日红字；on 浅绿底 5.06:1 ✓ */
  --bl-cal-off: #C9C4B6;         /* 不可点日期（上/下月） */

  /* 水墨修饰层：宣纸晕染（三层径向渐变，比 SVG 噪点更省性能，小程序端同样可用） */
  --bl-wash:
    radial-gradient(circle at 18% 8%, rgba(47, 93, 78, .055), transparent 42%),
    radial-gradient(circle at 86% 78%, rgba(47, 93, 78, .045), transparent 46%),
    radial-gradient(circle at 60% 34%, rgba(178, 58, 46, .022), transparent 34%);
  /* 笔触下划线遮罩（不支持 mask 时自然退化为直条） */
  --bl-brush-mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='44' height='3'><path d='M0 2C8 .6 16 2.6 24 1.4S38 2.4 44 1.6' stroke='black' stroke-width='2.4' fill='none' stroke-linecap='round'/></svg>");

  /* 字号（标准模式） */
  --bl-font-caption: 28rpx;
  --bl-font-body: 32rpx;
  --bl-font-title: 40rpx;
  --bl-font-display: 48rpx;
  --bl-font-huge: 56rpx;
  --bl-font-tab: 26rpx;

  /* 间距 8pt 栅格 */
  --bl-space-xs: 8rpx;
  --bl-space-sm: 16rpx;
  --bl-space-md: 24rpx;
  --bl-space-lg: 32rpx;
  --bl-space-xl: 48rpx;
  --bl-space-xxl: 64rpx;

  /* 圆角 */
  --bl-radius-bubble: 24rpx;
  --bl-radius-card: 32rpx;
  --bl-radius-pill: 999rpx;

  /* 触控尺寸 */
  --bl-touch: 96rpx;
  --bl-row: 112rpx;
  --bl-tabbar: 112rpx;
  --bl-avatar: 104rpx;

  --bl-shadow-card: 0 2rpx 4rpx rgba(31, 33, 29, .05), 0 8rpx 24rpx rgba(31, 33, 29, .07);
  --bl-shadow-lift: 0 4rpx 12rpx rgba(31, 33, 29, .08), 0 16rpx 40rpx rgba(31, 33, 29, .10);

  background-color: var(--bl-bg);
  /* 宣纸晕染：作为页面最底层铺一次，内容层在它之上 */
  background-image: var(--bl-wash);
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
  --bl-font-tab: 34rpx;
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
  /* uni-app 的 uni-view 默认 content-box；不写这句时 .bl-btn--block 的 width:100%
     会把左右内边距额外加上去，导致通栏按钮溢出屏幕、圆角跑到视口外 */
  box-sizing: border-box;
  min-height: var(--bl-touch);
  padding: 0 var(--bl-space-xl);
  border-radius: var(--bl-radius-pill);
  font-size: var(--bl-font-body);
  font-weight: 600;
  border: none;
  line-height: 1.2;
}
.bl-btn--primary { background-color: var(--bl-primary); color: var(--bl-surface); }
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
.bl-page-footer__text--on { color: var(--bl-surface); }

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
.bl-row:active { background-color: var(--bl-surface-2); }
.bl-row__icon {
  width: 80rpx;
  height: 80rpx;
  border-radius: 22rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: var(--bl-primary-soft);
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
  color: var(--bl-surface);
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

/* ==========================================================================
   水墨公用元素
   ========================================================================== */

/* 笔触下划线：区块标题前的短横，取「落笔」之意。
   不支持 mask-image 的端会自然退化为一条直色条，不影响可读性。 */
.bl-brush-rule {
  width: 88rpx;
  height: 6rpx;
  flex: none;
  background-color: var(--bl-primary);
  border-radius: 3rpx;
  opacity: .85;
  -webkit-mask-image: var(--bl-brush-mask);
  mask-image: var(--bl-brush-mask);
  -webkit-mask-size: 100% 100%;
  mask-size: 100% 100%;
  -webkit-mask-repeat: no-repeat;
  mask-repeat: no-repeat;
}

/* 带笔触的区块标题：替代原 .bl-section-title 的水墨版 */
.bl-section-title--ink {
  display: flex;
  align-items: center;
  gap: var(--bl-space-sm);
  padding: var(--bl-space-lg) var(--bl-space-lg) var(--bl-space-sm);
}
.bl-section-title--ink .bl-section-title__text {
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  letter-spacing: .06em;
}

/* 墨印胶囊：用于「当前陪伴：儿子·小明」这类身份标签 */
.bl-ink-pill {
  display: inline-flex;
  align-items: center;
  gap: 8rpx;
  padding: 10rpx 22rpx;
  border-radius: var(--bl-radius-pill);
  background-color: var(--bl-primary-soft);
  color: var(--bl-primary);
  font-size: var(--bl-font-caption);
  font-weight: 500;
}

/* 纸面卡：水墨版的通用卡片，带淡墨描边与双层柔影 */
.bl-paper {
  background-color: var(--bl-surface);
  border-radius: var(--bl-radius-card);
  border: 1rpx solid var(--bl-border);
  box-shadow: var(--bl-shadow-card);
  box-sizing: border-box;
}

/* 输入框占位符色。
   注意：uni-app H5 把占位符渲染成独立的 .uni-input-placeholder 元素，它不在引用方
   组件的 scoped 作用域内，所以这个类必须写在全局样式里（写在页面 scoped 里会失效）。 */
.bl-input-ph {
  color: #B9B3A4;
  font-size: var(--bl-font-body);
}
</style>