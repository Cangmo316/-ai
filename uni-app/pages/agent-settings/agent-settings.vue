<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar title="智能体设置" back solid @back="back" />

    <scroll-view class="bl-body" scroll-y>
      <view class="bl-ag__intro">
        <text class="bl-ag__intro-text">选一个大脑来跟您说话。默认用它自带的，也可以接您自己的。</text>
      </view>

      <!-- 1 模型选择 -->
      <view class="bl-f">
        <text class="bl-f__label">1. 模型选择</text>
        <text class="bl-f__hint">第一项是自带的，不用额外配置</text>

        <view
          v-for="opt in MODES"
          :key="opt.value"
          class="bl-ag__opt"
          :class="{ 'is-on': form.mode === opt.value }"
          role="button"
          :aria-label="opt.label"
          :aria-pressed="form.mode === opt.value ? 'true' : 'false'"
          @click="form.mode = opt.value"
        >
          <view class="bl-ag__opt-radio" :class="{ 'is-on': form.mode === opt.value }">
            <view v-if="form.mode === opt.value" class="bl-ag__opt-dot" />
          </view>
          <view class="bl-ag__opt-main">
            <text class="bl-ag__opt-label">{{ opt.label }}</text>
            <text class="bl-ag__opt-desc">{{ opt.desc }}</text>
          </view>
        </view>
      </view>

      <!-- 自定义三项：只有选了"使用其他模型"才出现 -->
      <view v-if="isCustom" class="bl-f">
        <text class="bl-f__label">2. 接入信息</text>
        <text class="bl-f__hint">填完可以点下面的「测试连接」先验一下</text>

        <!-- API URL -->
        <view class="bl-ag__field">
          <text class="bl-ag__field-label">API URL</text>
          <view class="bl-f__box" :class="{ 'is-error': errors.baseUrl }">
            <input
              v-model="form.baseUrl"
              class="bl-f__input"
              :maxlength="200"
              placeholder="比如：https://api.deepseek.com/v1"
              placeholder-class="bl-input-ph"
            />
          </view>
          <text v-if="errors.baseUrl" class="bl-f__err">{{ errors.baseUrl }}</text>
        </view>

        <!-- API KEY -->
        <view class="bl-ag__field">
          <text class="bl-ag__field-label">API KEY</text>
          <view class="bl-f__box" :class="{ 'is-error': errors.apiKey }">
            <input
              v-model="form.apiKey"
              class="bl-f__input"
              :password="!keyVisible"
              :maxlength="200"
              :placeholder="keyPlaceholder"
              placeholder-class="bl-input-ph"
            />
            <!-- 已配置时允许看一眼自己刚填的；服务端只回脱敏值，所以不会泄露完整 key -->
            <view class="bl-ag__eye" role="button" :aria-label="keyVisible ? '隐藏密钥' : '显示密钥'" @click="keyVisible = !keyVisible">
              <bl-icon :name="keyVisible ? 'eye' : 'eyeoff'" color="#8A8A8A" :size="40" />
            </view>
          </view>
          <text class="bl-ag__field-note">{{ keyNote }}</text>
          <text v-if="errors.apiKey" class="bl-f__err">{{ errors.apiKey }}</text>
        </view>

        <!-- 模型名称 -->
        <view class="bl-ag__field">
          <text class="bl-ag__field-label">模型名称</text>
          <view class="bl-f__box" :class="{ 'is-error': errors.model }">
            <input
              v-model="form.model"
              class="bl-f__input"
              :maxlength="80"
              placeholder="比如：deepseek-chat、qwen-max"
              placeholder-class="bl-input-ph"
            />
          </view>
          <text v-if="errors.model" class="bl-f__err">{{ errors.model }}</text>
        </view>

        <view
          class="bl-ag__test"
          :class="{ 'is-busy': testing }"
          role="button"
          aria-label="测试连接"
          @click="onTest"
        >
          <text class="bl-ag__test-text">{{ testing ? '正在测试…' : '测试连接' }}</text>
        </view>
        <text v-if="testResult" class="bl-ag__test-result" :class="{ 'is-bad': !testResult.ok }">
          {{ testResult.ok ? '连上了：' + (testResult.sample || '模型有回应') : '没连上：' + testResult.reason }}
        </text>
      </view>

      <!-- 当前实际在用的模型（避免"设置看着对、其实没生效"） -->
      <view class="bl-f">
        <text class="bl-f__label">当前实际使用</text>
        <view class="bl-ag__active">
          <text class="bl-ag__active-main">{{ activeText }}</text>
          <text v-if="modelSetting.fallbackReason" class="bl-ag__active-warn">
            {{ modelSetting.fallbackReason }}
          </text>
        </view>
      </view>

      <view class="bl-ag__submit">
        <view
          class="bl-btn bl-btn--primary bl-btn--block"
          :class="{ 'is-busy': saving }"
          role="button"
          aria-label="保存设置"
          @click="save"
        >
          <text class="bl-btn__text">{{ saving ? '正在保存…' : '保存设置' }}</text>
        </view>
      </view>
    </scroll-view>
  </view>
