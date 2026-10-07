<template>
  <!-- 时间分隔线 -->
  <view v-if="type === 'time'" class="bl-msg-time">
    <text class="bl-msg-time__text">{{ text }}</text>
  </view>

  <!-- 系统提示：居中灰字（合规提示 / 出错提示 / 「没听清」） -->
  <view v-else-if="type === 'system'" class="bl-msg-system">
    <text class="bl-msg-system__text">{{ text }}</text>
  </view>

  <!-- 表情包：无气泡、大图（素材位就位前用 emoji 占位） -->
  <view v-else-if="type === 'sticker'" class="bl-msg" :class="{ 'bl-msg--me': mine }">
    <view class="bl-msg__avatar" :style="{ backgroundColor: avatarColor }">
      <bl-icon name="person" color="#FFFFFF" :size="52" />
    </view>
    <view class="bl-sticker">
      <image v-if="stickerInfo.src" class="bl-sticker__img" :src="stickerInfo.src" mode="aspectFit" />
      <text v-else class="bl-sticker__emoji">{{ stickerInfo.emoji }}</text>
      <text class="bl-sticker__label">{{ stickerInfo.label }}</text>
    </view>
  </view>

  <!-- 卡片：计划卡 / 内容卡 -->
  <view v-else-if="type === 'card'" class="bl-msg" :class="{ 'bl-msg--me': mine }">
    <view class="bl-msg__avatar" :style="{ backgroundColor: avatarColor }">
      <bl-icon name="person" color="#FFFFFF" :size="52" />
    </view>
    <view class="bl-card-slot">
      <bl-plan-card
        v-if="cardStyle === 'plan'"
        :time="planData.time"
        :title="planData.title"
        :desc="planData.desc"
        :state="planData.state"
      />
      <view v-else class="bl-news">
        <text class="bl-news__title">{{ plainData.title || '消息' }}</text>
        <text v-if="plainData.summary || plainData.desc" class="bl-news__desc">
          {{ plainData.summary || plainData.desc }}
        </text>
        <text v-if="plainData.source" class="bl-news__src">来源 {{ plainData.source }}</text>
      </view>
    </view>
  </view>

  <!-- 文本 / 语音 -->
  <view v-else class="bl-msg" :class="{ 'bl-msg--me': mine }">
    <view class="bl-msg__avatar" :style="{ backgroundColor: avatarColor }">
      <bl-icon name="person" color="#FFFFFF" :size="52" />
    </view>

    <view class="bl-bubble-wrap">
      <view class="bl-bubble" :class="mine ? 'bl-bubble--me' : 'bl-bubble--ai'">
        <view v-if="type === 'voice'" class="bl-bubble__voice" @click="$emit('play')">
          <bl-icon name="speaker" :color="voiceColor" :size="36" />
          <view class="bl-wave">
            <view
              v-for="(h, i) in WAVE"
              :key="i"
              class="bl-wave__bar"
              :style="{ height: h + 'rpx' }"
            />
          </view>
          <text class="bl-bubble__dur">{{ seconds }}&#8243;</text>
        </view>

        <view v-else class="bl-bubble__line">
          <text class="bl-bubble__text">{{ text }}</text>
          <text v-if="streaming" class="bl-bubble__caret">▍</text>
        </view>
      </view>

      <!-- 失败可重发；停止只是告知，不做操作 -->
      <text v-if="status === 'failed'" class="bl-msg__tip bl-msg__tip--retry" @click="$emit('retry')">
        没发出去 点这里重发
      </text>
      <text v-else-if="status === 'stopped'" class="bl-msg__tip">已停止</text>
    </view>
  </view>
</template>

<script setup>
import { computed } from 'vue'
import { stickerOf } from '@/common/stickers.js'
import { tokens } from '@/common/tokens.js'

const props = defineProps({
  text: { type: String, default: '' },
  /** 右侧「我」的消息 */
  mine: { type: Boolean, default: false },
  /** text | voice | sticker | card | system | time */
  type: { type: String, default: 'text' },
  seconds: { type: [Number, String], default: 6 },
  avatarColor: { type: String, default: '#2F5D4E' },
  /** 表情包受控 token，如 love / hug */
  sticker: { type: String, default: '' },
  /** 卡片数据：{ kind:'plan_item', plan:{...} } 或 { kind:'news', title, summary, source } */
  card: { type: Object, default: null },
  /** 正在流式接收（显示光标） */
  streaming: { type: Boolean, default: false },
  /** sent | streaming | stopped | failed */
  status: { type: String, default: 'sent' }
})

defineEmits(['play', 'retry'])

