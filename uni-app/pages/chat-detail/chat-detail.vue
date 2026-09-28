<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar
      :title="chat.persona.name"
      back
      action="video"
      action-color="#07C160"
      @back="back"
      @action="toVision"
    />

    <!-- 身份透明：AI 数字人标识常驻，不可移除（设计方案 §1.4 红线 2） -->
    <view class="bl-ai-notice">
      <text class="bl-ai-notice__text">AI 数字人 · 内容仅供参考</text>
    </view>

    <scroll-view class="bl-chat-body" scroll-y :scroll-top="scrollTop" :scroll-with-animation="true">
      <view v-for="m in chat.messages" :key="m.id" :id="'msg-' + m.id">
        <bl-chat-bubble
          :text="m.text"
          :type="m.type"
          :mine="m.role === 'elder'"
          :seconds="m.seconds"
          :avatar-color="m.role === 'elder' ? '#8C8C8C' : chat.persona.avatarColor"
          :sticker="m.sticker"
          :card="m.card"
          :streaming="m.status === 'streaming'"
          :status="m.status"
          @play="playVoice(m)"
          @retry="onRetry"
        />
      </view>
      <view class="bl-chat-body__pad" />
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
      <view class="bl-composer__btn" @click="toast('长按就能说话（语音在 P3 接入）')">
        <bl-icon name="mic" color="#1A1A1A" :size="48" />
      </view>
      <input
        v-model="draft"
        class="bl-composer__input"
        placeholder="说点什么…"
        placeholder-class="bl-composer__ph"
        confirm-type="send"
        @confirm="onSend"
      />
      <view class="bl-composer__btn" @click="emojiOpen = !emojiOpen">
        <bl-icon name="emoji" :color="emojiOpen ? '#07C160' : '#1A1A1A'" :size="48" />
      </view>
      <view
        class="bl-composer__send"
        :class="sendClass"
        @click="onPrimary"
      >
        <text class="bl-composer__send-text">{{ chat.streaming ? '停止' : '发送' }}</text>
      </view>
    </view>
  </view>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { settings } from '@/common/store.js'
import { chat, initChat, retry, send, stop } from '@/stores/chat.js'

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
const scrollTop = ref(0)

const sendClass = computed(() => {
  if (chat.streaming) return 'bl-composer__send--stop'
  if (!draft.value.trim()) return 'bl-composer__send--off'
  return ''
})

// 流式期间用「最后一条消息的文本长度」当信号：每来一个字都滚到底，
// 但只在真的变化时才 setData，避免低端机被刷爆。
watch(
  () => {
    const last = chat.messages[chat.messages.length - 1]
    return chat.messages.length + '|' + (last ? (last.text || '').length : -1)
  },
  () => scrollToBottom()
)

onMounted(() => {
  initChat()
  scrollToBottom()
})

function scrollToBottom() {
  nextTick(() => {
    // scroll-top 必须是变化的值才会触发滚动；累加一个远超内容高度的数字即可贴底
    scrollTop.value += 100000
  })
}

function insert(ch) {
  draft.value = (draft.value || '') + ch
}

function onPrimary() {
  if (chat.streaming) {
    stop()
    return
  }
  onSend()
}

function onSend() {
  if (chat.streaming) {
    toast('等我说完再发哦')
    return
  }
  const text = draft.value
  if (!text || !text.trim()) {
    toast('说点什么吧')
    return
  }
  if (send(text)) {
    draft.value = ''
    emojiOpen.value = false
    scrollToBottom()
  }
}

function onRetry() {
  if (retry()) scrollToBottom()
}

function playVoice() {
  toast('正在播放语音（P3 接入 CosyVoice 2）')
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
.bl-ai-notice {
  flex: none;
  display: flex;
  justify-content: center;
  padding: 0 24rpx 12rpx;
  background-color: var(--bl-bg);
}
.bl-ai-notice__text {
  font-size: 22rpx;
  color: var(--bl-text-2);
  line-height: 1.6;
}

.bl-chat-body {
  flex: 1;
  min-height: 0;
  padding: 16rpx 24rpx 0;
  background-color: var(--bl-bg);
  box-sizing: border-box;
}
.bl-chat-body__pad { height: 32rpx; }

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

/* 发送 / 停止：一个按钮两种身份，老人只需要记一个位置 */
.bl-composer__send {
  flex: none;
  min-width: 148rpx;
  height: 88rpx;
  padding: 0 28rpx;
  border-radius: var(--bl-radius-pill);
  background-color: var(--bl-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
}
.bl-composer__send:active { background-color: var(--bl-primary-pressed); }
/* 停止用更深的红：白字压在 #E64340 上对比度只有 4.0:1，达不到适老化 4.5:1 */
.bl-composer__send--stop { background-color: #C7362F; }
.bl-composer__send--stop:active { background-color: #A82C26; }
/* 输入为空时置灰：文字 #5A5A5A 压 #E4E4E4，对比度约 5.6:1，仍然达标 */
.bl-composer__send--off { background-color: #E4E4E4; }
.bl-composer__send--off:active { background-color: #DADADA; }
.bl-composer__send--off .bl-composer__send-text { color: #5A5A5A; }
.bl-composer__send-text {
  font-size: var(--bl-font-body);
  font-weight: 600;
  color: #FFFFFF;
  line-height: 1.2;
}
</style>
