/**
 * 比邻AI · 端侧 3D 资产与形象选项（纯数据，零依赖，可在任何端 import）
 * ---------------------------------------------------------------------------
 * 放在 common/face-gl/ 而不是 common/face/：后者是 `E:\blender demo` 交付流水线
 * 生成的只读产物（见其 README「再生成」），渲染层不能混进去，否则下次再生成会被覆盖。
 *
 * 本文件不 import three.js：App 端逻辑层也会 import 它（只为拿性别选项），
 * 不能把 1.2 MB 的 three.js 拖进逻辑层包体。
 */

/** 端侧形象资产（2026-10-05 换成 Q 版医生形象：男医 / 女医）。
 *
 * 两份资产都由同一条 Blender 无头管线产出：
 *   OBJ（Y-up）→ 转轴 → 骨架（含左右手臂链，招手用）→ 减面 59k
 *   → 权重 → 口型/表情形态键（vis_* 15 + expr_* 8）→ 招手动画（glTF `wave`）→ 导出
 * 契约：41 骨 / ~59k 三角面 / 23 个 morph / 1 段动画。
 */
export const AVATAR_ASSET = Object.freeze({
  female: 'static/avatar/BilinAI_FemaleFaceRig_60k_edit.glb',
  male: 'static/avatar/BilinAI_MaleFaceRig_60k_edit.glb',
})

/** 口型 / 表情资产（运行期，vis_* / expr_*）。捏脸页不用，视觉模式用，先登记在此避免路径写两处。 */
export const AVATAR_DELIVERY_ASSET = Object.freeze({
  female: 'static/avatar/BilinAI_FemaleFaceRig_60k_delivery_baked.glb',
  male: 'static/avatar/BilinAI_MaleFaceRig_60k_delivery_baked.glb',
})

export const DEFAULT_GENDER = 'female'

/** 形象性别选项。性别只决定加载哪份 .glb，不影响参数表与捏脸结果语义。 */
export const GENDER_OPTIONS = Object.freeze([
  Object.freeze({ value: 'female', label: '女性' }),
  Object.freeze({ value: 'male', label: '男性' }),
])

export function genderLabel(value) {
  const hit = GENDER_OPTIONS.find((g) => g.value === value)
  return hit ? hit.label : GENDER_OPTIONS[0].label
}

/**
 * 资产地址解析。两端 webview 的基准不同，必须分开处理：
 *   H5   → 文档 URL 会随路由变化（pages/face/face），相对路径会拼错，故用站点根；
 *   App  → 页面在 _www/ 下，用站点根会解析到文件系统根（必然 404），故用相对路径。
 */
export function resolveAssetUrl(rel) {
  const p = String(rel == null ? '' : rel).replace(/^\/+/, '')
  const loc = (typeof location !== 'undefined') ? location : null
  if (loc && loc.protocol && /^https?:$/.test(loc.protocol)) return loc.origin + '/' + p
  return p
}

export default { AVATAR_ASSET, AVATAR_DELIVERY_ASSET, DEFAULT_GENDER, GENDER_OPTIONS, genderLabel, resolveAssetUrl }