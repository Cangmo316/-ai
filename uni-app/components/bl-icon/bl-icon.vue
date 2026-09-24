<template>
  <image class="bl-icon" :src="src" :style="sizeStyle" mode="aspectFit" />
</template>

<script setup>
import { computed } from 'vue'
import { iconSrc } from '@/common/icons.js'

const props = defineProps({
  name: { type: String, required: true },
  color: { type: String, default: '#1A1A1A' },
  /** 数字按 rpx 处理，字符串原样输出（如 '48rpx' / '24px'） */
  size: { type: [Number, String], default: 48 }
})

const src = computed(() => iconSrc(props.name, props.color))
const sizeStyle = computed(() => {
  const s = typeof props.size === 'number' ? props.size + 'rpx' : props.size
  return { width: s, height: s }
})
</script>

<style scoped>
.bl-icon { display: block; flex: none; }
</style>