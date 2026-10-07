<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar title="我的" solid />

    <scroll-view class="bl-body" scroll-y>
      <!-- 已登录：头像（可点更换）+ 名字（加粗）+ 编号 -->
      <view v-if="loggedIn" class="bl-profile">
        <view
          class="bl-profile__avatar"
          role="button"
          aria-label="更换头像，长按可退出登录"
          @click="pickAvatar"
          @longpress="confirmSignOut"
        >
          <!-- 换过头像就显示图片；没有就画名字首字，比一个通用小人更像"我的" -->
          <image v-if="avatarSrc" class="bl-profile__avatar-img" :src="avatarSrc" mode="aspectFill" />
          <text v-else class="bl-profile__initial">{{ initial }}</text>
          <!-- 右下角小相机角标：让"这里能点"这件事看得见 -->
          <view class="bl-profile__badge">
            <bl-icon name="plus" color="#FFFDF8" :size="24" />
          </view>
        </view>
        <view class="bl-profile__main">
          <text class="bl-profile__name">{{ profile.name }}</text>
          <text class="bl-profile__id">{{ idLabel }}</text>
        </view>
      </view>

      <!-- 未登录：整卡可点去登录/注册。做成整卡可点而不是只点文字，
           老人的手指粗、瞄准小字很难 -->
      <view
        v-else
        class="bl-profile is-tappable"
        role="button"
        aria-label="请登录或注册"
        @click="toAuth"
      >
        <view class="bl-profile__avatar">
          <bl-icon name="person" color="#FFFDF8" :size="80" />
        </view>
        <view class="bl-profile__main">
          <text class="bl-profile__name">请登录或注册</text>
        </view>
        <bl-icon name="chev" color="#B9B3A4" :size="34" />
      </view>

      <view class="bl-section-title--ink">
        <view class="bl-brush-rule" />
        <text class="bl-section-title__text">陪伴设置</text>
      </view>
      <view class="bl-group">
        <view class="bl-row" @click="toRoles">
          <view class="bl-row__icon">
            <bl-icon name="role" color="#2F5D4E" :size="44" />
          </view>
          <text class="bl-row__label">智能体角色</text>
          <bl-icon name="chev" color="#B9B3A4" :size="34" />
        </view>

        <view class="bl-row" @click="toFace">
          <view class="bl-row__icon">
            <bl-icon name="face" color="#2F5D4E" :size="44" />
          </view>
          <text class="bl-row__label">数字人形象</text>
          <bl-icon name="chev" color="#B9B3A4" :size="34" />
        </view>

        <view class="bl-row" @click="toFamily">
          <view class="bl-row__icon">
            <bl-icon name="family" color="#2F5D4E" :size="44" />
          </view>
          <text class="bl-row__label">家人绑定</text>
          <text v-if="familyCount" class="bl-row__value">已绑定 {{ familyCount }} 位</text>
          <bl-icon name="chev" color="#B9B3A4" :size="34" />
        </view>
      </view>

      <view class="bl-section-title--ink">
        <view class="bl-brush-rule" />
        <text class="bl-section-title__text">健康与设置</text>
      </view>
      <view class="bl-group">
        <view class="bl-row" @click="toHealth">
          <view class="bl-row__icon">
            <bl-icon name="health" color="#2F5D4E" :size="44" />
          </view>
          <text class="bl-row__label">健康档案</text>
          <bl-icon name="chev" color="#B9B3A4" :size="34" />
        </view>

        <view class="bl-row">
          <view class="bl-row__icon">
            <bl-icon name="settings" color="#2F5D4E" :size="44" />
          </view>
          <text class="bl-row__label">大字体模式</text>
          <bl-switch :checked="settings.largeFont" @change="onLargeChange" />
        </view>

        <view class="bl-row" @click="toast('AI 记忆可查看与删除（原型演示）')">
          <view class="bl-row__icon">
            <bl-icon name="privacy" color="#2F5D4E" :size="44" />
          </view>
          <text class="bl-row__label">隐私 · AI 记忆</text>
          <bl-icon name="chev" color="#B9B3A4" :size="34" />
        </view>

        <view class="bl-row" @click="toTokens">
          <view class="bl-row__icon">
            <bl-icon name="palette" color="#2F5D4E" :size="44" />
          </view>
          <text class="bl-row__label">设计规范</text>
          <bl-icon name="chev" color="#B9B3A4" :size="34" />
        </view>
      </view>

      <view class="bl-me-foot">天涯若比邻 · 比邻AI v1.0</view>
    </scroll-view>

    <bl-tabbar active="me" />

    <!-- 原生端压缩头像用的离屏画布（H5 走 canvas API，不需要它） -->
    <!-- #ifndef H5 -->
    <canvas canvas-id="avatarCanvas" class="bl-offscreen-canvas" />
    <!-- #endif -->
  </view>
</template>

