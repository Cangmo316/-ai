<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar
      title="修改备注"
      back
      solid
      action="save"
      action-label="保存备注"
      @back="back"
      @action="save"
    />

    <scroll-view class="bl-body" scroll-y>
      <view class="bl-remark__head">
        <text class="bl-remark__who">原来是：{{ originalName }}</text>
        <text class="bl-remark__tip">改完只有你自己看到，对方那边还是原来的名字</text>
      </view>

      <view class="bl-remark__field">
        <text class="bl-f__label">备注名</text>
        <view class="bl-f__box" :class="{ 'is-error': error }">
          <input
            v-model="remark"
            class="bl-f__input"
            :maxlength="16"
            placeholder="比如：大儿子、楼下李姐"
            placeholder-class="bl-input-ph"
            confirm-type="done"
            @confirm="save"
          />
        </view>
        <text v-if="error" class="bl-f__err">{{ error }}</text>
        <text v-else-if="remark.trim()" class="bl-remark__preview">
          列表里会显示成「{{ remark.trim() }}」
        </text>
      </view>

      <!-- 常用备注：老人打字慢，给几个一键填的 -->
      <view class="bl-remark__quick">
        <text class="bl-f__label">或者选一个</text>
        <view class="bl-remark__chips">
          <view
            v-for="opt in QUICK"
            :key="opt"
            class="bl-remark__chip"
            role="button"
            :aria-label="opt"
            @click="remark = opt"
          >
            <text class="bl-remark__chip-text">{{ opt }}</text>
          </view>
        </view>
      </view>

      <view class="bl-remark__actions">
        <view class="bl-btn bl-btn--primary bl-btn--block" role="button" @click="save">
          <text class="bl-btn__text">保存备注</text>
        </view>
        <view
          v-if="hasRemark"
          class="bl-remark__clear"
          role="button"
          aria-label="删除备注"
          @click="clear"
        >
          <text class="bl-remark__clear-text">删掉备注，用回原来的名字</text>
        </view>
      </view>
    </scroll-view>
  </view>
</template>

<script setup>
/**
 * 修改备注。
 *
 * 入口：对话栏目里每行右侧的「备注」按钮（比长按更容易发现）。
 *
 * 按需求**只有我这边改**，所以备注只存本机、按账号隔离（见 stores/contacts.js）。
 * 页面上明说了这一点，免得老人以为对方也会看到。
 */
import { computed, ref } from 'vue'
import { settings } from '@/common/store.js'
import { pending, remarkOf, setRemark } from '@/stores/contacts.js'

/** 常用备注：老人打字慢，点一下就填 */
const QUICK = ['大儿子', '小女儿', '老伴', '家里人', '李姐', '老张']

/** 会话上下文由列表页通过 store 登记（不走 URL 参数，避免 id 里的冒号被重复编码） */
const conversationId = ref(pending.conversationId || '')
const originalName = ref(pending.title || '')
const remark = ref(remarkOf(conversationId.value))
const error = ref('')

const hasRemark = computed(() => !!remarkOf(conversationId.value))

function save() {
  error.value = ''
  const value = remark.value.trim()
  if (!conversationId.value) {
    error.value = '没找到这个会话，请退回列表重新进'
    return
  }
  if (value.length > 16) {
    error.value = '备注太长了，写短一点'
    return
  }
  setRemark(conversationId.value, value)
  uni.showToast({ title: value ? '备注已保存' : '已恢复原名', icon: 'none' })
  setTimeout(() => back(), 700)
}

function clear() {
  setRemark(conversationId.value, '')
  uni.showToast({ title: '已恢复原名', icon: 'none' })
  setTimeout(() => back(), 700)
}

function back() {
  const pages = getCurrentPages()
  if (pages.length > 1) uni.navigateBack()
  else uni.reLaunch({ url: '/pages/chats/chats' })
}
</script>

<style scoped>
.bl-remark__head { padding: 32rpx var(--bl-space-lg) 0; }
.bl-remark__who {
  display: block;
  font-size: var(--bl-font-body);
  color: var(--bl-text);
  font-weight: 600;
}
.bl-remark__tip {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  line-height: 1.5;
  margin-top: 10rpx;
}

.bl-remark__field { padding: 32rpx var(--bl-space-lg) 0; }

.bl-f__label {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  letter-spacing: .04em;
  margin-bottom: var(--bl-space-sm);
}
.bl-f__box {
  display: flex;
  align-items: center;
  padding: 0 var(--bl-space-md);
  min-height: 104rpx;
  background-color: var(--bl-surface);
  border: 2rpx solid var(--bl-border-strong);
  border-radius: var(--bl-radius-bubble);
  box-sizing: border-box;
}
.bl-f__box:focus-within { border-color: var(--bl-primary); }
.bl-f__box.is-error { border-color: var(--bl-danger); }
.bl-f__input {
  flex: 1;
  min-width: 0;
  height: 100rpx;
  font-size: var(--bl-font-body);
  color: var(--bl-text);
}
.bl-f__err {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-danger);
  margin-top: 10rpx;
}
.bl-remark__preview {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-primary);
  margin-top: 10rpx;
}

.bl-remark__quick { padding: 32rpx var(--bl-space-lg) 0; }
.bl-remark__chips { display: flex; flex-wrap: wrap; gap: 16rpx; }
.bl-remark__chip {
  min-height: var(--bl-touch);
  padding: 0 28rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: var(--bl-surface);
  border: 2rpx solid var(--bl-border-strong);
  border-radius: 999rpx;
  box-sizing: border-box;
}
.bl-remark__chip-text {
  font-size: var(--bl-font-body);
  font-weight: 600;
  color: var(--bl-text);
  line-height: 1;
}
.bl-remark__chip:active { background-color: var(--bl-surface-2); }

.bl-remark__actions { padding: var(--bl-space-xl) var(--bl-space-lg) var(--bl-space-xxl); }
.bl-remark__clear {
  margin-top: var(--bl-space-lg);
  min-height: var(--bl-touch);
  display: flex;
  align-items: center;
  justify-content: center;
}
.bl-remark__clear-text {
  font-size: var(--bl-font-body);
  font-weight: 600;
  color: var(--bl-text);
  text-decoration: underline;
  text-underline-offset: 6rpx;
}
</style>
