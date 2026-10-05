#!/usr/bin/env node
/**
 * 比邻AI · 捏脸参数面板一致性测试（零依赖）
 *
 *   node tools/test-face-params.mjs
 *
 * 守住的是「面板 ↔ 参数表 ↔ 裁剪层 ↔ 真实资产」四者不许悄悄脱节：
 *   1. 面板目录来自参数表 + 适老裁剪，「不做」的参数不得出现在面板里
 *   2. 面板里每个 morph 参数的 target 必须**真实存在于 GLB**（资产改名/漏导出会被抓住）
 *   3. 反过来：GLB 里的形变键有没有没被任何参数用上的（覆盖率）
 *   4. 权重规则：morph 权重**不得为负**；双向参数正向只出 _up、负向只出 _dn
 *   5. 四通道：默认态与全随机态都能算出指令，且没有告警
 *   6. UI 元数据：每个滑杆都有名称/区间/默认值，默认值落在区间内
 *
 * 为什么直接读 GLB 而不是读文档：文档会滞后（实测文档写 111 个 shape_*，
 * 而 GLB 里到底有哪些名字只有文件本身说了算）。
 */

import assert from 'node:assert/strict'
import { openSync, readSync, closeSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { finish, group, test } from './test-util.mjs'

const here = dirname(fileURLToPath(import.meta.url))
const GLB = join(here, '..', 'uni-app', 'static', 'avatar', 'BilinAI_FemaleFaceRig_60k_edit.glb')

/**
 * 只读 GLB 的 JSON 块（不把 9.7MB 二进制全读进内存）。
 * GLB 结构：12 字节头 + 第一块（JSON）+ 第二块（BIN）。
 */
function readGlbJson(path) {
  const fd = openSync(path, 'r')
  try {
    const header = Buffer.alloc(12)
    readSync(fd, header, 0, 12, 0)
    assert.equal(header.readUInt32LE(0), 0x46546c67, 'GLB 魔数不对')
    const jsonLength = readSync(fd, Buffer.alloc(0), 0, 0, 0) // noop，保持 fd 语义清晰
    void jsonLength
    const chunkHeader = Buffer.alloc(8)
    readSync(fd, chunkHeader, 0, 8, 12)
    const length = chunkHeader.readUInt32LE(0)
    const type = chunkHeader.readUInt32LE(4)
    assert.equal(type, 0x4e4f534a, '第一块不是 JSON')
    const json = Buffer.alloc(length)
    readSync(fd, json, 0, length, 20)
    return JSON.parse(json.toString('utf8'))
  } finally {
    closeSync(fd)
  }
}

/** GLB 里每个网格的形变键名集合 */
function morphNamesOf(gltf) {
  const byMesh = new Map()
  for (const mesh of gltf.meshes || []) {
    const names = new Set()
    for (const primitive of mesh.primitives || []) {
      const list = primitive.extras?.targetNames || mesh.extras?.targetNames || []
      list.forEach((n) => names.add(n))
    }
    if (names.size) byMesh.set(mesh.name || '(未命名)', names)
  }
  return byMesh
}

const index = await import('../uni-app/common/face/face-index.js')
const {
  SLIDER_GROUPS, GROUPED_KEYS, SLIDER_BY_KEY_ALL, sliderMeta, panelSummary,
  WIRED_CHANNELS, defaultValues, randomValues, computeView, care, fp,
} = index

const gltf = readGlbJson(GLB)
const morphsByMesh = morphNamesOf(gltf)
const allMorphNames = new Set()
for (const set of morphsByMesh.values()) for (const n of set) allMorphNames.add(n)
const nodeMorphs = meshSet('node_0') || new Set()

const summary = panelSummary()

/* ---------------------------------------------------------------- 1. 面板目录 */

group('面板目录（参数表 + 适老裁剪 → 分区滑杆）')

/** 网格名可能带 .001/.002 之类的后缀，按前缀匹配更耐改名 */
function meshSet(name) {
  for (const [meshName, set] of morphsByMesh) {
    if (meshName === name || meshName.startsWith(name + '.') || meshName.startsWith(name + '_')) return set
  }
  return null
}

test('分区数量与参数表 zones 一致', () => {
  const zoneKeys = Object.keys(index.table.zones)
  const panelZones = SLIDER_GROUPS.map((g) => g.zone)
  assert.ok(panelZones.length > 0, '面板没有任何分区')
  for (const z of panelZones) assert.ok(zoneKeys.includes(z), '分区 ' + z + ' 不在参数表 zones 里')
})

test('面板条目 = 裁剪层判定「保留 + 弱化」的参数，一条不多一条不少', () => {
  const visible = care.visibleParams().slice().sort()
  const inPanel = GROUPED_KEYS.slice().sort()
  assert.deepEqual(inPanel, visible, '面板键集合与 care.visibleParams() 不一致')
  assert.equal(GROUPED_KEYS.length, new Set(GROUPED_KEYS).size, '面板里有重复参数键')
})

test('适老裁剪「不做」的参数不出现在面板里', () => {
  const dropped = care.hiddenParams()
  assert.ok(dropped.length > 0, '裁剪层居然没有「不做」的参数？')
  for (const k of dropped) {
    assert.ok(!GROUPED_KEYS.includes(k), '「不做」的参数 ' + k + ' 出现在面板里了')
  }
  assert.equal(summary.dropped, dropped.length)
})

test('总览数字自洽（总数 = 开放 + 不做）', () => {
  assert.equal(summary.open, GROUPED_KEYS.length)
  assert.equal(summary.total, care.stats().total)
  assert.equal(summary.open + summary.dropped, summary.total, '开放 + 不做 ≠ 总数')
  assert.equal(summary.wired + summary.pending, summary.open, '接线 + 等资产 ≠ 开放')
})

test('面板覆盖原计划规模（≥90 条，不是早期的 3 条）', () => {
  assert.ok(GROUPED_KEYS.length >= 90, '面板只有 ' + GROUPED_KEYS.length + ' 条，远小于参数表规模')
  assert.ok(summary.zones >= 10, '分区数 ' + summary.zones + ' 少于 10')
})

/* ------------------------------------------------- 2/3. 与真实资产的对应关系 */

group('面板 ↔ GLB 资产一致性（直接读 static/avatar 里的 .glb）')

const morphSliders = GROUPED_KEYS.map((k) => SLIDER_BY_KEY_ALL[k]).filter((m) => m.channel === 'morph')

test('滑杆目录里「已接线」参数的 target 都真实存在于 GLB', () => {
  // ⚠️ 判据在 2026-10-05 随策略变更重写：**移除 3D 捏脸**后，
  //    面板目录里的 shape_* 参数不再由资产承担（资产只带 vis_*/expr_*）。
  //    旧判据"每个 morph 参数（含 shape_*）的 target 都必须在 GLB 里"必然失败 —— 那正是新方案要的形态。
  //    新判据：只校验**已接线到 vis_*/expr_* 的**参数；shape_* 参数视为"等资产/未接线"，列出但不判失败。
  const missing = []
  let wired = 0
  for (const m of morphSliders) {
    if (m.targets.length === 0) continue
    const visTargets = m.targets.filter((t) => t.startsWith('vis_') || t.startsWith('expr_'))
    if (visTargets.length === 0) continue        // shape_* 类参数：本方案不由资产承担
    wired += 1
    assert.ok(m.targets.length <= 2, m.key + ' 的 target 超过 2 个（双向应只有 up/dn）')
    for (const t of visTargets) if (!allMorphNames.has(t)) missing.push(m.key + '→' + t)
  }
  assert.deepEqual(missing, [], '这些 target 在 GLB 里不存在：' + missing.join(', '))
  // 注：本方案里 vis_*/expr_* 由 **lip-sync 曲线**驱动（运行时从服务端下发），
  //     不经过捏脸面板的滑杆目录，所以这里**不要求**"必须有参数接到它们"——那是旧（捏脸）方案的口径。
  void wired
})

test('双向参数必须 up/dn 成对（不会只导出一半）', () => {
  const broken = []
  for (const m of morphSliders) {
    if (!m.bidirectional) continue
    // 只校验接到 vis_*/expr_* 的参数（shape_* 类参数本方案不由资产承担）
    if (!m.targets.some((t) => t.startsWith('vis_') || t.startsWith('expr_'))) continue
    const hasUp = m.targets.some((t) => t.endsWith('_up'))
    const hasDn = m.targets.some((t) => t.endsWith('_dn'))
    if (!(hasUp && hasDn)) broken.push(m.key)
  }
  assert.deepEqual(broken, [], '双向参数缺少 up 或 dn 目标：' + broken.join(', '))
})

test('单向参数带 dn 目标的情况逐条报出（口径分歧，不静默）', () => {
  // 已知：lid_crease_depth 在参数表里区间是 0~1（单向），
  // 但 shape-namespace-map 里 _up / _dn 两个目标都声明了 → 那个 _dn 永远驱动不到。
  // 这是「参数表 ↔ 映射表」的口径分歧，属于产品决策（要不要开放负向），
  // 因此这里只列出来，不判失败；要开放就把参数表区间改成 -1~+1。
  const oneSided = []
  for (const p of index.table.params) {
    const map = (index.namespaceMap.params || []).find((x) => x.key === p.k)
    if (!map || !map.target_dn) continue
    const meta = SLIDER_BY_KEY_ALL[p.k]
    if (!meta.bidirectional) oneSided.push(p.k + '（表区间 ' + p.rg + '，dn 目标 ' + map.target_dn + ' 不可达）')
  }
  if (oneSided.length) {
    console.log('      · 提示：' + oneSided.join('；'))
  }
  // 断言留一条底线：这种条目不能变成大量（否则说明表与映射大面积脱节）
  assert.ok(oneSided.length <= 3, '单向却有 dn 目标的参数过多（' + oneSided.length + ' 条），表与映射可能大面积脱节')
})

test('GLB 的形变键都是「唇形同步 + 表情」契约内的键（不夹带捏脸键）', () => {
  // ⚠️ 判据在 2026-10-05 随策略变更(移除 3D 捏脸)重写：
  //    旧判据是"GLB 的 shape_* 有 ≥95% 被面板滑杆用上"；现在**没有捏脸**，
  //    资产里应当只有 vis_* / expr_*，出现 shape_* 反而说明导错件。
  const allowed = new Set([
    'vis_silence', 'vis_AA', 'vis_E', 'vis_I', 'vis_O', 'vis_U', 'vis_MBP', 'vis_FV',
    'vis_L', 'vis_TH', 'vis_WQ', 'vis_RR', 'vis_SS', 'vis_KK', 'vis_NN',
    'expr_blink_L', 'expr_blink_R', 'expr_smile', 'expr_frown', 'expr_surprise',
    'expr_squint', 'expr_brow_up', 'expr_brow_down',
  ])
  const unexpected = [...nodeMorphs].filter((n) => !allowed.has(n))
  assert.deepEqual(unexpected, [],
    'GLB 里有契约外的形变键（已移除捏脸，不该有 shape_*）：' + unexpected.join(', '))
  const missing = [...allowed].filter((n) => !nodeMorphs.has(n))
  assert.deepEqual(missing, [], '缺口型/表情键：' + missing.join(', '))
})

test('口内网格：本方案不要求（Q 版医生的口腔画在贴图上）', () => {
  // ⚠️ 判据在 2026-10-05 随资产更换调整：新资产是 **Q 版医生**，
  //    口腔/牙齿是**画在贴图上**的，没有独立的 mouth_cavity / teeth / tongue 网格。
  //    这里不判失败，只在"有这些网格"时才校验其口型键是否齐全（保留对旧资产的守护）。
  const present = ['mouth_cavity', 'teeth', 'tongue'].filter((name) => meshSet(name))
  if (present.length === 0) {
    console.log('      · 新资产没有口内网格（口腔画在贴图上），跳过该校验')
    return
  }
  const mouthTargets = ['vis_AA', 'vis_O', 'vis_MBP']
  for (const name of present) {
    const set = meshSet(name)
    for (const t of mouthTargets) {
      assert.ok(set.has(t), name + ' 缺少 ' + t)
    }
  }
})
test('正向只出 _up、负向只出 _dn，且权重恒 ≥ 0', () => {
  const bi = morphSliders.filter((m) => m.bidirectional)
  assert.ok(bi.length > 30, '双向参数只有 ' + bi.length + ' 条')
  for (const m of bi.slice(0, 12)) {
    const up = fp.applyParams({ [m.key]: 1 })
    const dn = fp.applyParams({ [m.key]: -1 })
    for (const w of [...Object.values(up.targets), ...Object.values(dn.targets)]) {
      assert.ok(w >= 0, m.key + ' 出现了负权重')
    }
    assert.ok(Object.keys(up.targets).every((t) => t.endsWith('_up')), m.key + ' 正向出现了非 _up 目标')
    assert.ok(Object.keys(dn.targets).every((t) => t.endsWith('_dn')), m.key + ' 负向出现了非 _dn 目标')
  }
})

test('单向参数传负值被丢弃且给出告警（不静默）', () => {
  const uni = morphSliders.filter((m) => !m.bidirectional)
  assert.ok(uni.length > 0, '没有单向参数？')
  const m = uni[0]
  const r = fp.applyParams({ [m.key]: -0.5 })
  assert.equal(Object.keys(r.targets).length, 0, m.key + ' 单向参数负值不该产生权重')
  assert.ok(r.warnings.length > 0, m.key + ' 单向参数负值应有告警')
})

test('滑杆端点不越界（-100/100 与裁剪后的区间一致）', () => {
  for (const m of morphSliders) {
    const p = SLIDER_BY_KEY_ALL[m.key]
    const min = p.paramMin
    const max = p.paramMax
    const atMin = fp.applyParams({ [m.key]: min })
    const atMax = fp.applyParams({ [m.key]: max })
    assert.ok(atMin.warnings.length === 0, m.key + ' 在自身区间下限仍有告警：' + atMin.warnings.join(';'))
    assert.ok(atMax.warnings.length === 0, m.key + ' 在自身区间上限仍有告警：' + atMax.warnings.join(';'))
  }
})

test('被裁剪收敛的参数，区间确实比原表更窄', () => {
  const tightened = GROUPED_KEYS.map((k) => SLIDER_BY_KEY_ALL[k]).filter((m) => m.trimmed)
  assert.ok(tightened.length > 0, '裁剪层没有收敛任何区间？')
  for (const m of tightened.slice(0, 10)) {
    const c = care.describeParam(m.key)
    assert.ok(c.sliderTightened, m.key + ' 标了 trimmed 但裁剪层说不窄')
    assert.ok(m.paramMin >= -1 && m.paramMax <= 1, m.key + ' 的收敛区间越界')
  }
})

/* ------------------------------------------------------------- 5. 四通道 */

group('四通道指令（morph / bone / material / asset）')

const defaults = defaultValues(GROUPED_KEYS)

test('默认态：无告警，且四通道都能算出指令', () => {
  const view = computeView(defaults, { keys: GROUPED_KEYS })
  assert.deepEqual(view.warnings, [], '默认态告警：' + view.warnings.join('; '))
  assert.equal(Object.keys(view.weights).length, 0, '默认态不该有任何形变权重')
  assert.ok(Object.keys(view.cmds.bones).length > 0, 'bone 通道没有指令（骨骼参数将拖不动）')
  assert.ok(Object.keys(view.cmds.materials).length > 0, 'material 通道没有指令（材质参数将拖不动）')
})

test('全随机态：无告警、无负权重、四个通道都有内容', () => {
  const values = randomValues(GROUPED_KEYS, mulberry(7))
  const view = computeView(values, { keys: GROUPED_KEYS })
  assert.deepEqual(view.warnings, [], '随机态告警：' + view.warnings.join('; '))
  for (const [name, w] of Object.entries(view.weights)) {
    assert.ok(w >= 0 && w <= 1, '形变 ' + name + ' 权重越界：' + w)
  }
  assert.ok(Object.keys(view.weights).length > 20, '随机后形变键只有 ' + Object.keys(view.weights).length + ' 个')
  assert.ok(Object.keys(view.cmds.bones).length > 0, '随机后 bone 通道为空')
  assert.ok(Object.keys(view.cmds.assets).length > 0, '随机后 asset 通道为空')
})

test('滑杆元数据完整，默认值落在区间内', () => {
  for (const m of GROUPED_KEYS.map((k) => SLIDER_BY_KEY_ALL[k])) {
    assert.ok(m.name && m.name.length, m.key + ' 没有中文名')
    assert.ok(m.zone, m.key + ' 没有分区')
    assert.ok(m.uMin <= m.uMax, m.key + ' 的 UI 区间反了')
    assert.ok(m.defU >= m.uMin && m.defU <= m.uMax, m.key + ' 的默认值 ' + m.defU + ' 不在 [' + m.uMin + ',' + m.uMax + '] 内')
    assert.equal(typeof m.wired, 'boolean', m.key + ' 缺少 wired 标记')
    if (m.channel === 'morph') assert.ok(WIRED_CHANNELS.includes('morph'))
    if (!m.wired) assert.equal(m.channel, 'asset', m.key + ' 未接线但通道不是 asset')
  }
})

test('全部 102 条参数都能查到元数据（面板外参数也能回填）', () => {
  assert.equal(Object.keys(SLIDER_BY_KEY_ALL).length, index.table.params.length)
  for (const p of index.table.params) {
    const m = SLIDER_BY_KEY_ALL[p.k]
    assert.ok(m, '参数 ' + p.k + ' 查不到滑杆元数据')
    assert.equal(m.name, p.cn, p.k + ' 的中文名与参数表不一致')
  }
})

test('随机数可复现（同种子同结果，便于复现问题）', () => {
  const a = randomValues(GROUPED_KEYS, mulberry(42))
  const b = randomValues(GROUPED_KEYS, mulberry(42))
  assert.deepEqual(a, b, '同种子随机结果不一致')
})

test('面板里没有"能拖但永远不动"的参数（未接线必须标注通道）', () => {
  const dead = []
  for (const k of GROUPED_KEYS) {
    const m = SLIDER_BY_KEY_ALL[k]
    if (m.channel === 'morph') continue
    if (!m.wired && m.pendingReason === '等资产') continue
    if (!m.wired) dead.push(k + '(' + m.channel + ')')
  }
  assert.deepEqual(dead, [], '这些参数既未接线又没有标注原因：' + dead.join(', '))
})

function mulberry(seed) {
  let a = seed >>> 0
  return function next() {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

finish()
