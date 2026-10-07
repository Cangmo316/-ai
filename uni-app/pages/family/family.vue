<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar title="家人绑定" back solid @back="back" />

    <scroll-view class="bl-body" scroll-y>
      <view class="bl-fam__head">
        <text class="bl-fam__tip">填家里人的编号绑定。绑定后点家人卡片，能看他的情况；在「对话」里能跟他发消息</text>
      </view>

      <!-- 别人发给我、等我同意（绑定要对方同意，见 server 的 Binding 说明）。
           放在最上面：有等人回应的邀请时它是**最该先处理**的事。 -->
      <view v-if="pendingInvites.length" class="bl-fam__section">
        <view class="bl-section-title--ink">
          <view class="bl-brush-rule" />
          <text class="bl-section-title__text">等你同意（{{ pendingInvites.length }} 位）</text>
        </view>

        <view class="bl-fam__list">
          <view v-for="p in pendingInvites" :key="p.peerId" class="bl-fam bl-fam--invite">
            <view class="bl-fam__avatar">
              <text class="bl-fam__initial">{{ (p.peerName || '家').slice(0, 1) }}</text>
            </view>
            <view class="bl-fam__main">
              <text class="bl-fam__name">{{ p.peerName || '家人' }}</text>
              <text class="bl-fam__id">ID:{{ p.peerNumber }}</text>
              <text class="bl-fam__go">想跟你绑定家人，同意后他能看你的日程</text>
            </view>
            <view class="bl-fam__invite-actions">
              <view
                class="bl-fam__accept"
                role="button"
                :aria-label="'同意与' + (p.peerName || '家人') + '绑定'"
                @click.stop="respondInvite(p, true)"
              >
                <text class="bl-fam__accept-text">同意</text>
              </view>
              <view
                class="bl-fam__reject"
                role="button"
                :aria-label="'拒绝与' + (p.peerName || '家人') + '绑定'"
                @click.stop="respondInvite(p, false)"
              >
                <text class="bl-fam__reject-text">拒绝</text>
              </view>
            </view>
          </view>
        </view>
      </view>

      <!-- 已绑定：列出家人，点一下就能去跟他说话 -->
      <view v-if="bindings.length" class="bl-fam__section">
        <view class="bl-section-title--ink">
          <view class="bl-brush-rule" />
          <text class="bl-section-title__text">已绑定的家人（{{ bindings.length }} 位）</text>
        </view>

        <view class="bl-fam__list">
          <view
            v-for="b in bindings"
            :key="b.peerId"
            class="bl-fam"
            role="button"
            :aria-label="b.peerName + '，编号 ' + b.peerNumber"
            @click="openManage(b)"
          >
            <view class="bl-fam__avatar">
              <text class="bl-fam__initial">{{ (b.peerName || '家').slice(0, 1) }}</text>
            </view>
            <view class="bl-fam__main">
              <text class="bl-fam__name">{{ b.peerName || '家人' }}</text>
              <text class="bl-fam__id">ID:{{ b.peerNumber }}</text>
              <text class="bl-fam__go">点一下看他的情况</text>
            </view>
            <view
              class="bl-fam__unbind"
              role="button"
              :aria-label="'解除与' + b.peerName + '的绑定'"
              @click.stop="confirmUnbind(b)"
            >
              <text class="bl-fam__unbind-text">解除</text>
            </view>
          </view>
        </view>
      </view>

      <!-- 添加：输入 8 位编号 -->
      <view class="bl-fam__section">
        <view class="bl-section-title--ink">
          <view class="bl-brush-rule" />
          <text class="bl-section-title__text">添加家人</text>
        </view>

        <view class="bl-fam__form">
          <text class="bl-f__label">家人ID</text>
          <text class="bl-f__hint">就是他的 8 位编号，在「我的」页名字下面能看到</text>
          <view class="bl-f__box" :class="{ 'is-error': error }">
            <input
              v-model="number"
              class="bl-f__input"
              type="number"
              :maxlength="8"
              placeholder="比如 00000001"
              placeholder-class="bl-input-ph"
              @blur="lookup"
            />
            <view class="bl-f__verify" role="button" aria-label="查找" @click="lookup">
              <text class="bl-f__verify-text">查找</text>
            </view>
          </view>
          <text v-if="error" class="bl-f__err">{{ error }}</text>
          <text v-else-if="found" class="bl-f__ok">已找到：{{ found.name }}（ID:{{ found.number }}）</text>

          <!-- 我已经发出去、还在等对方同意的邀请。
               不列出来的话，用户点完"绑定"看不到任何变化，会以为没成功而反复点。 -->
          <view v-if="outgoingInvites.length" class="bl-fam__outgoing">
            <text class="bl-f__label">已发出邀请（等对方同意）</text>
            <view
              v-for="o in outgoingInvites"
              :key="o.peerId"
              class="bl-fam__pending-row"
            >
              <text class="bl-fam__pending-text">
                {{ o.peerName || '家人' }} · ID:{{ o.peerNumber }}
              </text>
              <view
                class="bl-fam__cancel"
                role="button"
                :aria-label="'撤回发给' + (o.peerName || '家人') + '的邀请'"
                @click="cancelInvite(o)"
              >
                <text class="bl-fam__cancel-text">撤回邀请</text>
              </view>
            </view>
          </view>

          <!-- 常用：拿本机已有账号当快捷入口（同设备测试用） -->
          <view v-if="candidates.length" class="bl-fam__quick">
            <text class="bl-f__label">本机上还有这些账号</text>
            <view class="bl-fam__chips">
              <view
                v-for="c in candidates"
                :key="c.number"
                class="bl-fam__chip"
                role="button"
                :aria-label="'选择 ' + c.name"
                @click="pickCandidate(c)"
              >
                <text class="bl-fam__chip-text">{{ c.name }} · {{ c.number }}</text>
              </view>
            </view>
          </view>
        </view>
      </view>

      <view class="bl-fam__submit">
        <view
          class="bl-btn bl-btn--primary bl-btn--block"
          :class="{ 'is-busy': binding }"
          role="button"
          aria-label="绑定家人"
          @click="doBind"
        >
          <text class="bl-btn__text">{{ binding ? '正在绑定…' : '绑定家人' }}</text>
        </view>
      </view>
    </scroll-view>
  </view>
