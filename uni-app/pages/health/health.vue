<template>
  <view class="bl-page" :class="{ 'bl-large': settings.largeFont }">
    <bl-navbar title="健康档案" back solid @back="back" />

    <!-- 两个标签：上面三项基础数据，下面病例病史 -->
    <view class="bl-tabs">
      <view
        class="bl-tab"
        :class="{ 'is-on': tab === 'basic' }"
        role="button"
        aria-label="基础数据"
        @click="tab = 'basic'"
      >
        <text class="bl-tab__text" :class="{ 'is-on': tab === 'basic' }">基础数据</text>
      </view>
      <view
        class="bl-tab"
        :class="{ 'is-on': tab === 'case' }"
        role="button"
        aria-label="病例病史"
        @click="switchToCases"
      >
        <text class="bl-tab__text" :class="{ 'is-on': tab === 'case' }">病例病史</text>
      </view>
    </view>

    <scroll-view class="bl-body" scroll-y>
      <!-- ═══════════ 基础数据 ═══════════ -->
      <template v-if="tab === 'basic'">
        <view class="bl-h__head">
          <text class="bl-h__tip">记下身体的数据，比邻会照着它关心你</text>
        </view>

        <view class="bl-h__list">
          <view
            v-for="item in summary"
            :key="item.itemType"
            class="bl-h"
            :class="{ 'is-empty': !item.latest }"
            role="button"
            :aria-label="'记录' + item.label"
            @click="openForm(item.itemType)"
          >
            <view class="bl-h__main">
              <text class="bl-h__label">{{ item.label }}</text>
              <text v-if="item.latest" class="bl-h__value">{{ item.latest.summary }}</text>
              <text v-else class="bl-h__empty">还没记过</text>
              <text v-if="item.latest" class="bl-h__when">
                {{ relativeOf(item.latest.measuredAt) }} · 共 {{ item.count }} 次
              </text>
              <text v-else-if="item.normalRange" class="bl-h__range">正常范围 {{ item.normalRange }}</text>
            </view>
            <view class="bl-h__add">
              <bl-icon name="plus" color="#2F5D4E" :size="40" />
            </view>
          </view>
        </view>

        <view v-if="history.length" class="bl-h__section">
          <view class="bl-section-title--ink">
            <view class="bl-brush-rule" />
            <text class="bl-section-title__text">最近的记录</text>
          </view>
          <view class="bl-h__history">
            <view
              v-for="r in history"
              :key="r.id"
              class="bl-h__row"
              @longpress="confirmDeleteRecord(r)"
            >
              <view class="bl-h__row-main">
                <text class="bl-h__row-label">{{ r.itemLabel }}</text>
                <text class="bl-h__row-summary">{{ r.summary }}</text>
              </view>
              <text class="bl-h__row-time">{{ clockOf(r.measuredAt) }}</text>
            </view>
          </view>
          <text class="bl-h__hint">按住一条不放可以删掉（记错了的时候）</text>
        </view>
      </template>

      <!-- ═══════════ 病例病史 ═══════════ -->
      <template v-else>
        <view class="bl-h__head">
          <text class="bl-h__tip">
            把医院的单据拍下来传上来，比邻会读上面的字，以后聊天时它就记得医生说过什么
          </text>
        </view>

        <!-- 识图不可用时如实告知（而不是等老人传完照片才失败） -->
        <view v-if="vision && vision.ready === false" class="bl-c__warn">
          <text class="bl-c__warn-text">
            拍照识别还没开通，你传的图片不会被读出文字。可以先手写「诊断」和「小结」。
          </text>
        </view>

        <!-- 新建病历 -->
        <view class="bl-c__new">
          <view class="bl-btn bl-btn--primary bl-btn--block" role="button" @click="startNewCase">
            <text class="bl-btn__text">添加一份病历</text>
          </view>
          <text class="bl-c__new-hint">可以拍照、传 PDF，也可以只写几行字</text>
        </view>

        <view v-if="cases.length" class="bl-c__list">
          <view
            v-for="c in cases"
            :key="c.id"
            class="bl-c"
            role="button"
            :aria-label="'查看' + (c.title || c.kindLabel)"
            @click="openCase(c)"
          >
            <view class="bl-c__top">
              <text class="bl-c__kind">{{ c.kindLabel }}</text>
              <text v-if="c.visitDate" class="bl-c__date">{{ c.visitDate.slice(0, 10) }}</text>
            </view>
            <text class="bl-c__title">{{ c.title || c.diagnosis || '（没写标题）' }}</text>
            <text v-if="c.hospital" class="bl-c__hospital">{{ c.hospital }}</text>
            <view class="bl-c__foot">
              <view class="bl-c__files">
                <text v-if="fileCount(c, 'image')" class="bl-c__file-tag">
                  {{ fileCount(c, 'image') }} 张照片
                </text>
                <text v-if="fileCount(c, 'pdf')" class="bl-c__file-tag">
                  {{ fileCount(c, 'pdf') }} 个 PDF
                </text>
                <text v-if="!c.files.length" class="bl-c__file-tag">没有附件</text>
              </view>
              <!-- 附件解析状态：老人要能看出"读到了没有" -->
              <text v-if="c.files.length" class="bl-c__status" :class="statusClass(c)">
                {{ statusText(c) }}
              </text>
            </view>
          </view>
        </view>

        <view v-else class="bl-c__empty">
          <text class="bl-c__empty-text">还没有病历。点上面「添加一份病历」吧</text>
        </view>
      </template>
    </scroll-view>

    <!-- ═══════════ 记基础数据的弹层 ═══════════ -->
    <view v-if="form.open" class="bl-sheet">
      <view class="bl-sheet__mask" @click="closeForm" />
      <view class="bl-sheet__panel">
        <view class="bl-sheet__head">
          <text class="bl-sheet__title">记录{{ form.label }}</text>
          <view class="bl-sheet__close" role="button" aria-label="关闭" @click="closeForm">
            <text class="bl-sheet__close-text">✕</text>
          </view>
        </view>

        <scroll-view class="bl-sheet__body" scroll-y>
          <text v-if="form.hint" class="bl-sheet__hint">{{ form.hint }}</text>

          <view v-for="f in form.fields" :key="f.key" class="bl-f">
            <text class="bl-f__label">
              {{ f.label }}<text v-if="form.unit" class="bl-f__unit">（{{ form.unit }}）</text>
            </text>
            <view class="bl-f__box" :class="{ 'is-error': form.errors[f.key] }">
              <input
                v-model="form.values[f.key]"
                class="bl-f__input"
                type="digit"
                :placeholder="'请输入' + f.label"
                placeholder-class="bl-input-ph"
              />
            </view>
            <text v-if="form.errors[f.key]" class="bl-f__err">{{ form.errors[f.key] }}</text>
          </view>

          <view v-if="form.timings.length" class="bl-f">
            <text class="bl-f__label">什么时候量的</text>
            <view class="bl-f__chips">
              <view
                v-for="t in form.timings"
                :key="t"
                class="bl-f__chip"
                :class="{ 'is-on': form.timing === t }"
                role="button"
                :aria-label="t"
                @click="form.timing = t"
              >
                <text class="bl-f__chip-text">{{ t }}</text>
              </view>
            </view>
          </view>

          <view class="bl-f">
            <text class="bl-f__label">备注（可以不填）</text>
            <view class="bl-f__box">
              <input
                v-model="form.note"
                class="bl-f__input"
                :maxlength="40"
                placeholder="比如：早上没吃饭量的"
                placeholder-class="bl-input-ph"
              />
            </view>
          </view>

          <text v-if="form.range" class="bl-sheet__ref">参考范围：{{ form.range }}</text>
          <text v-if="form.error" class="bl-f__err bl-sheet__error">{{ form.error }}</text>
        </scroll-view>

        <view class="bl-sheet__foot">
          <view class="bl-btn bl-btn--ghost bl-sheet__btn" role="button" @click="closeForm">
            <text class="bl-page-footer__text">取消</text>
          </view>
          <view
            class="bl-btn bl-btn--primary bl-sheet__btn"
            :class="{ 'is-busy': form.saving }"
            role="button"
            @click="saveRecord"
          >
            <text class="bl-btn__text bl-sheet__btn-text--on">{{ form.saving ? '保存中…' : '保存' }}</text>
          </view>
        </view>
      </view>
    </view>

    <!-- ═══════════ 新建病历的弹层 ═══════════ -->
    <view v-if="caseForm.open" class="bl-sheet">
      <view class="bl-sheet__mask" @click="closeCaseForm" />
      <view class="bl-sheet__panel">
        <view class="bl-sheet__head">
          <text class="bl-sheet__title">添加病历</text>
          <view class="bl-sheet__close" role="button" aria-label="关闭" @click="closeCaseForm">
            <text class="bl-sheet__close-text">✕</text>
          </view>
        </view>

        <scroll-view class="bl-sheet__body" scroll-y>
          <!-- 病历类型 -->
          <view class="bl-f">
            <text class="bl-f__label">这是什么单子</text>
            <view class="bl-f__chips">
              <view
                v-for="t in caseTypes"
                :key="t.kind"
                class="bl-f__chip"
                :class="{ 'is-on': caseForm.kind === t.kind }"
                role="button"
                :aria-label="t.label"
                @click="caseForm.kind = t.kind"
              >
                <text class="bl-f__chip-text">{{ t.label }}</text>
              </view>
            </view>
          </view>

          <!-- 图片 / PDF -->
          <view class="bl-f">
            <text class="bl-f__label">单据照片或 PDF（可以多选）</text>
            <view class="bl-c__picked">
              <view v-for="(p, i) in caseForm.picked" :key="i" class="bl-c__picked-item">
                <text class="bl-c__picked-name">{{ p.name || ('文件 ' + (i + 1)) }}</text>
                <view class="bl-c__picked-del" role="button" aria-label="移除" @click="removePicked(i)">
                  <text class="bl-c__picked-del-text">✕</text>
                </view>
              </view>
            </view>
            <view class="bl-c__pick-btns">
              <view class="bl-btn bl-btn--ghost bl-c__pick-btn" role="button" @click="pickImage">
                <text class="bl-page-footer__text">拍照 / 选图片</text>
              </view>
              <!-- 选文件（PDF）只在 App/小程序端有；H5 走 input 的方式 -->
              <view class="bl-btn bl-btn--ghost bl-c__pick-btn" role="button" @click="pickPdf">
                <text class="bl-page-footer__text">选 PDF 文件</text>
              </view>
            </view>
          </view>

          <view class="bl-f">
            <text class="bl-f__label">哪家医院（可以不填）</text>
            <view class="bl-f__box">
              <input v-model="caseForm.hospital" class="bl-f__input" placeholder="比如：市第一医院" placeholder-class="bl-input-ph" />
            </view>
          </view>

          <view class="bl-f">
            <text class="bl-f__label">什么时候去的（可以不填）</text>
            <view class="bl-f__box">
              <input v-model="caseForm.visitDate" class="bl-f__input" placeholder="比如：2026-10-01" placeholder-class="bl-input-ph" />
            </view>
          </view>

          <view class="bl-f">
            <text class="bl-f__label">诊断（可以不填，传了文件我会自动读）</text>
            <view class="bl-f__box">
              <input v-model="caseForm.diagnosis" class="bl-f__input" placeholder="比如：高血压3级" placeholder-class="bl-input-ph" />
            </view>
          </view>

          <view class="bl-f">
            <text class="bl-f__label">小结 / 医嘱（可以不填）</text>
            <view class="bl-f__box bl-f__box--area">
              <textarea
                v-model="caseForm.summary"
                class="bl-f__area"
                :maxlength="300"
                placeholder="比如：医生让低盐低脂饮食，一个月后复查"
                placeholder-class="bl-input-ph"
              />
            </view>
          </view>

          <text v-if="caseForm.error" class="bl-f__err bl-sheet__error">{{ caseForm.error }}</text>
          <text v-if="caseForm.busy" class="bl-sheet__hint">{{ caseForm.progress }}</text>
        </scroll-view>

        <view class="bl-sheet__foot">
          <view class="bl-btn bl-btn--ghost bl-sheet__btn" role="button" @click="closeCaseForm">
            <text class="bl-page-footer__text">取消</text>
          </view>
          <view
            class="bl-btn bl-btn--primary bl-sheet__btn"
            :class="{ 'is-busy': caseForm.busy }"
            role="button"
            @click="saveCase"
          >
            <text class="bl-btn__text bl-sheet__btn-text--on">{{ caseForm.busy ? '正在读…' : '保存' }}</text>
          </view>
        </view>
      </view>
    </view>

    <!-- ═══════════ 病历详情 ═══════════ -->
    <view v-if="detail.open" class="bl-sheet">
      <view class="bl-sheet__mask" @click="detail.open = false" />
      <view class="bl-sheet__panel">
        <view class="bl-sheet__head">
          <text class="bl-sheet__title">{{ detail.case.kindLabel || '病历' }}</text>
          <view class="bl-sheet__close" role="button" aria-label="关闭" @click="detail.open = false">
            <text class="bl-sheet__close-text">✕</text>
          </view>
        </view>

        <scroll-view class="bl-sheet__body" scroll-y>
          <view class="bl-d__meta">
            <text v-if="detail.case.visitDate" class="bl-d__meta-line">就诊：{{ detail.case.visitDate.slice(0, 10) }}</text>
            <text v-if="detail.case.hospital" class="bl-d__meta-line">医院：{{ detail.case.hospital }}</text>
          </view>

          <view v-if="detail.case.diagnosis" class="bl-d__block">
            <text class="bl-d__block-title">诊断</text>
            <text class="bl-d__block-text">{{ detail.case.diagnosis }}</text>
          </view>
          <view v-if="detail.case.summary" class="bl-d__block">
            <text class="bl-d__block-title">小结 / 医嘱</text>
            <text class="bl-d__block-text">{{ detail.case.summary }}</text>
          </view>

          <!-- 附件与解析结果 -->
          <view v-for="f in detail.case.files" :key="f.fileId" class="bl-d__file">
            <view class="bl-d__file-head">
              <text class="bl-d__file-name">{{ f.fileType === 'pdf' ? 'PDF' : '照片' }} · {{ f.filename }}</text>
              <view class="bl-d__file-del" role="button" aria-label="删掉这个附件" @click="confirmDeleteFile(f)">
                <text class="bl-d__file-del-text">删除</text>
              </view>
            </view>
            <text v-if="f.extractStatus === 'ok'" class="bl-d__file-status is-ok">读到了文字</text>
            <text v-else-if="f.extractStatus === 'scanned'" class="bl-d__file-status is-warn">
              {{ f.extractReason }}
            </text>
            <text v-else class="bl-d__file-status is-warn">
              {{ f.extractReason || '没能读出文字，你可以自己写诊断' }}
            </text>
            <text v-if="f.extractedText" class="bl-d__file-text">{{ f.extractedText }}</text>
          </view>

          <text v-if="!detail.case.files.length" class="bl-sheet__hint">这份病历没有附件</text>

          <text class="bl-d__note">
            比邻只会照着上面这些内容聊天，不会自己判断病情。
          </text>
        </scroll-view>

        <view class="bl-sheet__foot">
          <view class="bl-btn bl-btn--ghost bl-sheet__btn" role="button" @click="confirmDeleteCase">
            <text class="bl-d__del-text">删掉这份病历</text>
          </view>
          <view class="bl-btn bl-btn--primary bl-sheet__btn" role="button" @click="detail.open = false">
            <text class="bl-btn__text bl-sheet__btn-text--on">知道了</text>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
