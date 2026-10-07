<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar title="智能体角色" back solid @back="back" />

    <scroll-view class="bl-body" scroll-y>
      <view class="bl-roles__head">
        <text class="bl-roles__sub">选一个角色陪你说话</text>
      </view>

      <!-- 角色列表：内置的「比邻AI」永远在最前 -->
      <view class="bl-ra-list">
        <view
          v-for="r in roles"
          :key="r.id"
          class="bl-ra"
          :class="{ 'is-on': currentId === r.id }"
          role="button"
          :aria-label="r.name + '，' + r.desc"
          @click="pick(r)"
          @longpress="confirmRemove(r)"
        >
          <view class="bl-ra__avatar" :style="{ backgroundColor: r.avatarColor }">
            <text class="bl-ra__initial">{{ r.name.slice(0, 1) }}</text>
          </view>

          <view class="bl-ra__main">
            <view class="bl-ra__title-row">
              <text class="bl-ra__name">{{ r.name }}</text>
              <text v-if="r.builtin" class="bl-ra__tag">默认</text>
            </view>
            <text class="bl-ra__desc">{{ r.desc }}</text>
          </view>

          <view class="bl-ra__check" :class="{ 'is-on': currentId === r.id }">
            <bl-icon v-if="currentId === r.id" name="check" color="#FFFFFF" :size="34" />
          </view>
        </view>

        <!-- 添加新角色：放在列表末尾，形状与角色卡一致 -->
        <view
          class="bl-ra bl-ra--add"
          role="button"
          aria-label="添加新角色"
          @click="toCreate"
        >
          <view class="bl-ra__avatar bl-ra__avatar--add">
            <bl-icon name="plus" color="#2F5D4E" :size="52" />
          </view>
          <view class="bl-ra__main">
            <text class="bl-ra__name bl-ra__name--add">添加新角色</text>
            <text class="bl-ra__desc">按你的想法，造一个熟悉的人</text>
          </view>
          <bl-icon name="chev" color="#B9B3A4" :size="34" />
        </view>
      </view>

      <view class="bl-roles__hint">
        <text class="bl-roles__hint-text">按住自己创建的角色不放，可以删除</text>
      </view>

      <view class="bl-page-footer">
        <view class="bl-btn bl-btn--primary bl-btn--block" role="button" @click="startChat">
          <text class="bl-page-footer__text bl-page-footer__text--on">用这个角色开始聊天</text>
        </view>
      </view>
    </scroll-view>
  </view>
</template>

<script setup>
/**
 * 智能体角色列表。
 *
 * 按需求：默认只有「比邻AI」；下方是「添加新角色」，点进创建页。
 *
 * 角色数据放在页面自己的 ref 里（listRoles() 返回副本），
 * 不在模板里直接引用 store 的模块绑定——原因见 stores/roles.js 顶部说明。
 */
import { onMounted, onUnmounted, ref } from 'vue'
import { settings, setRole } from '@/common/store.js'
import { EVENT_ROLES_CHANGED, listRoles, removeRole } from '@/stores/roles.js'

const roles = ref(listRoles())
/** 当前选中的角色 id：跟着 settings.role（存的是角色名）走 */
const currentId = ref(resolveCurrentId())

function resolveCurrentId() {
  const match = roles.value.find((r) => r.name === settings.role)
  return match ? match.id : 'p_bilin'
}

function refresh() {
  roles.value = listRoles()
  currentId.value = resolveCurrentId()
}

function pick(r) {
  setRole(r.name)
  currentId.value = r.id
  uni.showToast({ title: '已选择：' + r.name, icon: 'none' })
}

function toCreate() {
  uni.navigateTo({ url: '/pages/role-new/role-new' })
}