</template>

<script setup>
/**
 * 智能体设置（我的 → 智能体设置）。
 *
 * 需求：第一栏是模型选择，默认「比邻AI」（= 自带的那个），
 * 也可以"使用其他模型"，填 **API URL / API KEY / 模型名称**。
 *
 * 【为什么要有"当前实际使用"那一栏】
 * 自定义配置写错了（URL 打不开、key 失效）时服务端会**退回内置模型**，
 * 但设置本身还是"自定义"。不把真实状态显出来，用户会以为换成了新模型、
 * 却一直在跟旧模型说话 —— 这种"以为生效了"最难发现。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { settings } from '@/common/store.js'
import {
  BUILTIN_LABEL,
  MODEL_MODE_BUILTIN,
  MODEL_MODE_CUSTOM,
  loadModelSetting,
  modelSetting,
  saveModel,
  testModel
} from '@/stores/agent.js'

const MODES = [
  { value: MODEL_MODE_BUILTIN, label: BUILTIN_LABEL, desc: '用它自带的模型，不用配置' },
  { value: MODEL_MODE_CUSTOM, label: '使用其他模型', desc: '接您自己的 API（DeepSeek、通义、Kimi…）' }
]

const form = reactive({
  mode: MODEL_MODE_BUILTIN,
  baseUrl: '',
  model: '',
  apiKey: ''
})
const errors = reactive({ baseUrl: '', apiKey: '', model: '' })
const saving = ref(false)
const testing = ref(false)
const keyVisible = ref(false)
const testResult = ref(null)

const isCustom = computed(() => form.mode === MODEL_MODE_CUSTOM)

/** 端侧拿不到完整 key：已配置时占位提示"留空即保留" */
const keyPlaceholder = computed(() => {
  if (modelSetting.hasApiKey && !form.apiKey) return '已配置（留空即不修改）'
  return '粘贴您的 API KEY'
})
const keyNote = computed(() => {
  if (modelSetting.hasApiKey && !form.apiKey) {
    return '当前：' + (modelSetting.apiKeyMasked || '已配置') + '（留空表示不改）'
  }
  return '只存在服务器上，不会回到这个界面'
})

const activeText = computed(() => {
  if (!modelSetting.loaded) return '读取中…'
  const name = modelSetting.activeModel || modelSetting.activeProvider || '未知'
  if (modelSetting.activeCustom) return name + '（您自己配的）'
  return name + '（' + BUILTIN_LABEL + '）'
})

onMounted(() => {
  loadModelSetting().then(() => {
    form.mode = modelSetting.mode
    form.baseUrl = modelSetting.baseUrl
    form.model = modelSetting.model
    // key 永远不回填（服务端只给脱敏值）
    form.apiKey = ''
  })
})

function clearErrors() {
  errors.baseUrl = ''
  errors.apiKey = ''
  errors.model = ''
}

function validate() {
  clearErrors()
  if (!isCustom.value) return true
  let ok = true
  if (!String(form.baseUrl).trim()) { errors.baseUrl = '请填 API URL'; ok = false }
  else if (!/^https?:\/\//i.test(String(form.baseUrl).trim())) {
    errors.baseUrl = '要以 http:// 或 https:// 开头'
    ok = false
  }
  // 只有"从没配过"时才强制填 key；已配过的留空表示不修改
  if (!String(form.apiKey).trim() && !modelSetting.hasApiKey) {
    errors.apiKey = '请填 API KEY'
    ok = false
  }
  if (!String(form.model).trim()) { errors.model = '请填模型名称'; ok = false }
  return ok
}

function payload() {
  return {
    mode: form.mode,
    baseUrl: String(form.baseUrl).trim(),
    apiKey: String(form.apiKey).trim(),
    model: String(form.model).trim()
  }
}

