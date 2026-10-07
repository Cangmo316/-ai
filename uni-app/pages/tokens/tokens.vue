<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar title="设计规范" solid back @back="back" />

    <scroll-view class="bl-body" scroll-y>
      <view class="bl-tokens">
        <text class="bl-tokens__h">色彩</text>
        <view class="bl-swatches">
          <view v-for="s in SWATCHES" :key="s.hex" class="bl-swatch">
            <view class="bl-swatch__chip" :style="{ backgroundColor: s.hex }" />
            <view class="bl-swatch__text">
              <text class="bl-swatch__name">{{ s.name }}</text>
              <text class="bl-swatch__hex">{{ s.hex }}</text>
            </view>
          </view>
        </view>

        <text class="bl-tokens__h">适老化基准</text>
        <view class="bl-spec">
          <view v-for="r in A11Y" :key="r.k" class="bl-spec__row">
            <text class="bl-spec__k">{{ r.k }}</text>
            <text class="bl-spec__v">{{ r.v }}</text>
          </view>
        </view>

        <text class="bl-tokens__h">评审自查</text>
        <view class="bl-spec">
          <view
            v-for="r in REVIEW"
            :key="r.k"
            class="bl-spec__row"
            :class="{ 'is-link': !!r.to }"
            @click="go(r.to)"
          >
            <text class="bl-spec__k">{{ r.k }}</text>
            <text class="bl-spec__v">{{ r.v }}</text>
          </view>
        </view>

        <text class="bl-tokens__foot">
          Token 唯一数据源在 App.vue 的 page 选择器；改一处需同步 common/tokens.js 与 uni.scss，核对基准是 prototype/tokens.json。
        </text>
      </view>
    </scroll-view>
  </view>
</template>

<script setup>
import { settings } from '@/common/store.js'

const SWATCHES = [
  { name: '主色 · 松烟墨绿', hex: '#2F5D4E' },
  { name: '主色按下', hex: '#264A3E' },
  { name: '页面底 · 宣纸', hex: '#F6F3EA' },
  { name: '卡片 / 气泡 · 暖白', hex: '#FFFDF8' },
  { name: '文字主色 · 墨', hex: '#1F211D' },
  { name: '文字辅助 · 淡墨', hex: '#6E6A5E' },
  { name: '提醒 · 暖墨黄', hex: '#955600' },
  { name: '警示 / 未读 · 朱砂', hex: '#B23A2E' },
  { name: '已完成 · 竹青', hex: '#48714F' },
  { name: '未激活图标 · 墨影', hex: '#B9B3A4' }
]

const A11Y = [
  { k: '正文字号', v: '≥16px（大字模式 ≥20px）' },
  { k: '标题字号', v: '20 – 24px' },
  { k: 'TabBar 标签', v: '13px（原 11px 不合规）' },
  { k: '触控目标', v: '≥44×44pt，适老 48 – 56px' },
  { k: '对比度', v: '≥4.5 : 1（正文实测 14.63:1）' },
  { k: '圆角', v: '气泡 12px / 卡片 16px / 主按钮全圆' },
  { k: '间距栅格', v: '8pt 基准' },
  { k: '画板', v: 'iOS 375×812 · Android 360×800 · 小程序 375×667' }
]

const REVIEW = [
  { k: '正文 ≥16px / 点击 ≥48px / 对比度 ≥4.5:1', v: '✓' },
  { k: '三个 Tab 图标 + 文字', v: '✓' },
  { k: 'AI 消息句末不加句号、口语化', v: '✓' },
  { k: '视觉模式控件 ≥56px', v: '✓' },
  { k: '大字体模式变体', v: '✓ 我的 → 大字体模式' },
  { k: '空态 / 首次使用', v: '见「空态」›', to: 'empty' }
]

function go(to) {
  if (!to) return
  if (to === 'empty') uni.navigateTo({ url: '/pages/empty/empty' })
}
function back() {
  const pages = getCurrentPages()
  if (pages.length > 1) uni.navigateBack()
  else uni.reLaunch({ url: '/pages/me/me' })
}
</script>

<style scoped>
.bl-tokens { padding: var(--bl-space-lg); }
.bl-tokens__h {
  display: block;
  font-size: var(--bl-font-body);
  font-weight: 700;
  color: var(--bl-text);
  margin: var(--bl-space-lg) 0 var(--bl-space-md);
}
.bl-tokens__h:first-child { margin-top: 0; }

/* 色板：两列自动换行（flex 比 grid 在三端更稳） */
.bl-swatches {
  display: flex;
  flex-wrap: wrap;
  gap: var(--bl-space-sm);
}
.bl-swatch {
  width: calc(50% - var(--bl-space-sm) / 2);
  display: flex;
  align-items: center;
  gap: var(--bl-space-sm);
  background-color: var(--bl-surface);
  border-radius: var(--bl-radius-bubble);
  padding: var(--bl-space-sm);
  box-sizing: border-box;
}
.bl-swatch__chip {
  width: 56rpx;
  height: 56rpx;
  border-radius: 16rpx;
  flex: none;
  border: 1rpx solid rgba(0, 0, 0, .06);
}
.bl-swatch__text { flex: 1; min-width: 0; }
.bl-swatch__name {
  display: block;
  font-size: 24rpx;
  color: var(--bl-text);
}
.bl-swatch__hex {
  display: block;
  font-size: 22rpx;
  color: var(--bl-text-2);
}

/* 规范表：用 view 而非 table —— 小程序不支持 table 标签 */
.bl-spec {
  background-color: var(--bl-surface);
  border-radius: var(--bl-radius-card);
  overflow: hidden;
}
.bl-spec__row {
  display: flex;
  align-items: center;
  gap: var(--bl-space-md);
  padding: 18rpx var(--bl-space-md);
  border-bottom: 1rpx solid var(--bl-divider);
}
.bl-spec__row:last-child { border-bottom: none; }
.bl-spec__row.is-link:active { background-color: var(--bl-surface-2); }
.bl-spec__k {
  flex: 1;
  font-size: 24rpx;
  line-height: 1.5;
  color: var(--bl-text);
}
.bl-spec__v {
  font-size: 24rpx;
  line-height: 1.5;
  color: var(--bl-text-2);
  text-align: right;
  flex: none;
  max-width: 52%;
}
.bl-spec__row.is-link .bl-spec__v { color: var(--bl-primary); }

.bl-tokens__foot {
  display: block;
  margin-top: var(--bl-space-lg);
  font-size: 22rpx;
  line-height: 1.6;
  color: var(--bl-text-2);
}
</style>