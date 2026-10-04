#!/usr/bin/env node
/**
 * v2 资产（staging）的"可替换性"契约测试
 *
 * 为什么需要它：`uni-app/static/avatar/` 里那两个 GLB 有两个**不同**的用途——
 *   · `*_edit.glb`        → 捏脸页（需要 `shape_*` 形态键，端侧按名字写 morph 权重）
 *   · `*_delivery_baked.glb` → 运行期数字人（8 骨、含眼球/口内网格/虹膜贴图）
 * v2 资产目前**只做到 `vis_*` / `expr_*`**，`shape_*` 还没建，
 * 直接把 v2 覆盖 `_edit.glb` 会让捏脸页所有滑杆失效
 * （实测：`node tools/test-face-params.mjs` 报"覆盖率只有 0.0%"）。
 * 本脚本把"能不能换"变成一条可复跑的命令，条件满足时打印 SWAP_READY。
 *
 * 用法： node tools/test-avatar-v2-glb.mjs [staging.glb 路径] [--role edit|delivery]
 *   默认 role=edit（对应 `*_edit.glb`：要 shape_*、骨数上限 40、≤60k tri）
 *   role=delivery（对应 `*_delivery_baked.glb`：8 骨、不要 shape_*、≤60k tri）
 * 退出码：0 = 可以替换；1 = 还不能替换（并列出缺什么）
 */

import { readFileSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const repo = join(here, '..')

const args = process.argv.slice(2)
const roleIndex = args.indexOf('--role')
const role = roleIndex >= 0 ? args[roleIndex + 1] : 'edit'
const positional = args.filter((a, i) => !a.startsWith('--') && i !== roleIndex + 1)

const target = positional[0] ||
  join(repo, '3D建模', '_rig_work', 'staging', 'BilinAI_FemaleRig_v2_60k.glb')

function readGlbJson(path) {
  const buffer = readFileSync(path)
  if (buffer.readUInt32LE(0) !== 0x46546c67) throw new Error('GLB 魔数不对')
  const length = buffer.readUInt32LE(12)
  const type = buffer.readUInt32LE(16)
  if (type !== 0x4e4f534a) throw new Error('第一块不是 JSON')
  return JSON.parse(buffer.subarray(20, 20 + length).toString('utf8'))
}

function targetNames(mesh) {
  const list = []
  for (const primitive of mesh.primitives || []) {
    const names = primitive.extras?.targetNames || mesh.extras?.targetNames || []
    if (names.length) list.push(...names)
  }
  return list
}

if (!existsSync(target)) {
  console.error(`找不到待测 GLB：${target}`)
  console.error('（先跑 tools/blender-morph-build.py 与 tools/blender-export-glb.py 生成）')
  process.exit(1)
}

const gltf = readGlbJson(target)
const meshes = gltf.meshes || []
const node0 = meshes.find((m) => m.name === 'node_0') || meshes[0]
const names = targetNames(node0)
const tris = (gltf.meshes || []).reduce((sum, mesh) => {
  let count = 0
  for (const primitive of mesh.primitives || []) {
    const accessor = gltf.accessors?.[primitive.indices]
    count += accessor ? accessor.count / 3 : 0
  }
  return sum + count
}, 0)
const joints = (gltf.skins || []).reduce((max, skin) => Math.max(max, (skin.joints || []).length), 0)
const sizeMB = (readFileSync(target).length / 1024 / 1024).toFixed(1)

const vis = names.filter((n) => n.startsWith('vis_'))
const expr = names.filter((n) => n.startsWith('expr_'))
const shape = names.filter((n) => n.startsWith('shape_'))
const boneLimit = role === 'edit' ? 40 : 8

console.log(`待测：${target}   role=${role}`)
console.log(`  ${sizeMB} MB / ${Math.round(tris)} tri / ${joints} joints / ${names.length} morphs`)
console.log(`  vis_* ${vis.length} / expr_* ${expr.length} / shape_* ${shape.length}`)

const blockers = []
if (tris > 60000) blockers.push(`三角面 ${Math.round(tris)} > 60000（交付预算）`)
if (joints > boneLimit) blockers.push(`骨数 ${joints} > ${boneLimit}（${role} 期上限）`)
if (role === 'edit' && shape.length === 0) {
  blockers.push('没有 shape_* 形态键 → 覆盖 _edit.glb 会让捏脸页 102 条滑杆全部失效'
    + '（复现：node tools/test-face-params.mjs 报"覆盖率 0.0%"）')
}
if (role === 'delivery' && shape.length > 0) {
  blockers.push(`交付件不该带 shape_*（实测 ${shape.length} 个）`)
}
if (vis.length !== 15) blockers.push(`vis_* 数量 ${vis.length} ≠ 15`)
if (expr.length !== 8) blockers.push(`expr_* 数量 ${expr.length} ≠ 8`)

const need = ['vis_silence', 'vis_AA', 'vis_E', 'vis_I', 'vis_O', 'vis_U', 'vis_MBP',
  'vis_FV', 'vis_L', 'vis_TH', 'vis_WQ', 'vis_RR', 'vis_SS', 'vis_KK', 'vis_NN',
  'expr_blink_L', 'expr_blink_R', 'expr_smile', 'expr_frown', 'expr_surprise',
  'expr_squint', 'expr_brow_up', 'expr_brow_down']
const missing = need.filter((n) => !names.includes(n))
if (missing.length) blockers.push(`缺形态键：${missing.join(', ')}`)

if (blockers.length === 0) {
  console.log(`\nSWAP_READY —— 可以替换 uni-app/static/avatar/ 里对应 role=${role} 的那个 GLB`)
  console.log('替换后必须复跑：node tools/test-face-params.mjs && npm test')
  process.exit(0)
}

console.log('\nSWAP_BLOCKED —— 还不能替换，缺：')
for (const item of blockers) console.log('  · ' + item)
process.exit(1)