<script setup>
/**
 * 我的页。
 *
 * 登录后：头像（可点更换）+ 名字（加粗）+ `ID:编号`。
 * 未登录：整卡可点去登录/注册。
 *
 * 账号数据不直接绑 store 的模块导出，而是放进页面自己的 ref
 * （原因见 stores/account.js 顶部说明：本项目的打包器会把 store 内联进多个 chunk，
 *  模板里引用模块绑定可能变成 undefined）。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { settings, setLargeFont } from '@/common/store.js'
import {
  EVENT_ACCOUNT_CHANGED,
  changeAvatar,
  idText,
  initialOf,
  initAccount,
  readAccount,
  signOut
} from '@/stores/account.js'
import { refreshBindings, readBindings } from '@/stores/contacts.js'

/** 已绑定的家人数：显示在「家人绑定」行右侧 */
const familyCount = ref(0)

function syncFamilyCount() {
  familyCount.value = readBindings().length
}

/** 当前账号（副本）。未登录时为 null。 */
const profile = ref(readAccount())
const loggedIn = computed(() => !!(profile.value && profile.value.number))

/** 编号展示：ID:00000000 */
const idLabel = computed(() => idText(profile.value))
/** 名字首字（没换头像时的占位） */
const initial = computed(() => initialOf(profile.value))

/**
 * 头像图片来源：
 *  · 预设名（grandma / son …）→ 本地静态图
 *  · data URI（老人自己传的）→ 直接用
 *  · 空 → 不显示图片，改画名字首字
 */
const avatarSrc = computed(() => {
  const avatar = (profile.value && profile.value.avatar) || ''
  if (!avatar) return ''
  if (avatar.indexOf('data:') === 0) return avatar
  return '/static/avatars/' + avatar + '.png'
})

// 冷启动时先用本地缓存渲染（老人立刻看到自己的名字），再向服务端确认
// 服务端确认结果通过事件回来，所以这里订阅一下（否则页面会一直显示缓存那份）
function onAccountChanged(account) {
  profile.value = account || null
}

onMounted(() => {
  uni.$on(EVENT_ACCOUNT_CHANGED, onAccountChanged)
  initAccount().then((account) => {
    profile.value = account
  })
  // 已绑定家人数要显示在「家人绑定」行上
  syncFamilyCount()
  refreshBindings().then(syncFamilyCount)
})

onUnmounted(() => {
  uni.$off(EVENT_ACCOUNT_CHANGED, onAccountChanged)
})

/** 换头像：选图 → 压成小图 → 上传 */
function pickAvatar() {
  if (!loggedIn.value) return
  uni.chooseImage({
    count: 1,
    sizeType: ['compressed'],
    sourceType: ['album', 'camera'],
    success(res) {
      const path = (res.tempFilePaths && res.tempFilePaths[0]) || ''
      if (!path) return
      compressToDataUri(path)
        .then((dataUri) => {
          if (!dataUri) {
            uni.showToast({ title: '这张照片读不出来，换一张', icon: 'none' })
            return
          }
          // 先本地生效（老人马上看到），失败会回滚
          profile.value = Object.assign({}, profile.value, { avatar: dataUri })
          return changeAvatar(dataUri).then((result) => {
            if (!result.ok) {
              profile.value = readAccount()
              uni.showToast({ title: result.message || '头像没换成功', icon: 'none' })
              return
            }
            profile.value = result.account
            uni.showToast({ title: '头像已更换', icon: 'none' })
          })
        })
        .catch(() => {
          uni.showToast({ title: '头像没换成功，再试一次', icon: 'none' })
        })
    }
  })
}

/**
 * 把图片压成小尺寸 data URI。
 * 为什么必须压：原始照片动辄几 MB，直接传会把接口撑爆、
 * 而且在 H5 上 base64 后更大。这里限到 240px、JPEG 0.82，约 10–30KB。
 */
function compressToDataUri(path) {
  return new Promise((resolve) => {
    // #ifdef H5
    const image = new Image()
    image.onload = () => {
      const max = 240
      const scale = Math.min(1, max / Math.max(image.width, image.height))
      const w = Math.max(1, Math.round(image.width * scale))
      const h = Math.max(1, Math.round(image.height * scale))
      const canvas = document.createElement('canvas')
      canvas.width = w
      canvas.height = h
      const ctx = canvas.getContext('2d')
      ctx.drawImage(image, 0, 0, w, h)
      resolve(canvas.toDataURL('image/jpeg', 0.82))
    }
    image.onerror = () => resolve('')
    image.src = path
    // #endif

    // #ifndef H5
    // 原生端用 canvas 压缩；拿不到就退回原图（uni 端 chooseImage 已选了 compressed）
    try {
      const ctx = uni.createCanvasContext('avatarCanvas')
      uni.getImageInfo({
        src: path,
        success(info) {
          const max = 240
          const scale = Math.min(1, max / Math.max(info.width, info.height))
          const w = Math.max(1, Math.round(info.width * scale))
          const h = Math.max(1, Math.round(info.height * scale))
          ctx.drawImage(path, 0, 0, w, h)
          ctx.draw(false, () => {
            uni.canvasToTempFilePath({
              canvasId: 'avatarCanvas',
              width: w,
              height: h,
              destWidth: w,
              destHeight: h,
              fileType: 'jpg',
              quality: 0.82,
              success(res2) {
                // 原生端把临时文件读成 base64
                try {
                  const fs = uni.getFileSystemManager()
                  const base64 = fs.readFileSync(res2.tempFilePath, 'base64')
                  resolve('data:image/jpeg;base64,' + base64)
                } catch (e) {
                  resolve('')
                }
              },
              fail() {
                resolve('')
              }
            })
          })
        },
        fail() {
          resolve('')
        }
      })
    } catch (e) {
      resolve('')
    }
    // #endif
  })
}

