<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar title="AI 了解我的" back solid @back="back" />

    <scroll-view class="bl-body" scroll-y>
      <!-- 为什么要有这一页：
           wiki 是 AI 自己学的，**它一定会记错**。
           看不到、改不了的话，老人会觉得"它根本不懂我，还乱记我"。
           能看、能删、能改，是这套系统对老人的基本尊重。 -->
      <view class="bl-wk__head">
        <text class="bl-wk__tip">
          这些是聊天的过程中慢慢记下来的。记错了可以删，也能自己改。
        </text>
      </view>

      <view v-if="loading" class="bl-wk__empty">
        <text class="bl-wk__empty-text">正在看…</text>
      </view>

      <view v-else-if="!hasAny" class="bl-wk__empty">
        <text class="bl-wk__empty-text">还没有记下什么。多聊几句，我就会慢慢了解您。</text>
      </view>

      <template v-else>
        <!-- 老人画像 -->
        <view v-for="board in boards" :key="board.kind" class="bl-wk__board">
          <view class="bl-section-title--ink">
            <view class="bl-brush-rule" />
            <text class="bl-section-title__text">{{ board.label }}</text>
          </view>

          <view v-if="!board.sections.length" class="bl-wk__blank">
            <text class="bl-wk__blank-text">{{ board.emptyHint }}</text>
          </view>

          <view v-for="sec in board.sections" :key="board.kind + sec.title" class="bl-wk__sec">
            <view class="bl-wk__sec-head">
              <text class="bl-wk__sec-title">{{ sec.title }}</text>
              <text class="bl-wk__sec-count">{{ sec.items.length }} 条</text>
            </view>

            <view class="bl-wk__items">
              <view
                v-for="(item, idx) in sec.items"
                :key="board.kind + sec.title + idx"
                class="bl-wk__item"
              >
                <text class="bl-wk__item-text">{{ item }}</text>
                <!-- 删除做成大按钮：老人手指点不准，图标太小会误触 -->
                <view
                  class="bl-wk__del"
                  role="button"
                  :aria-label="'删掉这条：' + item"
                  @click="removeItem(board, sec, item)"
                >
                  <text class="bl-wk__del-text">删</text>
                </view>
              </view>
            </view>
          </view>
        </view>
      </template>

      <!-- 聊天摘要：让用户知道"它还记着更早聊过的事" -->
      <view v-if="summary" class="bl-wk__board">
        <view class="bl-section-title--ink">
          <view class="bl-brush-rule" />
          <text class="bl-section-title__text">更早聊过的（已压缩）</text>
        </view>
        <view class="bl-wk__summary">
          <text class="bl-wk__summary-text">{{ summary }}</text>
        </view>
      </view>

      <view class="bl-wk__foot">
        <text class="bl-wk__foot-text">
          忘了某些事是正常的。想让它重新认识您，删掉几条再聊就会更新。
        </text>
      </view>
    </scroll-view>
  </view>
</template>

<script setup>
/**
 * 「AI 了解我的」—— 展示并管理 wiki（AI 从对话里学到的东西）。
 *
 * 设计要点：
 *   · **只读 + 删除**为主：不鼓励老人手工编辑大段内容（适老化）
 *   · 删除做成有文字的大按钮，不是小叉号（老人点不准）
 *   · 空状态有意义："多聊几句，我就会慢慢了解您"，而不是干巴巴的"暂无数据"
 */
import { computed, onMounted, ref } from 'vue'
import { settings } from '@/common/store.js'
import { readAccount, readToken } from '@/stores/account.js'
import { deleteWikiItem, getWiki } from '@/api/index.js'

const loading = ref(true)
const elderBoard = ref({ kind: 'elder', label: 'AI 记住的我', sections: [], emptyHint: '还没记下关于您的事' })
const personaBoard = ref({ kind: 'persona', label: '家人说话的样子', sections: [], emptyHint: '还没记下家里人的说话习惯' })
const summary = ref('')

const boards = computed(() => [elderBoard.value, personaBoard.value])
const hasAny = computed(() =>
  elderBoard.value.sections.length > 0 ||
  personaBoard.value.sections.length > 0 ||
  !!summary.value
)

function applySections(board, data) {
  const list = (data && data.sections) || []
  board.value.sections = list.filter((s) => (s.items || []).length > 0)
}

