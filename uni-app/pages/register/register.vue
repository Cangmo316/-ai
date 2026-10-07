<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar title="注册" back solid @back="back" />

    <scroll-view class="bl-body" scroll-y>
      <!-- 品牌区：与登录页完全同一套结构，切换时不会"跳" -->
      <view class="bl-auth__brand">
        <view class="bl-auth__seal">
          <image class="bl-auth__seal-img" :src="brandSrc" mode="aspectFit" />
        </view>
        <text class="bl-auth__brand-name">比邻AI</text>
        <text class="bl-auth__brand-sub">天涯若比邻</text>
      </view>

      <!-- 第一栏：账号名称 -->
      <view class="bl-field">
        <text class="bl-field__label">账号名称</text>
        <view class="bl-field__box" :class="{ 'is-error': errors.account }">
          <input
            v-model="account"
            class="bl-field__input"
            type="text"
            :maxlength="20"
            placeholder="请输入账号名称"
            placeholder-class="bl-input-ph"
            confirm-type="next"
          />
        </view>
        <text v-if="errors.account" class="bl-field__err">{{ errors.account }}</text>
      </view>

      <!-- 第二栏：密码（8–16 位数字或字母）-->
      <view class="bl-field">
        <text class="bl-field__label">密码</text>
        <text class="bl-field__hint">{{ ruleText }}</text>
        <view class="bl-field__box" :class="{ 'is-error': errors.password }">
          <input
            v-model="password"
            class="bl-field__input"
            :password="!showPassword"
            :maxlength="16"
            placeholder="请输入密码"
            placeholder-class="bl-input-ph"
            confirm-type="next"
          />
          <view
            class="bl-field__eye"
            role="button"
            :aria-label="showPassword ? '隐藏密码' : '显示密码'"
            @click="showPassword = !showPassword"
          >
            <bl-icon :name="showPassword ? 'eye' : 'eyeoff'" color="#6E6A5E" :size="44" />
          </view>
        </view>
        <text v-if="errors.password" class="bl-field__err">{{ errors.password }}</text>
      </view>

      <!-- 第三栏：再次输入密码确认 -->
      <view class="bl-field">
        <text class="bl-field__label">请再次输入密码确认</text>
        <view class="bl-field__box" :class="{ 'is-error': errors.confirm }">
          <input
            v-model="confirm"
            class="bl-field__input"
            :password="!showConfirm"
            :maxlength="16"
            placeholder="请再次输入密码"
            placeholder-class="bl-input-ph"
            confirm-type="done"
            @confirm="submit"
          />
          <view
            class="bl-field__eye"
            role="button"
            :aria-label="showConfirm ? '隐藏密码' : '显示密码'"
            @click="showConfirm = !showConfirm"
          >
            <bl-icon :name="showConfirm ? 'eye' : 'eyeoff'" color="#6E6A5E" :size="44" />
          </view>
        </view>
        <text v-if="errors.confirm" class="bl-field__err">{{ errors.confirm }}</text>
      </view>

      <!-- 墨黑可点入口：回登录页 -->
      <view class="bl-auth__links">
        <text class="bl-auth__link" role="button" @click="back">已有账号？返回登录</text>
      </view>

      <view class="bl-auth__submit">
        <view
          class="bl-btn bl-btn--primary bl-btn--block"
          :class="{ 'is-busy': submitting }"
          role="button"
          :aria-label="submitting ? '正在注册' : '注册'"
          @click="submit"
        >
          <text class="bl-btn__text">{{ submitting ? '正在注册…' : '注册' }}</text>
        </view>
      </view>
    </scroll-view>
  </view>
</template>

<script setup>
/**
 * 注册页。
 *
 * 栏目分布与登录页一致（品牌区 → 输入栏 → 墨黑可点入口 → 主按钮），
 * 只多一栏「请再次输入密码确认」。
 *
 * 密码规则（按需求）：**8–16 位，只能是数字或字母**。
 * 规则同时写在输入框上方的提示里和校验错误里——老人不该靠猜。
 *
 * 注意：本页的 <style> 与 pages/auth/auth.vue 是同一套（刻意重复）。
 * 两页的视觉必须完全一致，改样式时**两处都要改**。
 */
import { computed, reactive, ref } from 'vue'
import { settings } from '@/common/store.js'
import { tokens } from '@/common/tokens.js'
import { INK_BRAND, iconSrcOf } from '@/common/icons.js'
import { PASSWORD_RULE_TEXT, passwordProblem } from '@/common/password.js'
import { signUp } from '@/stores/account.js'

const brandSrc = computed(() => iconSrcOf(INK_BRAND, tokens.color.primary, 32))

const account = ref('')
const password = ref('')
const confirm = ref('')
const showPassword = ref(false)
const showConfirm = ref(false)
const errors = reactive({ account: '', password: '', confirm: '' })
/** 规则提示文字：和校验逻辑同源，不会写歪 */
const ruleText = PASSWORD_RULE_TEXT
/** 正在请求：防连点 */
const submitting = ref(false)

