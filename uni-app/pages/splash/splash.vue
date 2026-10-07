<template>
  <view class="bl-page bl-splash" :class="{ 'bl-large': settings.largeFont }">
    <view class="bl-splash__ring">
      <view class="bl-splash__wash" />
      <view class="bl-splash__avatar">
        <image class="bl-splash__seal" :src="brandSrc" mode="aspectFit" />
      </view>
    </view>

    <text class="bl-splash__title">比邻AI</text>
    <text class="bl-splash__sub">天涯若比邻</text>

    <view class="bl-btn bl-splash__cta" @click="start">
      <text class="bl-splash__cta-text">开始使用</text>
    </view>
  </view>
</template>

<script setup>
import { computed } from 'vue'
import { settings } from '@/common/store.js'
import { tokens } from '@/common/tokens.js'
import { INK_BRAND, iconSrcOf } from '@/common/icons.js'

const brandSrc = computed(() => iconSrcOf(INK_BRAND, tokens.color.primary, 32))

function start() {
  uni.reLaunch({ url: '/pages/chats/chats' })
}
</script>

<style scoped>
/* 水墨版启动页：宣纸底 + 墨印 + 松烟墨绿。
   替代原来的微信绿渐变——第一眼就要和主界面是同一套语言。 */
.bl-splash {
  align-items: center;
  justify-content: center;
  background-color: var(--bl-bg);
  background-image: var(--bl-wash);
  padding: 128rpx 96rpx;
  box-sizing: border-box;
}

.bl-splash__ring {
  position: relative;
  width: 320rpx;
  height: 320rpx;
  border-radius: 50%;
  border: 4rpx solid rgba(47, 93, 78, .45);
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
}
/* 墨晕：用主色径向渐变替代原来的白色发光，避免在宣纸上泛白 */
.bl-splash__wash {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 560rpx;
  height: 560rpx;
  margin-top: -280rpx;
  margin-left: -280rpx;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(47, 93, 78, .16) 0%, rgba(47, 93, 78, 0) 68%);
}
.bl-splash__avatar {
  position: relative;
  width: 200rpx;
  height: 200rpx;
  border-radius: 50%;
  background-color: var(--bl-surface);
  border: 1rpx solid var(--bl-border);
  box-shadow: var(--bl-shadow-card);
  display: flex;
  align-items: center;
  justify-content: center;
}
.bl-splash__seal { width: 132rpx; height: 132rpx; }

.bl-splash__title {
  margin-top: 64rpx;
  font-size: 72rpx;
  font-weight: 700;
  letter-spacing: 8rpx;
  color: var(--bl-text);
}
.bl-splash__sub {
  margin-top: 20rpx;
  font-size: var(--bl-font-body);
  letter-spacing: 6rpx;
  color: var(--bl-text-2);
}

.bl-splash__cta {
  margin-top: auto;
  width: 100%;
  background-color: var(--bl-primary);
}
.bl-splash__cta:active { background-color: var(--bl-primary-pressed); }
.bl-splash__cta-text {
  font-size: var(--bl-font-body);
  font-weight: 700;
  color: var(--bl-surface);
  line-height: 1.2;
}
</style>