/**
 * 健康档案 = 两块内容（按需求）
 *
 *  ① **基础数据**：血压 / 血糖 / 体重（只留这三项）
 *     老人自己量的**数值**，看的是趋势
 *  ② **病例病史**：医院单据（图片 / PDF）
 *     医院的**文书**，看的是"医生说过什么"
 *
 * 两块都会注入智能体的人设 prompt（见 server/app/persona/prompts.py），
 * 区别是：基础数据让关心说得出具体数字，病例病史让背景知识准确。
 *
 * 关键设计：**字段不写死在前端**。基础数据的测量项、病例的类型下拉
 * 都由服务端下发（`/v1/health/types`、`/v1/cases/types`），
 * 以后加指标只改服务端一处。
 */
import { computed, reactive, ref } from 'vue'
import { settings } from '@/common/store.js'
import { readToken } from '@/stores/account.js'
import {
  addHealthRecord,
  createCase,
  deleteCase,
  deleteCaseFile,
  deleteHealthRecord,
  fetchCases,
  fetchCaseTypes,
  fetchHealthRecords,
  fetchHealthSummary,
  fetchHealthTypes,
  fetchVisionStatus
} from '@/api/index.js'

const tab = ref('basic')
const summary = ref([])
const history = ref([])
const types = ref([])
const loading = ref(true)

