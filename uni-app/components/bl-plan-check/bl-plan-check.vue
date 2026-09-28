<template>
  <view class="bl-check" :class="{ 'is-done': done }" @click="$emit('toggle')">
    <view class="bl-check__head">
      <text class="bl-check__time">{{ time }}</text>
      <text class="bl-check__type">{{ type }}</text>
      <text v-if="strongRemind && !done" class="bl-check__flag">重要</text>
    </view>

    <text class="bl-check__title">{{ title }}</text>
    <text v-if="detail" class="bl-check__desc">{{ detail }}</text>

    <!-- 整个卡片都是打卡区域（手指不准也能点到），右侧给一个明确的大字反馈 -->
    <view class="bl-check__action" :class="{ 'is-done': done, 'is-busy': busy }">
      <bl-icon :name="done ? 'check' : 'clock'" :color="done ? '#FFFFFF' : '#07C160'" :size="44" />
      <text class="bl-check__action-text">{{ busy ? '保存中' : (done ? '已完成' : '打卡') }}</text>
    </view>
  </view>
</template>

<script setup>
/**
 * 计划项 + 大字打卡（设计方案 §6 的 `bl-plan-check`）
 *
 * 适老化要点：
 * - 整张卡片可点（触控区远超 48px），不用瞄准小按钮
 * - 状态变化同时用颜色 + 图标 + 文字三重表达（老人对纯颜色变化不敏感）
 * - 已完成不用删除线（降低可读性），改成绿底 + 对勾 + 文字「已完成」
 */
defineProps({
  time: { type: String, default: '' },
  type: { type: String, default: '' },
  title: { type: String, default: '' },
  detail: { type: String, default: '' },
  done: { type: Boolean, default: false },
  strongRemind: { type: Boolean, default: false },
  /** 请求进行中：避免老人连点导致来回抖动 */
  busy: { type: Boolean, default: false }
})

defineEmits(['toggle'])
</script>

<style scoped>
.bl-check {
  position: relative;
  background-color: var(--bl-surface);
  border-radius: var(--bl-radius-card);
  box-shadow: var(--bl-shadow-card);
  padding: 32rpx;
  box-sizing: border-box;
}
.bl-check:active { background-color: #F7F7F7; }
.bl-check.is-done {
  background-color: #F2FBF6;
  border: 2rpx solid #CDEEDC;
}

.bl-check__head {
  display: flex;
  align-items: center;
  gap: 16rpx;
}
.bl-check__time {
  font-size: var(--bl-font-title);
  font-weight: 700;
  color: var(--bl-primary);
  line-height: 1;
}
.bl-check__type {
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  background-color: rgba(0, 0, 0, .04);
  border-radius: var(--bl-radius-pill);
  padding: 4rpx 16rpx;
}
.bl-check__flag {
  font-size: var(--bl-font-caption);
  color: #C7362F;
  border: 2rpx solid #C7362F;
  border-radius: var(--bl-radius-pill);
  padding: 2rpx 14rpx;
}

.bl-check__title {
  display: block;
  font-size: var(--bl-font-body);
  font-weight: 700;
  line-height: 1.4;
  color: var(--bl-text);
  margin-top: 20rpx;
}
.bl-check__desc {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  line-height: 1.5;
  margin-top: 8rpx;
}

.bl-check__action {
  margin-top: 24rpx;
  min-height: var(--bl-touch);
  border-radius: var(--bl-radius-pill);
  background-color: #EAF9F1;
  border: 3rpx solid var(--bl-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12rpx;
  box-sizing: border-box;
}
.bl-check__action.is-done {
  background-color: var(--bl-primary);
  border-color: var(--bl-primary);
}
.bl-check__action.is-busy { opacity: .6; }
.bl-check__action-text {
  font-size: var(--bl-font-body);
  font-weight: 700;
  color: var(--bl-primary);
  line-height: 1.2;
}
.bl-check__action.is-done .bl-check__action-text { color: #FFFFFF; }
</style>
