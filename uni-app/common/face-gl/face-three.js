/**
 * 比邻AI · 端侧 3D 捏脸渲染层（方案 A）
 * ---------------------------------------------------------------------------
 * 方案 A 是唯一渲染方案：只在端侧用 WebGL 实时渲染；不做云渲染 B、不做接口预留。
 * 本文件是渲染层的唯一实现，捏脸页（pages/face）与后续视觉模式共用它。
 *
 * 分工（严格单向依赖）：
 *   common/face/face-index.js   逻辑层：参数 → 形态键权重（纯函数，零 I/O，可单测）
 *   common/face-gl/face-three.js 渲染层：权重 → 顶点（three.js / WebGL）  ← 本文件
 *   pages/face/face.vue         宿主：H5 直连 DOM + App 走 renderjs，两条路径都调本文件
 *
 * 硬性约定（交付规范 §7）：
 *   1) morph 一律按 **名字** 定位（mesh.morphTargetDictionary），禁止硬编码 index——
 *      资产重导后 index 会变，名字不会。
 *   2) 骨骼一律按名字取，bindThree() 已内置 `.L` / `_L` 两代骨名互回退。
 *   3) 资产为 1K 贴图 / 无 Draco / 无动画；不引 OrbitControls，不引任何新依赖。
 *
 * 本文件不做任何持久化：读写 storage 由页面负责。
 */

import * as THREE from '../../libs/three/three.module.js'
import { GLTFLoader } from '../../libs/three/GLTFLoader.js'
import { DRACOLoader } from '../../libs/three/DRACOLoader.js'
import { adapter, bindThree, createThrottle, DEFAULT_THROTTLE_HZ } from '../face/face-index.js'

export const FACE_THREE_VERSION = 'face-three/1.0.0'

/**
 * 权重写入节流频率（Hz）。复用逻辑层唯一来源（face-adapter 的 DEFAULT_THROTTLE_HZ=30），
 * 不在渲染层另写一个 30，避免两处漂移。
 */
const DEFAULT_HZ = DEFAULT_THROTTLE_HZ

/**
 * 拖动灵敏度与俯仰限位。自实现最简轨道旋转，刻意不引 OrbitControls（规范 §7：不引新依赖）。
 * yaw / pitch 是「每像素弧度」；pitchLimit 是俯仰硬限位，防止转到脑后把模型翻过去。
 */
const DRAG = Object.freeze({ yaw: 0.008, pitch: 0.005, pitchLimit: 0.55 })

/** 相机纵向视角（度）。30° 接近人像镜头的压缩感，正脸不变形。 */
const FOV = 30

/** 像素比上限。老人机性能弱，3 倍 DPR 只会白烧电，2 倍已足够清晰。 */
const MAX_DPR = 2

/** 构图留白系数。按包围盒算出的贴合距离再放大一点，避免头顶／下巴贴边。 */
const FIT_MARGIN = 2.2   // ⚠️ 实测调参：1.25 时 Q 版医生资产在横画布预览里只露出上半张脸（见任务笔记）

/**
 * 取景框向下越过 head 骨的长度，单位是「头高」。露一点脖子与肩，
 * 免得整张脸贴死在画框上像证件照。
 */
const FOCUS_BELOW_HEAD = 0.45

// 资产路径与性别选项在 ./assets.js（纯数据、零依赖）。这里转出同一份定义，
// 宿主从 face-three.js 或 assets.js import 到的都是同一个对象。
// 资产路径与性别选项在 ./assets.js（纯数据、零依赖）。
// 必须「先 import 再 export」，不能用 `export ... from`：后者只做转发、不建立本地绑定，
// 而本文件内部（load 取资产路径、default 导出）要用到这几个名字，
// 写成 `export ... from` 会在模块求值期抛 ReferenceError: AVATAR_ASSET is not defined，
// 表现为 H5 端整页被 uni-app 的 AsyncError 兜底页接管（「连接服务器超时，点击屏幕重试」）。
import {
  AVATAR_ASSET, AVATAR_DELIVERY_ASSET, DEFAULT_GENDER, GENDER_OPTIONS, genderLabel, resolveAssetUrl,
} from './assets.js'
// 宿主从 face-three.js 或 assets.js import 到的都是同一个对象。
export { AVATAR_ASSET, AVATAR_DELIVERY_ASSET, DEFAULT_GENDER, GENDER_OPTIONS, genderLabel, resolveAssetUrl }

/** 一次遍历建「morph 名 → 拥有它的网格列表」。 */
function collectMorphOwners(root) {
  const owners = new Map()
  root.traverse((n) => {
    if (!n.isMesh || !n.morphTargetDictionary) return
    const d = n.morphTargetDictionary
    for (const name of Object.keys(d)) {
      if (!owners.has(name)) owners.set(name, [])
      owners.get(name).push(n)
    }
  })
  return owners
}

/**
 * 程序化生成一张棚拍感的环境贴图（零额外文件）。
 *
 * 为什么需要它：见场景里 `scene.environment` 的注释——没有环境贴图时，
 * 皮肤的镜面高光只能来自解析灯，又硬又集中，观感就是"偏油亮"。
 *
 * 做法：canvas 画一张上冷下暖的竖向渐变 → 等距圆柱映射 → PMREM 预滤波。
 * 只用于 **IBL（间接光）**，不作为背景显示（renderer 的 clearAlpha 仍为 0，保持透明）。
 */
function createStudioEnvironment(renderer) {
  try {
    const canvas = document.createElement('canvas')
    canvas.width = 64
    canvas.height = 32
    const ctx = canvas.getContext('2d')
    if (!ctx) return null
    const gradient = ctx.createLinearGradient(0, 0, 0, 32)
    gradient.addColorStop(0, '#dfe9f2')     // 顶部：偏冷的天空
    gradient.addColorStop(0.5, '#f2f0ea')   // 中部：中性亮（主反射面）
    gradient.addColorStop(1, '#8f8b84')     // 底部：偏暖的地面反弹
    ctx.fillStyle = gradient
    ctx.fillRect(0, 0, 64, 32)
    const texture = new THREE.CanvasTexture(canvas)
    texture.mapping = THREE.EquirectangularReflectionMapping
    if ('colorSpace' in texture && THREE.SRGBColorSpace) texture.colorSpace = THREE.SRGBColorSpace
    const pmrem = new THREE.PMREMGenerator(renderer)
    pmrem.compileEquirectangularShader()
    const env = pmrem.fromEquirectangular(texture).texture
    pmrem.dispose()
    texture.dispose()
    return env
  } catch (e) {
    // 环境贴图只是观感优化，**失败了不能让数字人加载不出来**，静默退回纯灯光
    return null
  }
}

function disposeObject(root, renderer) {
  if (!root) return
  root.traverse((n) => {
    if (n.geometry && typeof n.geometry.dispose === 'function') n.geometry.dispose()
    const mats = n.material ? (Array.isArray(n.material) ? n.material : [n.material]) : []
    for (const m of mats) {
      for (const k of Object.keys(m)) {
        const v = m[k]
        if (v && v.isTexture && typeof v.dispose === 'function') v.dispose()
      }
      if (typeof m.dispose === 'function') m.dispose()
    }
  })
  void renderer
}

/**
 * 建立 3D 舞台。
 * @param {object} opt
 *   el        {HTMLElement} 容器（舞台会自己往里塞 canvas）
 *   onReady   {Function} 首次加载完成
 *   onError   {Function} 加载/初始化失败（含降级说明）
 *   onStatus  {Function} 状态文案（加载中 / 已就绪 / 参数告警数）
 */