// ---- 病例病史 ----
const cases = ref([])
const caseTypes = ref([])
const vision = ref(null)
const casesLoaded = ref(false)

/** 基础数据的记录弹层 */
const form = reactive({
  open: false, itemType: '', label: '', unit: '', hint: '', range: '',
  fields: [], timings: [], values: {}, timing: '', note: '', errors: {}, error: '', saving: false
})

/** 新建病历弹层 */
const caseForm = reactive({
  open: false, kind: 'outpatient', hospital: '', visitDate: '', diagnosis: '', summary: '',
  picked: [], error: '', busy: false, progress: ''
})

/** 病历详情 */
const detail = reactive({ open: false, case: { files: [] } })

const typeMap = computed(() => {
  const map = {}
  types.value.forEach((t) => { map[t.itemType] = t })
  return map
})

function clockOf(stamp) {
  if (!stamp) return ''
  const d = new Date(stamp)
  if (isNaN(d.getTime())) return ''
  const p = (n) => String(n).padStart(2, '0')
  return (d.getMonth() + 1) + '月' + d.getDate() + '日 ' + p(d.getHours()) + ':' + p(d.getMinutes())
}

function relativeOf(stamp) {
  const at = Date.parse(stamp)
  if (isNaN(at)) return ''
  const min = Math.floor((Date.now() - at) / 60000)
  if (min < 1) return '刚刚'
  if (min < 60) return min + ' 分钟前'
  const hour = Math.floor(min / 60)
  if (hour < 24) return hour + ' 小时前'
  const day = Math.floor(hour / 24)
  if (day < 30) return day + ' 天前'
  return clockOf(stamp)
}