/** 退出登录（长按头像触发，避免误触） */
function confirmSignOut() {
  if (!loggedIn.value) return
  uni.showModal({
    title: '要退出登录吗？',
    content: '退出后要重新输密码才能进来',
    confirmText: '退出',
    cancelText: '再想想',
    success(res) {
      if (!res.confirm) return
      signOut()
      profile.value = null
      uni.showToast({ title: '已退出登录', icon: 'none' })
    }
  })
}

function toast(title) {
  uni.showToast({ title: title, icon: 'none' })
}
function onLargeChange(value) {
  setLargeFont(value)
  toast(value ? '已开启大字体模式' : '已关闭大字体模式')
}
function toRoles() {
  uni.navigateTo({ url: '/pages/roles/roles' })
}
function toFace() {
  // 形象页**已开放**（用户要求）：页面里可切换男女形象；精细捏脸在页面内标注"正在开发中"。
  // 所以这里恢复为正常跳转 —— 之前"点进来只弹提示"的做法已作废
  // （那时捏脸整体下线、页面打不开，用户就没有切换男女的入口了）。
  uni.navigateTo({ url: '/pages/face/face' })
}
function toTokens() {
  uni.navigateTo({ url: '/pages/tokens/tokens' })
}
function toAuth() {
  uni.navigateTo({ url: '/pages/auth/auth' })
}
function toHealth() {
  uni.navigateTo({ url: '/pages/health/health' })
}
function toFamily() {
  uni.navigateTo({ url: '/pages/family/family' })
}
</script>

<style scoped>
.bl-profile {
  display: flex;
  align-items: center;
  gap: 32rpx;
  /* 纸面卡：与两侧留边，替代原来的通栏白底 */
  margin: 0 var(--bl-space-lg) var(--bl-space-md);
  padding: 40rpx 32rpx;
  background-color: var(--bl-surface);
  border: 1rpx solid var(--bl-border);
  border-radius: var(--bl-radius-card);
  box-shadow: var(--bl-shadow-card);
  box-sizing: border-box;
}
.bl-profile__avatar {
  position: relative;
  width: 160rpx;
  height: 160rpx;
  flex: none;
  border-radius: 50%;
  background-color: var(--bl-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: visible;
}
/* 换过的头像照片：圆形裁切铺满 */
.bl-profile__avatar-img {
  width: 160rpx;
  height: 160rpx;
  border-radius: 50%;
  display: block;
}
/* 没换过头像时画名字首字 */
.bl-profile__initial {
  font-size: 64rpx;
  font-weight: 700;
  color: #FFFDF8;
  line-height: 1;
}
/* 右下角小角标：让"这里能点"看得见（老人不会去猜哪里可以点） */
.bl-profile__badge {
  position: absolute;
  right: -4rpx;
  bottom: -4rpx;
  width: 44rpx;
  height: 44rpx;
  border-radius: 50%;
  background-color: var(--bl-primary);
  border: 4rpx solid var(--bl-surface);
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
}
.bl-profile__avatar:active { opacity: .85; }
.bl-profile__main { flex: 1; min-width: 0; }
/* 可点卡片：按下时纸面变深一点，老人能确认"点到了" */
.bl-profile.is-tappable:active {
  background-color: var(--bl-surface-2);
  border-color: var(--bl-border-strong);
}
.bl-profile__name {
  display: block;
  font-size: var(--bl-font-display);
  font-weight: 700;
  color: var(--bl-text);
  letter-spacing: .01em;
}

/* 页脚落款 */
.bl-me-foot {
  padding: var(--bl-space-md) var(--bl-space-lg) var(--bl-space-xl);
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  letter-spacing: .02em;
}

/* 编号：名字下方一行，`ID:00000000`。
   等宽数字——编号是给人念/抄的，位数对齐了不容易看错。 */
.bl-profile__id {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  margin-top: 10rpx;
  line-height: 1.4;
  letter-spacing: .02em;
  font-variant-numeric: tabular-nums;
}

/* 原生端压缩头像用的离屏画布：不参与布局 */
.bl-offscreen-canvas {
  position: fixed;
  left: -9999rpx;
  top: -9999rpx;
  width: 1rpx;
  height: 1rpx;
}
</style>