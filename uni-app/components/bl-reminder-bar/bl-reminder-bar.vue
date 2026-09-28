<template>
  <view
    v-if="item"
    class="bl-reminder"
    :class="{ 'is-strong': item.strong }"
    @click="$emit('open', item)"
  >
    <view class="bl-reminder__badge">
      <bl-icon name="clock" :color="item.strong ? '#FFFFFF' : '#07C160'" :size="40" />
    </view>

    <view class="bl-reminder__main">
      <text class="bl-reminder__label">
        {{ item.label }}{{ item.strong ? ' · 重要' : '' }}
      </text>
      <text class="bl-reminder__title">{{ item.title }}</text>
    </view>

    <view class="bl-reminder__action" @click.stop="$emit('dismiss', item)">
      <text class="bl-reminder__action-text">知道了</text>
    </view>
  </view>
</template>

<script setup>
/**
 * 顶部提醒条（到点提醒的前台呈现）
 *
 * 适老化要点：
 * - 整条可点（去日程页打卡），右侧「知道了」独立按钮，两个动作都不需要瞄准
 * - 强提醒（用药/午餐）用红底白字，普通提醒用绿字白底，一眼能分辨重要程度
 * - 不用模态框打断老人正在做的事，靠震动 + 这条横幅
 */
defineProps({
  /** { taskId, planItemId, title, label, strong, levelLabel } | null */
  item: { type: Object, default: null }
})

defineEmits(['open', 'dismiss'])
</script>

<style scoped>
.bl-reminder {
  flex: none;
  display: flex;
  align-items: center;
  gap: 20rpx;
  margin: 0 24rpx 16rpx;
  padding: 24rpx;
  background-color: var(--bl-surface);
  border: 3rpx solid var(--bl-primary);
  border-radius: var(--bl-radius-card);
  box-shadow: var(--bl-shadow-card);
  box-sizing: border-box;
}
.bl-reminder.is-strong {
  background-color: #C7362F;
  border-color: #C7362F;
}
.bl-reminder:active { opacity: .92; }

.bl-reminder__badge {
  flex: none;
  width: 72rpx;
  height: 72rpx;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: transparent;
}
.bl-reminder.is-strong .bl-reminder__badge { background-color: rgba(255, 255, 255, .18); }

.bl-reminder__main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6rpx;
}
.bl-reminder__label {
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
}
.bl-reminder.is-strong .bl-reminder__label { color: #FFE3E1; }
.bl-reminder__title {
  font-size: var(--bl-font-body);
  font-weight: 700;
  color: var(--bl-text);
  line-height: 1.4;
}
.bl-reminder.is-strong .bl-reminder__title { color: #FFFFFF; }

.bl-reminder__action {
  flex: none;
  min-width: 148rpx;
  height: var(--bl-touch);
  padding: 0 24rpx;
  border-radius: var(--bl-radius-pill);
  background-color: #EAF9F1;
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
}
.bl-reminder.is-strong .bl-reminder__action { background-color: #FFFFFF; }
.bl-reminder__action:active { opacity: .8; }
.bl-reminder__action-text {
  font-size: var(--bl-font-caption);
  font-weight: 700;
  color: var(--bl-primary);
  line-height: 1.2;
}
</style>
