<template>
  <view class="bl-page bl-splash" :class="{ 'bl-large': settings.largeFont }">
    <view class="bl-splash__ring">
      <view class="bl-splash__glow" />
      <view class="bl-splash__avatar">
        <bl-icon name="person" color="#07C160" :size="150" />
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
import { settings } from '@/common/store.js'

function start() {
  uni.reLaunch({ url: '/pages/chats/chats' })
}
</script>

<style scoped>
.bl-splash {
  align-items: center;
  justify-content: center;
  background: linear-gradient(180deg, #07C160 0%, #06AD56 100%);
  padding: 128rpx 96rpx;
  box-sizing: border-box;
}

.bl-splash__ring {
  position: relative;
  width: 320rpx;
  height: 320rpx;
  border-radius: 50%;
  border: 4rpx solid rgba(255, 255, 255, .45);
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
}
.bl-splash__glow {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 560rpx;
  height: 560rpx;
  margin-top: -280rpx;
  margin-left: -280rpx;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(255, 255, 255, .5) 0%, rgba(255, 255, 255, 0) 68%);
}
.bl-splash__avatar {
  position: relative;
  width: 200rpx;
  height: 200rpx;
  border-radius: 50%;
  background-color: #FFFFFF;
  display: flex;
  align-items: center;
  justify-content: center;
}

.bl-splash__title {
  margin-top: 64rpx;
  font-size: 72rpx;
  font-weight: 700;
  letter-spacing: 8rpx;
  color: #FFFFFF;
}
.bl-splash__sub {
  margin-top: 20rpx;
  font-size: var(--bl-font-body);
  letter-spacing: 6rpx;
  color: rgba(255, 255, 255, .9);
}

.bl-splash__cta {
  margin-top: auto;
  width: 100%;
  background-color: #FFFFFF;
}
.bl-splash__cta:active { background-color: #F0F0F0; }
.bl-splash__cta-text {
  font-size: var(--bl-font-body);
  font-weight: 700;
  color: #07C160;
  line-height: 1.2;
}
</style>