</template>

<script setup>
/**
 * 家人绑定。
 *
 * 按需求：**从对话栏目里已绑定的对话人里选**。
 * 实现上"选人"就是填/选对方的 8 位编号（编号是账号对外的唯一标识），
 * 所以这一页既能手输、也能从本机已有账号里点选（同设备联调最方便）。
 *
 * 绑定之后会产生一条**共享会话**：双方在「对话」里都能看到、
 * 都能发消息、都能看到已读状态（见 server/app/messaging）。
 */
import { computed, ref } from 'vue'
import { settings } from '@/common/store.js'
import {
  bind,
  readAllBindings,
  readBindings,
  refreshAllBindings,
  refreshBindings,
  respondBinding,
  setPendingFamily,
  unbind
} from '@/stores/contacts.js'
import { lookupAccount } from '@/api/index.js'
import { readAccount } from '@/stores/account.js'

const number = ref('')
const error = ref('')
const found = ref(null)
const binding = ref(false)
const bindings = ref(readBindings())

/**
 * 别人发给我、等我同意的邀请。
 *
 * 绑定**要对方同意**（见 server 的 Binding 说明）：只发邀请不生效，
 * 所以在页面上必须让人看得到"谁在等我同意"，否则邀请就石沉大海。
 */
const pendingInvites = computed(() =>
  allBindings.value.filter((b) => b.status === 'pending' && !b.outgoing)
)

/** 我发出去、等对方同意的邀请 */
const outgoingInvites = computed(() =>
  allBindings.value.filter((b) => b.status === 'pending' && b.outgoing)
)

/** 全部绑定（含 pending / rejected），拉一次给上面两个 computed 用 */
const allBindings = ref(readAllBindings())

/** 本机上存过的账号（登录过就会有 bl_account_profile；多个账号靠测试时自己记） */
const candidates = ref(collectLocalAccounts())

function collectLocalAccounts() {
  const out = []
  try {
    const current = readAccount()
    if (current && current.number) out.push({ name: current.name, number: current.number })
  } catch (e) {
    // 忽略
  }
  // 去重
  const seen = {}
  return out.filter((item) => {
    if (seen[item.number]) return false
    seen[item.number] = true
    return true
  })
}