export function createFaceStage(opt) {
  const o = opt || {}
  const el = o.el
  if (!el) throw new Error('face-three: 缺少容器元素 el')

  const canvas = document.createElement('canvas')
  // ⚠️ 画布必须**绝对定位铺满宿主**，而不是靠 `width/height:100%` 参与宿主的 flex 布局：
  //    在通话页那种"竖向 flex 列 + 底部按钮"的布局里，100% 高的画布会把页面挤高、
  //    把下面的按钮顶出视口（实测 body 高度被撑到 485+ 而舞台元素高 520）。
  //    绝对定位后宿主高度由 CSS 决定，画布只负责铺满它。
  canvas.style.cssText = 'display:block;position:absolute;left:0;top:0;width:100%;height:100%;'
    + 'touch-action:none;outline:none;'
  el.appendChild(canvas)

  let renderer = null
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'high-performance' })
  } catch (e) {
    el.removeChild(canvas)
    const err = new Error('WebGL 初始化失败：' + ((e && e.message) || e))
    if (o.onError) o.onError(err)
    throw err
  }

  renderer.setClearAlpha(0)
  if ('outputColorSpace' in renderer && THREE.SRGBColorSpace) renderer.outputColorSpace = THREE.SRGBColorSpace
  renderer.toneMapping = THREE.NoToneMapping

  const scene = new THREE.Scene()
  // 解析灯基准强度（`setLighting` 按比例缩放它们，标定观感时不必改代码重编）
  const LIGHT_BASE = { hemi: 0.75, key: 0.75, fill: 0.35, rim: 0.45 }
  // ── 环境贴图：**修"皮肤偏油亮"的关键**（2026-10-05 实测定因）──
  // 没有 `scene.environment` 时，皮肤上的镜面高光**只能来自解析灯** → 又硬又集中，
  // 观感就是"涂了一层油"。实测（同一模型/相机/灯光，只切换环境贴图）：
  //   无环境贴图：最亮 0.1% 像素均值 231、全图均值 63 → **高光集中度 168**
  //   有环境贴图：                                               → **集中度 115~124（降 26%+）**
  //   且全图均值 63 → 109（暗部被环境光补上，脸不再"半明半暗"）。
  // 环境贴图**程序化生成**（canvas 渐变 → PMREM），不引入任何额外文件，
  // 也避免为一张 HDR 多背几百 KB（本仓库对体积有硬预算）。
  // 要更接近棚拍感可以换 three 的 RoomEnvironment，但那要多带一个模块，先用零依赖方案。
  scene.environment = createStudioEnvironment(renderer)
  // 标定过程（真渲染器离屏取像素，头肩取景）：
  //   env=0.85 灯×1.00 → 均值 85.0  高光集中度 170.0  过曝 2.78%
  //   env=0.60 灯×0.80 → 均值 80.0  高光集中度 175.0  过曝 **0.73%** ← 取这组（拐点）
  //   env=0.45 灯×0.65 → 均值 76.0  高光集中度 179.0  过曝 0.25%（更暗，收益变小）
  // 取"过曝断崖下降、亮度几乎不降"的那一档。要再调可用 `stage.setLighting(env, 灯倍数)`。
  if ('environmentIntensity' in scene) scene.environmentIntensity = SPECULAR_ENV_INTENSITY
  const hemi = new THREE.HemisphereLight(0xFFFFFF, 0x9AA6A0, LIGHT_BASE.hemi * 0.8)
  const keyLight = new THREE.DirectionalLight(0xFFFFFF, LIGHT_BASE.key * 0.8)
  keyLight.position.set(0.55, 0.95, 1.45)
  const fillLight = new THREE.DirectionalLight(0xBFD4E6, LIGHT_BASE.fill * 0.8)
  fillLight.position.set(-1.05, 0.25, 0.65)
  const rimLight = new THREE.DirectionalLight(0xFFFFFF, LIGHT_BASE.rim * 0.8)
  rimLight.position.set(0, 0.65, -1.25)
  scene.add(hemi, keyLight, fillLight, rimLight)

  /**
   * 出厂材质默认值（**每副资产都用它**，不必各页面各传一次）。
   *
   * 依据（真渲染器离屏取像素，女医交付件半身取景）：
   *   金属=1 粗糙×1.0（资产原值）→ 均值 48.4，反光面积 0.22%，过曝 0.083%，集中度 203
   *   金属=0 粗糙×1.0           → 均值 59.1，反光面积 0.10%，过曝 0.045%
   *   **金属=0 粗糙×1.2（采用）** → 均值 58.2，反光面积 **0.01%**，过曝 **0.006%**，集中度 **124**
   *   金属=0 粗糙×1.5           → 均值 57.1（过曝不再降，脸开始发灰）
   *
   * 为什么金属度必须归零：资产自带的 metallic 贴图 B 通道偏高（男医均值 0.259、
   * **女医均值 0.374 且 33.8% 像素 > 0.5**），而这是卡通角色的**皮肤与布料**，
   * 物理上金属度应接近 0 —— 不归零就会有近三分之一表面被当金属渲染（"反光太强"）。
   */
  const DEFAULT_MATERIAL = { metalness: 0, roughnessScale: 1.2 }

  function applyDefaultMaterial() {
    if (!root) return
    setMaterial(DEFAULT_MATERIAL)
  }

  /**
   * 材质校正：**金属度与粗糙度**（治"反光太强/像金属"）。
   *
   * 实测资产自带贴图的通道分布（glTF 规范：G = 粗糙度、B = 金属度）：
   *   男医：R 1.000（AO）/ G 0.469 / B 0.259
   *   女医：R 1.000 / G 0.526 / **B 0.374（33.8% > 0.5）**
   * 另注：three r160 的 `texture.channel` 对 ORM 打包图**不生效**
   * （实测 glTF 里 metalnessMap/roughnessMap 的 `channel` 都是 0），
   * 所以压金属度只能改**材质**的 `metalness`，改不动采样通道。
   */
  function setMaterial(options) {
    const opt = options || {}
    const metal = typeof opt.metalness === 'number' ? Math.max(0, Math.min(1, opt.metalness)) : null
    const roughScale = typeof opt.roughnessScale === 'number' ? Math.max(0.1, Math.min(3, opt.roughnessScale)) : null
    let touched = 0
    scene.traverse((n) => {
      if (!n.isMesh) return
      const list = Array.isArray(n.material) ? n.material : [n.material]
      for (const mat of list) {
        if (!mat) continue
        if (metal !== null && 'metalness' in mat) mat.metalness = metal
        if (roughScale !== null && 'roughness' in mat) mat.roughness = roughScale
        mat.needsUpdate = true
        touched += 1
      }
    })
    renderer.render(scene, camera)
    return { materials: touched, metalness: metal, roughnessScale: roughScale }
  }

  /**
   * `scene.environmentIntensity` 在 three r160（本仓库版本）上**不生效**。
   *
   * 实证：`debug().material.envMapIntensity = 1` 始终不变（该属性由 `scene.environmentIntensity` 赋值），
   * 且场景里没有 `USE_ENVMAP` 宏；不同取值下的像素度量完全一致。
   * 而 `MeshStandardMaterial.envMapIntensity` 是**每材质**生效的，所以 r160 上改走材质。
   * r161+ 恢复用 `scene.environmentIntensity`（见 setLighting 里的版本判断）。
   */
  const ENV_INTENSITY_SUPPORTED = parseInt(THREE.REVISION, 10) >= 161
  const SPECULAR_ENV_INTENSITY = 0.6

  /**
   * 压"皮肤油亮"的**正确那一刀**：只缩**镜面反射**，不碰漫反射。
   *
   * 上一轮我错在"把解析灯降到 0.8×"——那会**同时压暗漫反射**（脸整体发灰），
   * 而"油"只来自镜面项。所以这里把镜面单独做成一个可调乘子：
   * 用户再觉得油，直接调它即可，不会把脸调暗。
   */
  function setSpecular(multiplier) {
    const m = typeof multiplier === 'number' ? Math.max(0, Math.min(2, multiplier)) : 1
    specularMultiplier = m
    if (scene.environment) {
      if (ENV_INTENSITY_SUPPORTED) scene.environmentIntensity = SPECULAR_ENV_INTENSITY * m
      else {
        // r160：逐个材质设 envMapIntensity（这是唯一真正生效的入口）
        scene.traverse((n) => {
          if (!n.isMesh) return
          const list = Array.isArray(n.material) ? n.material : [n.material]
          for (const mat of list) if (mat && 'envMapIntensity' in mat) mat.envMapIntensity = m
        })
      }
    }
    renderer.render(scene, camera)
    return { specularMultiplier: m, supported: ENV_INTENSITY_SUPPORTED }
  }
  let specularMultiplier = 1

  /**
   * 运行时调光（标定"皮肤偏油亮"用）。
   *
   * 为什么做成接口而不是写死常量：这个观感是**要在真机上对着看**才能定的
   * （同一组参数在不同屏幕/不同环境光下感受不同），做参数化后调一次不用改代码重编。
   * `concentration`（高光集中度）从 `measureShading()` 读，两者配合就能定标。
   */
  function setLighting(environmentIntensity, lightScale) {
    const env = typeof environmentIntensity === 'number' ? environmentIntensity : 0.85
    const k = typeof lightScale === 'number' ? lightScale : 1
    if (scene.environment) scene.environmentIntensity = env
    hemi.intensity = LIGHT_BASE.hemi * k
    keyLight.intensity = LIGHT_BASE.key * k
    fillLight.intensity = LIGHT_BASE.fill * k
    rimLight.intensity = LIGHT_BASE.rim * k
    renderer.render(scene, camera)
    return { environmentIntensity: env, lightScale: k }
  }
  // 注：**不要在这里就调 setLighting()** —— 此刻 `camera` 还没定义（下面才 new），
  // 会抛 `ReferenceError: Cannot access 'camera' before initialization`（实测踩到过）。
  // 灯的初值在 `LIGHT_BASE` 里已经是目标值，环境强度在创建时已设，无需额外调用。

  const camera = new THREE.PerspectiveCamera(FOV, 1, 0.01, 400)
  camera.position.set(0, 0, 2)

  const tiltGroup = new THREE.Group()
  const spinGroup = new THREE.Group()
  tiltGroup.add(spinGroup)
  scene.add(tiltGroup)

  let raf = 0
  let alive = true
  let ready = false
  let root = null
  let bound = null
  let morphOwners = new Map()
  let weights = {}
  /**
   * 已被写过的 morph 名。逻辑层只输出 > 0 的权重（face-params.js 里 `if (wUp > 0)`），
   * 滑杆回到 0 时该名字会从 weights 里消失；不主动清零就会残留上一次的形变
   * （脸宽从 +100 直接拉到 -100 时，up / dn 两个目标会同时生效）。
   */
  const morphTouched = new Set()
  let yaw = 0
  let pitch = 0
  let lastCmdWarnings = 0
  let lastLoadMs = 0
  /** 正在加载中 / 当前已加载的性别，用于 load() 的幂等判定。 */
  let loading = false
  let currentGender = null
  /**
   * 当前加载的是哪一份资产：
   *   `edit`     → 编辑期件（捏脸页用，含 shape_*）
   *   `delivery` → 交付件（通话页用，含 vis_* / expr_* 与招手动画）
   * 同一性别在两个页面下要加载两个不同文件，所以 role 必须参与幂等判断。
   */
  let currentRole = null
  // §7 排查用：把"正在加载哪个性别 / 哪个资产地址 / 最近一次错误"记下来，
  // 由 stats() 暴露。没有这几个字段时，"UI 选了男性但模型没换"只能靠肉眼猜。
  let loadingGender = null
  let lastAssetUrl = ''
  let lastError = ''
  /** 构图基准距离（applyFraming 算出），滚轮缩放在它上面做比例。 */
  let baseDist = 2
  /** 最近一次构图实测值（焦点盒 / 全身盒 / 距离 / 画布），供 stats() 暴露给验收诊断。 */
  let frameInfo = null
  /** 取景焦点盒 { center, size }（rest pose）。null = 还没量过。 */
  let focus = null
  /** 上一次画布尺寸，用于「只在尺寸真变了才重新构图」，避免把滚轮缩放顶掉。 */
  let canvasSize = { w: 0, h: 0 }

  /**
   * glTF 加载器 + **Draco 解码**（2026-10-05 引入）。
   *
   * 为什么需要：交付规范 §5 的「`.glb` ≤ 8MB」**前提就是"Draco 压缩后"**，
   * 而 Q 版医生这套 4K 原始贴图在未压缩时导出是 **14.5MB**；开 Draco 后 **6.4MB**。
   * 也就是说：不加解码器就得放宽规范或牺牲贴图/面数，加解码器则**什么都不牺牲**。
   *
   * 解码器按 three 的常规布局放在 **`static/draco/`**（不是 `libs/`）——
   * uni-app 只保证 `static/` 目录在打包时**全量拷贝**，`libs/` 下的 `.wasm` 有被漏掉的风险。
   * 路径用 `resolveAssetUrl`（H5 用站点根、App 用相对路径，两端口径已在 assets.js 里分好）。
   */
  const dracoLoader = new DRACOLoader()
  dracoLoader.setDecoderPath(resolveAssetUrl('static/draco/') + '/')
  // 只用 WASM 解码（不挂 JS 回退版），省掉 700KB 的 draco_decoder.js
  dracoLoader.setDecoderConfig({ type: 'wasm' })

  const loader = new GLTFLoader()
  loader.setDRACOLoader(dracoLoader)

  // ── 动画（"招手互动"用）────────────────────────────────────────────
  // 交付件里带 glTF animation（`wave`），由 AnimationMixer 驱动。
  // 时钟单独持有：不能依赖帧率，否则不同机器上招手快慢不一致。
  let mixer = null
  /** 口型写入计数（诊断用）：能区分「驱动层没调」与「渲染层没写进去」 */
  let visemeWrites = 0
  let lastVisemeApplied = 0
  let clips = []
  /** 手臂基准姿势（A-pose）诊断读数：量不出轴时为 null（保持原样，不乱转） */
  let armRestInfo = null
  /** 程序化招手诊断读数（null = 回落交付件的 wave） */
  let waveGestureInfo = null
  let actions = {}
  let activeClipName = ''
  /**
   * 当前**所有**在跑的片段名。
   *
   * 为什么要一个集合而不是单个字符串：待机系统会**同时**跑两段——
   * 底层的 `Idle` 循环 + 上层的 `Nod`/`wave` 一次性动作。
   * 只记一个名字的话，`stats().playing` 会漏掉一段，排查时看不到真相。
   */
  const playingClips = new Set()
  const clock = new THREE.Clock()

  /**
   * §7 诊断：**渲染瞬间**的 morph 权重快照。
   *
   * 为什么必须单独抓：写完权重后立刻回读只能证明"数组被改了"，
   * 不能证明"画出来的那一帧用的是这个值"（本轮实测踩到：回读 22 个非零，画面却一动不动）。
   * 快照必须在 mixer.update 之后、renderer.render 之前取，才是 GPU 真正拿到的值。
   */
  let renderInfluenceSample = null
  function captureRenderInfluences() {
    let max = -1
    let maxName = ''
    let nonZero = 0
    for (const [name, meshes] of morphOwners) {
      for (const mesh of meshes) {
        const inf = mesh.morphTargetInfluences
        const dict = mesh.morphTargetDictionary
        if (!inf || !dict) continue
        const idx = dict[name]
        if (typeof idx !== 'number') continue
        const v = Number(inf[idx]) || 0
        if (v > 0.001) nonZero += 1
        if (v > max) { max = v; maxName = name }
      }
    }
    renderInfluenceSample = {
      name: maxName,
      max: max < 0 ? null : +max.toFixed(3),
      nonZero,
      frame: renderer && renderer.info ? renderer.info.render.frame : null,
      at: Date.now(),
    }
  }

  function schedule() {
    if (!alive || raf) return
    raf = requestAnimationFrame(() => {
      raf = 0
      if (!alive) return
      if (mixer) mixer.update(clock.getDelta())
      else clock.getDelta()               // 没动画也要推进时钟，避免下次播放跳一大步
      captureRenderInfluences()
      renderer.render(scene, camera)
      // 动画播放期间要持续出帧（原本只在有交互时渲染一次）
      if (mixer && activeClipName) schedule()
    })
  }

  /** 播放指定动画片段（默认 `wave`）。**幂等**：同一段正在播就直接返回。 */
  function playAnimation(name, options) {
    const clipName = name || 'wave'
    if (!mixer || !actions[clipName]) {
      return { ok: false, reason: mixer ? ('没有动画片段 ' + clipName) : '当前资产没有动画（要用交付件 + --animations 导出）' }
    }
    if (activeClipName === clipName && actions[clipName].isRunning()) {
      return { ok: true, name: clipName, alreadyPlaying: true }
    }
    const opt = options || {}
    const action = actions[clipName]
    // 一次性动作要**叠在底层循环之上**（待机时播 Nod，不该把 Idle 掐掉）：
    // 所以一次性动作不重置 mixer、也不改 activeClipName（那是"主循环"的标记）。
    const isOneShot = opt.loop === false
    action.reset()
    action.setLoop(isOneShot ? THREE.LoopOnce : THREE.LoopRepeat, isOneShot ? 1 : Infinity)
    action.clampWhenFinished = isOneShot
    action.timeScale = typeof opt.speed === 'number' ? opt.speed : 1
    // 一次性动作起点比循环更硬一点：0.18s 的淡入会让点头看起来"飘"
    action.fadeIn(isOneShot ? 0.12 : 0.18)
    action.play()
    playingClips.add(clipName)
    if (!isOneShot) activeClipName = clipName
    clock.getDelta()
    schedule()
    return { ok: true, name: clipName, duration: action.getClip().duration, oneShot: isOneShot }
  }

  /** 停止动画并回到静止姿势。 */
  function stopAnimation() {
    if (!mixer) return { ok: false, reason: '当前资产没有动画' }
    for (const name of Object.keys(actions)) actions[name].stop()
    activeClipName = ''
    playingClips.clear()
    // 停完要立刻出帧，否则画面会停在最后一帧的动作上
    renderer.render(scene, camera)
    return { ok: true }
  }

  /* ─────────────────── 待机动作：不定时随机触发 ─────────────────── */

  /**
   * 待机动作池（**只放不会位移的片段**）。
   *
   * 实测各片段的根位移（`E:\UI\.uni-shot\probe-anims.mjs` 量的）：
   *   Nod / Turn / wave / waveBye / IdleToWalk / WalkToIdle → 0 m（纯姿势，安全）
   *   Sit   → 0.100 m（髋部下沉）
   *   Walk  → 0.308 m，WalkTalk → 0.308 m  ← **会走出画面，绝不能放进待机池**
   *
   * 所以 Walk / WalkTalk / Sit 全部排除。前两个是"位移"问题，
   * Sit 是"坐下再站起来"——站立特写下突然蹲一下很怪。
   *
   * `weight` 是相对权重：打招呼比点头少见，纯待机循环最常见。
   */
  const IDLE_GESTURES = [
    { clip: 'Idle', weight: 3 },
    { clip: 'Nod', weight: 2 },
    { clip: 'Turn', weight: 1 },
    { clip: 'wave', weight: 1 },
    { clip: 'waveBye', weight: 1 },
  ]

  /** 待机参数：第一次动作的延迟、两次动作的间隔范围、随机数的可注入实现（便于测试） */
  const IDLE_CONFIG = {
    firstDelayMs: [2500, 6000],
    intervalMs: [9000, 26000],
    //: 上面两个区间会被外部覆盖（页面可调），这里只是默认
  }

  let idleTimer = null
  let idleRunning = false
  let idleLastPick = ''
  let idleFired = 0
  let idleRandom = Math.random

  /** 按权重随机挑一个待机动作；**避免连续两次同一个**（连播点头很假） */
  function pickIdleClip() {
    const pool = IDLE_GESTURES.filter((g) => actions[g.clip] && (g.clip !== idleLastPick || IDLE_GESTURES.length === 1))
    const usable = pool.length ? pool : IDLE_GESTURES.filter((g) => actions[g.clip])
    if (!usable.length) return ''
    const total = usable.reduce((sum, g) => sum + g.weight, 0)
    let roll = idleRandom() * total
    for (const g of usable) {
      roll -= g.weight
      if (roll <= 0) return g.clip
    }
    return usable[usable.length - 1].clip
  }

  function scheduleNextIdle(first) {
    if (!idleRunning) return
    const range = first ? IDLE_CONFIG.firstDelayMs : IDLE_CONFIG.intervalMs
    const wait = range[0] + idleRandom() * Math.max(0, range[1] - range[0])
    idleTimer = setTimeout(() => {
      idleTimer = null
      if (!idleRunning || !ready || !mixer) return
      const clip = pickIdleClip()
      if (clip) {
        // 循环类（Idle）走主循环；一次性（Nod/wave…）叠在底层之上。
        // 真在说话时**跳过这一次**——嘴里在动、人还在点头，看着不像在听人说话。
        const oneShot = clip !== 'Idle'
        if (!oneShot || !activeClipName || activeClipName === 'Idle') {
          // 一次性动作若正在跑，等它跑完再排下一次，避免动作叠加打结
          const busy = [...playingClips].some((n) => n !== 'Idle' && actions[n] && actions[n].isRunning())
          if (!busy) {
            const result = playAnimation(clip, oneShot ? { loop: false } : undefined)
            if (result && result.ok) {
              idleLastPick = clip
              idleFired += 1
            }
          }
        }
      }
      // 一次性动作按它自己的时长多等一会儿，别在动作没做完时又切一个
      const extra = idleLastPick && idleLastPick !== 'Idle'
        && actions[idleLastPick] && actions[idleLastPick].isRunning()
        ? actions[idleLastPick].getClip().duration * 1000
        : 0
      if (extra) {
        idleTimer = setTimeout(() => { idleTimer = null; scheduleNextIdle(false) }, extra)
      } else {
        scheduleNextIdle(false)
      }
    }, wait)
  }

  /**
   * 开始待机动作。
   *
   * @param {object} [options]
   * @param {number[]} [options.firstDelayMs] 第一次动作的延迟区间 [min,max]
   * @param {number[]} [options.intervalMs]   两次动作的间隔区间 [min,max]
   * @param {Function} [options.random]       随机数实现（**测试时注入确定性实现**）
   */
  function startIdle(options) {
    const opt = options || {}
    if (Array.isArray(opt.firstDelayMs) && opt.firstDelayMs.length === 2) IDLE_CONFIG.firstDelayMs = opt.firstDelayMs
    if (Array.isArray(opt.intervalMs) && opt.intervalMs.length === 2) IDLE_CONFIG.intervalMs = opt.intervalMs
    idleRandom = typeof opt.random === 'function' ? opt.random : Math.random
    if (idleRunning) return { ok: true, alreadyRunning: true, clips: clips.map((c) => c.name) }
    if (!mixer || !clips.length) return { ok: false, reason: '当前资产没有动画片段' }
    idleRunning = true
    idleFired = 0
    // 先把 Idle 循环起起来：静止 T-pose 站着最假，这是待机的底色
    if (actions.Idle) playAnimation('Idle')
    scheduleNextIdle(true)
    return { ok: true, clips: clips.map((c) => c.name), pool: IDLE_GESTURES.map((g) => g.clip) }
  }

  /** 停止待机动作（离开页面时必须调用，否则定时器会在后台一直跑） */
  function stopIdle() {
    idleRunning = false
    if (idleTimer) { clearTimeout(idleTimer); idleTimer = null }
    return { ok: true, fired: idleFired }
  }

  /** 待机系统的自检读数（排查"到底有没有在触发"） */
  function idleStats() {
    return {
      running: idleRunning,
      fired: idleFired,
      lastPick: idleLastPick,
      pool: IDLE_GESTURES.map((g) => g.clip),
      hasTimer: !!idleTimer,
      // 列表里哪些片段真的存在（资产缺片段时能一眼看出来）
      available: IDLE_GESTURES.filter((g) => actions[g.clip]).map((g) => g.clip),
      missing: IDLE_GESTURES.filter((g) => !actions[g.clip]).map((g) => g.clip),
    }
  }

  /**
   * 口型驱动：把「viseme 名 → 权重」写成形态键影响值。
   * 与 `applyWeights` 分开，是因为这两条通道会同时工作（口型来自语音，表情来自交互），
   * 合在一起会互相覆盖。名字必须是 `vis_*` / `expr_*`（交付件命名空间）。
   */
  function setVisemes(next) {
    if (!next) return 0
    // ⚠️ 兜底：`morphOwners` 为空时**按需重建**。
    //    实测（2026-10-05）：交付件在 load 期间收集到的 owners 是空的
    //    （`setVisemes` 直接调用返回 applied=0，而 `stats()` 却能报出 23 个形态键——
    //      因为 stats 走的是另一条读法）。没有这个兜底，口型会**静默失效**：
    //      驱动层照常每帧调用、日志与计数都是 0，脸上一点不动。
    if (!morphOwners.size && root) morphOwners = collectMorphOwners(root)
    let applied = 0
    for (const [name, meshes] of morphOwners) {
      const value = Number(next[name])
      if (!Number.isFinite(value)) continue
      const clamped = Math.max(0, Math.min(1, value))
      for (const mesh of meshes) {
        if (!mesh.morphTargetDictionary || !mesh.morphTargetInfluences) continue
        const index = mesh.morphTargetDictionary[name]
        if (typeof index === 'number') {
          mesh.morphTargetInfluences[index] = clamped
          applied += 1
        }
      }
    }
    // **只写权重、不主动渲染**：口型由 30Hz 驱动层（lipsync.js）逐帧调用，
    // 渲染交给 schedule() 的动画帧 —— 每次调用都同步渲染会变成"一帧渲两次"。
    if (applied) schedule()
    visemeWrites += applied
    lastVisemeApplied = applied
    return applied
  }

  function measure() {
    const w = Math.max(1, Math.round(el.clientWidth || el.offsetWidth || 1))
    const h = Math.max(1, Math.round(el.clientHeight || el.offsetHeight || 1))
    return { w, h }
  }

  /**
   * 量几何体「静止姿态」包围盒。
   *
   * 不能用 Box3.setFromObject(root)：对 SkinnedMesh，three 走的是蒙皮包围盒
   * （object.boundingBox），而它依赖 skeleton.boneMatrices 是否已更新。
   * 实测在首帧之前拿到的是错的 —— size.y = 0.9111（真值 1.1882）、
   * center.y = 0.4484（真值 0.5941），于是模型被放大 1.3 倍并整体上移、头顶被裁。
   * 这里改成直接读顶点的 rest pose，与 glTF accessor 的 min/max 完全一致。
   */
  function restBoxOf(obj) {
    const box = new THREE.Box3()
    const tmp = new THREE.Box3()
    obj.traverse((n) => {
      if (!n.isMesh || !n.geometry) return
      if (!n.geometry.boundingBox) n.geometry.computeBoundingBox()
      if (!n.geometry.boundingBox) return
      tmp.copy(n.geometry.boundingBox).applyMatrix4(n.matrixWorld)
      box.union(tmp)
    })
    return box
  }

  /** 逐顶点取「y ≥ cutY」那一段的包围盒，用来把取景框收到头部。 */
  function boxAbove(obj, cutY) {
    const box = new THREE.Box3()
    const v = new THREE.Vector3()
    obj.traverse((n) => {
      if (!n.isMesh || !n.geometry || !n.geometry.attributes || !n.geometry.attributes.position) return
      const pos = n.geometry.attributes.position
      const m = n.matrixWorld
      for (let i = 0; i < pos.count; i += 1) {
        v.fromBufferAttribute(pos, i).applyMatrix4(m)
        if (v.y >= cutY) box.expandByPoint(v)
      }
    })
    return box
  }

  /**
   * 算取景焦点盒，并把焦点盒中心平移到原点。
   *
   * 为什么不按全身包围盒构图：这是捏脸页，三条滑杆（脸宽 / 眼睛大小 / 年龄感）全作用在脸上，
   * 而资产是**全身**模型（高 1.1882），脸只占身高 1/8 左右；
   * 按全身构图时脸只有几十像素，滑杆动了也看不出来。
   * 故以 rig 的 head 骨为基准：上取到头顶，下探 FOCUS_BELOW_HEAD 个头高（带出脖子与肩）。
   *
   * root 自身无旋转（实测 FaceRig 是单位变换），故「position = -center」等价于把焦点盒
   * 平移到原点，围绕原点的 Y 轴旋转就是「绕头部中轴转头」；用 copy+negate 而非 sub()，
   * 保证重复调用不会二次平移。
   */
  /**
   * 当前取景模式：`'head'`（捏脸页看脸）/ `'bust'`（通话页看半身）/ `'body'`（全身）。
   * 由 `load()` 的 `frameMode` 选项设置；默认 head 保持既有行为。
   */
  let focusMode = 'head'
  /**
   * 构图松紧（乘在 Fit 距离上，越小人物越大）。
   * 默认 `FIT_MARGIN`（= 捏脸页调出来的松紧）；通话页传更小的值让人物撑满画面。
   */
  let fitMargin = FIT_MARGIN
  /**
   * 垂直构图偏移（取景框高度的比例，**正值把人物往上放**）。
   *
   * 只对 `bust`（通话页半身）生效。默认 0 保持既有构图；
   * 通话页传正值——半身取景下人物的头容易偏下、下巴离底部按钮太近。
   */
  let frameLiftY = 0

  function computeFocus() {
    if (!root) return
    root.position.set(0, 0, 0)
    root.updateWorldMatrix(true, true)
    const body = restBoxOf(root)

    // ── 半身取景（通话页用）──
    // 全身取景虽然"完整"，但在通话页里人物只占画面高度约 **53%**（可见高 2.18 vs 身高 1.15），
    // 看着就是"人很小、四周一圈空"。通话场景本来就该是**半身/胸像**（和视频通话一样），
    // 所以这里截"胯以上"：上到头顶、下到身体中心再往下 12%，高度约占身高 60%，人物能撑满画面。
    if (focusMode === 'bust') {
      const box = boxAbove(root, body.min.y + (body.max.y - body.min.y) * 0.38)
      const center = (box.isEmpty() ? body : box).getCenter(new THREE.Vector3())
      const size = (box.isEmpty() ? body : box).getSize(new THREE.Vector3())
      size.y *= 1.02
      // 垂直构图偏移：**正值把人物往上放**。
      //
      // 为什么需要这个：镜头固定在 `(0,0,dist)` 且模型被 `-center` 归零，
      // 于是"取景框的中心"就等于 `center` —— 把 `center.y` 抬上去，
      // 模型在画面里就整体上移。取景框高度是 `size.y`，
      // 所以偏移用**比例**表示（0.06 = 抬高约 6% 的画面高），换资产/换屏都还有意义。
      center.y += size.y * frameLiftY
      root.position.copy(center).negate()
      root.updateWorldMatrix(true, true)
      focus = { center, size }
      frameInfo = {
        mode: 'bust',
        liftY: +frameLiftY.toFixed(4),
        focus: [+size.x.toFixed(4), +size.y.toFixed(4), +size.z.toFixed(4)],
        body: [+(body.max.x - body.min.x).toFixed(4),
               +(body.max.y - body.min.y).toFixed(4),
               +(body.max.z - body.min.z).toFixed(4)],
        center: [+center.x.toFixed(4), +center.y.toFixed(4), +center.z.toFixed(4)],
      }
      return
    }

    // ── 全身取景（保留：需要在画面里看到完整站姿时用）──
    if (focusMode === 'body') {
      const center = body.getCenter(new THREE.Vector3())
      const size = body.getSize(new THREE.Vector3())
      size.multiplyScalar(1.06)          // 留一点边，避免脚尖/头顶贴边
      root.position.copy(center).negate()
      root.updateWorldMatrix(true, true)
      focus = { center, size }
      frameInfo = {
        mode: 'body',
        focus: [+size.x.toFixed(4), +size.y.toFixed(4), +size.z.toFixed(4)],
        body: [+(body.max.x - body.min.x).toFixed(4),
               +(body.max.y - body.min.y).toFixed(4),
               +(body.max.z - body.min.z).toFixed(4)],
        center: [+center.x.toFixed(4), +center.y.toFixed(4), +center.z.toFixed(4)],
      }
      return
    }
    const headBone = bound ? bound.getBone('head') : null
    let headY = null
    if (headBone) {
      headBone.updateWorldMatrix(true, false)
      headY = headBone.matrixWorld.elements[13]
    }
    const bodyH = body.max.y - body.min.y
    // 兜底：拿不到 head 骨时按「身高 1/7.5 是头」的经验比例推一个
    if (!(headY > body.min.y && headY < body.max.y)) headY = body.max.y - bodyH / 7.5

    // ⚠️ **不要只信 head 骨**（2026-10-05 换成 Q 版医生资产时踩到）：
    //    head 骨在"下巴稍下"，而 Q 版角色的**头发体积很高**，于是"单头高度"被算小
    //    （实测 headRatio 只有 0.13，而真实头身比约 0.3~0.4），取景框偏上、**下半张脸被切**。
    //    这里改成**用几何实测头高**：取"头顶到下巴"的 z 跨度——头顶取 body 顶点最高处，
    //    下巴用 head 骨往下一点（骨在下巴附近，往下 10% 身高兜住下巴）。
    const chinGuess = Math.min(headY + bodyH * 0.02, body.max.y - bodyH * 0.05)
    const headTop = body.max.y
    const measuredHeadH = Math.max(headTop - chinGuess, bodyH * 0.15)
    // 两个估计取**更大**的那个（宁可多留，不要切脸）
    const headH = Math.max(Math.max(1e-4, headTop - headY), measuredHeadH)
    // 构图余量按头身比自适应（成人 7.5 头身 → 余量小；Q 版大头 → 余量大）
    const headRatio = headH / Math.max(bodyH, 1e-6)
    const below = FOCUS_BELOW_HEAD * Math.max(1, 0.22 / Math.max(headRatio, 1e-6))
    const cutY = headTop - headH - below * headH * 0.35
    const head = boxAbove(root, cutY)
    let box = head.isEmpty() ? body : head
    // 头部包围盒再放宽一点（头发、耳朵与侧转余量）
    {
      const center0 = box.getCenter(new THREE.Vector3())
      const size0 = box.getSize(new THREE.Vector3())
      size0.multiplyScalar(1.15)
      const min = center0.clone().sub(size0.clone().multiplyScalar(0.5))
      const max = center0.clone().add(size0.clone().multiplyScalar(0.5))
      box = new THREE.Box3(min, max)
    }
    // ⚠️ 最后一步关键：把取景盒**补成与画布同纵横比**。
    //    预览区是横的（aspect≈1.37），若盒子比画布更"方"，等比取景会按宽度对齐、
    //    竖直方向溢出 → 脸被切。按画布 aspect 补高（或补宽）即可彻底消除这类裁切。
    {
      const canvas = measure()
      const aspect = canvas.h > 0 ? canvas.w / canvas.h : 1
      const center0 = box.getCenter(new THREE.Vector3())
      const size0 = box.getSize(new THREE.Vector3())
      const width = Math.max(size0.x, size0.z, 1e-4)
      const height = Math.max(size0.y, 1e-4)
      // 需要的世界高 = 宽 / aspect（横画布下通常要更高）
      const neededH = width / Math.max(aspect, 1e-4)
      const neededW = height * aspect
      if (neededH > height) size0.y = neededH
      if (neededW > width) {
        const grow = neededW / width
        size0.x *= grow
        size0.z *= grow
      }
      const min = center0.clone().sub(size0.clone().multiplyScalar(0.5))
      const max = center0.clone().add(size0.clone().multiplyScalar(0.5))
      box = new THREE.Box3(min, max)
    }
    const center = box.getCenter(new THREE.Vector3())
    const size = box.getSize(new THREE.Vector3())
    root.position.copy(center).negate()
    root.updateWorldMatrix(true, true)
    focus = { center, size }
    frameInfo = {
      focus: [+size.x.toFixed(4), +size.y.toFixed(4), +size.z.toFixed(4)],
      body: [+(body.max.x - body.min.x).toFixed(4), +bodyH.toFixed(4), +(body.max.z - body.min.z).toFixed(4)],
      center: [+center.x.toFixed(4), +center.y.toFixed(4), +center.z.toFixed(4)],
      headY: +headY.toFixed(4), cutY: +cutY.toFixed(4),
      headRatio: +headRatio.toFixed(3),
    }
  }

  /**
   * 按当前画布宽高比把焦点盒装满画面。
   * 水平方向取 size.x / size.z 的较大者：转头到 90° 时原本的「厚度」会变成宽度，
   * 不预留就会在转到侧面时切边。
   */
  function applyFraming() {
    if (!focus) return
    const { w, h } = measure()
    const aspect = w / h
    const tan = Math.tan((FOV / 2) * Math.PI / 180)
    const distV = (focus.size.y / 2) / tan
    const spanH = Math.max(focus.size.x, focus.size.z)
    const distH = (spanH / 2) / (tan * aspect)
    // ⚠️ 这里的 1.25/2.2 是**捏脸页**调出来的（预览区是横的、且要留头部转动余量）。
    //    通话页是竖屏、要"人看着够大"，沿用这个松紧会只剩约 45% 画面高度。
    //    故把松紧做成可配：`load(..., {fitMargin})`。
    const dist = Math.max(distV, distH) * fitMargin
    baseDist = dist
    camera.position.set(0, 0, dist)
    camera.near = Math.max(0.005, dist / 100)
    camera.far = dist * 20
    camera.updateProjectionMatrix()
    if (frameInfo) {
      frameInfo.dist = +dist.toFixed(4)
      frameInfo.aspect = +aspect.toFixed(4)
      frameInfo.canvas = { w, h }
    }
  }

  function resize() {
    const { w, h } = measure()
    const changed = (w !== canvasSize.w || h !== canvasSize.h)
    canvasSize = { w, h }
    const dpr = Math.min((typeof devicePixelRatio === 'number' ? devicePixelRatio : 1) || 1, MAX_DPR)
    renderer.setPixelRatio(dpr)
    renderer.setSize(w, h, false)
    camera.aspect = w / h
    camera.updateProjectionMatrix()
    if (changed) applyFraming()
    schedule()
  }

    function applyCommands(cmds) {
    if (!bound) return
    const r = adapter.applyToModel(bound, cmds)
    lastCmdWarnings = (r && r.warnings ? r.warnings.length : 0)
  }

  /**
   * 写形态键权重。
   * 走逻辑层的 adapter 算好的指令（按名字查字典），再补一处已知盲区：
   * adapter.getMorph() 只命中「第一个」拥有该名字的网格，而实测资产里
   * shape_mouth_width/height/protrusion 六个目标同时挂在 node_0 / mouth_cavity /
   * teeth / tongue 上；只写主网格会让口腔与牙齿不跟随嘴型。这里补齐其余网格。
   */
  /** 把「只含正值」的权重补成「全量」：上一轮写过、这一轮没出现的名字一律补 0。 */
  function normalizeWeights(next) {
    const full = {}
    for (const n of morphTouched) full[n] = 0
    const src = next || {}
    for (const n of Object.keys(src)) full[n] = src[n]
    morphTouched.clear()
    for (const n of Object.keys(full)) morphTouched.add(n)
    return full
  }

  /**
   * 写「整包四通道指令」：morph / bone / material / asset。
   *
   * 背景（实测缺口）：旧版 applyWeights 只发 morphs，其余三通道恒传空对象，
   * 于是 bones（脖子粗细、眼球转动等 6 条 bone 参数）与 materials（肤色/唇色/牙齿色
   * 等 27 条材质参数）在界面上"能拖但不动"。这里整包下发，交给 adapter.applyToModel
   * 的四通道实现（bindThree 已提供 getBone / getMaterial 视图）。
   *
   * morph 仍走 normalizeWeights 补零：上一轮写过、这一轮没出现的名字必须归零，
   * 否则拖完 A 参数留下的形变会一直挂在模型上。
   */
  function applyCommandPack(cmds) {
    const pack = cmds || {}
    weights = normalizeWeights(pack.morphs || {})
    if (!bound) return 0
    applyCommands({
      morphs: weights,
      bones: pack.bones || {},
      materials: pack.materials || {},
      assets: pack.assets || {},
      channels: pack.channels || {}
    })
    let patched = 0
    for (const [name, list] of morphOwners) {
      if (list.length < 2) continue
      if (!Object.prototype.hasOwnProperty.call(weights, name)) continue
      for (const mesh of list) {
        const idx = mesh.morphTargetDictionary ? mesh.morphTargetDictionary[name] : undefined
        if (typeof idx === 'number' && mesh.morphTargetInfluences) mesh.morphTargetInfluences[idx] = weights[name]
      }
      patched += 1
    }
    schedule()
    return patched
  }

  /** 兼容旧接口：只发 morphs 时等价于「只含 morph 通道的整包」。 */
  function applyWeights(next) {
    return applyCommandPack({ morphs: next || {} })
  }

  const throttle = createThrottle((w) => applyCommandPack({ morphs: w }), { hz: DEFAULT_HZ })
  /** 整包节流通道：面板拖动时按 30Hz 下发四通道指令 */
  const commandThrottle = createThrottle((c) => applyCommandPack(c), { hz: DEFAULT_HZ })

  function rotate(nextYaw, nextPitch) {
    yaw = Number(nextYaw) || 0
    const limit = DRAG.pitchLimit
    const p = Number(nextPitch) || 0
    pitch = Math.max(-limit, Math.min(limit, p))
    spinGroup.rotation.y = yaw
    tiltGroup.rotation.x = pitch
    schedule()
  }

  /** 收到宿主下发的完整状态：{ commands, weights, yaw, pitch }。 */
  function applyPayload(payload) {
    if (!payload) return
    if (payload.commands) applyCommandPack(payload.commands)
    if (payload.weights) applyWeights(payload.weights)
    if (payload.yaw !== undefined || payload.pitch !== undefined) rotate(payload.yaw, payload.pitch)
  }

  function dispose() {
    alive = false
    try {
      canvas.removeEventListener('pointerdown', onDown)
      canvas.removeEventListener('pointermove', onMove)
      canvas.removeEventListener('pointerup', onUp)
      canvas.removeEventListener('pointercancel', onUp)
      canvas.removeEventListener('touchstart', onDown)
      canvas.removeEventListener('touchmove', onMove)
      canvas.removeEventListener('touchend', onUp)
      canvas.removeEventListener('touchcancel', onUp)
      canvas.removeEventListener('mousedown', onDown)
      canvas.removeEventListener('wheel', onWheel)
      if (typeof window !== 'undefined') {
        window.removeEventListener('mousemove', onMove)
        window.removeEventListener('mouseup', onUp)
      }
    } catch (e) { void e }
    if (raf) { cancelAnimationFrame(raf); raf = 0 }
    throttle.reset()
    // 动画与解码器都要跟着拆：mixer 不停会继续驱动已 dispose 的骨骼（报错或闪帧），
    // dracoLoader 持有 wasm worker，不 terminate 会在反复进出页面时堆积。
    if (mixer) { try { mixer.stopAllAction(); mixer.uncacheRoot(root || spinGroup) } catch (e) { void e } }
    mixer = null
    actions = {}
    clips = []
    activeClipName = ''
    // 待机定时器必须在这里停掉：舞台都拆了，定时器再触发会去碰已释放的骨骼
    stopIdle()
    playingClips.clear()
    waveGestureInfo = null
    try { dracoLoader.dispose() } catch (e) { void e }
    // 环境贴图是 GPU 资源，舞台销毁时要显式释放（否则反复进出页面会漏显存）
    if (scene && scene.environment) {
      try { scene.environment.dispose() } catch (e) { void e }
      scene.environment = null
    }
    disposeObject(root, renderer)
    if (root) spinGroup.remove(root)
    root = null
    bound = null
    focus = null
    morphOwners = new Map()
    morphTouched.clear()
    try { renderer.dispose() } catch (e) { void e }
    try { renderer.forceContextLoss() } catch (e) { void e }
    if (canvas.parentNode) canvas.parentNode.removeChild(canvas)
  }

  /**
   * 加载（或切换）形象资产。切性别时复用同一舞台，只换模型。
   *
   * ⚠️ 两个实测过的坑（§7 排查）：
   *   1. **失败必须把 `loading`/`ready` 复位**：否则一次加载失败后，
   *      后面所有 `load()` 都会被"幂等守卫"挡掉（切性别永远不生效、也不报错）。
   *   2. 状态要能被外部观测：`stats()` 里带 `gender` / `asset` / `lastError`，
   *      否则"UI 选了男性但模型没换"这种问题只能靠肉眼猜。
   */
