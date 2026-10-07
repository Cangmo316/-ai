<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar title="创建新角色" back solid @back="back" />

    <scroll-view class="bl-body" scroll-y>
      <view class="bl-new__intro">
        <text class="bl-new__intro-text">回答下面几个问题，它就会像那个人一样跟你说话</text>
      </view>

      <!-- 1 你想叫我什么 -->
      <view class="bl-f">
        <text class="bl-f__label">1. 你想叫我什么</text>
        <text class="bl-f__hint">它以后就这么称呼你</text>
        <view class="bl-f__box" :class="{ 'is-error': errors.callMe }">
          <input
            v-model="form.callMe"
            class="bl-f__input"
            :maxlength="12"
            placeholder="比如：老李、张阿姨、妈"
            placeholder-class="bl-input-ph"
          />
        </view>
        <text v-if="errors.callMe" class="bl-f__err">{{ errors.callMe }}</text>
      </view>

      <!-- 2 我们是什么关系 -->
      <view class="bl-f">
        <text class="bl-f__label">2. 我们是什么关系</text>
        <view class="bl-f__box" :class="{ 'is-error': errors.relation }">
          <input
            v-model="form.relation"
            class="bl-f__input"
            :maxlength="16"
            placeholder="比如：儿子、老邻居、棋友"
            placeholder-class="bl-input-ph"
          />
        </view>
        <text v-if="errors.relation" class="bl-f__err">{{ errors.relation }}</text>
      </view>

      <!-- 3 我们之间的故事 -->
      <view class="bl-f">
        <text class="bl-f__label">3. 我们之间的故事</text>
        <text class="bl-f__hint">写点你们之间的事，它会更懂怎么跟你聊</text>
        <view class="bl-f__box bl-f__box--area">
          <textarea
            v-model="form.story"
            class="bl-f__area"
            :maxlength="120"
            placeholder="比如：我们在公园下棋认识十几年了"
            placeholder-class="bl-input-ph"
            auto-height
          />
        </view>
      </view>

      <!-- 4 我是一个什么样的人 -->
      <view class="bl-f">
        <text class="bl-f__label">4. 我是一个什么样的人</text>
        <view class="bl-f__box bl-f__box--area">
          <textarea
            v-model="form.persona"
            class="bl-f__area"
            :maxlength="120"
            placeholder="比如：爱热闹、爱下棋、血压有点高"
            placeholder-class="bl-input-ph"
            auto-height
          />
        </view>
      </view>

      <!-- 5 我平时多久给你发一次消息 -->
      <view class="bl-f">
        <text class="bl-f__label">5. 我平时多久给你发一次消息</text>
        <view class="bl-f__chips">
          <view
            v-for="opt in FREQUENCIES"
            :key="opt"
            class="bl-f__chip"
            :class="{ 'is-on': form.frequency === opt }"
            role="button"
            :aria-label="opt"
            :aria-pressed="form.frequency === opt ? 'true' : 'false'"
            @click="form.frequency = opt"
          >
            <text class="bl-f__chip-text">{{ opt }}</text>
          </view>
        </view>
        <text v-if="errors.frequency" class="bl-f__err">{{ errors.frequency }}</text>
      </view>

      <!-- 6 是否绑定家人 -->
      <view class="bl-f">
        <view class="bl-f__row">
          <view class="bl-f__row-main">
            <text class="bl-f__label bl-f__label--inline">6. 是否绑定家人</text>
            <text class="bl-f__hint bl-f__hint--inline">绑上以后，它能替你给家里人捎话</text>
          </view>
          <bl-switch :checked="form.bindFamily" @change="onBindChange" />
        </view>

        <!-- 开关打开才出现的「请输入家人ID」 -->
        <view v-if="form.bindFamily" class="bl-f__family">
          <text class="bl-f__label">请输入家人ID</text>
          <view class="bl-f__box" :class="{ 'is-error': errors.familyNumber }">
            <input
              v-model="form.familyNumber"
              class="bl-f__input"
              type="number"
              :maxlength="8"
              placeholder="8 位数字，比如 00000000"
              placeholder-class="bl-input-ph"
              @blur="checkFamily"
            />
            <view class="bl-f__verify" role="button" aria-label="查找家人" @click="checkFamily">
              <text class="bl-f__verify-text">查找</text>
            </view>
          </view>
          <!-- 查到了就明确告诉老人绑的是谁，填错一位也能立刻发现 -->
          <text v-if="familyState.found" class="bl-f__ok">
            已找到：{{ familyState.name }}（ID:{{ form.familyNumber }}）
          </text>
          <text v-else-if="familyState.checked && form.familyNumber" class="bl-f__err">
            没找到这个编号，核对一下再填
          </text>
          <text v-if="errors.familyNumber" class="bl-f__err">{{ errors.familyNumber }}</text>
        </view>
      </view>

      <view class="bl-new__submit">
        <view
          class="bl-btn bl-btn--primary bl-btn--block"
          :class="{ 'is-busy': saving }"
          role="button"
          aria-label="保存角色"
          @click="save"
        >
          <text class="bl-btn__text">{{ saving ? '正在保存…' : '保存这个角色' }}</text>
        </view>
      </view>
    </scroll-view>
  </view>
