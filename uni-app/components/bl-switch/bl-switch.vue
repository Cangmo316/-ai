<template>
  <switch
    class="bl-switch"
    :checked="checked"
    :color="tokens.color.primary"
    @change="onChange"
  />
</template>

<script setup>
import { tokens } from '@/common/tokens.js'

const props = defineProps({
  checked: { type: Boolean, default: false }
})
const emit = defineEmits(['update:checked', 'change'])

function onChange(e) {
  const v = e.detail.value
  emit('update:checked', v)
  emit('change', v)
}
</script>

<style scoped>
/* 适老化：把原生开关放大，方便老人点按 */
.bl-switch { transform: scale(1.15); transform-origin: right center; }
</style>