/* ─────────────────── 手臂基准姿势：把交付件的 T-pose 收成「自然下垂」 ─────────────────── */

/**
 * 静息姿势是 T-pose 的资产**怎么调都假**：不讲话时两臂平举像稻草人，
 * 挥手也只是「从平举刻度上抖一下」。所以给手臂叠一层「自然下垂」基准（A-pose）。
 *
 * 三步：
 *   1. **实测轴**：逐个候选局部轴把上臂转一次，量 `hand.*` 的**世界 Y 下降最多**那组。
 *      交付件过了外轴（Y-up→Z-up）后局部轴与直觉不一致，写死 `rotation_euler[2]`
 *      会让手前后晃而不是上下动 —— Blender 侧 `tools/blender-wave-anim.py` 踩过同一个坑，
 *      那里的做法同样是「实测」。
 *   2. **有动画轨道的骨**：把偏移**乘进每个关键帧**（`q → q * offset`）。glTF 四元数插值
 *      是逐段 slerp，而 `slerp(q0*p, q1*p) = slerp(q0,q1)*p`，所以「后乘常量」对动作**无损**，
 *      只是把整段动画搬到下垂基准上播。关键是**不要在每帧和 AnimationMixer 抢着写骨骼**：
 *      谁先谁后、动作停了要不要补一次，都会变成「姿势闪一下」这种很难查的 bug。
 *   3. **没有动画轨道的骨**：直接把偏移写进骨骼静息值。
 *
 * 量不出轴（骨名对不上／换了资产）时**整体跳过**：宁可保持原样，也不要乱转。
 */
