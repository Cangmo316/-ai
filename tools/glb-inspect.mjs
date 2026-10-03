#!/usr/bin/env node
/**
 * 比邻AI · GLB 检查与反抽工具（零依赖）
 *
 * 用法：
 *   node tools/glb-inspect.mjs <文件.glb> [更多.glb...]              # 列出形变键名、贴图、骨架、网格
 *   node tools/glb-inspect.mjs --extract-images <文件.glb> <输出目录>
 *                                                                   # 把 GLB 内嵌贴图导出为 PNG
 *
 * 为什么需要它：
 *   · .blend 里的贴图路径可能失效（渲染成品红），但 GLB 通常已把贴图内嵌（bufferView）——
 *     可以从 GLB 反抽回来重新链接，不必再找原始素材
 *   · 形变键（morph target）名字是端侧"捏脸参数"的唯一来源，必须直接从 GLB 读，
 *     不能靠文档转述（文档可能滞后）
 */

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { basename, join } from 'node:path'

function parseGlb(path) {
  const buffer = readFileSync(path)
  if (buffer.readUInt32LE(0) !== 0x46546c67) throw new Error('不是 GLB 文件: ' + path)
  const total = buffer.readUInt32LE(8)
  let offset = 12
  let json = null
  let bin = null
  while (offset < total) {
    const length = buffer.readUInt32LE(offset)
    const type = buffer.readUInt32LE(offset + 4)
    const chunk = buffer.subarray(offset + 8, offset + 8 + length)
    if (type === 0x4e4f534a) json = JSON.parse(chunk.toString('utf8'))
    else if (type === 0x004e4942) bin = chunk
    offset += 8 + length + ((4 - (length % 4)) % 4 === 4 ? 0 : (4 - (length % 4)) % 4)
  }
  return { json, bin, bytes: buffer.length }
}

/** 每个网格的形变键名（glTF 把名字放在 primitive.extras.targetNames 或 mesh.extras.targetNames） */
function morphNames(json) {
  const out = {}
  for (const mesh of json.meshes || []) {
    const names = new Set()
    for (const primitive of mesh.primitives || []) {
      const list = primitive.extras?.targetNames || mesh.extras?.targetNames || []
      list.forEach((name) => names.add(name))
    }
    if (names.size) out[mesh.name || '(未命名网格)'] = [...names]
  }
  return out
}

function namespaces(names) {
  const counts = {}
  for (const name of names) {
    const prefix = name.includes('_') ? name.slice(0, name.indexOf('_') + 1) : '(无前缀)'
    counts[prefix] = (counts[prefix] || 0) + 1
  }
  return counts
}

function extractImages(path, outDir) {
  const { json, bin } = parseGlb(path)
  mkdirSync(outDir, { recursive: true })
  const written = []
  ;(json.images || []).forEach((image, index) => {
    if (image.bufferView === undefined) {
      written.push({ name: image.name || `image_${index}`, skipped: '外链 uri=' + image.uri })
      return
    }
    const view = json.bufferViews[image.bufferView]
    const start = view.byteOffset || 0
    const data = bin.subarray(start, start + view.byteLength)
    const ext = (image.mimeType || 'image/png').includes('jpeg') ? '.jpg' : '.png'
    const safe = (image.name || `image_${index}`).replace(/[^\w.\-]+/g, '_')
    const file = join(outDir, safe + ext)
    writeFileSync(file, data)
    written.push({ name: image.name || `image_${index}`, file, bytes: data.length })
  })
  return written
}

function describe(path) {
  const { json, bytes } = parseGlb(path)
  console.log('='.repeat(78))
  console.log(basename(path) + '   ' + (bytes / 1024 / 1024).toFixed(1) + 'MB')
  const skins = (json.skins || []).map((s) => (s.joints || []).length)
  console.log('  骨架 joints: ' + (skins.length ? skins.join(', ') : '无'))
  const meshes = (json.meshes || []).map((m, i) => {
    const prim = m.primitives?.[0] || {}
    const pos = prim.attributes?.POSITION
    const count = pos !== undefined ? json.accessors[pos].count : 0
    return `${m.name || 'mesh' + i}(${count}v)`
  })
  console.log('  网格: ' + meshes.join(', '))
  console.log('  材质: ' + (json.materials || []).map((m) => m.name).join(', '))
  console.log('  贴图: ' + (json.images || []).map((im) => im.name).join(', '))
  const morphs = morphNames(json)
  for (const [mesh, names] of Object.entries(morphs)) {
    const counts = namespaces(names)
    console.log(`  形变键 ${mesh}: 共 ${names.length} 个  ` + JSON.stringify(counts))
    const shape = names.filter((n) => n.startsWith('shape_'))
    if (shape.length) {
      console.log('    shape_*: ' + shape.join(', '))
    }
    const vis = names.filter((n) => n.startsWith('vis_'))
    if (vis.length) console.log('    vis_*: ' + vis.join(', '))
    const expr = names.filter((n) => n.startsWith('expr_'))
    if (expr.length) console.log('    expr_*: ' + expr.join(', '))
  }
  return { path, morphs }
}

const args = process.argv.slice(2)

if (args[0] === '--extract-images') {
  const written = extractImages(args[1], args[2])
  written.forEach((item) =>
    console.log(item.skipped ? `  跳过 ${item.name}（${item.skipped}）` : `  写出 ${basename(item.file)}  ${(item.bytes / 1024).toFixed(0)}KB`)
  )
} else if (args[0] === '--json') {
  const result = args.slice(1).map((path) => describe(path))
  console.log('\nGLB_JSON ' + JSON.stringify(result, null, 2))
} else if (args.length === 0) {
  console.log('用法: node tools/glb-inspect.mjs <文件.glb> [...] | --extract-images <文件.glb> <目录>')
  process.exit(1)
} else {
  args.forEach((path) => describe(path))
}