</template>

<script setup>
/**
 * 创建新角色。
 *
 * 六个栏目按需求顺序排列（见 stores/roles.js 的 ROLE_FIELDS 定义）：
 *   1 你想叫我什么  2 我们是什么关系  3 我们之间的故事
 *   4 我是一个什么样的人  5 我平时多久给你发一次消息  6 是否绑定家人
 *
 * 第 6 栏是开关，打开后才出现「请输入家人ID」——并且填完能**当场查证**，
 * 免得老人把编号填错一位却以为绑上了。
 */
import { computed, reactive, ref } from 'vue'
import { settings } from '@/common/store.js'
import { addRole } from '@/stores/roles.js'
import { isLoggedIn, readAccount } from '@/stores/account.js'
import { lookupAccount } from '@/api/index.js'

/** 第 5 栏的选项（与 store 保持一致，改这里也要改 store 的 ROLE_FIELDS） */
const FREQUENCIES = ['每天', '隔两三天', '每周', '想起来就发', '很少发']

const form = reactive({
  callMe: '',
  relation: '',
  story: '',
  persona: '',
  frequency: '',
  bindFamily: false,
  familyNumber: '',
  familyName: ''
})

const errors = reactive({
  callMe: '',
  relation: '',
  frequency: '',
  familyNumber: ''
})

const saving = ref(false)
/** 家人编号的查证状态：found=查到了，checked=查过了（用来区分"没查"和"查了没有"） */
const familyState = reactive({ found: false, checked: false, name: '' })

/** 自己不能绑自己，顺手挡一下 */
const myNumber = computed(() => {
  const account = readAccount()
  return (account && account.number) || ''
})

function clearErrors() {
  errors.callMe = ''
  errors.relation = ''
  errors.frequency = ''
  errors.familyNumber = ''
}

function onBindChange(value) {
  form.bindFamily = value
  if (!value) {
    // 关掉开关就清干净，避免"关了却还存着编号"这种半吊子状态
    form.familyNumber = ''
    form.familyName = ''
    familyState.found = false
    familyState.checked = false
    errors.familyNumber = ''
  }
}

/** 查这个编号是谁（填错一位能立刻发现） */
function checkFamily() {
  const number = String(form.familyNumber || '').trim()
  familyState.found = false
  familyState.checked = false
  familyState.name = ''
  form.familyName = ''

  if (!number) return
  if (!/^\d{8}$/.test(number)) {
    errors.familyNumber = '家人ID 是 8 位数字'
    return
  }
  errors.familyNumber = ''
  if (myNumber.value && number === myNumber.value) {
    errors.familyNumber = '这是你自己的ID，换一个'
    return
  }

  lookupAccount(number)
    .then((data) => {
      familyState.checked = true
      if (data && data.found && data.account) {
        familyState.found = true
        familyState.name = data.account.name
        form.familyName = data.account.name
      }
    })
    .catch((error) => {
      familyState.checked = true
      errors.familyNumber = (error && error.message) || '查不到，稍后再试'
    })
}