const ARM_DROP_JOINTS = [
  { key: 'upperarm', share: 0.72 },   // 肩：承担主要的下垂量
  { key: 'forearm', share: 0.28 },    // 肘：留一点自然弯曲（全压在肩上看像木偶吊着）
]
/** 不折到 100%：完全垂直会贴住身体，留一点角度更像自然站姿 */
const ARM_DROP_FRACTION = 0.85
/**
 * 「手臂自然下垂」修正的开关。
 *
 * ## 现在**关闭**，这是 2026-10-07 定下的
 *
 * 这层修正原本是给**旧交付件**做的：那些资产静息是 T-pose、两臂平举，
 * 不修正就"平举着挥手"，很假。它靠改动画关键帧（把偏移左乘进四元数轨道）
 * 实现，代价是**会改写资产的动画数据**。
 *
 * ### 为什么关掉
 *
 * 用户交付的 Q 版男医**静息姿态本身就是自然站姿**，几何上不需要修正。
 * 强行烘焙偏移的后果是**骨骼被改坏**——实测：
 *   · 不播动画时看不出问题（Mixer 会把骨骼还原成绑定姿态）
 *   · 一旦播 `Idle`（也就是待机系统一起来）→ **整个模型塌成一条竖线**
 *
 * 我一开始想用"夹角门槛"自动判断（手臂本来就垂着就跳过），
 * 但 Q 版男医的手臂是 A-pose 下垂约 45°，量出来仍算"没垂下"，
 * 门槛挡不住。所以改成**显式开关**，不猜。
 *
 * ### 什么时候要打开
 *
 * 只有再接回 **T-pose 平举** 的交付件时才需要。
 * 打开前务必在做那个资产上验证：播 `Idle` 不塌、招手高度正常。
 */
const ARM_REST_ENABLED = false

/**
 * 「手臂已经垂下」的判定门槛（度）——仅在 `ARM_REST_ENABLED` 打开时生效。
 *
 * 整臂方向与"竖直向下"的夹角小于这个值 → 认为这件资产本来就是自然站姿。
 *
 * ⚠️ 实测这个门槛**挡不住 A-pose**：Q 版男医手臂下垂约 45°，仍然超过它。
 * 留着是因为"完全平举"（≈90°）与"稍微收拢"之间还是能分开，
 * 但**不要依赖它来判断"要不要做修正"**——那件事由 `ARM_REST_ENABLED` 决定。
 */
const ARM_REST_MIN_DEG = 25
/**
 * 「这条轨道算不算真的在动」的门槛（弧度，≈20°）。
 * 交付件里没被动画驱动的骨也会带一条**常量轨道**（左臂那两根就是 2 关键帧 STEP），
 * 它们的"离基准距离"恒为 0；把常量轨道当成动画，左臂会在挥手期间被推回 T-pose。
 */
const ARM_CLIP_DEV_MIN = 0.35

/**
 * 骨名归一化：GLTFLoader 会过一遍 PropertyBinding.sanitizeNodeName，把 . : _ 之类从节点名里抹掉
 * —— 交付件里叫 upperarm.R 的骨，**运行时叫 upperarmR**。取骨不能按字面名硬取
 * （第一版就是这么写的，结果一根也取不到，静默退化成"什么都不做"），统一按「只留字母数字并小写」建索引。
 */
function normalizeBoneKey(name) {
  return String(name || '').replace(/[^a-z0-9]/gi, '').toLowerCase()
}

/** 收集 root 下所有骨骼：骨骼既可能挂在 Armature 节点上，也可能只出现在 skin.bones 里 */
function collectBones(root) {
  const map = new Map()
  const visit = (node) => {
    if (!node) return
    if (node.isBone && node.name) map.set(normalizeBoneKey(node.name), node)
    if (node.isSkinnedMesh && node.skeleton && Array.isArray(node.skeleton.bones)) {
      for (const bone of node.skeleton.bones) {
        if (bone && bone.name) map.set(normalizeBoneKey(bone.name), bone)
      }
    }
    const kids = node.children || []
    for (const kid of kids) visit(kid)
  }
  visit(root)
  return map
}

/**
 * 骨骼在**模型内部**的父级旋转（一路乘到 root 为止）。
 * 刻意不走 matrixWorld：那条链上还挂着 tiltGroup / spinGroup，取景一晃这层姿势就跟着歪。
 */
function modelParentRotation(bone, root) {
  const chain = []
  let cursor = bone ? bone.parent : null
  while (cursor && cursor !== root) {
    chain.push(cursor)
    cursor = cursor.parent
  }
  const matrix = new THREE.Matrix4()
  for (let i = chain.length - 1; i >= 0; i -= 1) {
    chain[i].updateMatrix()
    matrix.multiply(chain[i].matrix)
  }
  return new THREE.Quaternion().setFromRotationMatrix(matrix)
}

/**
 * 求「把这条手臂折下去」的旋转（**局部四元数**，左乘到骨骼上即生效）。
 *
 * 世界系里的转轴取 `手相对肩的方向 × 竖直向下`：这条轴上的旋转**完全落在这两者张成的平面内**，
 * 所以手臂只会"往下走"，既不会被带进身体、也不会前后穿。
 * （写死某个局部轴的做法试过，会得到"手往下但整个人像耸肩"的怪姿势。）
 */
function solveArmDropRotation(armBone, handBone, root, radians, applyTo) {
  const head = new THREE.Vector3()
  const hand = new THREE.Vector3()
  armBone.getWorldPosition(head)
  handBone.getWorldPosition(hand)
  const direction = hand.sub(head)
  if (!(direction.length() > 1e-6)) return null
  direction.normalize()
  const down = new THREE.Vector3(0, -1, 0)
  // 世界 → 模型系（**必须换**）：下面的 modelParentRotation 是相对 root 的旋转，
  // 而 root 自己（以及外层的 spinGroup/tiltGroup）带着朝向；用户拖拽转动模型时，
  // 不换系的话"竖直向下"会跟着歪，下垂轴就不再是脚下的那条。
  const rootQuat = new THREE.Quaternion()
  root.getWorldQuaternion(rootQuat).invert()
  direction.applyQuaternion(rootQuat)
  down.applyQuaternion(rootQuat)
  const axis = new THREE.Vector3().crossVectors(direction, down)
  if (!(axis.length() > 1e-6)) return null
  axis.normalize()
  const world = new THREE.Quaternion().setFromAxisAngle(axis, radians)
  // ⚠️ 父级坐标系要取**真正要挨这一刀的那根骨**（applyTo），不是用来量方向的上臂：
  // 肘的父级是上臂，两者差一个"上臂静息旋转"。用错的话前臂绕的是另一条轴 ——
  // 下垂看着还行（角度小、看不出），但挥手摆动会变成拧手腕（实测：手部几乎不动）。
  const parent = modelParentRotation(applyTo || armBone, root)
  return parent.clone().invert().multiply(world).multiply(parent)
}

/** 两个四元数之间的夹角（弧度，0..π）。取 |dot|：q 与 -q 是同一个旋转 */
function quatAngle(x, y, z, w, ref) {
  const dot = Math.abs(x * ref.x + y * ref.y + z * ref.z + w * ref.w)
  return 2 * Math.acos(Math.max(0, Math.min(1, dot)))
}

/* ─────────────────── 程序化「招手」：交付件的 wave 幅度不够 ─────────────────── */

/**
 * 为什么不用交付件里的 `wave`：拿 GLB 做 FK 复算（_tts_probe/anim6.cjs）实测那 2.6 秒里
 * 上臂只摆了 ±5°、手腕 5°，**手部全程位移约 1cm** —— 它不是"挥手"，是"举着胳膊抖"，
 * 所以看着假。资产契约不动（GLB 里仍然有 wave），运行时用**同名程序化片段**替代播放；
 * 量不出轴（换资产 / 骨名对不上）时自动回落到交付件那一版。
 *
 * 动作全部绕**同一条实测平面轴**（就是下垂基准那条：手-肩方向 × 竖直向下）：
 * 绕它转 = 手臂只在这个平面里上下走 → 抬臂与摆动都不可能穿进身体。
 *   0    → 0.42s   抬臂到 WAVE_ARM_FROM_DOWN（smoothstep，别像机械臂）
 *   0.42 → 1.92s   前臂摆动 ±WAVE_WIPER_DEG × 3 个来回，手腕相位领先一点跟着摆
 *   1.92 → 2.34s   收回静息（终点就是下垂基准，与"没在播动画"同一姿势 → 首尾无缝）
 */
const WAVE_ARM_FROM_DOWN = 148   // 抬到离"竖直向下"多少度（90=平举，148≈斜上 58°）
const WAVE_WIPER_DEG = 22        // 前臂摆动幅度
const WAVE_WRIST_DEG = 9         // 手腕跟随幅度（相位领先，像甩出去的手）
const WAVE_CYCLES = 3
const WAVE_RAISE_MS = 420
const WAVE_HOLD_MS = 1500
const WAVE_LOWER_MS = 420
const WAVE_KEY_MS = 60

/**
 * 量「肩 → 手」相对**竖直向下**的角度（度）。
 * 抬手到底抬起来没有，用这个读数验，不靠肉眼猜 —— 与下垂基准同一套量纲。
 */
function armAngleFromDown(armBone, handBone) {
  const head = new THREE.Vector3()
  const hand = new THREE.Vector3()
  armBone.getWorldPosition(head)
  handBone.getWorldPosition(hand)
  const dir = hand.sub(head)
  if (!(dir.length() > 1e-6)) return null
  dir.normalize()
  return THREE.MathUtils.radToDeg(Math.acos(Math.max(-1, Math.min(1, dir.dot(new THREE.Vector3(0, -1, 0))))))
}

/**
 * 生成程序化「招手」片段。
 * @returns {null|{clip:THREE.AnimationClip, info:object}} 量不出轴时返回 null（上层回落交付件）
 */