function load() {
  const token = readToken()
  if (!token) {
    loading.value = false
    return
  }
  loading.value = true
  getWiki(token)
    .then((data) => {
      applySections(elderBoard, data && data.elder)
      applySections(personaBoard, data && data.persona)
      summary.value = (data && data.summary) || ''
    })
    .catch(() => {
      uni.showToast({ title: '没读上来，一会儿再试', icon: 'none' })
    })
    .then(() => {
      loading.value = false
    })
}

function removeItem(board, sec, text) {
  uni.showModal({
    title: '删掉这条？',
    content: text,
    confirmText: '删掉',
    cancelText: '留着',
    success: (res) => {
      if (!res.confirm) return
      const token = readToken()
      if (!token) return
      deleteWikiItem(token, { kind: board.kind, section: sec.title, text })
        .then(() => {
          // 本地先摘掉，不用等整页刷新（老人要立刻看到效果）
          sec.items = sec.items.filter((item) => item !== text)
          if (!sec.items.length) {
            board.sections = board.sections.filter((s) => s.title !== sec.title)
          }
          uni.showToast({ title: '忘了这条', icon: 'none' })
        })
        .catch(() => uni.showToast({ title: '没删掉，再试一次', icon: 'none' }))
    }
  })
}

function back() {
  const pages = getCurrentPages()
  if (pages.length > 1) uni.navigateBack()
  else uni.reLaunch({ url: '/pages/me/me' })
}

onMounted(load)
</script>

<style scoped>
.bl-wk__head {
  padding: 8rpx 4rpx 24rpx;
}

.bl-wk__tip {
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  line-height: 1.6;
}

.bl-wk__board {
  margin-bottom: 34rpx;
}

.bl-wk__empty {
  padding: 80rpx 30rpx;
  text-align: center;
}

.bl-wk__empty-text {
  font-size: var(--bl-font-body);
  color: var(--bl-text-2);
  line-height: 1.7;
}

.bl-wk__blank {
  padding: 26rpx 24rpx;
  background-color: var(--bl-surface-2);
  border-radius: var(--bl-radius-card);
}

.bl-wk__blank-text {
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
}

.bl-wk__sec {
  margin-bottom: 22rpx;
}

.bl-wk__sec-head {
  display: flex;
  align-items: baseline;
  gap: 12rpx;
  padding: 0 4rpx 10rpx;
}

.bl-wk__sec-title {
  font-size: 32rpx;
  font-weight: 700;
  color: var(--bl-text);
}

.bl-wk__sec-count {
  font-size: 22rpx;
  color: var(--bl-text-3, var(--bl-text-2));
}

.bl-wk__items {
  background-color: var(--bl-surface);
  border-radius: var(--bl-radius-card);
  box-shadow: var(--bl-shadow-card);
  overflow: hidden;
}

.bl-wk__item {
  display: flex;
  align-items: center;
  gap: 16rpx;
  padding: 24rpx 22rpx;
  border-bottom: 1rpx solid var(--bl-divider);
}

.bl-wk__item:last-child {
  border-bottom: none;
}

.bl-wk__item-text {
  flex: 1;
  min-width: 0;
  font-size: var(--bl-font-body);
  color: var(--bl-text);
  line-height: 1.5;
}

/* 删除做成方框 + 文字，触控面积远大于最小标准 */
.bl-wk__del {
  flex: none;
  min-width: 84rpx;
  padding: 14rpx 18rpx;
  border-radius: 12rpx;
  border: 2rpx solid var(--bl-border);
  display: flex;
  align-items: center;
  justify-content: center;
}

.bl-wk__del:active {
  background-color: var(--bl-surface-2);
}

.bl-wk__del-text {
  font-size: 26rpx;
  color: var(--bl-danger);
  font-weight: 600;
}

.bl-wk__summary {
  padding: 24rpx 24rpx;
  background-color: var(--bl-surface);
  border-radius: var(--bl-radius-card);
  box-shadow: var(--bl-shadow-card);
}

.bl-wk__summary-text {
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  line-height: 1.75;
  white-space: pre-wrap;
}

.bl-wk__foot {
  padding: 20rpx 4rpx 60rpx;
}

.bl-wk__foot-text {
  font-size: 22rpx;
  color: var(--bl-text-2);
  line-height: 1.6;
}
</style>
