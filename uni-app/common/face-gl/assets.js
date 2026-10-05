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

/**
 * 资产版本号：**只用来破浏览器缓存**。
 *
 * ⚠️ 踩坑（2026-10-05）：资产同名替换后，H5 里仍显示**旧模型**（用户看到的是企鹅玩偶，
 * 而磁盘上早已是白大褂医生）。原因是 URL 没变、浏览器用了缓存副本。
 * 以后**每次重新导出资产都要把这个号加一**，否则改了等于没改。
 */
export const ASSET_VERSION = '3'   // 2026-10-05 换成正确的新女医资产（旧的是企鹅玩偶）

/** 口型 / 表情资产（运行期，vis_* / expr_*）。捏脸页不用，视觉模式用，先登记在此避免路径写两处。 */
export const AVATAR_DELIVERY_ASSET = Object.freeze({
  female: 'static/avatar/BilinAI_FemaleFaceRig_60k_delivery_baked.glb',
  male: 'static/avatar/BilinAI_MaleFaceRig_60k_delivery_baked.glb',
})

/**
 * 默认性别。
 *
 * ⚠️ 2026-10-05 从 `female` 改成 `male`：用户核对发现「进 3D 模式看到的是企鹅玩偶」——
 * 因为默认加载女那份，而 `3D建模/女医` 里的 OBJ 经几何指纹比对**其实就是企鹅玩偶的网格**
 * （与企鹅资产余弦相似度 0.9679，与男医只有 0.8862），不是穿白大褂的女医。
 * 男医源文件是**正确的白大褂医生**（已渲染确认）。
 * 等用户提供正确的女医资产后再把默认改回或保持，届时重新走一遍管线。
 */
export const DEFAULT_GENDER = 'male'

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
  // 破缓存：**只对 .glb 资产**追加版本号。同名替换资产后浏览器会继续用缓存副本，
  // 实测表现为"磁盘上改了、页面上还是旧模型"（用户看到企鹅玩偶就是这个原因）。
  // 只给 .glb 加，避免给所有静态资源（如解码器 wasm）都带上无意义的参数。
  const versioned = /\.glb$/i.test(p) ? p + '?v=' + ASSET_VERSION : p
  const loc = (typeof location !== 'undefined') ? location : null
  if (loc && loc.protocol && /^https?:$/.test(loc.protocol)) return loc.origin + '/' + versioned
  return versioned
}

export default {
  AVATAR_ASSET, AVATAR_DELIVERY_ASSET, ASSET_VERSION,
  DEFAULT_GENDER, GENDER_OPTIONS, genderLabel, resolveAssetUrl,
}