function fileCount(item, type) {
  return (item.files || []).filter((f) => f.fileType === type).length
}

/** 附件解析状态：老人要能一眼看出"读到了没有" */
function statusText(item) {
  const files = item.files || []
  if (files.some((f) => f.extractStatus === 'ok')) return '已读到文字'
  if (files.some((f) => f.extractStatus === 'scanned')) return '扫描件读不出'
  if (files.every((f) => f.extractStatus === 'failed')) return '没读到文字'
  return ''
}

function statusClass(item) {
  const files = item.files || []
  return { 'is-ok': files.some((f) => f.extractStatus === 'ok') }
}

function loadBasic() {
  const token = readToken()
  if (!token) {
    loading.value = false
    uni.showToast({ title: '请先登录', icon: 'none' })
    return
  }
  Promise.all([fetchHealthTypes(), fetchHealthSummary(token), fetchHealthRecords(token, '', 50)])
    .then(([typesRes, summaryRes, recordsRes]) => {
      loading.value = false
      types.value = (typesRes && typesRes.types) || []
      summary.value = (summaryRes && summaryRes.items) || []
      history.value = (recordsRes && recordsRes.records) || []
    })
    .catch((error) => {
      loading.value = false
      uni.showToast({ title: (error && error.message) || '健康档案没拉到', icon: 'none' })
    })
}

function loadCases() {
  const token = readToken()
  if (!token) return
  fetchCases(token)
    .then((data) => {
      casesLoaded.value = true
      cases.value = (data && data.cases) || []
      vision.value = (data && data.vision) || null
    })
    .catch((error) => {
      casesLoaded.value = true
      uni.showToast({ title: (error && error.message) || '病历没拉到', icon: 'none' })
    })
  if (!caseTypes.value.length) {
    fetchCaseTypes()
      .then((data) => { caseTypes.value = (data && data.types) || [] })
      .catch(() => {})
  }
}

loadBasic()
fetchVisionStatus().then((v) => { vision.value = v }).catch(() => {})