function clearErrors() {
  errors.account = ''
  errors.password = ''
  errors.confirm = ''
}

function submit() {
  if (submitting.value) return
  clearErrors()
  const name = account.value.trim()
  if (!name) {
    errors.account = '请输入账号名称'
    return
  }
  const pwProblem = passwordProblem(password.value)
  if (pwProblem) {
    errors.password = pwProblem
    return
  }
  if (!confirm.value) {
    errors.confirm = '请再次输入密码'
    return
  }
  if (confirm.value !== password.value) {
    errors.confirm = '两次输入的密码不一样，请重新输入'
    return
  }

  // 真实调用服务端：成功后拿到 8 位编号，直接就是登录态
  submitting.value = true
  signUp(name, password.value, confirm.value)
    .then((result) => {
      submitting.value = false
      if (!result.ok) {
        // 服务端会告诉我们是重名还是密码不合规，按文案落在对应栏下
        const message = result.message || '注册失败，再试一次'
        if (message.indexOf('账号名称') !== -1) errors.account = message
        else errors.password = message
        return
      }
      const number = (result.account && result.account.number) || ''
      uni.showToast({ title: '注册成功 · ID ' + number, icon: 'none' })
      setTimeout(() => {
        uni.reLaunch({ url: '/pages/me/me' })
      }, 1000)
    })
    .catch(() => {
      submitting.value = false
      errors.password = '出了点问题，再试一次'
    })
}

function back() {
  const pages = getCurrentPages()
  if (pages.length > 1) uni.navigateBack()
  else uni.reLaunch({ url: '/pages/auth/auth' })
}
</script>

<style scoped>
/* ---------------- 品牌区 ---------------- */
.bl-auth__brand {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 56rpx 0 24rpx;
}
.bl-auth__seal {
  width: 152rpx;
  height: 152rpx;
  border-radius: 50%;
  background-color: var(--bl-surface);
  border: 1rpx solid var(--bl-border);
  box-shadow: var(--bl-shadow-card);
  display: flex;
  align-items: center;
  justify-content: center;
}
.bl-auth__seal-img { width: 96rpx; height: 96rpx; }
.bl-auth__brand-name {
  margin-top: 28rpx;
  font-size: var(--bl-font-title);
  font-weight: 700;
  letter-spacing: 4rpx;
  color: var(--bl-text);
}
.bl-auth__brand-sub {
  margin-top: 8rpx;
  font-size: var(--bl-font-caption);
  letter-spacing: 4rpx;
  color: var(--bl-text-2);
}

/* ---------------- 输入栏 ---------------- */
.bl-field { padding: 0 var(--bl-space-lg); }
.bl-field:first-of-type { margin-top: 32rpx; }
.bl-field + .bl-field { margin-top: 32rpx; }

.bl-field__label {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  letter-spacing: .04em;
  margin-bottom: var(--bl-space-sm);
}
/* 规则提示：放在标签和输入框之间，填之前就能看到 */
.bl-field__hint {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-primary);
  line-height: 1.4;
  margin: -4rpx 0 var(--bl-space-sm);
}

.bl-field__box {
  display: flex;
  align-items: center;
  gap: 12rpx;
  padding: 0 var(--bl-space-md);
  min-height: 104rpx;
  background-color: var(--bl-surface);
  border: 2rpx solid var(--bl-border-strong);
  border-radius: var(--bl-radius-bubble);
  box-sizing: border-box;
}
.bl-field__box:focus-within { border-color: var(--bl-primary); }
.bl-field__box.is-error { border-color: var(--bl-danger); }

.bl-field__input {
  flex: 1;
  min-width: 0;
  height: 100rpx;
  font-size: var(--bl-font-body);
  color: var(--bl-text);
}

/* 显隐密码：48×48 触控区。
   flex:none 是必须的 —— 否则在 flex 行里会被压扁（实测只剩 52×19px）。 */
.bl-field__eye {
  flex: none;
  width: var(--bl-touch);
  height: var(--bl-touch);
  min-width: var(--bl-touch);
  align-self: center;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
}
.bl-field__eye:active { background-color: var(--bl-primary-soft); }

.bl-field__err {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-danger);
  line-height: 1.4;
  margin-top: 10rpx;
}

/* ---------------- 墨黑可点入口 ---------------- */
.bl-auth__links {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--bl-space-md);
  padding: var(--bl-space-lg) var(--bl-space-lg) 0;
}
.bl-auth__link {
  display: flex;
  align-items: center;
  min-height: var(--bl-touch);
  font-size: var(--bl-font-body);
  font-weight: 600;
  color: var(--bl-text);
  line-height: 1.3;
  padding: 0 var(--bl-space-xs);
  text-decoration: underline;
  text-underline-offset: 6rpx;
}
.bl-auth__link:active { color: var(--bl-primary); }

.bl-auth__submit { padding: var(--bl-space-xl) var(--bl-space-lg) var(--bl-space-xxl); }
.bl-auth__submit .is-busy { opacity: .7; }
</style>
