<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar title="说话方式" back solid @back="back" />

    <scroll-view class="bl-body" scroll-y>
      <!-- 为什么默认是"智能切换"：老人不一定清楚什么时候该换人设，
           有人甚至不太会用手机。默认自动 = 他什么都不用做也不会出错。 -->
      <view class="bl-pm__head">
        <text class="bl-pm__tip">平时怎么跟您说话。不用改也行，默认就是最合适的。</text>
      </view>

      <view class="bl-pm__list">
        <view
          v-for="m in modes"
          :key="m.value"
          class="bl-pm__card"
          :class="{ 'is-on': current === m.value }"
          role="button"
          :aria-label="m.label + '，' + m.hint"
          @click="choose(m)"
        >
          <view class="bl-pm__main">
            <view class="bl-pm__title-row">
              <!-- 字号刻意放大：这是给老人看的，不是给开发者看的 -->
              <text class="bl-pm__label">{{ m.label }}</text>
              <text v-if="m.badge" class="bl-pm__badge">{{ m.badge }}</text>
            </view>
            <text class="bl-pm__hint">{{ m.hint }}</text>
          </view>

          <!-- 勾选必须做得明显：小圆点老人看不清 -->
          <view class="bl-pm__check" :class="{ 'is-on': current === m.value }">
            <bl-icon v-if="current === m.value" name="check" color="#FFFFFF" :size="40" />
          </view>
        </view>
      </view>

      <!-- 合规说明：不能让人误以为"选只用陪伴助手就不用看医生了" -->
      <view class="bl-pm__note">
        <text class="bl-pm__note-title">说一句要紧的话</text>
        <text class="bl-pm__note-text">
          不管选哪一种，只要聊到病情、吃药、检查，回答最后都会提醒一句「仅供参考，
          实际情况请以医嘱为准，及时线下就医」。这是对您负责，不能关掉。
        </text>
      </view>

      <view class="bl-page-footer">
        <view class="bl-btn bl-btn--primary bl-btn--block" role="button" @click="back">
          <text class="bl-page-footer__text bl-page-footer__text--on">好了</text>
        </view>
      </view>
    </scroll-view>
  </view>
</template>

<script setup>
/**
 * 说话方式（人设模式）选择。
 *
 * 三档的语义：
 *   auto    智能切换——按说的话自动选日常 / 医疗人设（默认）
 *   chat    只用陪伴助手——什么话题都家常聊
 *   medical 只用健康顾问——什么话题都按健康口径答
 *
 * ⚠️ 无论哪一档，医疗免责都由**服务端代码**强制补上，选 chat 也关不掉。
 *    这一点写在页面上（下方 bl-pm__note），不能让人误解成"选了陪聊就不用看医生"。
 */
import { computed, ref } from 'vue'
import { settings, PERSONA_MODES, readPersonaMode, setPersonaMode } from '@/common/store.js'

const modes = PERSONA_MODES
const current = ref(readPersonaMode())

/** 当前档位的名字（返回上一页时「我的」页要用） */
const currentLabel = computed(() => {
  const hit = modes.find((m) => m.value === current.value)
  return hit ? hit.label : '智能切换'
})

function choose(mode) {
  const next = setPersonaMode(mode.value)
  current.value = next
  if (next === mode.value) {
    // 立刻给反馈：老人点完要马上知道"成了"
    uni.showToast({ title: '已换成' + mode.label, icon: 'none' })
  }
}

function back() {
  const pages = getCurrentPages()
  if (pages.length > 1) uni.navigateBack()
  else uni.reLaunch({ url: '/pages/me/me' })
}
</script>

<style scoped>
.bl-pm__head {
  padding: 8rpx 4rpx 26rpx;
}

.bl-pm__tip {
  font-size: var(--bl-font-body);
  color: var(--bl-text-2);
  line-height: 1.6;
}

.bl-pm__list {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
}

/* 卡片整体是触控区：高度按内容撑开，远超 48px 最小触控标准 */
.bl-pm__card {
  display: flex;
  align-items: center;
  gap: 20rpx;
  padding: 30rpx 26rpx;
  background-color: var(--bl-surface);
  border: 3rpx solid transparent;
  border-radius: var(--bl-radius-card);
  box-shadow: var(--bl-shadow-card);
}

.bl-pm__card.is-on {
  border-color: var(--bl-primary);
  background-color: var(--bl-primary-soft);
}

.bl-pm__main {
  flex: 1;
  min-width: 0;
}

.bl-pm__title-row {
  display: flex;
  align-items: center;
  gap: 14rpx;
  flex-wrap: wrap;
}

.bl-pm__label {
  font-size: 38rpx;
  font-weight: 700;
  color: var(--bl-text);
  line-height: 1.3;
}

.bl-pm__badge {
  padding: 2rpx 14rpx;
  font-size: 22rpx;
  color: #FFFFFF;
  background-color: var(--bl-primary);
  border-radius: 8rpx;
}

.bl-pm__hint {
  display: block;
  margin-top: 10rpx;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  line-height: 1.55;
}

.bl-pm__check {
  flex: none;
  width: 60rpx;
  height: 60rpx;
  border-radius: 50%;
  border: 3rpx solid var(--bl-divider);
  background-color: transparent;
  display: flex;
  align-items: center;
  justify-content: center;
}

.bl-pm__check.is-on {
  border-color: var(--bl-primary);
  background-color: var(--bl-primary);
}

.bl-pm__note {
  margin-top: 34rpx;
  padding: 24rpx 26rpx;
  background-color: var(--bl-surface-2);
  border-radius: var(--bl-radius-card);
  border-left: 6rpx solid var(--bl-primary);
}

.bl-pm__note-title {
  display: block;
  font-size: var(--bl-font-caption);
  font-weight: 700;
  color: var(--bl-primary);
  margin-bottom: 10rpx;
}

.bl-pm__note-text {
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  line-height: 1.65;
}
</style>
