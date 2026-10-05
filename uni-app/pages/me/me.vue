<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar title="我的" solid />

    <scroll-view class="bl-body" scroll-y>
      <view class="bl-profile">
        <view class="bl-profile__avatar">
          <bl-icon name="person" color="#FFFFFF" :size="80" />
        </view>
        <view class="bl-profile__main">
          <text class="bl-profile__name">王奶奶</text>
          <text class="bl-profile__desc">有人陪着说说话，日子就有滋味</text>
        </view>
      </view>

      <view class="bl-section-title">陪伴设置</view>
      <view class="bl-group">
        <view class="bl-row" @click="toRoles">
          <view class="bl-row__icon">
            <bl-icon name="role" color="#07C160" :size="44" />
          </view>
          <text class="bl-row__label">智能体角色</text>
          <text class="bl-row__value">{{ settings.role }}</text>
          <bl-icon name="chev" color="#C4C4C4" :size="34" />
        </view>

        <view class="bl-row" @click="toFace">
          <view class="bl-row__icon">
            <bl-icon name="face" color="#07C160" :size="44" />
          </view>
          <text class="bl-row__label">数字人形象</text>
          <text class="bl-row__value">小明 3D 形象</text>
          <bl-icon name="chev" color="#C4C4C4" :size="34" />
        </view>

        <view class="bl-row" @click="toast('已绑定：儿子 小明、女儿 小红')">
          <view class="bl-row__icon">
            <bl-icon name="family" color="#07C160" :size="44" />
          </view>
          <text class="bl-row__label">家人绑定</text>
          <text class="bl-row__value">儿子 / 女儿 已绑定</text>
          <bl-icon name="chev" color="#C4C4C4" :size="34" />
        </view>
      </view>

      <view class="bl-section-title">健康与设置</view>
      <view class="bl-group">
        <view class="bl-row" @click="toast('用药 · 血压 · 体检（原型演示）')">
          <view class="bl-row__icon">
            <bl-icon name="health" color="#07C160" :size="44" />
          </view>
          <text class="bl-row__label">健康档案</text>
          <bl-icon name="chev" color="#C4C4C4" :size="34" />
        </view>

        <view class="bl-row">
          <view class="bl-row__icon">
            <bl-icon name="settings" color="#07C160" :size="44" />
          </view>
          <text class="bl-row__label">大字体模式</text>
          <bl-switch :checked="settings.largeFont" @change="onLargeChange" />
        </view>

        <view class="bl-row" @click="toast('AI 记忆可查看与删除（原型演示）')">
          <view class="bl-row__icon">
            <bl-icon name="privacy" color="#07C160" :size="44" />
          </view>
          <text class="bl-row__label">隐私 · AI 记忆</text>
          <bl-icon name="chev" color="#C4C4C4" :size="34" />
        </view>

        <view class="bl-row" @click="toTokens">
          <view class="bl-row__icon">
            <bl-icon name="palette" color="#07C160" :size="44" />
          </view>
          <text class="bl-row__label">设计规范</text>
          <bl-icon name="chev" color="#C4C4C4" :size="34" />
        </view>
      </view>
    </scroll-view>

    <bl-tabbar active="me" />
  </view>
</template>

<script setup>
import { settings, setLargeFont } from '@/common/store.js'

function toast(title) {
  uni.showToast({ title: title, icon: 'none' })
}
function onLargeChange(value) {
  setLargeFont(value)
  toast(value ? '已开启大字体模式' : '已关闭大字体模式')
}
function toRoles() {
  uni.navigateTo({ url: '/pages/roles/roles' })
}
function toFace() {
  // 形象页**已开放**（用户要求）：页面里可切换男女形象；精细捏脸在页面内标注"正在开发中"。
  // 所以这里恢复为正常跳转 —— 之前"点进来只弹提示"的做法已作废
  // （那时捏脸整体下线、页面打不开，用户就没有切换男女的入口了）。
  uni.navigateTo({ url: '/pages/face/face' })
}
function toTokens() {
  uni.navigateTo({ url: '/pages/tokens/tokens' })
}
</script>

<style scoped>
.bl-profile {
  display: flex;
  align-items: center;
  gap: 32rpx;
  padding: 48rpx 32rpx;
  background-color: var(--bl-surface);
}
.bl-profile__avatar {
  width: 160rpx;
  height: 160rpx;
  flex: none;
  border-radius: 50%;
  background-color: var(--bl-primary);
  display: flex;
  align-items: center;
  justify-content: center;
}
.bl-profile__main { flex: 1; min-width: 0; }
.bl-profile__name {
  display: block;
  font-size: var(--bl-font-title);
  font-weight: 700;
  color: var(--bl-text);
}
.bl-profile__desc {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  margin-top: 10rpx;
  line-height: 1.4;
}
</style>