function switchToCases() {
  tab.value = 'case'
  if (!casesLoaded.value) loadCases()
  else loadCases()
}

// ---------------------------------------------------------------- 基础数据

function openForm(itemType) {
  const spec = typeMap.value[itemType]
  if (!spec) {
    uni.showToast({ title: '这个测量项暂时不可用', icon: 'none' })
    return
  }
  const values = {}
  spec.fields.forEach((f) => { values[f.key] = '' })
  form.open = true
  form.itemType = itemType
  form.label = spec.label
  form.unit = spec.unit || ''
  form.hint = spec.hint || ''
  form.range = spec.normalRange || ''
  form.fields = spec.fields || []
  form.timings = spec.timings || []
  form.values = values
  form.timing = ''
  form.note = ''
  form.errors = {}
  form.error = ''
  form.saving = false
}

function closeForm() {
  form.open = false
}

function saveRecord() {
  if (form.saving) return
  form.errors = {}
  form.error = ''

  const values = {}
  let missing = ''
  form.fields.forEach((f) => {
    const raw = String(form.values[f.key] == null ? '' : form.values[f.key]).trim()
    if (!raw) {
      if (f.required) missing = f.label
      return
    }
    values[f.key] = raw
  })
  if (missing) {
    form.error = '请填写' + missing
    return
  }
  if (!Object.keys(values).length) {
    form.error = '请至少填一项'
    return
  }
  if (form.timing) values.timing = form.timing

  const token = readToken()
  if (!token) {
    form.error = '请先登录'
    return
  }

  form.saving = true
  addHealthRecord(token, { itemType: form.itemType, values, note: form.note })
    .then(() => {
      form.saving = false
      form.open = false
      uni.showToast({ title: '记下了', icon: 'none' })
      loadBasic()
    })
    .catch((error) => {
      form.saving = false
      // 服务端给的是人话（"高压应该比低压大，是不是填反了"），直接用
      form.error = (error && error.message) || '没存上，再试一次'
    })
}

function confirmDeleteRecord(record) {
  uni.showModal({
    title: '删掉这条记录？',
    content: record.itemLabel + ' ' + record.summary,
    confirmText: '删除',
    cancelText: '再想想',
    success(res) {
      if (!res.confirm) return
      const token = readToken()
      if (!token) return
      deleteHealthRecord(token, record.id)
        .then(() => {
          uni.showToast({ title: '已删除', icon: 'none' })
          loadBasic()
        })
        .catch((error) => {
          uni.showToast({ title: (error && error.message) || '删不掉', icon: 'none' })
        })
    }
  })
}

// ---------------------------------------------------------------- 病例病史

function startNewCase() {
  caseForm.open = true
  caseForm.kind = 'outpatient'
  caseForm.hospital = ''
  caseForm.visitDate = ''
  caseForm.diagnosis = ''
  caseForm.summary = ''
  caseForm.picked = []
  caseForm.error = ''
  caseForm.busy = false
  caseForm.progress = ''
  if (!caseTypes.value.length) {
    fetchCaseTypes().then((data) => { caseTypes.value = (data && data.types) || [] }).catch(() => {})
  }
}

function closeCaseForm() {
  if (caseForm.busy) return
  caseForm.open = false
}

/** 选图片（拍照或相册） */
function pickImage() {
  uni.chooseImage({
    count: 9,
    sizeType: ['compressed'],
    sourceType: ['camera', 'album'],
    success(res) {
      const files = res.tempFilePaths || res.tempFiles || []
      files.forEach((item) => {
        const path = typeof item === 'string' ? item : (item.path || item.tempFilePath)
        if (path) caseForm.picked.push({ name: '照片', uri: path })
      })
    }
  })
}

/**
 * 选 PDF。
 *
 * 分平台：小程序/App 用 `chooseMessageFile`；H5 没有这个 API，
 * 用隐藏的 `<input type=file>` 让浏览器自己弹选择框。
 */
function pickPdf() {
  // #ifdef H5
  if (typeof document === 'undefined') return
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = 'application/pdf'
  input.multiple = true
  input.onchange = () => {
    Array.from(input.files || []).forEach((file) => {
      caseForm.picked.push({ name: file.name, uri: file, isBlob: true })
    })
  }
  input.click()
  return
  // #endif
  // #ifndef H5
  uni.chooseMessageFile({
    count: 5,
    type: 'file',
    extension: ['pdf'],
    success(res) {
      (res.tempFiles || []).forEach((file) => {
        if (String(file.name || '').toLowerCase().endsWith('.pdf')) {
          caseForm.picked.push({ name: file.name, uri: file.path })
        }
      })
    }
  })
  // #endif
}

function removePicked(index) {
  caseForm.picked.splice(index, 1)
}