/** 删除：只有自定义角色能删，且要二次确认（内置角色删了老人就没得聊了） */
function confirmRemove(r) {
  if (r.builtin) {
    uni.showToast({ title: '「比邻AI」是默认角色，删不掉', icon: 'none' })
    return
  }
  uni.showModal({
    title: '删除这个角色？',
    content: r.name + '（' + r.relation + '）',
    confirmText: '删除',
    cancelText: '再想想',
    success(res) {
      if (!res.confirm) return
      const result = removeRole(r.id)
      if (!result.ok) {
        uni.showToast({ title: result.reason || '删不掉', icon: 'none' })
        return
      }
      // 删掉的正是当前选中的 → 退回默认角色
      if (currentId.value === r.id) {
        setRole('比邻AI')
      }
      refresh()
      uni.showToast({ title: '已删除', icon: 'none' })
    }
  })
}

function startChat() {
  uni.reLaunch({ url: '/pages/chats/chats' })
}

function back() {
  const pages = getCurrentPages()
  if (pages.length > 1) uni.navigateBack()
  else uni.reLaunch({ url: '/pages/me/me' })
}

// 从创建页返回时刷新列表。
// 为什么用事件而不是 onShow：本项目所有页面都没依赖 @dcloudio/uni-app 的页面钩子
// （该包只在 HBuilderX 插件目录里，不在项目依赖中），用 uni.$on 更稳且全项目一致。
onMounted(() => {
  uni.$on(EVENT_ROLES_CHANGED, refresh)
})
onUnmounted(() => {
  uni.$off(EVENT_ROLES_CHANGED, refresh)
})
</script>

<style scoped>
.bl-roles__head { padding: 32rpx var(--bl-space-lg) 0; }
.bl-roles__sub {
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
}

.bl-ra-list {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
  padding: var(--bl-space-md) var(--bl-space-lg) 0;
}

.bl-ra {
  display: flex;
  align-items: center;
  gap: 24rpx;
  padding: 28rpx 32rpx;
  min-height: 152rpx;
  background-color: var(--bl-surface);
  border: 4rpx solid transparent;
  border-radius: var(--bl-radius-card);
  box-shadow: var(--bl-shadow-card);
  box-sizing: border-box;
}
.bl-ra.is-on {
  border-color: var(--bl-primary);
  background-color: var(--bl-surface-2);
}
.bl-ra:active { background-color: var(--bl-surface-2); }

.bl-ra__avatar {
  width: 108rpx;
  height: 108rpx;
  flex: none;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}
.bl-ra__initial {
  font-size: 44rpx;
  font-weight: 700;
  color: #FFFDF8;
  line-height: 1;
}

.bl-ra__main { flex: 1; min-width: 0; }
.bl-ra__title-row {
  display: flex;
  align-items: center;
  gap: 12rpx;
}
.bl-ra__name {
  font-size: var(--bl-font-title);
  font-weight: 700;
  color: var(--bl-text);
  line-height: 1.25;
}
/* 「默认」标记：让老人知道这个不能删、也是没得选时的兜底 */
.bl-ra__tag {
  flex: none;
  font-size: 22rpx;
  color: var(--bl-primary);
  background-color: var(--bl-primary-soft);
  border-radius: 999rpx;
  padding: 2rpx 14rpx;
  line-height: 1.6;
}
.bl-ra__desc {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  margin-top: 8rpx;
  line-height: 1.4;
}

.bl-ra__check {
  flex: none;
  width: 60rpx;
  height: 60rpx;
  border-radius: 50%;
  border: 4rpx solid var(--bl-divider);
  box-sizing: border-box;
  display: flex;
  align-items: center;
  justify-content: center;
}
.bl-ra__check.is-on {
  border-color: var(--bl-primary);
  background-color: var(--bl-primary);
}

/* 添加卡：虚线圈 + 主色加号，和角色卡区分但同一形状 */
.bl-ra--add { border: 4rpx dashed var(--bl-border-strong); }
.bl-ra__avatar--add {
  background-color: var(--bl-primary-soft);
  border: 2rpx dashed var(--bl-primary);
  box-sizing: border-box;
}
.bl-ra__name--add { color: var(--bl-primary); }

.bl-roles__hint { padding: var(--bl-space-sm) var(--bl-space-lg) 0; }
.bl-roles__hint-text {
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
}
</style>