function buildWaveGesture(spec) {
  if (!spec || !spec.shoulder || !spec.elbow || !spec.wrist) return null
  const { shoulder, elbow, wrist } = spec
  const before = armAngleFromDown(shoulder.bone, wrist.bone)
  if (before === null) return null
  const rad = THREE.MathUtils.degToRad
  const target = before + (WAVE_ARM_FROM_DOWN - before)   // 语义自明：抬到 WAVE_ARM_FROM_DOWN
  const raiseDeg = WAVE_ARM_FROM_DOWN - before

  /** 试一个方向：把肩按 dir 转 raiseDeg，返回"肩→手"的新角度（试完立刻还原） */
  const probe = (dir) => {
    const keep = [shoulder.bone, elbow.bone, wrist.bone].map((b) => b.quaternion.clone())
    try {
      shoulder.bone.quaternion.copy(shoulder.base).premultiply(
        new THREE.Quaternion().setFromAxisAngle(shoulder.axis, dir * rad(raiseDeg)))
      shoulder.bone.updateWorldMatrix(false, true)
      return armAngleFromDown(shoulder.bone, wrist.bone)
    } finally {
      shoulder.bone.quaternion.copy(keep[0])
      elbow.bone.quaternion.copy(keep[1])
      wrist.bone.quaternion.copy(keep[2])
      shoulder.bone.updateWorldMatrix(false, true)
    }
  }
  // 符号**实测**：下垂基准是"绕该轴正向 = 往下"，但换资产后未必；
  // 取"更接近目标角"的那个方向，而不是写死正负。
  const up = probe(-1)
  const dn = probe(1)
  const sign = (up !== null && (dn === null || Math.abs(up - target) <= Math.abs(dn - target))) ? -1 : 1

  const total = WAVE_RAISE_MS + WAVE_HOLD_MS + WAVE_LOWER_MS
  const times = []
  const vS = []
  const vE = []
  const vW = []
  const push = (ms) => {
    const inHold = ms > WAVE_RAISE_MS && ms < WAVE_RAISE_MS + WAVE_HOLD_MS
    const uHold = inHold ? (ms - WAVE_RAISE_MS) / WAVE_HOLD_MS : 0
    const win = inHold ? Math.sin(Math.PI * uHold) : 0          // 两端为 0：摆动与抬臂不打架
    let phi = 0
    if (ms <= WAVE_RAISE_MS) {
      const u = WAVE_RAISE_MS ? ms / WAVE_RAISE_MS : 1
      phi = raiseDeg * (0.5 - 0.5 * Math.cos(Math.PI * u))
    } else if (inHold) {
      phi = raiseDeg
    } else {
      const u = Math.min(1, (ms - WAVE_RAISE_MS - WAVE_HOLD_MS) / WAVE_LOWER_MS)
      phi = raiseDeg * (0.5 + 0.5 * Math.cos(Math.PI * u))
    }
    const psi = WAVE_WIPER_DEG * win * Math.sin(2 * Math.PI * WAVE_CYCLES * uHold)
    const chi = -WAVE_WRIST_DEG * win * Math.sin(2 * Math.PI * WAVE_CYCLES * uHold - Math.PI / 6)
    const qS = shoulder.base.clone().premultiply(new THREE.Quaternion().setFromAxisAngle(shoulder.axis, sign * rad(phi)))
    const qE = elbow.base.clone().premultiply(new THREE.Quaternion().setFromAxisAngle(elbow.axis, rad(psi)))
    const qW = wrist.base.clone().premultiply(new THREE.Quaternion().setFromAxisAngle(wrist.axis, rad(chi)))
    times.push(ms / 1000)
    vS.push(qS.x, qS.y, qS.z, qS.w)
    vE.push(qE.x, qE.y, qE.z, qE.w)
    vW.push(qW.x, qW.y, qW.z, qW.w)
  }
  push(0)
  for (let ms = WAVE_KEY_MS; ms < total; ms += WAVE_KEY_MS) push(ms)
  push(total)
  const clip = new THREE.AnimationClip('wave', total / 1000, [
    new THREE.QuaternionKeyframeTrack(shoulder.bone.name + '.quaternion', times, vS),
    new THREE.QuaternionKeyframeTrack(elbow.bone.name + '.quaternion', times, vE),
    new THREE.QuaternionKeyframeTrack(wrist.bone.name + '.quaternion', times, vW),
  ])
  // blArmRest：别再被 applyArmRestPose 的"按偏离量加权"改一遍（它的关键帧已经是最终姿势）
  clip.userData = Object.assign({}, clip.userData, { blArmRest: true, blProcedural: true })
  const after = probe(sign)
  return {
    clip,
    info: {
      procedural: true, keys: times.length, duration: +(total / 1000).toFixed(2),
      fromDownBefore: +before.toFixed(1), fromDownPeak: after === null ? null : +after.toFixed(1),
      raiseDeg: +raiseDeg.toFixed(1), wiperDeg: WAVE_WIPER_DEG, sign,
    },
  }
}

/**
 * 把「自然下垂」基准叠到手臂上。
 *
 * ⚠️ **只在手臂确实平举时才做**（见下方 `ARM_REST_MIN_DEG` 门槛）。
 *
 * 为什么加这个门槛（2026-10-07 实测）：
 *   这层修正原本是给**旧交付件**做的——那些资产的静息姿态是 T-pose、
 *   两臂平举，不修正就"平举着挥手"，很假。
 *   但用户交付的 Q 版男医**静息姿态本身就是自然站姿**（手臂已垂下），
 *   几何上不需要任何修正。强行烘焙偏移的后果是**骨骼被改坏**：
 *   实测播 `Idle` 时整个模型塌成一条竖线（静止不播动画时看不出来，
 *   因为 Mixer 会把骨骼还原成绑定姿态）。
 *
 * 所以先量"整臂方向与竖直向下的夹角"：本来就快垂下了（夹角小）就直接跳过，
 * 既保住新资产，也不影响将来再接入 T-pose 资产。
 *
 * @returns {null|{bones:number, clips:number, names:string[], degrees:number}} 诊断读数（stats().armRest）
 */