/** 语音波纹高度（rpx），对应设计稿里的波形 */
const WAVE = [12, 24, 36, 20, 32, 16, 28, 24, 36, 12]
// 语音条波形与图标统一取主色，避免硬编码色值在两处漂移
const voiceColor = tokens.color.primary

const stickerInfo = computed(() => stickerOf(props.sticker))

const plainData = computed(() => props.card || {})
const cardStyle = computed(() => {
  const kind = plainData.value.kind
  if (kind === 'plan_item' || kind === 'plan') return 'plan'
  if (plainData.value.plan) return 'plan'
  return 'plain'
})
const planData = computed(() => plainData.value.plan || plainData.value)
</script>

<style scoped>
.bl-msg {
  display: flex;
  align-items: flex-start;
  gap: 16rpx;
  margin-bottom: 32rpx;
}
.bl-msg--me { flex-direction: row-reverse; }

.bl-msg__avatar {
  width: 80rpx;
  height: 80rpx;
  border-radius: 50%;
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 时间分隔线与系统提示：居中，不占气泡宽度 */
.bl-msg-time {
  display: flex;
  justify-content: center;
  margin: 16rpx 0 32rpx;
}
.bl-msg-time__text { font-size: 24rpx; color: var(--bl-text-2); }

.bl-msg-system {
  display: flex;
  justify-content: center;
  margin: 0 0 32rpx;
}
.bl-msg-system__text {
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  background-color: var(--bl-primary-soft);
  border-radius: var(--bl-radius-pill);
  padding: 8rpx 24rpx;
  text-align: center;
  line-height: 1.5;
}

.bl-bubble-wrap {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  max-width: 464rpx;
}
.bl-msg--me .bl-bubble-wrap { align-items: flex-end; }

.bl-bubble {
  max-width: 464rpx;
  padding: 20rpx 28rpx;
  border-radius: var(--bl-radius-bubble);
  box-sizing: border-box;
}
.bl-bubble--me {
  background-color: var(--bl-bubble-me);
  border-top-right-radius: 8rpx;
}
.bl-bubble--ai {
  background-color: var(--bl-surface);
  border-top-left-radius: 8rpx;
}
.bl-bubble__line { display: flex; flex-direction: row; align-items: flex-end; }
.bl-bubble__text {
  font-size: var(--bl-font-body);
  line-height: 1.5;
  color: var(--bl-text);
  word-break: break-word;
  white-space: pre-wrap;
}
/* 流式光标：只做透明度闪烁，不用 transform，低端机也不会掉帧 */
.bl-bubble__caret {
  font-size: var(--bl-font-body);
  color: var(--bl-primary);
  margin-left: 4rpx;
  animation: bl-caret 1s steps(2, start) infinite;
}
@keyframes bl-caret {
  0%, 50% { opacity: 1; }
  50.01%, 100% { opacity: 0; }
}

.bl-msg__tip {
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  margin-top: 8rpx;
  padding: 4rpx 8rpx;
}
.bl-msg__tip--retry {
  color: var(--bl-danger);
  min-height: 56rpx;
  line-height: 56rpx;
}

.bl-bubble__voice {
  display: flex;
  align-items: center;
  gap: 16rpx;
  min-width: 200rpx;
}
.bl-wave {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8rpx;
  height: 40rpx;
}
.bl-wave__bar {
  width: 6rpx;
  border-radius: 3rpx;
  background-color: var(--bl-primary);
}
.bl-bubble__dur { font-size: 24rpx; color: var(--bl-text-2); }

/* 表情包 */
.bl-sticker {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  padding-top: 8rpx;
}
.bl-sticker__emoji { font-size: 120rpx; line-height: 1.1; }
.bl-sticker__img { width: 240rpx; height: 240rpx; }
.bl-sticker__label { font-size: 22rpx; color: var(--bl-text-2); margin-top: 4rpx; }

/* 卡片槽位：卡片本身有圆角阴影，这里只负责限宽 */
.bl-card-slot { max-width: 560rpx; }
.bl-news {
  background-color: var(--bl-surface);
  border-radius: var(--bl-radius-card);
  box-shadow: var(--bl-shadow-card);
  padding: 28rpx 32rpx;
}
.bl-news__title {
  display: block;
  font-size: var(--bl-font-body);
  font-weight: 700;
  color: var(--bl-text);
  line-height: 1.4;
}
.bl-news__desc {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  line-height: 1.5;
  margin-top: 12rpx;
}
.bl-news__src {
  display: block;
  font-size: 22rpx;
  color: var(--bl-icon-muted);
  margin-top: 16rpx;
}
</style>