function saveCase() {
  if (caseForm.busy) return
  const token = readToken()
  if (!token) {
    caseForm.error = '请先登录'
    return
  }
  if (!caseForm.diagnosis.trim() && !caseForm.summary.trim() && !caseForm.picked.length) {
    caseForm.error = '写几个字或者传一张单据都行'
    return
  }

  caseForm.error = ''
  caseForm.busy = true
  caseForm.progress = caseForm.picked.length ? '正在读单据上的字，稍等一下…' : '正在保存…'

  createCase(token, {
    kind: caseForm.kind,
    hospital: caseForm.hospital,
    visitDate: caseForm.visitDate,
    diagnosis: caseForm.diagnosis,
    summary: caseForm.summary,
    files: caseForm.picked
  })
    .then((data) => {
      caseForm.busy = false
      caseForm.open = false
      const problems = (data && data.problems) || []
      if (problems.length) {
        // 附件被拒时病历仍然建起来了，要把原因说清楚
        uni.showModal({ title: '病历存下了，但有个提示', content: problems.join('\n'), showCancel: false })
      } else {
        uni.showToast({ title: '记下了', icon: 'none' })
      }
      loadCases()
    })
    .catch((error) => {
      caseForm.busy = false
      caseForm.progress = ''
      caseForm.error = (error && error.message) || '没存上，再试一次'
    })
}

function openCase(item) {
  const token = readToken()
  if (!token) return
  detail.case = item
  detail.open = true
}

function confirmDeleteFile(file) {
  uni.showModal({
    title: '删掉这个附件？',
    content: file.filename,
    confirmText: '删除',
    cancelText: '再想想',
    success(res) {
      if (!res.confirm) return
      const token = readToken()
      if (!token) return
      deleteCaseFile(token, detail.case.id, file.fileId)
        .then((data) => {
          detail.case = (data && data.case) || detail.case
          uni.showToast({ title: '已删除', icon: 'none' })
          loadCases()
        })
        .catch((error) => {
          uni.showToast({ title: (error && error.message) || '删不掉', icon: 'none' })
        })
    }
  })
}

