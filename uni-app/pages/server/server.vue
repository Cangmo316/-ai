<template>
  <view class="bl-page">
    <bl-navbar title="服务器地址" solid />

    <scroll-view class="bl-body" scroll-y>
      <view class="bl-hint">
        连不上服务器时，先在这里确认地址对不对，再点「测试连接」。
        改完保存**不需要重新安装 App**。
      </view>

      <!-- 当前生效的地址 -->
      <view class="bl-section-title--ink">
        <view class="bl-brush-rule" />
        <text class="bl-section-title__text">当前地址</text>
      </view>
      <view class="bl-group">
        <view class="bl-row bl-row--stack">
          <text class="bl-row__label">正在使用</text>
          <text class="bl-value">{{ current }}</text>
        </view>
        <view class="bl-row bl-row--stack">
          <text class="bl-row__label">来源</text>
          <text class="bl-value">{{ source }}</text>
        </view>
        <view class="bl-row bl-row--stack">
          <text class="bl-row__label">接口 token</text>
          <text class="bl-value">{{ tokenHint }}</text>
        </view>
      </view>

      <!-- 修改 -->
      <view class="bl-section-title--ink">
        <view class="bl-brush-rule" />
        <text class="bl-section-title__text">改成别的地址</text>
      </view>
      <view class="bl-group">
        <view class="bl-field">
          <textarea
            v-model="draft"
            class="bl-textarea"
            placeholder="例如 http://121.196.160.179:8000 或 https://api.你的域名"
            :maxlength="120"
            auto-height
          />
          <view class="bl-field__foot">
            <text class="bl-field__tip">必须带 http:// 或 https://，不要以斜杠结尾</text>
          </view>
        </view>
      </view>

      <view class="bl-actions">
        <view class="bl-btn bl-btn--primary" @click="test">
          <text class="bl-btn__text">{{ testing ? '测试中…' : '测试连接' }}</text>
        </view>
        <view class="bl-btn" @click="save">
          <text class="bl-btn__text">保存并使用</text>
        </view>
        <view class="bl-btn" @click="reset">
          <text class="bl-btn__text">恢复打包时的地址</text>
        </view>
      </view>

      <!-- 测试结果 -->
      <view v-if="result" class="bl-group">
        <view class="bl-row bl-row--stack">
          <text class="bl-row__label">{{ result.ok ? '✅ 连接正常' : '❌ 连不上' }}</text>
          <text class="bl-value">{{ result.detail }}</text>
        </view>
      </view>

      <!-- 排查指引 -->
      <view class="bl-section-title--ink">
        <view class="bl-brush-rule" />
        <text class="bl-section-title__text">连不上怎么排查</text>
      </view>
      <view class="bl-group">
        <view class="bl-tip">1. 地址必须能被手机访问（不能填 127.0.0.1，那是手机自己）</view>
        <view class="bl-tip">2. 用手机浏览器打开同一地址的 /healthz，能看到 {"ok":true} 才算通</view>
        <view class="bl-tip">3. 家里 WiFi 换过地址会变，出门用流量时局域网地址一定连不上</view>
        <view class="bl-tip">4. 服务器安全组要放行对应端口（如 8000）</view>
      </view>
    </scroll-view>
  </view>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import {
  getBaseURL,
  setBaseURL,
  STORAGE_KEY_BASE_URL,
  getApiToken
} from '../../api/config.js'

const current = ref('')
const draft = ref('')
const source = ref('')
const testing = ref(false)
const result = ref(null)

/** 打包时注入的地址（用于判断当前是不是被运行期覆盖了） */
function buildTimeURL() {
  return String(import.meta.env.VITE_API_BASE_URL || '').trim()
}

const tokenHint = computed(() => (getApiToken() ? '已配置' : '未配置（服务端未开鉴权时可正常用）'))

