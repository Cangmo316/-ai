#!/usr/bin/env node
/**
 * guidelines.yaml 结构校验器（零依赖）
 *
 * 用法：node validate.mjs [file]
 *
 * 只解析本文件用到的 YAML 子集：顶层映射 + 列表项映射 + 行内 flow mapping。
 * 校验的是「条目表能不能被计划引擎安全使用」，而不是通用 YAML 兼容性。
 */
import { readFileSync } from 'node:fs'

const file = process.argv[2] || new URL('./guidelines.yaml', import.meta.url)
const text = readFileSync(file, 'utf8')
const lines = text.split(/\r?\n/)

const REQUIRED = ['id', 'source', 'version', 'category', 'audience', 'advice', 'detail', 'boundary', 'plan_hint', 'reviewed_by', 'review_by']
const PLAN_KEYS = ['time', 'type', 'freq', 'strong_remind', 'weight']
const PLAN_TYPES = ['用药', '午餐', '活动', '监测', '问候']
const FREQS = ['每日', '每周', '每月', '每季度', '每年']

const errors = []
const warnings = []

function parseFlowMap(raw) {
  const inner = raw.trim().replace(/^\{\s*/, '').replace(/\s*\}$/, '')
  const out = {}
  let depth = 0, buf = '', parts = []
  for (const ch of inner) {
    if (ch === '[' || ch === '{') depth++
    if (ch === ']' || ch === '}') depth--
    if (ch === ',' && depth === 0) { parts.push(buf); buf = '' } else buf += ch
  }
  if (buf.trim()) parts.push(buf)
  for (const part of parts) {
    const idx = part.indexOf(':')
    if (idx === -1) continue
    out[part.slice(0, idx).trim()] = part.slice(idx + 1).trim().replace(/^"|"$/g, '')
  }
  return out
}

function parseInlineSeq(raw) {
  return raw.trim().replace(/^\[\s*/, '').replace(/\s*\]$/, '').split(',').map(s => s.trim()).filter(Boolean)
}

// ── 解析 ──
const meta = { sources: [] }
const entries = []
let section = null, cur = null, curSource = null

lines.forEach((line, i) => {
  const no = i + 1
  if (/^\s*#/.test(line) || !line.trim()) return
  if (/^\t/.test(line)) errors.push(`L${no} 使用了 Tab 缩进（YAML 只允许空格）`)

  if (/^meta:/.test(line)) { section = 'meta'; return }
  if (/^entries:/.test(line)) { section = 'entries'; return }

  if (section === 'meta') {
    if (/^\s{2}sources:/.test(line)) { curSource = 'list'; return }
    if (/^\s{4}- id:\s*(.+)$/.test(line)) { meta.sources.push({ id: line.split(':')[1].trim() }); return }
    return
  }

  if (section === 'entries') {
    const mId = line.match(/^ {2}- id:\s*(.+)$/)
    if (mId) { cur = { id: mId[1].trim() }; entries.push(cur); return }
    const mKV = line.match(/^ {4}([A-Za-z_]+):\s*(.*)$/)
    if (mKV && cur) { cur[mKV[1]] = mKV[2].trim(); return }
  }
})

const sourceIds = new Set(meta.sources.map(s => s.id))

// ── 校验 ──
const seen = new Map()
for (const e of entries) {
  const where = `[${e.id || '无 id'}]`
  for (const k of REQUIRED) {
    if (!(k in e)) errors.push(`${where} 缺少必填字段 ${k}`)
  }
  if (e.id) {
    if (seen.has(e.id)) errors.push(`${where} id 重复（首次出现于条目 ${seen.get(e.id) + 1}）`)
    else seen.set(e.id, entries.indexOf(e))
  }
  if (e.source && !sourceIds.has(e.source)) errors.push(`${where} source "${e.source}" 未在 meta.sources 中声明`)
  if (e.audience && !/^\[.*\]$/.test(e.audience)) errors.push(`${where} audience 应为行内数组，如 [全员]`)
  if (e.review_by && !/^"?\d{4}-\d{2}-\d{2}"?$/.test(e.review_by)) errors.push(`${where} review_by 应为 YYYY-MM-DD，当前为 "${e.review_by}"`)
  if (e.reviewed_by === '""' ) warnings.push(`${where} 待医学签字（reviewed_by 为空）`)
  else if (!e.reviewed_by) errors.push(`${where} reviewed_by 字段必须存在（未签字请写 ""）`)

  if (e.plan_hint) {
    const ph = parseFlowMap(e.plan_hint)
    for (const k of PLAN_KEYS) if (!(k in ph)) errors.push(`${where} plan_hint 缺少 ${k}`)
    if (ph.type && !PLAN_TYPES.includes(ph.type)) errors.push(`${where} plan_hint.type "${ph.type}" 不在允许值 ${PLAN_TYPES.join('/')}`)
    if (ph.freq && !FREQS.includes(ph.freq)) errors.push(`${where} plan_hint.freq "${ph.freq}" 不在允许值 ${FREQS.join('/')}`)
    if (ph.time && !/^\d{2}:\d{2}$/.test(ph.time)) errors.push(`${where} plan_hint.time 应为 HH:MM，当前为 "${ph.time}"`)
    if (ph.strong_remind && !/^(true|false)$/.test(ph.strong_remind)) errors.push(`${where} plan_hint.strong_remind 应为 true/false`)
    if (ph.weight && Number.isNaN(Number(ph.weight))) errors.push(`${where} plan_hint.weight 应为数字`)
    if (/\{|\[/.test(e.plan_hint.replace(/^\{\s*/, '').replace(/\s*\}$/, ''))) errors.push(`${where} plan_hint 疑似括号不配对`)
  }

  // 产品规则：念给老人听的话，句末不加句号
  for (const f of ['advice', 'detail']) {
    if (e[f] && /[。.]$/.test(e[f].replace(/^"|"$/g, ''))) warnings.push(`${where} ${f} 以句号结尾（产品规则：句末不加句号）`)
  }
}

// ── 报告 ──
console.log(`条目数：${entries.length}`)
console.log(`来源数：${meta.sources.length}  [${[...sourceIds].join(', ')}]`)
const bySource = {}
for (const e of entries) bySource[e.source] = (bySource[e.source] || 0) + 1
for (const [k, v] of Object.entries(bySource)) console.log(`  ${k}: ${v} 条`)
console.log(`待签字：${warnings.filter(w => w.includes('待医学签字')).length} / ${entries.length}`)

if (warnings.length) {
  console.log(`\n⚠️  警告 ${warnings.length} 条：`)
  for (const w of warnings) console.log('  - ' + w)
}
if (errors.length) {
  console.log(`\n❌ 错误 ${errors.length} 条：`)
  for (const e of errors) console.log('  - ' + e)
  process.exit(1)
}
console.log('\n✅ 结构校验通过')