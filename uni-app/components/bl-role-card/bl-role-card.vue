<template>
  <view class="bl-role" :class="{ 'is-selected': selected }" @click="$emit('select')">
    <view class="bl-role__avatar" :style="{ backgroundColor: avatarColor }">
      <bl-icon name="person" color="#FFFFFF" :size="64" />
    </view>
    <view class="bl-role__main">
      <text class="bl-role__name">{{ name }}</text>
      <text class="bl-role__desc">{{ desc }}</text>
    </view>
    <view class="bl-role__check" :class="{ 'is-on': selected }">
      <bl-icon v-if="selected" name="check" color="#FFFFFF" :size="34" />
    </view>
  </view>
</template>

<script setup>
defineProps({
  name: { type: String, default: '' },
  desc: { type: String, default: '' },
  avatarColor: { type: String, default: '#07C160' },
  selected: { type: Boolean, default: false }
})

defineEmits(['select'])
</script>

<style scoped>
.bl-role {
  display: flex;
  align-items: center;
  gap: 24rpx;
  padding: 32rpx;
  min-height: 176rpx;
  background-color: var(--bl-surface);
  border-radius: var(--bl-radius-card);
  border: 4rpx solid transparent;
  box-shadow: var(--bl-shadow-card);
  box-sizing: border-box;
}
.bl-role.is-selected {
  border-color: var(--bl-primary);
  background-color: #F4FFF9;
}
.bl-role:active { background-color: #F7F7F7; }

.bl-role__avatar {
  width: 120rpx;
  height: 120rpx;
  border-radius: 50%;
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
}
.bl-role__main { flex: 1; min-width: 0; }
.bl-role__name {
  display: block;
  font-size: var(--bl-font-title);
  font-weight: 700;
  line-height: 1.25;
  color: var(--bl-text);
}
.bl-role__desc {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  margin-top: 8rpx;
}

.bl-role__check {
  flex: none;
  width: 64rpx;
  height: 64rpx;
  border-radius: 50%;
  border: 4rpx solid var(--bl-divider);
  box-sizing: border-box;
  display: flex;
  align-items: center;
  justify-content: center;
}
.bl-role__check.is-on {
  border-color: var(--bl-primary);
  background-color: var(--bl-primary);
}
</style>