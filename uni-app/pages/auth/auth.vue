<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar title="登录" back solid @back="back" />

    <scroll-view class="bl-body" scroll-y>
      <!-- 品牌区：和启动页同一套墨印语言，第一眼知道还在比邻 -->
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

      <!-- 第二栏：密码 -->
      <view class="bl-field">
        <text class="bl-field__label">密码</text>
        <view class="bl-field__box" :class="{ 'is-error': errors.password }">
          <input
            v-model="password"
            class="bl-field__input"
            :password="!showPassword"
            :maxlength="32"
            placeholder="请输入密码"
            placeholder-class="bl-input-ph"
            confirm-type="done"
            @confirm="submit"
          />
          <!-- 显隐按钮：48px 触控区，老人不用瞄准 -->
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

      <!-- 两个可点入口：墨黑字 -->
      <view class="bl-auth__links">
        <text class="bl-auth__link" role="button" @click="forgot">忘记密码?</text>
        <text class="bl-auth__link" role="button" @click="toRegister">没有账号请点击注册</text>
      </view>

      <view class="bl-auth__submit">
        <view
          class="bl-btn bl-btn--primary bl-btn--block"
          :class="{ 'is-busy': submitting }"
          role="button"
          :aria-label="submitting ? '正在登录' : '登录'"
          @click="submit"
        >
          <text class="bl-btn__text">{{ submitting ? '正在登录…' : '登录' }}</text>
        </view>
      </view>
    </scroll-view>
  </view>
</template>

<script setup>
/**
 * 登录 / 注册入口页。
 *
 * 布局按需求：第一栏账号名称，第二栏密码，下方两个墨黑可点文字
 * （「忘记密码?」与「没有账号请点击注册」）。
 *
 * 适老化取舍：
 * - 输入框高 104rpx（52px），显隐按钮 48px，都是明确的触控目标
 * - 标签在输入框**上方**而不是占位符里：老人填到一半时占位符会消失，标签会跟着丢
 * - 出错时框变红并给出具体一句话，而不是只把边框变红
 */
import { computed, reactive, ref } from 'vue'
import { settings } from '@/common/store.js'
import { tokens } from '@/common/tokens.js'
import { INK_BRAND, iconSrcOf } from '@/common/icons.js'
import { signIn } from '@/stores/account.js'

const brandSrc = computed(() => iconSrcOf(INK_BRAND, tokens.color.primary, 32))

const account = ref('')
const password = ref('')
const showPassword = ref(false)
const errors = reactive({ account: '', password: '' })
/** 正在请求：防止老人连点两次，也给他一个"在忙"的反馈 */
const submitting = ref(false)

function clearErrors() {
  errors.account = ''
  errors.password = ''
}

/** 登录：真实调用服务端 /v1/accounts/login */
function submit() {
  if (submitting.value) return
  clearErrors()
  const name = account.value.trim()
  if (!name) {
    errors.account = '请输入账号名称'
    return
  }
  if (!password.value) {
    errors.password = '请输入密码'
    return
  }

  submitting.value = true
  signIn(name, password.value)
    .then((result) => {
      submitting.value = false
      if (!result.ok) {
        // 服务端刻意不区分"账号不存在"和"密码错"，所以统一挂在密码栏下方
        errors.password = result.message || '账号或密码不对，再试一次'
        return
      }
      const number = (result.account && result.account.number) || ''
      uni.showToast({ title: '登录成功 · ID ' + number, icon: 'none' })
      // 回「我的」页：那里显示头像、名字和编号
      setTimeout(() => {
        uni.reLaunch({ url: '/pages/me/me' })
      }, 900)
    })
    .catch(() => {
      submitting.value = false
      errors.password = '出了点问题，再试一次'
    })
}

function forgot() {
  uni.showToast({ title: '请联系家人帮你找回密码', icon: 'none' })
}

/** 去注册页。用 redirectTo：登录和注册是同一件事的两个面，
    不该在返回栈里越堆越多（否则老人按返回要按好几次） */
function toRegister() {
  uni.redirectTo({ url: '/pages/register/register' })
}

function back() {
  const pages = getCurrentPages()
  if (pages.length > 1) uni.navigateBack()
  else uni.reLaunch({ url: '/pages/me/me' })
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
/* 规则提示：与注册页同一处样式（两页保持一致） */
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
/* 聚焦/出错：边框加重，老人能看出"我在这一栏" */
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
   flex:none 是必须的 —— 否则在 flex 行里会被压扁（实测只剩 52×19px），
   老人根本点不到。 */
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

/* ---------------- 两个可点入口（墨黑字）---------------- */
.bl-auth__links {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--bl-space-md);
  padding: var(--bl-space-lg) var(--bl-space-lg) 0;
}
.bl-auth__link {
  /* 墨黑正文级字号：老人看得清。
     上下内边距按 48px 触控下限给足 —— 实测只给 sm 时热区仅 38px，点不准。 */
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
/* 请求中：降低不透明度，让老人看出"已经点了、在等" */
.bl-auth__submit .is-busy { opacity: .7; }
</style>