function onTest() {
  if (testing.value) return
  if (!validate()) return
  testing.value = true
  testResult.value = null
  // 测试要用"即将生效的三项"；key 留空时用服务端已存的那把（服务端会处理）
  testModel(payload()).then((res) => {
    testing.value = false
    testResult.value = res
  }).catch(() => {
    testing.value = false
    testResult.value = { ok: false, reason: '测试请求失败' }
  })
}

function save() {
  if (saving.value) return
  if (!validate()) return
  saving.value = true
  saveModel(payload()).then((res) => {
    saving.value = false
    if (!res.ok) {
      uni.showToast({ title: res.reason || '存不上', icon: 'none' })
      return
    }
    uni.showToast({ title: '设置已保存', icon: 'none' })
    setTimeout(() => back(), 900)
  })
}

function back() {
  const pages = getCurrentPages()
  if (pages.length > 1) uni.navigateBack()
  else uni.reLaunch({ url: '/pages/me/me' })
}
</script>

<style scoped>
.bl-ag__intro { padding: 28rpx var(--bl-space-lg) 0; }
.bl-ag__intro-text {
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  line-height: 1.5;
}

/* 模型选项：单选样式（图标 + 标题 + 说明），比原生 picker 更好点、也更好读 */
.bl-ag__opt {
  display: flex;
  align-items: center;
  gap: 20rpx;
  margin-top: 20rpx;
  padding: 24rpx var(--bl-space-lg);
  background-color: var(--bl-surface);
  border-radius: var(--bl-radius-card);
  border: 2rpx solid transparent;
}
.bl-ag__opt.is-on { border-color: var(--bl-primary, #2F5D4E); }
.bl-ag__opt-radio {
  width: 44rpx;
  height: 44rpx;
  flex: none;
  border-radius: 50%;
  border: 3rpx solid var(--bl-icon-muted);
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
}
.bl-ag__opt-radio.is-on { border-color: var(--bl-primary, #2F5D4E); }
.bl-ag__opt-dot {
  width: 22rpx;
  height: 22rpx;
  border-radius: 50%;
  background-color: var(--bl-primary, #2F5D4E);
}
.bl-ag__opt-main { flex: 1; min-width: 0; }
.bl-ag__opt-label { display: block; font-size: var(--bl-font-body); color: var(--bl-text); }
.bl-ag__opt-desc {
  display: block;
  margin-top: 6rpx;
  font-size: 24rpx;
  color: var(--bl-text-2);
}

.bl-ag__field { margin-top: 28rpx; }
.bl-ag__field-label {
  display: block;
  margin-bottom: 12rpx;
  font-size: 26rpx;
  color: var(--bl-text-2);
}
.bl-ag__field-note {
  display: block;
  margin-top: 10rpx;
  font-size: 22rpx;
  color: var(--bl-icon-muted);
}
/* 密钥框里的眼睛按钮 */
.bl-ag__eye {
  width: 64rpx;
  height: 64rpx;
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
}

.bl-ag__test {
  margin-top: 28rpx;
  height: 80rpx;
  border-radius: var(--bl-radius-btn, 16rpx);
  border: 2rpx solid var(--bl-primary, #2F5D4E);
  display: flex;
  align-items: center;
  justify-content: center;
}
.bl-ag__test.is-busy { opacity: .6; }
.bl-ag__test-text { font-size: var(--bl-font-body); color: var(--bl-primary, #2F5D4E); }
.bl-ag__test-result {
  display: block;
  margin-top: 16rpx;
  font-size: 24rpx;
  color: var(--bl-primary, #2F5D4E);
  line-height: 1.5;
}
.bl-ag__test-result.is-bad { color: var(--bl-danger, #C0392B); }

.bl-ag__active {
  margin-top: 16rpx;
  padding: 24rpx var(--bl-space-lg);
  background-color: var(--bl-surface);
  border-radius: var(--bl-radius-card);
}
.bl-ag__active-main { display: block; font-size: var(--bl-font-body); color: var(--bl-text); }
.bl-ag__active-warn {
  display: block;
  margin-top: 12rpx;
  font-size: 24rpx;
  color: var(--bl-danger, #C0392B);
  line-height: 1.5;
}

.bl-ag__submit { padding: var(--bl-space-xl) var(--bl-space-lg) var(--bl-space-xxl); }
.bl-ag__submit .is-busy { opacity: .7; }
</style>
