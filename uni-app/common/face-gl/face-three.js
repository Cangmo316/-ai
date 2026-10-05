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
  canvas.style.cssText = 'display:block;width:100%;height:100%;touch-action:none;outline:none;'
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
  const hemi = new THREE.HemisphereLight(0xFFFFFF, 0x9AA6A0, 2.0)
  const keyLight = new THREE.DirectionalLight(0xFFFFFF, 2.1)
  keyLight.position.set(0.55, 0.95, 1.45)
  const fillLight = new THREE.DirectionalLight(0xBFD4E6, 0.85)
  fillLight.position.set(-1.05, 0.25, 0.65)
  const rimLight = new THREE.DirectionalLight(0xFFFFFF, 1.0)
  rimLight.position.set(0, 0.65, -1.25)
  scene.add(hemi, keyLight, fillLight, rimLight)

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

  function schedule() {
    if (!alive || raf) return
    raf = requestAnimationFrame(() => {
      raf = 0
      if (!alive) return
      renderer.render(scene, camera)
    })
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
  function computeFocus() {
    if (!root) return
    root.position.set(0, 0, 0)
    root.updateWorldMatrix(true, true)
    const body = restBoxOf(root)
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
    const dist = Math.max(distV, distH) * FIT_MARGIN
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
  async function load(gender) {
    const g = AVATAR_ASSET[gender] ? gender : DEFAULT_GENDER
    // 幂等：H5 的 onMounted 与 App 的 renderjs mounted 都可能触发首次加载，
    // 加上首帧兜底的 boot tick，同一性别最多只真正加载一次。
    if (loading) return stats()
    if (ready && currentGender === g) return stats()
    const url = resolveAssetUrl(AVATAR_ASSET[g])
    loading = true
    ready = false
    loadingGender = g
    lastAssetUrl = url
    lastError = ''
    if (o.onStatus) o.onStatus('正在加载' + (g === 'female' ? '女性' : '男性') + '形象…')
    const t0 = Date.now()
    try {
      const gltf = await loader.loadAsync(url)
      // 换模型：先拆旧的再挂新的，避免两套骨骼同时参与渲染
      if (root) { spinGroup.remove(root); disposeObject(root, renderer) }
      root = gltf.scene
      spinGroup.add(root)
      bound = bindThree(root)
      morphOwners = collectMorphOwners(root)
      lastLoadMs = Date.now() - t0
      computeFocus()
      resize()
      applyFraming()
      applyWeights(weights)
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
    }
  }

  /** load 的失败兜底包装：任何异常都要把 loading 复位，否则后续切换性别会被幂等守卫挡住。 */
  const loadSafe = (g) => Promise.resolve().then(() => load(g)).catch((e) => {
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