function save() {
  if (saving.value) return
  clearErrors()

  const result = addRole({
    callMe: form.callMe,
    relation: form.relation,
    story: form.story,
    persona: form.persona,
    frequency: form.frequency,
    bindFamily: form.bindFamily,
    familyNumber: form.familyNumber,
    familyName: form.familyName
  })

  if (!result.ok) {
    const field = result.field || 'callMe'
    if (errors[field] !== undefined) errors[field] = result.reason
    uni.showToast({ title: result.reason, icon: 'none' })
    return
  }

  saving.value = true
  uni.showToast({ title: '角色已创建', icon: 'none' })
  setTimeout(() => {
    saving.value = false
    back()
  }, 900)
}

function back() {
  const pages = getCurrentPages()
  if (pages.length > 1) uni.navigateBack()
  else uni.reLaunch({ url: '/pages/roles/roles' })
}
</script>

<style scoped>
.bl-new__intro { padding: 32rpx var(--bl-space-lg) 0; }
.bl-new__intro-text {
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  line-height: 1.5;
}

/* ---------------- 栏目 ---------------- */
.bl-f { padding: 32rpx var(--bl-space-lg) 0; }

.bl-f__label {
  display: block;
  font-size: var(--bl-font-body);
  font-weight: 600;
  color: var(--bl-text);
  line-height: 1.4;
  margin-bottom: var(--bl-space-sm);
}
.bl-f__label--inline { margin-bottom: 4rpx; }

.bl-f__hint {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  line-height: 1.4;
  margin: -4rpx 0 var(--bl-space-sm);
}
.bl-f__hint--inline { margin: 0; }

.bl-f__box {
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
.bl-f__box:focus-within { border-color: var(--bl-primary); }
.bl-f__box.is-error { border-color: var(--bl-danger); }
/* 多行：上下留白，不要固定高度 */
.bl-f__box--area {
  align-items: stretch;
  padding: var(--bl-space-sm) var(--bl-space-md);
  min-height: 140rpx;
}

.bl-f__input {
  flex: 1;
  min-width: 0;
  height: 100rpx;
  font-size: var(--bl-font-body);
  color: var(--bl-text);
}
.bl-f__area {
  width: 100%;
  min-height: 100rpx;
  font-size: var(--bl-font-body);
  color: var(--bl-text);
  line-height: 1.5;
}

.bl-f__err {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-danger);
  line-height: 1.4;
  margin-top: 10rpx;
}
.bl-f__ok {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-success);
  line-height: 1.4;
  margin-top: 10rpx;
}

/* 第 5 栏：一排选项，共边保证每格够宽 */
.bl-f__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 16rpx;
}
.bl-f__chip {
  min-height: var(--bl-touch);
  padding: 0 28rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: var(--bl-surface);
  border: 2rpx solid var(--bl-border-strong);
  border-radius: 999rpx;
  box-sizing: border-box;
}
.bl-f__chip-text {
  font-size: var(--bl-font-body);
  font-weight: 600;
  color: var(--bl-text);
  line-height: 1;
}
.bl-f__chip.is-on {
  background-color: var(--bl-text);
  border-color: var(--bl-text);
}
.bl-f__chip.is-on .bl-f__chip-text { color: #FFFDF8; }
.bl-f__chip:active { opacity: .85; }

/* 第 6 栏 */
.bl-f__row {
  display: flex;
  align-items: center;
  gap: var(--bl-space-md);
}
.bl-f__row-main { flex: 1; min-width: 0; }

.bl-f__family {
  margin-top: var(--bl-space-md);
  padding: var(--bl-space-md);
  background-color: var(--bl-surface-2);
  border-radius: var(--bl-radius-card);
}
.bl-f__verify {
  flex: none;
  min-height: var(--bl-touch);
  padding: 0 24rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 999rpx;
  border: 2rpx solid var(--bl-primary);
  box-sizing: border-box;
}
.bl-f__verify-text {
  font-size: var(--bl-font-caption);
  font-weight: 600;
  color: var(--bl-primary);
}
.bl-f__verify:active { background-color: var(--bl-primary-soft); }

.bl-new__submit { padding: var(--bl-space-xl) var(--bl-space-lg) var(--bl-space-xxl); }
.bl-new__submit .is-busy { opacity: .7; }
</style>