function applyArmRestPose(root, clips) {
  // 开关关掉时直接跳过（当前就是关的，原因见 ARM_REST_ENABLED 的注释：
  // 这层修正会改写动画关键帧，对"静息已经是自然站姿"的资产会把骨骼改坏）
  if (!ARM_REST_ENABLED) return null
  if (!root) return null
  root.updateWorldMatrix(true, true)
  const bones = collectBones(root)
  const offsets = new Map()
  let totalDegrees = 0

  for (const side of ['L', 'R']) {
    const arm = bones.get(normalizeBoneKey('upperarm.' + side)) || null
    const fore = bones.get(normalizeBoneKey('forearm.' + side)) || null
    const hand = bones.get(normalizeBoneKey('hand.' + side)) || null
    if (!arm || !hand) continue
    const bindArm = arm.quaternion.clone()
    const bindFore = fore ? fore.quaternion.clone() : null
    const restore = () => {
      arm.quaternion.copy(bindArm)
      if (fore) fore.quaternion.copy(bindFore)
      root.updateWorldMatrix(true, true)
    }
    // 下垂总量：量「肩 → 手」这条整臂方向与竖直向下的夹角，再取一个比例。
    const head = new THREE.Vector3()
    const tail = new THREE.Vector3()
    arm.getWorldPosition(head)
    hand.getWorldPosition(tail)
    const span = tail.sub(head)
    const total = span.length() > 1e-6
      ? Math.acos(Math.max(-1, Math.min(1, span.normalize().dot(new THREE.Vector3(0, -1, 0))))) * ARM_DROP_FRACTION
      : 0
    if (!(total > 0)) continue
    totalDegrees = THREE.MathUtils.radToDeg(total)
    // 手臂本来就垂着（静息已经是自然站姿）→ **整体跳过**，不做任何烘焙。
    // 这一条是 2026-10-07 加的：新交付的 Q 版男医属于这种，
    // 之前不看这个直接烘焙偏移，结果是播动画时模型塌成一条线。
    if (totalDegrees < ARM_REST_MIN_DEG) {
      restore()
      continue
    }
    for (const joint of ARM_DROP_JOINTS) {
      const bone = joint.key === 'upperarm' ? arm : fore
      if (!bone) continue
      restore()
      // 轴一律按「整臂方向」算，两节才落在同一个平面里（各算各的会拧成麻花）
      const local = solveArmDropRotation(arm, hand, root, total * joint.share, bone)
      if (local) {
        // 记「轴 + 角度」而不只是四元数：关键帧要按偏离量**缩放这个角度**（见下方加权）。
        const axis = new THREE.Vector3(local.x, local.y, local.z)
        const sin = axis.length()
        const angle = 2 * Math.atan2(sin, local.w)
        if (sin > 1e-6) axis.multiplyScalar(1 / sin)
        else axis.set(1, 0, 0)
        // neutral = 骨骼**改之前**（= T-pose 基准）的静息四元数：量每根关键帧"离基准多远"要用它。
        // 必须 clone —— 下面会让这些骨骼自己转起来，引用同一对象会量出恒等于 0 的距离。
        offsets.set(normalizeBoneKey(bone.name), {
          name: bone.name, bone, local, axis, angle, neutral: bone.quaternion.clone(),
        })
      }
    }
    restore()
  }
  if (!offsets.size) return null

  // 关键帧**按「离基准多远」加权左乘偏移**。
  //   交付管线的烘焙关键帧 = "T-pose 基准 + 姿势偏移"，静止帧就等于 T-pose。
  //   于是：越贴着 T-pose 的关键帧吃越多的下垂偏移（w→1），越自定义的姿势越保留原样（w→0）。
  //   好处是挥手的**抬起高度仍然是美术作者定的**（不是我们猜一个角度叠上去），
  //   而进场/收场会自然接回下垂静息：t=0 与末尾的关键帧等于静息值（w=1），
  //   所以起止两端无缝，不会出现"抬手瞬间弹回 T-pose、收手再弹回来"。
  //   （左乘对 slerp 无损：slerp(p·q0, p·q1) = p·slerp(q0,q1)，逐段插值不会漏。）
  const inClip = new Set()
  let clipCount = 0
  const scratch = new THREE.Quaternion()
  for (const clip of clips || []) {
    if (clip.userData && clip.userData.blArmRest) { clipCount += 1; continue }
    let touched = 0
    for (const track of clip.tracks || []) {
      const dot = String(track.name).lastIndexOf('.')
      if (dot < 0) continue
      const entry = offsets.get(normalizeBoneKey(track.name.slice(0, dot)))
      if (!entry) continue
      if (track.getValueTypeName && track.getValueTypeName() !== 'quaternion') continue
      const values = track.values
      const ref = entry.neutral
      // 先量这条轨道"离基准最远"有多远（弧度），拿它当分母把权重归一到 0..1。
      // 常量轨道的分母为 0 → 判为"没在动" → 全程 w=1（挥手期间左臂稳稳垂着，不会被推回 T-pose）。
      let maxDev = 0
      for (let k = 0; k + 3 < values.length; k += 4) {
        const dev = quatAngle(values[k], values[k + 1], values[k + 2], values[k + 3], ref)
        if (dev > maxDev) maxDev = dev
      }
      const animated = maxDev > ARM_CLIP_DEV_MIN
      for (let k = 0; k + 3 < values.length; k += 4) {
        const x = values[k]
        const y = values[k + 1]
        const z = values[k + 2]
        const w = values[k + 3]
        let weight = 1
        if (animated) weight = Math.max(0, 1 - quatAngle(x, y, z, w, ref) / maxDev)
        if (weight >= 0.999) scratch.copy(entry.local)
        else scratch.setFromAxisAngle(entry.axis, entry.angle * weight)
        const o = scratch
        values[k] = o.w * x + o.x * w + o.y * z - o.z * y
        values[k + 1] = o.w * y - o.x * z + o.y * w + o.z * x
        values[k + 2] = o.w * z + o.x * y - o.y * x + o.z * w
        values[k + 3] = o.w * w - o.x * x - o.y * y - o.z * z
      }
      inClip.add(entry.name)
      touched += 1
    }
    if (clip.userData) clip.userData.blArmRest = true
    if (touched) clipCount += 1
  }

  // **静息值也要带上偏移**：AnimationMixer 在动作停掉时会 restoreOriginalState()，
  // 不改这里，"打断 / 停止"之后两臂会自己弹回 T-pose。
  for (const entry of offsets.values()) {
    try {
      entry.bone.quaternion.premultiply(entry.local)
      entry.bone.updateWorldMatrix(false, true)
    } catch (error) { void error }
  }
  // 程序化招手要用的三件东西：肩/肘的**实测轴** + 下垂后的静息四元数（当基准姿势）。
  // 腕部没有独立偏移（它不参与下垂），它的轴按"肘轴换算到手的父级坐标系"得出：
  // 绕同一条轴 → 手腕摆动与前臂摆动共面，不会把手腕拧出去。
  const uaR = offsets.get(normalizeBoneKey('upperarm.R'))
  const foR = offsets.get(normalizeBoneKey('forearm.R'))
  const handR = bones.get(normalizeBoneKey('hand.R'))
  let gesture = null
  if (uaR && foR && handR) {
    gesture = {
      shoulder: { bone: uaR.bone, axis: uaR.axis.clone(), base: uaR.bone.quaternion.clone() },
      elbow: { bone: foR.bone, axis: foR.axis.clone(), base: foR.bone.quaternion.clone() },
      wrist: {
        bone: handR,
        axis: foR.axis.clone().applyQuaternion(foR.bone.quaternion.clone().invert()),
        base: handR.quaternion.clone(),
      },
    }
  }
  return {
    bones: offsets.size,
    clips: clipCount,
    degrees: Math.round(totalDegrees),
    names: [...offsets.values()].map((item) => item.name),
    gesture,
  }
}



  async function load(gender, role, options) {
    const wantRole = role === 'delivery' ? 'delivery' : 'edit'
    const g = AVATAR_ASSET[gender] ? gender : DEFAULT_GENDER
    const opt = options || {}
    // 取景模式：捏脸页要"看脸"，通话页要"看人"（用户反馈"只有一个头"→"人太小"两轮都在调这个）
    const wantFocusMode = opt.frameMode === 'body' ? 'body'
      : (opt.frameMode === 'bust' ? 'bust' : 'head')
    const wantFitMargin = typeof opt.fitMargin === 'number'
      ? Math.max(0.8, Math.min(4, opt.fitMargin)) : FIT_MARGIN
    // 垂直构图偏移（只对 bust 有意义）。夹在 ±0.3 之间：
    // 再大就把人物推出画面了，那不是"往上放"而是"放坏了"。
    const wantLiftY = typeof opt.frameLiftY === 'number'
      ? Math.max(-0.3, Math.min(0.3, opt.frameLiftY)) : 0
    // 幂等：H5 的 onMounted 与 App 的 renderjs mounted 都可能触发首次加载，
    // 加上首帧兜底的 boot tick，同一性别最多只真正加载一次。
    // 注意 role 也要参与幂等判断：同一个性别在"捏脸页（edit 件）"与"通话页（delivery 件）"
    // 下要加载的是**两个不同的文件**，只比 gender 会让第二个页面拿到错的资产。
    // focusMode 同理：同一个资产在两种取景下都要能重建构图。
    if (loading) return stats()
    if (ready && currentGender === g && currentRole === wantRole
        && focusMode === wantFocusMode && fitMargin === wantFitMargin
        && frameLiftY === wantLiftY) {
      return stats()
    }
    focusMode = wantFocusMode
    fitMargin = wantFitMargin
    frameLiftY = wantLiftY
    // 首次加载前先把材质默认值定好（**不放在 load 之后**，否则每次切性别都要重设一遍材质）
    applyDefaultMaterial()
    const url = resolveAssetUrl((wantRole === 'delivery' ? AVATAR_DELIVERY_ASSET : AVATAR_ASSET)[g])
    loading = true
    ready = false
    loadingGender = g
    currentRole = wantRole
    lastAssetUrl = url
    lastError = ''
    // 用 genderLabel 而不是 `g === 'female' ? '女性' : '男性'`：
    // 形象从两项变三项后，三元会把 qdoctor 也说成"男性"。
    if (o.onStatus) o.onStatus('正在加载' + genderLabel(g) + '形象…')
    const t0 = Date.now()
    try {
      const gltf = await loader.loadAsync(url)
      // 换模型：先拆旧的再挂新的，避免两套骨骼同时参与渲染
      if (root) { spinGroup.remove(root); disposeObject(root, renderer) }
      // 动画混合器必须跟着旧模型一起丢，否则它会继续驱动已经 dispose 的骨骼
      if (mixer) { mixer.stopAllAction(); mixer.uncacheRoot(mixer.getRoot() || root || spinGroup) }
      mixer = null
      activeClipName = ''
      // 换资产（切形象）时先把待机停掉：新资产的片段表不同，
      // 旧定时器会按旧表挑片段，挑到不存在的会静默不动
      stopIdle()
      playingClips.clear()
      clips = gltf.animations || []
      root = gltf.scene
      spinGroup.add(root)
      bound = bindThree(root)
      morphOwners = collectMorphOwners(root)
      if (clips.length) {
        mixer = new THREE.AnimationMixer(root)
        actions = {}
        for (const clip of clips) actions[clip.name] = mixer.clipAction(clip)
        // 一次性动作播完要把名字从 playingClips 里摘掉，
        // 否则 `playingAll` 会一直挂着已经停了的片段（排查时看到假状态）
        mixer.addEventListener('finished', (event) => {
          const finished = event && event.action && event.action.getClip
            ? event.action.getClip().name : ''
          if (finished) playingClips.delete(finished)
        })
      }
      // 交付件静息是 T-pose：不叠这层「自然下垂」，挥手从平举起挥，怎么调都假。
      armRestInfo = applyArmRestPose(root, clips)
      // 招手用**同名程序化片段**替换交付件那一版（幅度实测只有 ±1cm，见 buildWaveGesture 注释）；
      // 量不出轴时不动，playAnimation('wave') 就照旧放交付件的动画。
      waveGestureInfo = null
      const waved = buildWaveGesture(armRestInfo && armRestInfo.gesture)
      // 规格里带着骨骼引用，用完立刻摘掉：stats() 会整个序列化 armRest，留着会带出整棵骨骼树
      if (armRestInfo) delete armRestInfo.gesture
      if (waved) {
        if (!mixer) { mixer = new THREE.AnimationMixer(root); actions = {} }
        clips = clips.filter((c) => c.name !== waved.clip.name)
        clips.push(waved.clip)
        actions[waved.clip.name] = mixer.clipAction(waved.clip)
        waveGestureInfo = waved.info
      }
      lastLoadMs = Date.now() - t0
      computeFocus()
      resize()
      applyFraming()
      applyWeights(weights)
      // 镜面强度是**每材质**的（r160 上 scene.environmentIntensity 不生效），
      // 所以必须在挂上新模型之后重新施加一次，否则换模型会把上一轮的值丢掉。
      setSpecular(specularMultiplier)
      // 金属度/粗糙度也是每材质的值，换模型后同样要重新施加（否则切性别会把校正丢掉）
      applyDefaultMaterial()
      rotate(yaw, pitch)
      ready = true
      currentGender = g
      if (o.onReady) o.onReady({ gender: g, stats: stats() })
      schedule()
      return stats()
    } catch (error) {
      lastError = String((error && error.message) || error)
      if (o.onStatus) o.onStatus('形象加载失败：' + lastError)
      throw error
    } finally {
      loading = false
    }
  }

  function stats() {
    const s = bound ? bound.stats() : { bones: 0, meshes: 0, materials: 0, morphNames: 0, slots: 0 }
    let tris = 0
    if (root) {
      root.traverse((n) => {
        if (n.isMesh && n.geometry && n.geometry.index) tris += n.geometry.index.count / 3
        else if (n.isMesh && n.geometry && n.geometry.attributes.position) tris += n.geometry.attributes.position.count / 3
      })
    }
    return {
      ready, bones: s.bones, meshes: s.meshes, materials: s.materials,
      morphSlots: s.morphNames, morphNames: morphOwners.size,
      triangles: Math.round(tris), loadMs: lastLoadMs, warnings: lastCmdWarnings,
      canvas: measure(), frame: frameInfo,
      // §7 排查用的可观测状态：性别 / 资产地址 / 是否正在加载 / 最近一次错误
      gender: currentGender, loadingGender, loading, asset: lastAssetUrl, lastError,
      // 资产角色（edit / delivery）与动画状态：通话页要能确认"招手到底有没有在放"
      role: currentRole,
      clips: clips.map((c) => c.name),
      playing: activeClipName,
      /** 同时在跑的全部片段（待机时是 Idle + 一个一次性动作） */
      playingAll: [...playingClips],
      /** 待机系统读数：running / fired / lastPick / 缺哪些片段 */
      idle: idleStats(),
      visemeWrites,
      // 手臂基准姿势（A-pose）读数：bones>0 表示已经不在 T-pose 上站着了
      armRest: armRestInfo,
      // 招手读数：procedural=true 表示放的是程序化片段（含抬臂角/手部抬高的实测值）
      gesture: waveGestureInfo,
      lastVisemeApplied,
    }
  }

  /** load 的失败兜底包装：任何异常都要把 loading 复位，否则后续切换性别会被幂等守卫挡住。 */
  const loadSafe = (g, role, options) => Promise.resolve().then(() => load(g, role, options)).catch((e) => {
    loading = false
    ready = false
    if (o.onStatus) o.onStatus('形象加载失败：' + ((e && e.message) || e))
    throw e
  })

  /* ───────────────────── 拖动旋转（刻意不引 OrbitControls，省一个依赖） ───────────────────── */

  let dragging = false
  let dragPointer = null
  let lastX = 0
  let lastY = 0

  /** 从 Pointer / Touch / Mouse 事件里统一取一个坐标点。 */
  function pointOf(ev) {
    if (ev.touches && ev.touches.length) return { x: ev.touches[0].clientX, y: ev.touches[0].clientY }
    if (ev.changedTouches && ev.changedTouches.length) return { x: ev.changedTouches[0].clientX, y: ev.changedTouches[0].clientY }
    return { x: ev.clientX, y: ev.clientY }
  }

  function swallow(ev) {
    if (ev.cancelable && typeof ev.preventDefault === 'function') ev.preventDefault()
  }

  function onDown(ev) {
    const pt = pointOf(ev)
    if (pt.x === undefined) return
    dragging = true
    dragPointer = (ev.pointerId === undefined) ? null : ev.pointerId
    lastX = pt.x
    lastY = pt.y
    canvas.style.cursor = 'grabbing'
    // 指针捕获：拖出画布边界后仍能收到 move，否则拖到边缘就「掉手」
    if (dragPointer !== null && typeof canvas.setPointerCapture === 'function') {
      try { canvas.setPointerCapture(dragPointer) } catch (e) { void e }
    }
    swallow(ev)
  }

  function onMove(ev) {
    if (!dragging) return
    if (dragPointer !== null && ev.pointerId !== undefined && ev.pointerId !== dragPointer) return
    const pt = pointOf(ev)
    const dx = pt.x - lastX
    const dy = pt.y - lastY
    lastX = pt.x
    lastY = pt.y
    rotate(yaw + dx * DRAG.yaw, pitch + dy * DRAG.pitch)
    swallow(ev)
  }

  function onUp(ev) {
    if (!dragging) return
    dragging = false
    if (dragPointer !== null && typeof canvas.releasePointerCapture === 'function') {
      try { canvas.releasePointerCapture(dragPointer) } catch (e) { void e }
    }
    dragPointer = null
    canvas.style.cursor = 'grab'
    swallow(ev)
  }

  /** 滚轮缩放：仅为 H5 桌面预览方便，不参与捏脸参数。 */
  function onWheel(ev) {
    if (!root) return
    const step = (ev.deltaY > 0 ? 1.06 : 1 / 1.06)
    baseDist = Math.max(0.05, Math.min(baseDist * step, 1e4))
    camera.position.set(0, 0, baseDist)
    schedule()
    swallow(ev)
  }

  canvas.style.cursor = 'grab'
  const usePointer = (typeof window !== 'undefined') && ('PointerEvent' in window)
  if (usePointer) {
    canvas.addEventListener('pointerdown', onDown)
    canvas.addEventListener('pointermove', onMove)
    canvas.addEventListener('pointerup', onUp)
    canvas.addEventListener('pointercancel', onUp)
  } else {
    // 老 WebView 兜底：触摸 + 鼠标双通道
    canvas.addEventListener('touchstart', onDown, { passive: false })
    canvas.addEventListener('touchmove', onMove, { passive: false })
    canvas.addEventListener('touchend', onUp)
    canvas.addEventListener('touchcancel', onUp)
    canvas.addEventListener('mousedown', onDown)
    if (typeof window !== 'undefined') {
      window.addEventListener('mousemove', onMove)
      window.addEventListener('mouseup', onUp)
    }
  }
  if (typeof window !== 'undefined') canvas.addEventListener('wheel', onWheel, { passive: false })

  resize()

  return {
    version: FACE_THREE_VERSION,
    canvas,
    /** 播放动画片段（默认 `wave` 招手）。通话页的"招手互动"入口。 */
    playAnimation,
    /** 停止动画回到静止姿势。 */
    stopAnimation,
    /**
     * 开始待机动作：先把 `Idle` 循环起起来，然后**不定时随机**触发池里的动作
     * （点头 / 转身 / 招手）。只挑**无根位移**的片段，`Walk` / `Sit` 已排除。
     */
    startIdle,
    /** 停止待机动作。**离开页面必须调用**，否则定时器会在后台一直跑。 */
    stopIdle,
    /** 待机自检读数（running / fired / lastPick / 哪些片段缺失）。 */
    idleStats,
    /** 口型驱动：{ vis_AA: 0.8, … }（lip-sync 曲线走这条通道，与表情互不覆盖）。 */
    setVisemes,
    /** 运行时调光（观感标定用）：`setLighting(环境强度, 解析灯倍数)`。 */
    setLighting,
    /**
     * 临时把场景背景设成纯色（**仅调试用**）。
     *
     * 为什么需要它：3D 场景的背景一直是空的（由页面 CSS 提供），
     * 于是 canvas 是透明的、`readPixels` 读不出人物轮廓，
     * "人物在画面里占多高/头顶在哪"就只能靠肉眼估。
     * 铺一个与人物反差极大的颜色后，用像素扫描就能量出精确边界。
     */
    debugSetBackground(color) {
      if (color == null) {
        if (scene) { scene.background = null }
      } else if (scene) {
        scene.background = new THREE.Color(color)
      }
      schedule()
      return { ok: true, background: color == null ? null : String(color) }
    },
    /**
     * 材质校正：`setMaterial({ metalness: 0, roughnessScale: 1 })`。
     * 压金属度是治"反光太强/像金属"的正确那一刀（资产自带 metallic 贴图 B 通道偏高）。
     */
    setMaterial,
    /**
     * 只调**镜面强度**（治"皮肤油亮"的正确那一刀）。
     * 与 `setLighting` 的区别：它不碰漫反射，所以压高光不会把脸一起调暗。
     * 用户再觉得油，调它即可（0 = 完全无镜面，1 = 默认）。
     */
    setSpecular,
    /**
     * 观感度量：渲染到**离屏目标**再取像素，算"高光集中度"。
     *
     * 为什么要离屏：渲染器没开 `preserveDrawingBuffer`（开了会一直占显存且掉帧），
     * 合成之后直接从画布 `readPixels` 只会读到**空缓冲**（实测 pixels:0）——
     * 所以必须"自己渲染一次、立刻读、再释放"。
     *
     * 口径：`concentration = 最亮 0.1% 像素均值 − 全图均值`。**越集中 = 越油亮**。
     * 参考值（Q 版女医、头肩取景）：加环境贴图前 **168**，加之后 **115~124**。
     */
    measureShading(size, options) {
      if (!root) return { ok: false, reason: '还没有加载资产' }
      const side = Math.max(64, Math.min(1024, Math.round(size || 384)))
      const opt = options || {}
      // A/B 诊断用：临时摘掉环境贴图（否则"加环境贴图到底有没有效"只能靠跟别的取景比、
      // 得出**错误结论**——实测第一版就是因为两次取景不同，把"改好了"误判成"更糟了"）。
      const savedEnv = scene.environment
      const savedIntensity = scene.environmentIntensity
      if (opt.withoutEnvironment) {
        scene.environment = null
        scene.needsUpdate = true
      }
      const target = new THREE.WebGLRenderTarget(side, side)
      const prevTarget = renderer.getRenderTarget()
      const prevAspect = camera.aspect
      try {
        camera.aspect = 1
        camera.updateProjectionMatrix()
        renderer.setRenderTarget(target)
        renderer.setClearAlpha(0)
        renderer.clear()
        renderer.render(scene, camera)
        const buffer = new Uint8Array(side * side * 4)
        renderer.readRenderTargetPixels(target, 0, 0, side, side, buffer)
        const luma = []
        let total = 0
        for (let i = 0; i < buffer.length; i += 4) {
          if (buffer[i + 3] < 8) continue
          const l = 0.2126 * buffer[i] + 0.7152 * buffer[i + 1] + 0.0722 * buffer[i + 2]
          luma.push(l)
          total += l
        }
        if (!luma.length) return { ok: false, reason: '画面里没有不透明像素' }
        luma.sort((a, b) => b - a)
        const mean = total / luma.length
        const topN = Math.max(1, Math.round(luma.length * 0.001))
        const highlight = luma.slice(0, topN).reduce((a, b) => a + b, 0) / topN
        let bright = 0
        let blown = 0
        for (const l of luma) {
          if (l > 200) bright += 1
          if (l > 240) blown += 1
        }
        return {
          ok: true,
          size: side,
          pixels: luma.length,
          meanLuma: +mean.toFixed(1),
          highlightMean: +highlight.toFixed(1),
          concentration: +(highlight - mean).toFixed(1),
          brightPct: +(100 * bright / luma.length).toFixed(2),
          blownPct: +(100 * blown / luma.length).toFixed(3),
          environment: !!scene.environment,
        }
      } finally {
        renderer.setRenderTarget(prevTarget)
        camera.aspect = prevAspect
        camera.updateProjectionMatrix()
        target.dispose()
        if (opt.withoutEnvironment) {
          scene.environment = savedEnv
          scene.environmentIntensity = savedIntensity
          scene.needsUpdate = true
        }
      }
    },
    /**
     * 量"人物在画面里占多大"：渲染到离屏目标，取**不透明像素的包围盒**，
     * 返回宽高占画布的百分比。这是"人太小/太大"唯一客观的判据
     * （肉眼估容易在两个方向之间来回摇摆 —— 实测已经走过"只有头 → 全身 → 半身"两轮）。
     *
     * 与 `measureShading` 一样必须走离屏：渲染器没开 `preserveDrawingBuffer`，
     * 合成后直接 `readPixels` 只会读到空缓冲。
     */
    measureSilhouette(size) {
      if (!root) return { ok: false, reason: '还没有加载资产' }
      const side = Math.max(64, Math.min(1024, Math.round(size || 384)))
      const target = new THREE.WebGLRenderTarget(side, side)
      const prevTarget = renderer.getRenderTarget()
      const prevAspect = camera.aspect
      try {
        camera.aspect = 1
        camera.updateProjectionMatrix()
        renderer.setRenderTarget(target)
        renderer.setClearAlpha(0)
        renderer.clear()
        renderer.render(scene, camera)
        const buffer = new Uint8Array(side * side * 4)
        renderer.readRenderTargetPixels(target, 0, 0, side, side, buffer)
        let minX = side
        let maxX = -1
        let minY = side
        let maxY = -1
        let count = 0
        for (let y = 0; y < side; y += 1) {
          for (let x = 0; x < side; x += 1) {
            if (buffer[(y * side + x) * 4 + 3] < 8) continue
            count += 1
            if (x < minX) minX = x
            if (x > maxX) maxX = x
            if (y < minY) minY = y
            if (y > maxY) maxY = y
          }
        }
        if (maxX < 0) return { ok: false, reason: '画面里没有不透明像素' }
        return {
          ok: true,
          frameMode: focusMode,
          fitMargin,
          widthPct: +(((maxX - minX + 1) / side) * 100).toFixed(1),
          heightPct: +(((maxY - minY + 1) / side) * 100).toFixed(1),
          fillPct: +((count / (side * side)) * 100).toFixed(1),
          dist: +camera.position.z.toFixed(3),
        }
      } finally {
        renderer.setRenderTarget(prevTarget)
        camera.aspect = prevAspect
        camera.updateProjectionMatrix()
        target.dispose()
      }
    },
    /**
     * 读当前生效的形态键权重（诊断口型用）。
     *
     * 为什么要单独给一个读数口子：口型是逐帧写进 `morphTargetInfluences` 的，
     * 而**渲染出来的画面截不到**（无头浏览器不合成 WebGL），
     * 所以"口型到底动没动"只能靠读权重来验，不能靠看图。
     */
    morphWeights(names) {
      const wanted = Array.isArray(names) && names.length ? names : null
      const out = {}
      // ⚠️ `morphOwners` 是 `Map<名字, mesh[]>`，**不是**普通对象：
      //    第一版写成 `for (const mesh of morphOwners)` 会逐个拿到 `[name, meshes]` 数组，
      //    于是 `mesh.morphTargetDictionary` 恒为 undefined、函数静默返回空对象。
      for (const [name, meshes] of morphOwners) {
        if (wanted && !wanted.includes(name)) continue
        for (const mesh of meshes) {
          if (!mesh.morphTargetDictionary || !mesh.morphTargetInfluences) continue
          const index = mesh.morphTargetDictionary[name]
          if (typeof index === 'number') {
            out[name] = +Number(mesh.morphTargetInfluences[index] || 0).toFixed(3)
          }
        }
      }
      return out
    },
    /**
     * 诊断：量每个形态键的**真实几何位移**（顶点最大 |Δ|，模型单位）。
     *
     * 为什么必须有这个读数：「口型不动」有两条真根因，外观一模一样——
     *   甲）权重根本没写进网格（看 `morphWeights` 就能分辨）；
     *   乙）权重写进去了，但形态键本身**没有几何位移**（空 target / 占位），
     *       此时 `morphWeights` 报 1.0，画面却一个像素都不变。
     * 乙只能靠量 `geometry.morphAttributes.position[index]` 才能与甲分开。
     */
    morphDeltas(names) {
      const wanted = Array.isArray(names) && names.length ? names : null
      const out = {}
      for (const [name, meshes] of morphOwners) {
        if (wanted && !wanted.includes(name)) continue
        let maxDelta = 0
        let attrMissing = 0
        let values = 0
        for (const mesh of meshes) {
          const g = mesh.geometry
          const dict = mesh.morphTargetDictionary
          if (!g || !dict) continue
          const idx = dict[name]
          if (typeof idx !== 'number') continue
          const attrs = g.morphAttributes || {}
          const pos = attrs.position ? attrs.position[idx] : null
          if (!pos || !pos.array) { attrMissing += 1; continue }
          values += pos.array.length
          const arr = pos.array
          for (let i = 0; i < arr.length; i += 1) {
            const v = Math.abs(arr[i])
            if (v > maxDelta) maxDelta = v
          }
        }
        out[name] = { maxDelta: +maxDelta.toFixed(6), attrMissing, values }
      }
      return out
    },
    /**
     * 诊断：把「有形态键的网格」与「场景里真正被渲染的网格」对上号，
     * 并读出 three 版本 / 渲染器能力 / 材质上的 morph 开关。
     * 用于分辨「morph 写错对象」与「morph 根本没被 GPU 应用」。
     */
    morphAudit() {
      const owners = []
      for (const [, meshes] of morphOwners) {
        for (const mesh of meshes) if (owners.indexOf(mesh) < 0) owners.push(mesh)
      }
      const sceneMeshes = []
      scene.traverse((n) => {
        if (!n.isMesh) return
        const mat = n.material || {}
        sceneMeshes.push({
          name: n.name || '(未命名)',
          uuid: n.uuid,
          skinned: !!n.isSkinnedMesh,
          morphs: n.morphTargetDictionary ? Object.keys(n.morphTargetDictionary).length : 0,
          visible: n.visible,
          isOwner: owners.indexOf(n) >= 0,
          matType: mat.type,
          matMorphTargets: typeof mat.morphTargets === 'boolean' ? mat.morphTargets : '未定义',
          matDefines: mat.defines ? Object.keys(mat.defines).filter((k) => /MORPH/i.test(k)) : null,
          influences: n.morphTargetInfluences ? n.morphTargetInfluences.length : 0,
          influencesNonZero: n.morphTargetInfluences ? n.morphTargetInfluences.filter((v) => v > 0.001).length : 0,
        })
      })
      const cap = renderer && renderer.capabilities ? renderer.capabilities : {}
      return {
        threeRevision: THREE.REVISION,
        isWebGL2: typeof cap.isWebGL2 === 'boolean' ? cap.isWebGL2 : '未知',
        maxVertexTextures: cap.maxVertexTextures,
        sceneMeshCount: sceneMeshes.length,
        ownerMeshCount: owners.length,
        ownersInScene: owners.filter((m) => sceneMeshes.some((s) => s.uuid === m.uuid)).length,
        renderFrame: renderer && renderer.info ? renderer.info.render.frame : null,
        sceneMeshes,
      }
    },
    /**
     * 诊断（**行为断言**，不是形态断言）：把场景渲进离屏 render target，
     * 比对「形态键全 0 / 单键拉满 / 全拉满」三种状态下的**像素哈希**。
     *
     * 为什么非要走到像素：本轮"嘴不动"的排查里，权重回读（形态断言）报了假绿——
     * 数组确实被改了，屏幕上一个像素都没变。只有读渲染结果才能把
     * 「morph 有没有真的影响画面」变成可判定的事实，而不是靠肉眼抽查截图。
     */
    probeMorphPixels() {
      const owners = []
      for (const [, meshes] of morphOwners) for (const mesh of meshes) if (owners.indexOf(mesh) < 0) owners.push(mesh)
      if (!owners.length) return { ok: false, reason: '场景里没有带形态键的网格' }
      const width = 256
      const height = 256
      const rt = new THREE.WebGLRenderTarget(width, height)
      const buf = new Uint8Array(width * height * 4)
      const saved = owners.map((m) => (m.morphTargetInfluences ? Array.prototype.slice.call(m.morphTargetInfluences) : null))
      const hash = () => {
        let h1 = 2166136261
        for (let i = 0; i < buf.length; i += 1) { h1 ^= buf[i]; h1 = Math.imul(h1, 16777619) }
        return (h1 >>> 0).toString(16)
      }
      const shot = () => {
        renderer.setRenderTarget(rt)
        renderer.render(scene, camera)
        renderer.readRenderTargetPixels(rt, 0, 0, width, height, buf)
        renderer.setRenderTarget(null)
        return hash()
      }
      const setAll = (v) => {
        for (const m of owners) {
          if (!m.morphTargetInfluences) continue
          for (let i = 0; i < m.morphTargetInfluences.length; i += 1) m.morphTargetInfluences[i] = v
        }
      }
      let result
      try {
        setAll(0)
        const hashZero = shot()
        const first = owners[0]
        if (first.morphTargetInfluences && first.morphTargetInfluences.length) first.morphTargetInfluences[0] = 1
        const hashFirst = shot()
        setAll(1)
        const hashAll = shot()
        result = {
          ok: true,
          size: [width, height],
          ownerCount: owners.length,
          influenceCount: owners[0].morphTargetInfluences ? owners[0].morphTargetInfluences.length : 0,
          firstName: first.morphTargetDictionary ? Object.keys(first.morphTargetDictionary)[0] : null,
          hashZero, hashFirst, hashAll,
          changedFirst: hashZero !== hashFirst,
          changedAll: hashZero !== hashAll,
          drawCalls: renderer.info ? renderer.info.render.calls : null,
        }
      } finally {
        owners.forEach((m, i) => {
          if (!m.morphTargetInfluences || !saved[i]) return
          for (let j = 0; j < saved[i].length; j += 1) m.morphTargetInfluences[j] = saved[i][j]
        })
        rt.dispose()
        renderer.setRenderTarget(null)
        renderer.render(scene, camera)
      }
      return result
    },
    /**
     * 诊断：**逐键**量"这个形态键拉满时，屏幕上真的变几个像素"。
     *
     * 为什么需要：vis_* 这些键在交付件里**可能有零位移的占位键**（实测 vis_silence 位移为 0），
     * 也可能位移小到在 399x165 的舞台里不足一个像素。只读权重（0.5~1.0）会让人误判
     * "口型在动"，但屏幕上嘴一动不动。这条口子把"可不可见"变成数字：
     * changedPixels 就是该键拉满时与静止姿态相差的像素个数。
     *
     * 渲染目标尺寸取画布真实绘制缓冲（含 DPR），保证"像素"口径与用户看到的画面一致。
     */

    /**
     * 诊断：**绑定审计** —— 「当前载入的交付件到底绑了什么」。
     *
     * 为什么单开一条口子：用户反复反馈「嘴没动」，而「形态键权重在变」是形状断言、
     * 不是行为断言。动手改幅度之前必须先拿到三个**事实**：
     *   1) 载入的到底是哪一份 GLB（会不会是旧资产 / 浏览器旧缓存）；
     *   2) 网格到底有没有蒙皮权重（JOINTS_0/WEIGHTS_0 压在 Draco 里，离线脚本读不到，只能在页面里读）；
     *   3) 嘴唇这块几何的权重落在**哪根骨**上 —— 落在 head 上就只能靠 morph 开合，
     *      落在 jaw 上才可能靠骨骼开合。
     *
     * 「嘴部区域」的定义刻意**从资产自身量出来**：被任一 vis_* 形态键真正移动过的顶点。
     * 不靠坐标猜「嘴在哪」，资产换尺度也不会失准。
     */
    rigAudit() {
      if (!root) return { ok: false, reason: '还没加载模型' }
      const skinned = []
      root.traverse((n) => { if (n.isSkinnedMesh) skinned.push(n) })
      const mesh = skinned[0]
      if (!mesh) return { ok: false, reason: '场景里没有蒙皮网格' }
      const geo = mesh.geometry
      const pos = geo.attributes.position
      const si = geo.attributes.skinIndex
      const sw = geo.attributes.skinWeight
      const dict = mesh.morphTargetDictionary || {}
      const morphPos = (geo.morphAttributes && geo.morphAttributes.position) ? geo.morphAttributes.position : []
      const boneList = (mesh.skeleton && mesh.skeleton.bones) ? mesh.skeleton.bones : []
      const visKeys = Object.keys(dict).filter((k) => k.indexOf('vis_') === 0)
      const flags = new Uint8Array(pos.count)
      for (const k of visKeys) {
        const attr = morphPos[dict[k]]
        if (!attr || !attr.array) continue
        const arr = attr.array
        for (let v = 0; v < pos.count; v += 1) {
          const i = v * 3
          if (Math.abs(arr[i]) > 1e-6 || Math.abs(arr[i + 1]) > 1e-6 || Math.abs(arr[i + 2]) > 1e-6) flags[v] = 1
        }
      }
      let mouthVerts = 0
      const bx = [Infinity, -Infinity]
      const by = [Infinity, -Infinity]
      const bz = [Infinity, -Infinity]
      for (let v = 0; v < pos.count; v += 1) {
        if (!flags[v]) continue
        const x = pos.getX(v)
        const y = pos.getY(v)
        const z = pos.getZ(v)
        mouthVerts += 1
        if (x < bx[0]) bx[0] = x
        if (x > bx[1]) bx[1] = x
        if (y < by[0]) by[0] = y
        if (y > by[1]) by[1] = y
        if (z < bz[0]) bz[0] = z
        if (z > bz[1]) bz[1] = z
      }
      const n = boneList.length
      const mouthW = new Array(n).fill(0)
      const mouthAt = new Array(n).fill(0)
      const mouthStrong = new Array(n).fill(0)
      const allW = new Array(n).fill(0)
      let unweighted = 0
      const jj = [0, 0, 0, 0]
      const ww = [0, 0, 0, 0]
      for (let v = 0; v < pos.count; v += 1) {
        let sum = 0
        for (let s = 0; s < 4; s += 1) {
          jj[s] = si.getComponent(v, s)
          ww[s] = sw.getComponent(v, s)
          sum += ww[s]
        }
        if (!(sum > 0)) {
          if (flags[v]) unweighted += 1
          continue
        }
        for (let s = 0; s < 4; s += 1) {
          const w = ww[s] / sum
          const j = jj[s]
          if (w <= 0.001 || !(j >= 0 && j < n)) continue
          allW[j] += w
          if (flags[v]) {
            mouthW[j] += w
            mouthAt[j] += 1
            if (w >= 0.5) mouthStrong[j] += 1
          }
        }
      }
      let mouthTotal = 0
      let allTotal = 0
      for (let j = 0; j < n; j += 1) { mouthTotal += mouthW[j]; allTotal += allW[j] }
      const rows = []
      for (let j = 0; j < n; j += 1) {
        if (!mouthAt[j]) continue
        rows.push({
          bone: boneList[j].name,
          shareOfMouth: mouthTotal > 0 ? +(mouthW[j] / mouthTotal).toFixed(4) : 0,
          verts: mouthAt[j],
          vertsOver05: mouthStrong[j],
          shareOfAll: allTotal > 0 ? +(allW[j] / allTotal).toFixed(4) : 0,
        })
      }
      rows.sort((a, b) => b.shareOfMouth - a.shareOfMouth)
      return {
        ok: true,
        asset: lastAssetUrl,
        gender: currentGender,
        role: currentRole,
        vertexCount: pos.count,
        hasSkinIndex: !!si,
        hasSkinWeight: !!sw,
        jointCount: n,
        joints: boneList.map((b) => b.name),
        visKeys,
        morphKeyCount: Object.keys(dict).length,
        mouthVerts,
        mouthUnweighted: unweighted,
        mouthBox: {
          x: [+bx[0].toFixed(4), +bx[1].toFixed(4)],
          y: [+by[0].toFixed(4), +by[1].toFixed(4)],
          z: [+bz[0].toFixed(4), +bz[1].toFixed(4)],
        },
        mouthBoneWeights: rows,
      }
    },
    /**
     * 诊断：把 jaw 骨转 deg 度，量屏幕上**真的变了几个像素**，与 vis_AA 拉满对照。
     * 这条口子回答的是「有没有可能靠骨骼张嘴」；数值与 vis_AA 的比值就是 morph 幅度差多少倍。
     */
    probeJawPixels(deg) {
      const d = typeof deg === 'number' ? deg : 14
      if (!root) return { ok: false, reason: '还没加载模型' }
      const jaw = collectBones(root).get('jaw')
      if (!jaw) return { ok: false, reason: '交付件里没有 jaw 骨' }
      const owners = []
      for (const [, meshes] of morphOwners) for (const m of meshes) if (owners.indexOf(m) < 0) owners.push(m)
      if (!owners.length) return { ok: false, reason: '场景里没有带形态键的网格' }
      const gl = renderer.getContext()
      const canvas = renderer.domElement
      const width = canvas.width
      const height = canvas.height
      const savedMorph = owners.map((m) => (m.morphTargetInfluences ? Array.prototype.slice.call(m.morphTargetInfluences) : null))
      const savedQuat = jaw.quaternion.clone()
      const zeroMorph = () => {
        for (const m of owners) {
          if (!m.morphTargetInfluences) continue
          for (let i = 0; i < m.morphTargetInfluences.length; i += 1) m.morphTargetInfluences[i] = 0
        }
      }
      const readPixels = () => {
        renderer.render(scene, camera)
        const out = new Uint8Array(width * height * 4)
        gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, out)
        return out
      }
      const compare = (a, b) => {
        let changed = 0
        let maxChannel = 0
        let minX = width
        let maxX = -1
        let minY = height
        let maxY = -1
        for (let y = 0; y < height; y += 1) {
          for (let x = 0; x < width; x += 1) {
            const i = (y * width + x) * 4
            const dd = Math.abs(b[i] - a[i]) + Math.abs(b[i + 1] - a[i + 1]) + Math.abs(b[i + 2] - a[i + 2])
            if (dd > 3) {
              changed += 1
              const row = height - 1 - y
              if (x < minX) minX = x
              if (x > maxX) maxX = x
              if (row < minY) minY = row
              if (row > maxY) maxY = row
              if (dd > maxChannel) maxChannel = dd
            }
          }
        }
        return {
          changedPixels: changed,
          bbox: maxX < 0 ? null : [minX, minY, maxX, maxY],
          boxW: maxX < 0 ? 0 : (maxX - minX + 1),
          boxH: maxX < 0 ? 0 : (maxY - minY + 1),
          maxChannelSum: maxChannel,
        }
      }
      const axis = new THREE.Vector3(1, 0, 0)
      const parentRot = modelParentRotation(jaw, root)
      const localFor = (sign) => {
        const world = new THREE.Quaternion().setFromAxisAngle(axis, sign * d * Math.PI / 180)
        return parentRot.clone().invert().multiply(world).multiply(parentRot)
      }
      const out = { ok: true, deg: d, canvas: [width, height] }
      try {
        zeroMorph()
        const rest = readPixels()
        zeroMorph()
        for (const m of owners) {
          const mm = m.morphTargetDictionary || {}
          const idx = mm.vis_AA
          if (typeof idx === 'number' && m.morphTargetInfluences) m.morphTargetInfluences[idx] = 1
        }
        out.morphVisAA = compare(rest, readPixels())
        out.jawPlus = null
        out.jawMinus = null
        for (const sign of [1, -1]) {
          zeroMorph()
          jaw.quaternion.copy(savedQuat)
          jaw.quaternion.premultiply(localFor(sign))
          const r = compare(rest, readPixels())
          if (sign > 0) out.jawPlus = r
          else out.jawMinus = r
        }
      } finally {
        owners.forEach((m, i) => {
          if (!m.morphTargetInfluences || !savedMorph[i]) return
          for (let j = 0; j < savedMorph[i].length; j += 1) m.morphTargetInfluences[j] = savedMorph[i][j]
        })
        jaw.quaternion.copy(savedQuat)
        renderer.render(scene, camera)
      }
      out.jawOpensDownward = out.jawPlus && out.jawMinus
        ? (out.jawPlus.boxH >= out.jawMinus.boxH ? 'plus' : 'minus')
        : null
      out.jawBest = out.jawOpensDownward === 'minus' ? out.jawMinus : out.jawPlus
      if (out.jawBest && out.morphVisAA && out.morphVisAA.changedPixels > 0) {
        out.ratioBestOverMorph = +(out.jawBest.changedPixels / out.morphVisAA.changedPixels).toFixed(2)
      }
      return out
    },

    /**
     * 诊断：**在 2D 画布上**做姿态差分（与「用户看到的画面」同一条坐标系）。
     *
     * 为什么再开一条：readPixels 读的是 GL 缓冲，行序（自下而上）与 drawImage 的源坐标
     * （自上而下）一旦换算错一处，「差异框」与「看到的图」就会互相矛盾 —— 本轮排查就卡在这里：
     * 读像素说差异在嘴，裁出来的图却拍到额头。
     * 这条口子把两帧都 drawImage 进 2D 画布、再用 getImageData 差分，坐标系与截图完全一致。
     * 同时回传差异区域的**平均颜色**：头发是暗的（R,G,B 都低），皮肤/嘴唇是亮的带红，
     * 一眼就能判定「到底动的是哪块」。
     */
    diff2d(opts) {
      const o = opts || {}
      const pose = o.pose || {}
      const owners = []
      for (const [, meshes] of morphOwners) for (const mesh of meshes) if (owners.indexOf(mesh) < 0) owners.push(mesh)
      if (!owners.length) return { ok: false, reason: '场景里没有带形态键的网格' }
      const src = renderer.domElement
      const width = src.width
      const height = src.height
      const saved = owners.map((m) => (m.morphTargetInfluences ? Array.prototype.slice.call(m.morphTargetInfluences) : null))
      const setAll = (v) => {
        for (const m of owners) {
          if (!m.morphTargetInfluences) continue
          for (let i = 0; i < m.morphTargetInfluences.length; i += 1) m.morphTargetInfluences[i] = v
        }
      }
      const grab = () => {
        renderer.render(scene, camera)
        const c = document.createElement('canvas')
        c.width = width
        c.height = height
        const g = c.getContext('2d')
        g.drawImage(src, 0, 0)
        return g.getImageData(0, 0, width, height).data
      }
      const out = { ok: true, canvas: [width, height] }
      try {
        setAll(0)
        const rest = grab()
        setAll(0)
        for (const m of owners) {
          const dict = m.morphTargetDictionary || {}
          if (!m.morphTargetInfluences) continue
          for (const name of Object.keys(pose)) {
            const idx = dict[name]
            if (typeof idx === 'number') m.morphTargetInfluences[idx] = pose[name]
          }
        }
        const posed = grab()
        let changed = 0
        let minX = width
        let maxX = -1
        let minY = height
        let maxY = -1
        let maxChannel = 0
        let sr = 0
        let sg = 0
        let sb = 0
        const rows = new Array(8).fill(0)
        const cols = new Array(8).fill(0)
        for (let y = 0; y < height; y += 1) {
          for (let x = 0; x < width; x += 1) {
            const i = (y * width + x) * 4
            const d = Math.abs(posed[i] - rest[i]) + Math.abs(posed[i + 1] - rest[i + 1]) + Math.abs(posed[i + 2] - rest[i + 2])
            if (d > 3) {
              changed += 1
              if (x < minX) minX = x
              if (x > maxX) maxX = x
              if (y < minY) minY = y
              if (y > maxY) maxY = y
              if (d > maxChannel) maxChannel = d
              rows[Math.min(7, Math.floor(y * 8 / height))] += 1
              cols[Math.min(7, Math.floor(x * 8 / width))] += 1
              sr += rest[i]
              sg += rest[i + 1]
              sb += rest[i + 2]
            }
          }
        }
        out.changedPixels = changed
        out.diffBBox = maxX < 0 ? null : [minX, minY, maxX, maxY]
        out.maxChannelSum = maxChannel
        out.rowHistogram = rows
        out.colHistogram = cols
        out.restMeanInDiff = changed ? [Math.round(sr / changed), Math.round(sg / changed), Math.round(sb / changed)] : null
        out.restMeanWhole = (() => {
          let r = 0
          let g = 0
          let b = 0
          const n = width * height
          for (let i = 0; i < rest.length; i += 4) { r += rest[i]; g += rest[i + 1]; b += rest[i + 2] }
          return [Math.round(r / n), Math.round(g / n), Math.round(b / n)]
        })()
        out.pose = Object.keys(pose).map((k) => k + '=' + pose[k]).join(',')
      } finally {
        owners.forEach((m, i) => {
          if (!m.morphTargetInfluences || !saved[i]) return
          for (let j = 0; j < saved[i].length; j += 1) m.morphTargetInfluences[j] = saved[i][j]
        })
        renderer.render(scene, camera)
      }
      return out
    },

    /**
     * 诊断：**每根骨的屏幕坐标**（画布像素，自上而下）。
     * 为什么需要：这一轮排查反复出现「差异框与肉眼看到的部位对不上」。
     * 光说"嘴在哪"是猜；把骨的世界坐标投影到屏幕，眼/下颌/手各在画面第几行就有了硬坐标，
     * 差异框到底落在嘴还是额头，一比就知道。
     */
    boneScreenPositions() {
      if (!root) return { ok: false, reason: '还没加载模型' }
      root.updateMatrixWorld(true)
      const w = renderer.domElement.width
      const h = renderer.domElement.height
      const list = []
      for (const [key, bone] of collectBones(root)) {
        const v = new THREE.Vector3()
        bone.getWorldPosition(v)
        const p = v.clone().project(camera)
        list.push({
          key,
          name: bone.name,
          world: [+v.x.toFixed(4), +v.y.toFixed(4), +v.z.toFixed(4)],
          screen: [Math.round((p.x * 0.5 + 0.5) * w), Math.round((0.5 - p.y * 0.5) * h)],
        })
      }
      return { ok: true, canvas: [w, h], bones: list }
    },
    probeVisemePixels() {
      const owners = []
      for (const [, meshes] of morphOwners) for (const mesh of meshes) if (owners.indexOf(mesh) < 0) owners.push(mesh)
      if (!owners.length) return { ok: false, reason: '场景里没有带形态键的网格' }
      const size = new THREE.Vector2()
      renderer.getDrawingBufferSize(size)
      const width = Math.max(64, Math.min(1024, Math.round(size.x) || 512))
      const height = Math.max(64, Math.min(1024, Math.round(size.y) || 512))
      const rt = new THREE.WebGLRenderTarget(width, height)
      const buf = new Uint8Array(width * height * 4)
      const base = new Uint8Array(width * height * 4)
      const saved = owners.map((m) => (m.morphTargetInfluences ? Array.prototype.slice.call(m.morphTargetInfluences) : null))
      const shot = () => {
        renderer.setRenderTarget(rt)
        renderer.render(scene, camera)
        renderer.readRenderTargetPixels(rt, 0, 0, width, height, buf)
        renderer.setRenderTarget(null)
      }
      const setAll = (v) => {
        for (const m of owners) {
          if (!m.morphTargetInfluences) continue
          for (let i = 0; i < m.morphTargetInfluences.length; i += 1) m.morphTargetInfluences[i] = v
        }
      }
      const diffCount = () => {
        let n = 0
        for (let i = 0; i < buf.length; i += 4) {
          if (Math.abs(buf[i] - base[i]) > 1 || Math.abs(buf[i + 1] - base[i + 1]) > 1 || Math.abs(buf[i + 2] - base[i + 2]) > 1) n += 1
        }
        return n
      }
      const out = []
      try {
        setAll(0)
        shot()
        base.set(buf)
        const mesh = owners[0]
        const dict = mesh.morphTargetDictionary || {}
        const names = Object.keys(dict)
        for (const name of names) {
          setAll(0)
          const idx = dict[name]
          if (typeof idx !== 'number' || !mesh.morphTargetInfluences) continue
          mesh.morphTargetInfluences[idx] = 1
          shot()
          let maxDelta = 0
          const attrs = mesh.geometry && mesh.geometry.morphAttributes ? mesh.geometry.morphAttributes.position : null
          const attr = attrs ? attrs[idx] : null
          if (attr && attr.array) {
            for (let i = 0; i < attr.array.length; i += 1) {
              const v = Math.abs(attr.array[i])
              if (v > maxDelta) maxDelta = v
            }
          }
          out.push({ name, changedPixels: diffCount(), maxDelta: +maxDelta.toFixed(6) })
        }
        out.sort((a, b) => b.changedPixels - a.changedPixels)
      } finally {
        owners.forEach((m, i) => {
          if (!m.morphTargetInfluences || !saved[i]) return
          for (let j = 0; j < saved[i].length; j += 1) m.morphTargetInfluences[j] = saved[i][j]
        })
        rt.dispose()
        renderer.setRenderTarget(null)
        renderer.render(scene, camera)
      }
      return { ok: true, size: [width, height], keys: out.length, totalPixels: width * height, perKey: out }
    },
    /**
     * 诊断：给指定姿态拍一张"静止 vs 姿态"上下并排的对比图（PNG dataURL）。
     *
     * 为什么必须能拍：本轮排查里，读权重（形态断言）反复给出假绿——
     * 数组确实被改了，用户却看不见嘴动。能不能看见只能看像素。
     * 而截图（CDP）在 WebGL 上不可靠，所以这里**在同一个任务里** render + readPixels
     * + drawImage 到 2D 画布，绕开 preserveDrawingBuffer=false 的坑。
     *
     * 裁剪区自动取"两种姿态差异像素"的外接框再加 pad 倍边距 —— 差异在哪就拍哪，
     * 不至于拍一大片背景、把嘴淹没在缩略图里。
     */
    poseShot(opts) {
      const o = opts || {}
      const pose = o.pose || {}
      const pad = typeof o.pad === 'number' ? o.pad : 2.2
      const owners = []
      for (const [, meshes] of morphOwners) for (const mesh of meshes) if (owners.indexOf(mesh) < 0) owners.push(mesh)
      if (!owners.length) return { ok: false, reason: '场景里没有带形态键的网格' }
      const gl = renderer.getContext()
      const canvas = renderer.domElement
      const width = canvas.width
      const height = canvas.height
      const saved = owners.map((m) => (m.morphTargetInfluences ? Array.prototype.slice.call(m.morphTargetInfluences) : null))
      const setAll = (v) => {
        for (const m of owners) {
          if (!m.morphTargetInfluences) continue
          for (let i = 0; i < m.morphTargetInfluences.length; i += 1) m.morphTargetInfluences[i] = v
        }
      }
      const applyPose = () => {
        for (const m of owners) {
          const dict = m.morphTargetDictionary || {}
          if (!m.morphTargetInfluences) continue
          for (const name of Object.keys(pose)) {
            const idx = dict[name]
            if (typeof idx === 'number') m.morphTargetInfluences[idx] = pose[name]
          }
        }
      }
      const readPixels = () => {
        renderer.render(scene, camera)
        const out = new Uint8Array(width * height * 4)
        gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, out)
        return out
      }
      let result
      try {
        setAll(0)
        const restPixels = readPixels()
        setAll(0)
        applyPose()
        const posePixels = readPixels()
        let minX = width
        let maxX = -1
        let minY = height
        let maxY = -1
        let changed = 0
        let maxChannel = 0
        for (let y = 0; y < height; y += 1) {
          for (let x = 0; x < width; x += 1) {
            const i = (y * width + x) * 4
            const d = Math.abs(posePixels[i] - restPixels[i]) + Math.abs(posePixels[i + 1] - restPixels[i + 1]) + Math.abs(posePixels[i + 2] - restPixels[i + 2])
            if (d > 3) {
              changed += 1
              // readPixels 第 0 行在**下边**，而 drawImage 的源矩形是**上边**为 0：
              // 这里统一换算成自上而下的行号，否则裁剪区会上下颠倒（实测拍到了肚子而不是嘴）。
              const row = height - 1 - y
              if (x < minX) minX = x
              if (x > maxX) maxX = x
              if (row < minY) minY = row
              if (row > maxY) maxY = row
              if (d > maxChannel) maxChannel = d
            }
          }
        }
        if (maxX < 0) { minX = 0; maxX = width - 1; minY = 0; maxY = height - 1 }
        const cx = (minX + maxX) / 2
        const cy = (minY + maxY) / 2
        const bw = Math.max(64, Math.min(width, Math.round((maxX - minX + 1) * pad)))
        const bh = Math.max(48, Math.min(height, Math.round((maxY - minY + 1) * pad)))
        const sx = Math.max(0, Math.min(width - bw, Math.round(cx - bw / 2)))
        const sy = Math.max(0, Math.min(height - bh, Math.round(cy - bh / 2)))
        const zoom = typeof o.zoom === 'number' && o.zoom > 0 ? o.zoom : 2
        const out = document.createElement('canvas')
        out.width = Math.round(bw * zoom)
        out.height = Math.round(bh * 2 * zoom)
        const ctx = out.getContext('2d')
        // 关掉插值：放大后能看清是"真的形变"还是模糊插值
        ctx.imageSmoothingEnabled = false
        ctx.fillStyle = '#000'
        ctx.fillRect(0, 0, out.width, out.height)
        setAll(0)
        renderer.render(scene, camera)
        ctx.drawImage(canvas, sx, sy, bw, bh, 0, 0, out.width, Math.round(bh * zoom))
        setAll(0)
        applyPose()
        renderer.render(scene, camera)
        ctx.drawImage(canvas, sx, sy, bw, bh, 0, Math.round(bh * zoom), out.width, Math.round(bh * zoom))
        result = {
          ok: true,
          canvas: [width, height],
          crop: [sx, sy, bw, bh],
          diffBBox: [minX, minY, maxX, maxY],
          changedPixels: changed,
          maxChannelSum: maxChannel,
          pose: Object.keys(pose).map((k) => k + '=' + pose[k]).join(','),
          width: out.width,
          height: out.height,
          zoom,
          dataUrl: out.toDataURL('image/png'),
        }
      } finally {
        owners.forEach((m, i) => {
          if (!m.morphTargetInfluences || !saved[i]) return
          for (let j = 0; j < saved[i].length; j += 1) m.morphTargetInfluences[j] = saved[i][j]
        })
        renderer.render(scene, camera)
      }
      return result
    },
    /** 诊断：最近一帧**渲染时**的 morph 权重（区分"写了"与"画了"） */
    renderInfluences() { return renderInfluenceSample },
    /** 诊断用：暴露渲染器内部状态（排"取景裁切"这类问题时不必再靠猜） */
    debug() {
      const info = renderer && renderer.info ? renderer.info : null
      const size = new THREE.Vector2()
      if (renderer) renderer.getSize(size)
      return {
        canvasCss: measure(),
        rendererSize: { w: size.x, h: size.y },
        pixelRatio: renderer ? renderer.getPixelRatio() : null,
        camera: camera ? {
          pos: [+camera.position.x.toFixed(4), +camera.position.y.toFixed(4), +camera.position.z.toFixed(4)],
          fov: camera.fov, near: +camera.near.toFixed(4), far: +camera.far.toFixed(3),
          aspect: +camera.aspect.toFixed(4),
        } : null,
        focus: focus ? {
          center: [+focus.center.x.toFixed(4), +focus.center.y.toFixed(4), +focus.center.z.toFixed(4)],
          size: [+focus.size.x.toFixed(4), +focus.size.y.toFixed(4), +focus.size.z.toFixed(4)],
        } : null,
        rootPos: root ? [+root.position.x.toFixed(4), +root.position.y.toFixed(4), +root.position.z.toFixed(4)] : null,
        spin: typeof spinGroup !== 'undefined' && spinGroup ? {
          pos: [+spinGroup.position.x.toFixed(4), +spinGroup.position.y.toFixed(4), +spinGroup.position.z.toFixed(4)],
          rotY: +spinGroup.rotation.y.toFixed(4),
        } : null,
        calls: info ? info.render.calls : null,
        triangles: info ? info.render.triangles : null,
      }
    },
    load: loadSafe,
    resize,
    rotate,
    applyPayload,
    applyWeights,
      applyCommands,
      applyCommandsThrottled: (c) => commandThrottle.call(c),
    applyWeightsThrottled: (w) => throttle.call(w),
      commandThrottleStats: () => commandThrottle.stats(),
    throttleStats: () => throttle.stats(),
    isReady: () => ready,
    stats,
    dispose,
  }
}

/* ─────────────── 双端单例：H5 直连 DOM 与 App renderjs 只会有一个真生效 ─────────────── */

let STAGE = null

/** 挂载舞台（幂等）。返回 null 表示已有实例在跑，本次调用不新建。 */
export function mountFaceStage(el, opt) {
  if (STAGE) return STAGE
  STAGE = createFaceStage(Object.assign({}, opt, { el }))
  // 自动化验收句柄：无头浏览器（CDP）里 import 本模块拿到的可能是**另一个模块实例**
  // （页面用 @ 别名、脚本用路径，Vite 会解析成不同 URL），因此把舞台挂到 window 上，
  // 让"拖了滑杆到底动没动模型"能被逐像素验证，而不是靠猜。
  if (typeof window !== 'undefined') window.__blFaceStage = STAGE
  return STAGE
}

export function getFaceStage() {
  return STAGE
}

export function unmountFaceStage() {
  if (!STAGE) return
  STAGE.dispose()
  STAGE = null
}

export default {
  FACE_THREE_VERSION, AVATAR_ASSET, DEFAULT_GENDER, GENDER_OPTIONS, DRAG, DEFAULT_HZ,
  resolveAssetUrl, createFaceStage, mountFaceStage, getFaceStage, unmountFaceStage,
}
