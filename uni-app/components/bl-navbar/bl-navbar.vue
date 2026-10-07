<template>
  <view class="bl-navbar" :class="{ 'is-solid': solid }">
    <!-- 状态栏让位高度由 JS 实测给出（App 端 env() 不可靠，见样式注释） -->
    <view class="bl-navbar__safe" :style="{ height: safeTop + 'px' }" />
    <view class="bl-navbar__bar">
      <!-- 左侧：返回按钮，或（无返回时）自定义内容插槽 -->
      <view v-if="back" class="bl-navbar__btn" role="button" aria-label="返回" @click="$emit('back')">
        <bl-icon name="back" :color="iconColor" :size="48" />
      </view>
      <view v-else-if="$slots.left" class="bl-navbar__left">
        <slot name="left" />
      </view>

      <!-- 中间：标题（有插槽时由使用方决定是否给 title） -->
      <view class="bl-navbar__titlebox">
        <!-- 品牌印记：比邻印章（两笔交叉）。仅在 title 左侧出现一次，不做重复装饰。 -->
        <image
          v-if="brand"
          class="bl-navbar__brand"
          :src="brandSrc"
          mode="aspectFit"
        />
        <text v-if="title" class="bl-navbar__title">{{ title }}</text>
      </view>

      <!-- 右侧：动作图标 -->
      <view
        v-if="action"
        class="bl-navbar__btn bl-navbar__btn--right"
        role="button"
        :aria-label="actionLabel"
        @click="$emit('action')"
      >
        <bl-icon :name="action" :color="actionColor" :size="48" />
      </view>
    </view>
  </view>
</template>

<script setup>
/**
 * 自定义导航栏。
 *
 * 支持两种排布：
 *   · 有 back：左返回 + 中标题 + 右动作（常规二级页）
 *   · 无 back 且有 left 插槽：左侧放任意内容（如「阳历 + 阴历」两行日期），右侧动作图标
 * 中间标题为空时自动不渲染，避免出现空占位。
 */
import { computed, onMounted, ref } from 'vue'
import { tokens } from '@/common/tokens.js'
import { INK_BRAND, iconSrcOf } from '@/common/icons.js'
import { topGap } from '@/common/safe-area.js'

/**
 * 顶部让位高度（px）。
 * 为什么不用纯 CSS 的 `env(safe-area-inset-top)`：见 common/safe-area.js 的注释
 * （App 端该变量返回 0，标题会顶到状态栏、挖孔屏上被摄像头压住）。
 */
const safeTop = ref(topGap())
onMounted(() => { safeTop.value = topGap() })

const props = defineProps({
  title: { type: String, default: '' },
  back: { type: Boolean, default: false },
  /** 右侧动作图标名；留空则不渲染 */
  action: { type: String, default: '' },
  actionColor: { type: String, default: tokens.color.primary },
  /** 右侧动作的无障碍名称（图标按钮必须有） */
  actionLabel: { type: String, default: '打开' },
  solid: { type: Boolean, default: false },
  /** 在标题左侧显示比邻印章（仅首页用） */
  brand: { type: Boolean, default: false }
})

defineEmits(['back', 'action'])

const iconColor = computed(() => tokens.color.text)
const brandSrc = computed(() => iconSrcOf(INK_BRAND, tokens.color.primary, 32))
</script>

<style scoped>
.bl-navbar { flex: none; background-color: transparent; }
.bl-navbar.is-solid {
  background-color: var(--bl-surface);
  border-bottom: 1rpx solid var(--bl-divider);
}
/* 刘海/状态栏让位。
 *
 * ⚠️ 只用 `env(safe-area-inset-top)` **在 App 端会失效**：uni-app 的 WebView
 *    默认不是 edge-to-edge，这个变量返回 0，于是标题直接顶到状态栏、
 *    在挖孔屏上被摄像头挡住，返回键也难点。
 *    所以高度由 JS 实测（`uni.getSystemInfoSync().statusBarHeight`）后
 *    以内联样式给出来，CSS 只做兜底。
 *    额外再加一点留白（EXTRA_TOP），需求明确要求"不要顶到屏幕顶端"。 */
.bl-navbar__safe {
  height: calc(env(safe-area-inset-top) + 20px);
}
.bl-navbar__bar {
  min-height: 92rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  padding: 0 var(--bl-space-lg);
  box-sizing: border-box;
}

/* 左侧插槽区：不再是绝对定位的圆按钮，而是参与布局的内容块 */
.bl-navbar__left {
  position: absolute;
  left: var(--bl-space-lg);
  top: 50%;
  transform: translateY(-50%);
  max-width: 60%;
}

.bl-navbar__titlebox {
  display: flex;
  align-items: center;
  gap: 12rpx;
  max-width: 70%;
}
.bl-navbar__brand {
  width: 52rpx;
  height: 52rpx;
  flex: none;
}
.bl-navbar__title {
  font-size: var(--bl-font-title);
  font-weight: 700;
  color: var(--bl-text);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  letter-spacing: .01em;
}
/* 动作/返回按钮：96rpx 保证触控 ≥48px */
.bl-navbar__btn {
  position: absolute;
  left: 12rpx;
  top: 50%;
  transform: translateY(-50%);
  width: 96rpx;
  height: 96rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
}
.bl-navbar__btn--right { left: auto; right: 12rpx; }
/* 按下反馈用色，不用半透明黑（在宣纸底上会发灰） */
.bl-navbar__btn:active { background-color: var(--bl-primary-soft); }
</style>