function confirmDeleteCase() {
  uni.showModal({
    title: '删掉这份病历？',
    content: '附件也会一起删掉',
    confirmText: '删除',
    cancelText: '再想想',
    success(res) {
      if (!res.confirm) return
      const token = readToken()
      if (!token) return
      deleteCase(token, detail.case.id)
        .then(() => {
          detail.open = false
          uni.showToast({ title: '已删除', icon: 'none' })
          loadCases()
        })
        .catch((error) => {
          uni.showToast({ title: (error && error.message) || '删不掉', icon: 'none' })
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
/* ---------- 标签 ---------- */
.bl-tabs {
  display: flex;
  gap: 16rpx;
  padding: var(--bl-space-md) var(--bl-space-lg) 0;
}
.bl-tab {
  flex: 1;
  min-height: var(--bl-touch);
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: var(--bl-surface);
  border: 2rpx solid var(--bl-border-strong);
  border-radius: 999rpx;
  box-sizing: border-box;
}
.bl-tab.is-on { background-color: var(--bl-text); border-color: var(--bl-text); }
.bl-tab__text { font-size: var(--bl-font-body); font-weight: 600; color: var(--bl-text); line-height: 1; }
.bl-tab__text.is-on { color: #FFFDF8; }

/* ---------- 基础数据 ---------- */
.bl-h__head { padding: var(--bl-space-md) var(--bl-space-lg) 0; }
.bl-h__tip { font-size: var(--bl-font-caption); color: var(--bl-text-2); line-height: 1.5; }

.bl-h__list { display: flex; flex-direction: column; gap: 16rpx; padding: var(--bl-space-md) var(--bl-space-lg) 0; }

.bl-h {
  display: flex;
  align-items: center;
  gap: 24rpx;
  padding: 26rpx 28rpx;
  min-height: 140rpx;
  background-color: var(--bl-surface);
  border: 1rpx solid var(--bl-border);
  border-radius: var(--bl-radius-card);
  box-shadow: var(--bl-shadow-card);
  box-sizing: border-box;
}
.bl-h:active { background-color: var(--bl-surface-2); }
.bl-h.is-empty { border-style: dashed; border-color: var(--bl-border-strong); }

.bl-h__main { flex: 1; min-width: 0; }
.bl-h__label { display: block; font-size: var(--bl-font-body); font-weight: 600; color: var(--bl-text); }
.bl-h__value {
  display: block;
  font-size: 40rpx;
  font-weight: 700;
  color: var(--bl-primary);
  margin-top: 6rpx;
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}
.bl-h__empty { display: block; font-size: var(--bl-font-caption); color: var(--bl-text-2); margin-top: 6rpx; }
.bl-h__when, .bl-h__range {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  margin-top: 4rpx;
  line-height: 1.4;
}
.bl-h__add {
  flex: none;
  width: var(--bl-touch);
  height: var(--bl-touch);
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2rpx dashed var(--bl-primary);
  border-radius: 50%;
  box-sizing: border-box;
}
.bl-h__section { padding-top: 32rpx; }
.bl-h__section .bl-section-title--ink { padding: 0 var(--bl-space-lg) 8rpx; }
.bl-h__history {
  display: flex;
  flex-direction: column;
  margin: 8rpx var(--bl-space-lg) 0;
  background-color: var(--bl-surface);
  border: 1rpx solid var(--bl-border);
  border-radius: var(--bl-radius-card);
  box-shadow: var(--bl-shadow-card);
  overflow: hidden;
}
.bl-h__row {
  display: flex;
  align-items: center;
  gap: 20rpx;
  padding: 22rpx 28rpx;
  border-top: 1rpx solid var(--bl-divider);
  box-sizing: border-box;
}
.bl-h__row:first-child { border-top-width: 0; }
.bl-h__row:active { background-color: var(--bl-surface-2); }
.bl-h__row-main { flex: 1; min-width: 0; }
.bl-h__row-label { display: block; font-size: var(--bl-font-caption); color: var(--bl-text-2); }
.bl-h__row-summary {
  display: block;
  font-size: var(--bl-font-body);
  font-weight: 600;
  color: var(--bl-text);
  margin-top: 4rpx;
  font-variant-numeric: tabular-nums;
}
.bl-h__row-time { flex: none; font-size: var(--bl-font-caption); color: var(--bl-text-2); }
.bl-h__hint { display: block; padding: 12rpx var(--bl-space-lg) 0; font-size: var(--bl-font-caption); color: var(--bl-text-2); }

/* ---------- 病例病史 ---------- */
.bl-c__warn {
  margin: var(--bl-space-md) var(--bl-space-lg) 0;
  padding: 20rpx 24rpx;
  background-color: #FDF7EC;
  border: 1rpx solid #E8D5A8;
  border-radius: var(--bl-radius-card);
  box-sizing: border-box;
}
.bl-c__warn-text { font-size: var(--bl-font-caption); color: #8A6A1F; line-height: 1.5; }

.bl-c__new { padding: var(--bl-space-md) var(--bl-space-lg) 0; }
.bl-c__new-hint {
  display: block;
  margin-top: 12rpx;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  text-align: center;
}

.bl-c__list { display: flex; flex-direction: column; gap: 16rpx; padding: var(--bl-space-md) var(--bl-space-lg) 0; }
.bl-c {
  padding: 24rpx 28rpx;
  background-color: var(--bl-surface);
  border: 1rpx solid var(--bl-border);
  border-radius: var(--bl-radius-card);
  box-shadow: var(--bl-shadow-card);
  box-sizing: border-box;
}
.bl-c:active { background-color: var(--bl-surface-2); }
.bl-c__top { display: flex; align-items: center; justify-content: space-between; gap: 16rpx; }
.bl-c__kind {
  font-size: var(--bl-font-caption);
  color: var(--bl-primary);
  background-color: var(--bl-primary-soft);
  padding: 4rpx 14rpx;
  border-radius: 999rpx;
}
.bl-c__date { font-size: var(--bl-font-caption); color: var(--bl-text-2); font-variant-numeric: tabular-nums; }
.bl-c__title {
  display: block;
  font-size: var(--bl-font-body);
  font-weight: 600;
  color: var(--bl-text);
  margin-top: 12rpx;
  line-height: 1.4;
}
.bl-c__hospital { display: block; font-size: var(--bl-font-caption); color: var(--bl-text-2); margin-top: 4rpx; }
.bl-c__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
  margin-top: 12rpx;
}
.bl-c__files { display: flex; flex-wrap: wrap; gap: 12rpx; }
.bl-c__file-tag { font-size: 22rpx; color: var(--bl-text-2); }
.bl-c__status { flex: none; font-size: 22rpx; color: var(--bl-text-2); }
.bl-c__status.is-ok { color: var(--bl-success); }

.bl-c__empty { padding: var(--bl-space-xl) var(--bl-space-lg); }
.bl-c__empty-text { font-size: var(--bl-font-caption); color: var(--bl-text-2); }

.bl-c__picked { display: flex; flex-direction: column; gap: 12rpx; }
.bl-c__picked-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
  padding: 16rpx 20rpx;
  background-color: var(--bl-surface);
  border: 1rpx solid var(--bl-border);
  border-radius: var(--bl-radius-bubble);
  box-sizing: border-box;
}
.bl-c__picked-name { flex: 1; min-width: 0; font-size: var(--bl-font-caption); color: var(--bl-text); }
.bl-c__picked-del {
  flex: none;
  min-width: 60rpx;
  min-height: 60rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}
.bl-c__picked-del-text { font-size: var(--bl-font-body); color: var(--bl-text-2); }
.bl-c__pick-btns { display: flex; gap: 16rpx; margin-top: 16rpx; }
.bl-c__pick-btn { flex: 1; }

/* ---------- 弹层公共 ---------- */
.bl-sheet { position: fixed; left: 0; right: 0; top: 0; bottom: 0; z-index: 70; display: flex; flex-direction: column; justify-content: flex-end; }
.bl-sheet__mask { position: absolute; left: 0; right: 0; top: 0; bottom: 0; background-color: var(--bl-overlay); }
.bl-sheet__panel {
  position: relative;
  background-color: var(--bl-bg);
  border-radius: 32rpx 32rpx 0 0;
  padding: var(--bl-space-lg) var(--bl-space-lg) calc(var(--bl-space-lg) + env(safe-area-inset-bottom));
  box-sizing: border-box;
  max-height: 88vh;
  display: flex;
  flex-direction: column;
}
.bl-sheet__head { flex: none; display: flex; align-items: center; justify-content: space-between; padding-bottom: var(--bl-space-md); }
.bl-sheet__title { font-size: var(--bl-font-title); font-weight: 700; color: var(--bl-text); }
.bl-sheet__close { width: var(--bl-touch); height: var(--bl-touch); display: flex; align-items: center; justify-content: center; border-radius: 50%; }
.bl-sheet__close:active { background-color: var(--bl-primary-soft); }
.bl-sheet__close-text { font-size: var(--bl-font-title); color: var(--bl-text-2); line-height: 1; }
.bl-sheet__body { flex: 1; min-height: 0; }
.bl-sheet__hint { display: block; font-size: var(--bl-font-caption); color: var(--bl-text-2); line-height: 1.5; margin-bottom: var(--bl-space-sm); }
.bl-sheet__ref { display: block; font-size: var(--bl-font-caption); color: var(--bl-text-2); padding-top: var(--bl-space-md); }
.bl-sheet__error { padding-top: var(--bl-space-sm); }

.bl-f { padding-top: var(--bl-space-md); }
.bl-f__label { display: block; font-size: var(--bl-font-caption); color: var(--bl-text-2); letter-spacing: .04em; margin-bottom: var(--bl-space-sm); }
.bl-f__unit { color: var(--bl-text-2); }
.bl-f__box {
  display: flex;
  align-items: center;
  padding: 0 var(--bl-space-md);
  min-height: 104rpx;
  background-color: var(--bl-surface);
  border: 2rpx solid var(--bl-border-strong);
  border-radius: var(--bl-radius-bubble);
  box-sizing: border-box;
}
.bl-f__box:focus-within { border-color: var(--bl-primary); }
.bl-f__box.is-error { border-color: var(--bl-danger); }
.bl-f__box--area { min-height: 160rpx; padding: var(--bl-space-sm) var(--bl-space-md); }
.bl-f__input { flex: 1; min-width: 0; height: 100rpx; font-size: var(--bl-font-body); color: var(--bl-text); font-variant-numeric: tabular-nums; }
.bl-f__area { width: 100%; min-height: 120rpx; font-size: var(--bl-font-body); color: var(--bl-text); line-height: 1.5; }
.bl-f__err { display: block; font-size: var(--bl-font-caption); color: var(--bl-danger); margin-top: 10rpx; line-height: 1.4; }
.bl-f__chips { display: flex; flex-wrap: wrap; gap: 16rpx; }
.bl-f__chip {
  min-height: var(--bl-touch);
  padding: 0 26rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: var(--bl-surface);
  border: 2rpx solid var(--bl-border-strong);
  border-radius: 999rpx;
  box-sizing: border-box;
}
.bl-f__chip-text { font-size: var(--bl-font-body); font-weight: 600; color: var(--bl-text); line-height: 1; }
.bl-f__chip.is-on { background-color: var(--bl-text); border-color: var(--bl-text); }
.bl-f__chip.is-on .bl-f__chip-text { color: #FFFDF8; }

.bl-sheet__foot { flex: none; display: flex; gap: var(--bl-space-md); padding-top: var(--bl-space-lg); }
.bl-sheet__btn { flex: 1; }
.bl-sheet__btn-text--on { color: var(--bl-surface); }
.bl-sheet__foot .is-busy { opacity: .7; }

/* ---------- 病历详情 ---------- */
.bl-d__meta { padding-bottom: var(--bl-space-sm); }
.bl-d__meta-line { display: block; font-size: var(--bl-font-caption); color: var(--bl-text-2); line-height: 1.6; }
.bl-d__block { padding-top: var(--bl-space-md); }
.bl-d__block-title { display: block; font-size: var(--bl-font-caption); color: var(--bl-text-2); letter-spacing: .04em; }
.bl-d__block-text {
  display: block;
  font-size: var(--bl-font-body);
  color: var(--bl-text);
  line-height: 1.6;
  margin-top: 6rpx;
}
.bl-d__file {
  margin-top: var(--bl-space-md);
  padding: 20rpx 24rpx;
  background-color: var(--bl-surface);
  border: 1rpx solid var(--bl-border);
  border-radius: var(--bl-radius-bubble);
  box-sizing: border-box;
}
.bl-d__file-head { display: flex; align-items: center; justify-content: space-between; gap: 16rpx; }
.bl-d__file-name { flex: 1; min-width: 0; font-size: var(--bl-font-caption); color: var(--bl-text); }
.bl-d__file-del { flex: none; min-height: 60rpx; display: flex; align-items: center; padding: 0 8rpx; }
.bl-d__file-del-text { font-size: var(--bl-font-caption); color: var(--bl-danger); }
.bl-d__file-status { display: block; font-size: 22rpx; margin-top: 8rpx; line-height: 1.4; }
.bl-d__file-status.is-ok { color: var(--bl-success); }
.bl-d__file-status.is-warn { color: #8A6A1F; }
.bl-d__file-text {
  display: block;
  font-size: var(--bl-font-caption);
  color: var(--bl-text-2);
  line-height: 1.6;
  margin-top: 8rpx;
  max-height: 400rpx;
  overflow: hidden;
}
.bl-d__note {
  display: block;
  font-size: 22rpx;
  color: var(--bl-text-2);
  line-height: 1.5;
  padding-top: var(--bl-space-lg);
}
.bl-d__del-text { font-size: var(--bl-font-body); color: var(--bl-danger); }
</style>