function refresh() {
  current.value = getBaseURL()
  const override = (() => {
    try {
      return String(uni.getStorageSync(STORAGE_KEY_BASE_URL) || '').trim()
    } catch (e) {
      return ''
    }
  })()
  source.value = override ? '本机设置（覆盖了打包时的地址）' : '打包时写死的地址'
  draft.value = current.value
}

onMounted(refresh)

/** 规范化：补协议、去尾部斜杠 */
function normalize(raw) {
  let text = String(raw || '').trim()
  if (!text) return ''
  if (!/^https?:\/\//i.test(text)) text = 'http://' + text
  return text.replace(/\/+$/, '')
}

async function test() {
  const url = normalize(draft.value)
  if (!url) {
    uni.showToast({ title: '先填一个地址', icon: 'none' })
    return
  }
  testing.value = true
  result.value = null
  const started = Date.now()
  try {
    const response = await new Promise((resolve, reject) => {
      uni.request({
        url: url + '/healthz',
        method: 'GET',
        timeout: 8000,
        success: resolve,
        fail: reject
      })
    })
    const ms = Date.now() - started
    if (response.statusCode === 200 && response.data && response.data.ok) {
      result.value = {
        ok: true,
        detail: `${ms}ms · 服务正常（${response.data.service || 'bilin'} v${response.data.version || '-'}）`
      }
    } else {
      result.value = {
        ok: false,
        detail: `HTTP ${response.statusCode}，但返回的不是预期格式`
      }
    }
  } catch (error) {
    const message = (error && (error.errMsg || error.message)) || '请求失败'
    result.value = { ok: false, detail: message + '（可能是地址错、端口没开、或服务没起）' }
  } finally {
    testing.value = false
  }
}

function save() {
  const url = normalize(draft.value)
  if (!url) {
    uni.showToast({ title: '先填一个地址', icon: 'none' })
    return
  }
  if (!/^https?:\/\/[^\s/]+/i.test(url)) {
    uni.showToast({ title: '地址格式不对', icon: 'none' })
    return
  }
  setBaseURL(url)
  uni.showToast({ title: '已保存，正在重新进入', icon: 'none' })
  setTimeout(() => {
    uni.reLaunch({ url: '/pages/index/index' })
  }, 600)
}

function reset() {
  setBaseURL('')
  refresh()
  uni.showToast({ title: '已恢复打包时的地址', icon: 'none' })
}
</script>

<style scoped>
.bl-body {
  flex: 1;
  padding-bottom: 60rpx;
}

.bl-hint {
  margin: 0 32rpx 24rpx;
  padding: 24rpx 28rpx;
  border-radius: 20rpx;
  background: #f4f1e8;
  color: #6d6656;
  font-size: 28rpx;
  line-height: 1.6;
}

.bl-row--stack {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10rpx;
  padding: 26rpx 28rpx;
}

.bl-value {
  font-size: 30rpx;
  color: #2f5d4e;
  word-break: break-all;
  line-height: 1.5;
}

.bl-field {
  padding: 24rpx 28rpx;
}

.bl-textarea {
  width: 100%;
  min-height: 96rpx;
  font-size: 32rpx;
  color: #2b2b28;
  line-height: 1.5;
}

.bl-field__foot {
  margin-top: 14rpx;
}

.bl-field__tip {
  font-size: 24rpx;
  color: #9a9484;
}

.bl-actions {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
  margin: 28rpx 32rpx;
}

.bl-btn {
  height: 96rpx;
  border-radius: 20rpx;
  border: 2rpx solid #d9d3c4;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fff;
}

.bl-btn--primary {
  background: #2f5d4e;
  border-color: #2f5d4e;
}

.bl-btn__text {
  font-size: 32rpx;
  color: #3a3a35;
}

.bl-btn--primary .bl-btn__text {
  color: #fff;
}

.bl-tip {
  padding: 22rpx 28rpx;
  font-size: 28rpx;
  color: #5d5747;
  line-height: 1.6;
  border-bottom: 1rpx solid #eee9dc;
}

.bl-tip:last-child {
  border-bottom: none;
}
</style>
