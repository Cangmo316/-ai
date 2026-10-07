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
 *
 * ## 两条资产路径（`role` 决定用哪条）
 *
 *   · `delivery`（**通话页 / 摄像头入口用这条**）
 *     → `QDoctor_hires.glb`（306MB，用户交付的高清件）
 *   · `edit`（捏脸页用）
 *     → 同一份高清件。下架旧形象后没有单独的编辑期件了。
 *
 * ⚠️ 高清件**不满足渲染器契约**，以下三条是已知的（都是"静默失效"，不报错）：
 *   1. **没有 `vis_silence`** → 嘴闭不上。母版里唇缝被真实切开（开口 2.94mm），
 *      静止姿态本身就是微张，而 `lipsync.js` 靠 `vis_silence=1` 表示闭嘴。
 *   2. **没有任何 `expr_*`**（眨眼/微笑/皱眉…）→ 表情通道全部无效。
 *   3. **没有 `jaw` / `eye` 骨**，且动画叫 `Wave`（渲染器找小写 `wave`）→ 招手不响应。
 *   另：4,491,242 顶点 / 28 个 morph 目标，实测**加载 35.7s、渲染 1.2fps**（软件渲染）。
 *
 * 已对齐契约的低模版备份在 `static/avatar/QDoctor_60k.glb`（15MB / 54.7fps /
 * 含 vis_silence / 动画已改名 wave / 骨骼已改 camelCase），
 * 但按用户选择**当前未启用**——要换只改下面这一行。
 */
export const AVATAR_ASSET = Object.freeze({
  qdoctor: 'static/avatar/QDoctor_hires.glb',
})

/**
 * 资产版本号：**只用来破浏览器缓存**。
 *
 * ⚠️ 踩坑（2026-10-05）：资产同名替换后，H5 里仍显示**旧模型**（用户看到的是企鹅玩偶，
 * 而磁盘上早已是白大褂医生）。原因是 URL 没变、浏览器用了缓存副本。
 * 以后**每次重新导出资产都要把这个号加一**，否则改了等于没改。
 */
export const ASSET_VERSION = '7'   // 2026-10-07 换成用户重新导出的 Q 版男医（checksum DF713DED）

/** 口型 / 表情资产（运行期，vis_* / expr_*）。与 AVATAR_ASSET 同源：同一个形象只有一份件。 */
export const AVATAR_DELIVERY_ASSET = Object.freeze({
  qdoctor: 'static/avatar/QDoctor_hires.glb',
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
