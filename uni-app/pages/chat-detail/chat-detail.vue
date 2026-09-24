<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar
      title="儿子 小明"
      back
      action="video"
      action-color="#07C160"
      @back="back"
      @action="toVision"
    />

    <scroll-view class="bl-chat-body" scroll-y>
      <view class="bl-chat-time">今天 09:10</view>

      <bl-chat-bubble text="妈，今天感觉怎么样" avatar-color="#07C160" />
      <bl-chat-bubble text="挺好的，就是有点想你们" mine avatar-color="#8C8C8C" />
      <bl-chat-bubble text="那我晚上给你打视频，顺便看看你气色" avatar-color="#07C160" />
      <bl-chat-bubble
        type="voice"
        :seconds="6"
        avatar-color="#07C160"
        @play="toast('正在播放语音（原型演示）')"
      />
      <bl-chat-bubble text="好呀，我等着" mine avatar-color="#8C8C8C" />
    </scroll-view>

    <view v-if="emojiOpen" class="bl-emoji-panel">
      <view class="bl-emoji-grid">
        <view v-for="e in EMOJIS" :key="e.ch" class="bl-emoji" @click="insert(e.ch)">
          <text class="bl-emoji__ch">{{ e.ch }}</text>
          <text class="bl-emoji__label">{{ e.label }}</text>
        </view>
      </view>
    </view>

    <view class="bl-composer">
      <view class="bl-composer__btn" @click="toast('长按即可说话（原型演示）')">
        <bl-icon name="mic" color="#1A1A1A" :size="48" />
      </view>
      <input
        v-model="draft"
        class="bl-composer__input"
        placeholder="说点什么…"
        placeholder-class="bl-composer__ph"
        confirm-type="send"
      />
      <view class="bl-composer__btn" @click="emojiOpen = !emojiOpen">
        <bl-icon name="emoji" :color="emojiOpen ? '#07C160' : '#1A1A1A'" :size="48" />
      </view>
      <view class="bl-composer__btn" @click="toast('更多：表情 / 照片 / 日程提醒')">
        <bl-icon name="plus" color="#1A1A1A" :size="48" />
      </view>
    </view>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { settings } from '@/common/store.js'

const EMOJIS = [
  { ch: '❤️', label: '爱心' },
  { ch: '☀️', label: '太阳' },
  { ch: '🤗', label: '拥抱' },
  { ch: '😊', label: '笑脸' },
  { ch: '💊', label: '药丸' },
  { ch: '🍚', label: '饭菜' }
]

const draft = ref('')
const emojiOpen = ref(false)

function insert(ch) {
  draft.value = (draft.value || '') + ch
  toast('已插入表情 ' + ch)
}

function toast(title) {
  uni.showToast({ title: title, icon: 'none' })
}

function back() {
  const pages = getCurrentPages()
  if (pages.length > 1) uni.navigateBack()
  else uni.reLaunch({ url: '/pages/chats/chats' })
}

function toVision() {
  uni.navigateTo({ url: '/pages/vision/vision' })
}
</script>

<style scoped>
.bl-chat-body {
  flex: 1;
  min-height: 0;
  padding: 32rpx 24rpx;
  background-color: var(--bl-bg);
  box-sizing: border-box;
}
.bl-chat-time {
  text-align: center;
  font-size: 24rpx;
  color: var(--bl-text-2);
  margin: 16rpx 0 32rpx;
}

.bl-emoji-panel {
  flex: none;
  background-color: #F7F7F7;
  border-top: 1rpx solid var(--bl-divider);
}
.bl-emoji-grid {
  display: flex;
  flex-wrap: wrap;
  padding: 24rpx 16rpx;
}
.bl-emoji {
  width: 33.33%;
  padding: 16rpx 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  border-radius: var(--bl-radius-bubble);
}
.bl-emoji:active { background-color: rgba(0, 0, 0, .06); }
.bl-emoji__ch { font-size: 52rpx; line-height: 1.2; }
.bl-emoji__label {
  font-size: 22rpx;
  color: var(--bl-text-2);
  margin-top: 4rpx;
}

.bl-composer {
  flex: none;
  display: flex;
  align-items: center;
  gap: 12rpx;
  padding: 16rpx 24rpx;
  background-color: #F7F7F7;
  border-top: 1rpx solid var(--bl-divider);
  padding-bottom: calc(16rpx + env(safe-area-inset-bottom));
}
.bl-composer__btn {
  width: 80rpx;
  height: 80rpx;
  flex: none;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}
.bl-composer__btn:active { background-color: rgba(0, 0, 0, .06); }
.bl-composer__input {
  flex: 1;
  min-width: 0;
  height: 80rpx;
  padding: 0 24rpx;
  background-color: var(--bl-surface);
  border-radius: 40rpx;
  font-size: var(--bl-font-caption);
  color: var(--bl-text);
  box-sizing: border-box;
}
.bl-composer__ph { color: var(--bl-icon-muted); }
</style>