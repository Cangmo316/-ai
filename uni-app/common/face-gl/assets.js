/**
 * 比邻AI · 端侧 3D 资产与形象选项（纯数据，零依赖，可在任何端 import）
 * ---------------------------------------------------------------------------
 * 放在 common/face-gl/ 而不是 common/face/：后者是 `E:\blender demo` 交付流水线
 * 生成的只读产物（见其 README「再生成」），渲染层不能混进去，否则下次再生成会被覆盖。
 *
 * 本文件不 import three.js：App 端逻辑层也会 import 它（只为拿形象选项），
 * 不能把 1.2 MB 的 three.js 拖进逻辑层包体。
 */

/**
 * 端侧形象资产。
 *
 * ## 现在只有一个形象：Q 版男医
 *
 * 2026-10-07 按需求**下架了原有女性 / 男性形象**（"暂时不开放"），
 * 只留用户交付的 Q 版男医，并把它设为唯一形象。
 *
 * 为什么还保留 `gender` 这个键、而不是把整套逻辑拆掉：
 * 「数字人形象」页、捏脸页、渲染器都按"当前形象"这个键选资产，
 * 拆掉要动十几处且很容易漏（`face-three.js` 的 load / 幂等判断、
 * `store.js` 的持久化、`face.vue` 的选项渲染）。留一个单键的表，
 * 以后要恢复多形象只需往表里加回几行。
 * ## 资产路径（`role` 决定用哪条，但当前两份指向同一个文件）
 *
 *   · `delivery`（**通话页 / 摄像头入口用这条**）→ `QDoctor_60k.glb`
 *   · `edit`（捏脸页用）→ 同一份
 *
 * ## 为什么用 60k 而不是 306MB 高清件（真机实测结论，2026-10-07）
 *
 * 在**荣耀 AAK-AN00（骁龙 8 Elite / Adreno 830 / Android 16）**上用 Chrome
 * 走 USB devtools 实测：
 *
 *   QDoctor_60k.glb（15MB）   加载 0.64s   56.4 fps   p50 16.6ms   JS堆 125MB
 *   QDoctor_hires.glb（306MB）加载失败 —— RangeError: Array buffer allocation failed
 *
 * 高清件**不是"卡"，是根本分配不出内存**：4,500,071 顶点 × 28 个 morph 目标
 * 要一次性分配几百 MB 的单个 ArrayBuffer，浏览器直接拒绝（与手机总内存无关，
 * 是单 buffer 上限）。所以它在真机上**完全无法加载**。
 *
 * ⚠️ 注意：H5 无头浏览器（软件渲染）能加载它，只有 1.2 fps —— 那个环境内存模型宽松，
 *    不能代表真机。以后判断"能不能用"必须上真机，别信无头浏览器的结论。
 *
 * 高清件另有三条契约缺失（都属"静默失效"，不报错）：
 *   1. **没有 `vis_silence`** → 嘴闭不上（母版唇缝被真实切开，静止姿态就微张）
 *   2. **没有任何 `expr_*`**（眨眼/微笑/皱眉…）→ 表情通道全部无效
 *   3. **没有 `jaw` / `eye` 骨**，且动画叫 `Wave`（渲染器找小写 `wave`）
 *
 * 60k 版已对齐全部契约：18 个 morph（含 `vis_silence` + `expr_blink` 三个）、
 * 动画名 `wave` 小写、骨骼名 camelCase、22 骨含手臂链。
 * 但按用户选择**当前未启用**——要换只改下面这一行。
 */
export const AVATAR_ASSET = Object.freeze({
  qdoctor: 'static/avatar/QDoctor_60k.glb',
})

/**
 * 资产版本号：**只用来破浏览器缓存**。
 *
 * ⚠️ 踩坑（2026-10-05）：资产同名替换后，H5 里仍显示**旧模型**（用户看到的是企鹅玩偶，
 * 而磁盘上早已是白大褂医生）。原因是 URL 没变、浏览器用了缓存副本。
 * 以后**每次重新导出资产都要把这个号加一**，否则改了等于没改。
 */
export const ASSET_VERSION = '8'   // 2026-10-07 真机实测后从 306MB 高清件切回 60k 低模版

/** 口型 / 表情资产（运行期，vis_* / expr_*）。与 AVATAR_ASSET 同源：同一个形象只有一份件。 */
export const AVATAR_DELIVERY_ASSET = Object.freeze({
  qdoctor: 'static/avatar/QDoctor_60k.glb',
})

/**
 * 默认形象。
 *
 * 下架旧形象后它就是唯一选项，所以**摄像头入口拿到的必定是 Q 版男医**。
 * 保留常量是因为渲染器的 `load()` 在收到未知形象名时会回退到它
 * （`const g = AVATAR_ASSET[gender] ? gender : DEFAULT_GENDER`）——
 * 本地存储里如果还存着旧值 `'female'` / `'male'`，靠这个回退纠正。
 */
export const DEFAULT_GENDER = 'qdoctor'

/** 形象选项。目前只有一个：Q 版男医。 */
export const GENDER_OPTIONS = Object.freeze([
  Object.freeze({ value: 'qdoctor', label: 'Q版男医' }),
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
