<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar title="比邻AI" />

    <scroll-view class="bl-body" scroll-y>
      <view
        v-for="c in rows"
        :key="c.name"
        class="bl-chat-row"
        @click="open"
      >
        <view class="bl-chat-row__avatar" :style="{ backgroundColor: c.color }">
          <bl-icon name="person" color="#FFFFFF" size="46%" />
        </view>

        <view class="bl-chat-row__main">
          <text class="bl-chat-row__name">{{ c.name }}</text>
          <text class="bl-chat-row__msg">{{ c.msg }}</text>
        </view>

        <view class="bl-chat-row__side">
          <text class="bl-chat-row__time">{{ c.time }}</text>
          <view v-if="c.unread" class="bl-badge">{{ c.unread }}</view>
        </view>
      </view>
    </scroll-view>

    <bl-tabbar active="chats" />
  </view>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { settings } from '@/common/store.js'
import { chat, initChat, lastPreview, lastTime } from '@/stores/chat.js'

/** 其余会话仍是静态占位：一期只有「儿子 小明」这条接了真实 agent */
const PLACEHOLDER = [
  { name: '老伴 老张', msg: '今天天气真好，出来晒晒太阳', time: '08:40', unread: 0, color: '#F5A623' },
  { name: '女儿 小红', msg: '晚上视频哦', time: '昨天', unread: 0, color: '#4C8DFF' }
]

const rows = computed(() => {
  const first = {
    name: chat.persona.name,
    msg: lastPreview(),
    time: lastTime() || '09:12',
    unread: 0,
    color: chat.persona.avatarColor
  }
  return [first].concat(PLACEHOLDER)
})

onMounted(() => {
  initChat()
})

function open() {
  uni.navigateTo({ url: '/pages/chat-detail/chat-detail' })
}
</script>

<style scoped>
.bl-chat-row {
  display: flex;
  align-items: center;
  gap: 24rpx;
  min-height: 152rpx;
  padding: 24rpx 32rpx;
  background-color: var(--bl-surface);
  position: relative;
  box-sizing: border-box;
}
.bl-chat-row + .bl-chat-row::before {
  content: '';
  position: absolute;
  left: calc(var(--bl-space-lg) + var(--bl-avatar) + var(--bl-space-md));
  right: 0;
  top: 0;
  height: 1rpx;
  background-color: var(--bl-divider);
}
.bl-chat-row:active { background-color: #F7F7F7; }

.bl-chat-row__avatar {
  width: var(--bl-avatar);
  height: var(--bl-avatar);
  border-radius: 50%;
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
}

.bl-chat-row__main { flex: 1; min-width: 0; }
.bl-chat-row__name {
  display: block;
  font-size: var(--bl-font-body);
  font-weight: 700;
  line-height: 1.3;
  color: var(--bl-text);
}
.bl-chat-row__msg {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  line-height: 1.4;
  margin-top: 6rpx;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.bl-chat-row__side {
  flex: none;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 12rpx;
}
.bl-chat-row__time { font-size: 24rpx; color: var(--bl-text-2); }
</style>