/** 查这个编号是谁（填错一位能立刻发现） */
function lookup() {
  error.value = ''
  found.value = null
  const value = String(number.value || '').trim()
  if (!value) return
  if (!/^\d{8}$/.test(value)) {
    error.value = '家人ID 是 8 位数字'
    return
  }
  const mine = readAccount()
  if (mine && mine.number === value) {
    error.value = '这是你自己的ID，换一个'
    return
  }
  lookupAccount(value)
    .then((data) => {
      if (data && data.found && data.account) {
        found.value = data.account
      } else {
        error.value = '没找到这个编号，核对一下'
      }
    })
    .catch((err) => {
      error.value = (err && err.message) || '查不到，稍后再试'
    })
}

function pickCandidate(c) {
  number.value = c.number
  lookup()
}

function doBind() {
  if (binding.value) return
  error.value = ''
  const value = String(number.value || '').trim()
  if (!value) {
    error.value = '请输入家人ID'
    return
  }
  if (!/^\d{8}$/.test(value)) {
    error.value = '家人ID 是 8 位数字'
    return
  }

  binding.value = true
  bind(value)
    .then((result) => {
      binding.value = false
      if (!result.ok) {
        error.value = result.message || '绑定失败，再试一次'
        return
      }
      number.value = ''
      found.value = null
      refreshAll().then(() => {
        // ⚠️ 文案要说清"要对方同意"：只说"绑定成功"会让人以为已经生效，
        //    然后跑去对话里找不到对方（其实还在等同意）。
        uni.showToast({ title: '邀请已发出，等对方同意', icon: 'none' })
      })
    })
    .catch(() => {
      binding.value = false
      error.value = '绑定失败，再试一次'
    })
}

/** 同时刷新"已绑定"和"全部（含待同意）"两份数据 */
function refreshAll() {
  return Promise.all([refreshBindings(), refreshAllBindings()]).then(() => {
    bindings.value = readBindings()
    allBindings.value = readAllBindings()
  })
}

/** 同意 / 拒绝一条邀请 */
function respondInvite(invite, accept) {
  if (binding.value) return
  const who = invite.peerName || '家人'
  const ask = accept
    ? { title: '同意绑定？', content: '同意后 ' + who + ' 能看到你的日程和聊天活跃情况' }
    : { title: '拒绝绑定？', content: who + ' 会收到"你拒绝了"的提示' }

  uni.showModal({
    title: ask.title,
    content: ask.content,
    confirmText: accept ? '同意' : '拒绝',
    cancelText: '再想想',
    success: (res) => {
      if (!res.confirm) return
      binding.value = true
      respondBinding(invite.peerNumber, accept)
        .then((result) => {
          binding.value = false
          if (!result.ok) {
            uni.showToast({ title: result.message || '没处理成功', icon: 'none' })
            return
          }
          refreshAll().then(() => {
            uni.showToast({ title: accept ? '已同意，可以互相说话了' : '已拒绝', icon: 'none' })
          })
        })
        .catch(() => {
          binding.value = false
          uni.showToast({ title: '没处理成功，再试一次', icon: 'none' })
        })
    }
  })
}

/** 撤回自己发出的邀请（对方还没回应时） */
function cancelInvite(invite) {
  const who = invite.peerName || '家人'
  uni.showModal({
    title: '撤回邀请？',
    content: '撤回后 ' + who + ' 那边就看不到这条邀请了',
    confirmText: '撤回',
    cancelText: '算了',
    success: (res) => {
      if (!res.confirm) return
      unbind(invite.peerNumber).then(() => refreshAll())
    }
  })
}

/**
 * 点家人卡片 → **查看管理界面**。
 *
 * 这里才是管理的入口（对话栏目里点家人是进聊天）。
 * 两处分开：家属想"看看他今天怎么样"和"跟他说句话"是两件事，
 * 混在一个入口里必然有一边别扭。
 */
function openManage(b) {
  setPendingFamily({
    id: b.conversationId,
    kind: 'family',
    title: b.peerName || '家人',
    peerNumber: b.peerNumber
  })
  uni.navigateTo({ url: '/pages/family-manage/family-manage' })
}

function confirmUnbind(b) {
  uni.showModal({
    title: '解除绑定？',
    content: '解除后你和' + (b.peerName || '这位家人') + '就不能互相发消息了',
    confirmText: '解除',
    cancelText: '再想想',
    success(res) {
      if (!res.confirm) return
      unbind(b.peerNumber).then((result) => {
        if (!result.ok) {
          uni.showToast({ title: result.message || '解除失败', icon: 'none' })
          return
        }
        refreshBindings().then(() => {
          bindings.value = readBindings()
        })
        uni.showToast({ title: '已解除绑定', icon: 'none' })
      })
    }
  })
}

function back() {
  const pages = getCurrentPages()
  if (pages.length > 1) uni.navigateBack()
  else uni.reLaunch({ url: '/pages/me/me' })
}
</script>

<style scoped>
.bl-fam__head { padding: 32rpx var(--bl-space-lg) 0; }
.bl-fam__tip {
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  line-height: 1.5;
}
.bl-fam__section { padding-top: 32rpx; }
.bl-fam__section .bl-section-title--ink { padding: 0 var(--bl-space-lg) 8rpx; }

.bl-fam__list {
  display: flex;
  flex-direction: column;
  gap: 16rpx;
  padding: 8rpx var(--bl-space-lg) 0;
}
.bl-fam {
  display: flex;
  align-items: center;
  gap: 24rpx;
  padding: 24rpx 28rpx;
  min-height: 132rpx;
  background-color: var(--bl-surface);
  border: 1rpx solid var(--bl-border);
  border-radius: var(--bl-radius-card);
  box-shadow: var(--bl-shadow-card);
  box-sizing: border-box;
}
.bl-fam:active { background-color: var(--bl-surface-2); }
.bl-fam__avatar {
  width: 88rpx;
  height: 88rpx;
  flex: none;
  border-radius: 50%;
  background-color: #7A6A4F;
  display: flex;
  align-items: center;
  justify-content: center;
}
.bl-fam__initial {
  font-size: 38rpx;
  font-weight: 700;
  color: #FFFDF8;
  line-height: 1;
}
.bl-fam__main { flex: 1; min-width: 0; }
.bl-fam__name {
  display: block;
  font-size: var(--bl-font-body);
  font-weight: 700;
  color: var(--bl-text);
}
.bl-fam__id {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  margin-top: 6rpx;
  font-variant-numeric: tabular-nums;
}
/* 明确这一行是点进管理的入口，免得家属以为点了是去聊天 */
.bl-fam__go {
  display: block;
  font-size: 22rpx;
  color: var(--bl-primary);
  margin-top: 6rpx;
}
.bl-fam__unbind {
  flex: none;
  min-height: var(--bl-touch);
  min-width: var(--bl-touch);
  padding: 0 18rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2rpx solid var(--bl-border-strong);
  border-radius: 999rpx;
  box-sizing: border-box;
}
.bl-fam__unbind-text { font-size: 22rpx; color: var(--bl-text-2); }

/* 表单 */
.bl-fam__form { padding: 8rpx var(--bl-space-lg) 0; }
.bl-f__label {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  margin-bottom: var(--bl-space-sm);
}
.bl-f__hint {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  line-height: 1.4;
  margin: -4rpx 0 var(--bl-space-sm);
}
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
.bl-f__input {
  flex: 1;
  min-width: 0;
  height: 100rpx;
  font-size: var(--bl-font-body);
  color: var(--bl-text);
  font-variant-numeric: tabular-nums;
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
.bl-f__verify-text { font-size: var(--bl-font-caption); font-weight: 600; color: var(--bl-primary); }
.bl-f__verify:active { background-color: var(--bl-primary-soft); }
.bl-f__err {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-danger);
  margin-top: 10rpx;
}
.bl-f__ok {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-success);
  margin-top: 10rpx;
}

.bl-fam__quick { margin-top: 32rpx; }
.bl-fam__chips { display: flex; flex-wrap: wrap; gap: 16rpx; }
.bl-fam__chip {
  min-height: var(--bl-touch);
  padding: 0 24rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: var(--bl-surface);
  border: 2rpx solid var(--bl-border-strong);
  border-radius: 999rpx;
  box-sizing: border-box;
}
.bl-fam__chip-text { font-size: var(--bl-font-caption); color: var(--bl-text); }
.bl-fam__chip:active { background-color: var(--bl-surface-2); }

.bl-fam__submit { padding: var(--bl-space-xl) var(--bl-space-lg) var(--bl-space-xxl); }
.bl-fam__submit .is-busy { opacity: .7; }
</style>
