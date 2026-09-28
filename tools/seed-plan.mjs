#!/usr/bin/env node
/**
 * 比邻AI · 生成并确认一份计划（演示 / 联调前的种子脚本）
 *
 *   node tools/seed-plan.mjs                        # 默认 e_1，打 http://127.0.0.1:8000
 *   node tools/seed-plan.mjs --elder e_2
 *   node tools/seed-plan.mjs --base http://127.0.0.1:8100 --fresh
 *
 * 为什么要单独有这个脚本：计划必须**家属确认后才生效**，所以刚起的服务里
 * 「今日计划」本来就是空的（这是闸门在起作用，不是坏了）。演示前跑一下这个脚本，
 * 相当于替家里人点了「确认」，日程页才会有内容。
 *
 * 零依赖，直接用 fetch。
 */

const DEFAULT_BASE = 'http://127.0.0.1:8000'

function parseArgs(argv) {
  const flags = {}
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i]
    if (!token.startsWith('--')) continue
    const eq = token.indexOf('=')
    if (eq !== -1) { flags[token.slice(2, eq)] = token.slice(eq + 1); continue }
    const key = token.slice(2)
    const next = argv[i + 1]
    if (next === undefined || next.startsWith('--')) flags[key] = true
    else { flags[key] = next; i += 1 }
  }
  return flags
}

async function call(base, path, { method = 'GET', body } = {}) {
  const init = { method, headers: { 'Content-Type': 'application/json' } }
  if (body) init.body = JSON.stringify(body)
  const res = await fetch(base + path, init)
  const text = await res.text()
  let data = text
  try { data = JSON.parse(text) } catch (e) { /* 保留原文 */ }
  if (!res.ok) {
    const message = (data && data.error && data.error.message) || text.slice(0, 200)
    throw new Error('HTTP ' + res.status + ' ' + message)
  }
  return data
}

async function main() {
  const flags = parseArgs(process.argv.slice(2))
  const base = String(flags.base || process.env.BILIN_BASE_URL || DEFAULT_BASE).replace(/\/+$/, '')
  const elderId = String(flags.elder || 'e_1')

  const health = await call(base, '/healthz').catch((error) => {
    console.error('连不上服务 ' + base + '：' + error.message)
    console.error('先起服务：cd server; .\\.venv\\Scripts\\python.exe run.py')
    process.exit(1)
  })
  console.log('服务: ' + base + '（模型 ' + health.llm.provider + '，知识库 ' + health.knowledge.version + '）')

  const today = await call(base, '/v1/plans/today?elderId=' + encodeURIComponent(elderId))
  if (today.total > 0 && !flags.fresh) {
    console.log('已有生效计划 ' + today.planId + '（' + today.total + ' 项，已完成 ' + today.done + '），不再新建')
    console.log('要重来一份就加 --fresh（新计划确认后旧计划自动结束）')
    return
  }

  const draft = await call(base, '/v1/plans/draft', {
    method: 'POST',
    body: { elderId, polish: !flags.nopolish }
  })
  const plan = draft.plan
  console.log('')
  console.log('生成草稿 ' + plan.id + '（' + plan.statusLabel + '，' + plan.items.length + ' 项）')
  for (const item of plan.items) {
    console.log('  ' + item.time + '  ' + item.type + '  ' + item.title)
    console.log('        依据: ' + item.basis.text)
  }
  if (draft.polish) {
    console.log('话术改写: 成功 ' + draft.polish.polished + ' 条，退回原文 ' + draft.polish.fallback + ' 条')
    if (draft.polish.reasons && draft.polish.reasons.length) {
      console.log('  ' + draft.polish.reasons.join('；'))
    }
  }

  const confirmed = await call(base, '/v1/plans/confirm', {
    method: 'POST',
    body: { planId: plan.id, actor: '种子脚本' }
  })
  console.log('')
  console.log('已确认生效（' + confirmed.plan.statusLabel + '）：' + confirmed.notice)

  const after = await call(base, '/v1/plans/today?elderId=' + encodeURIComponent(elderId))
  console.log('')
  console.log('今日计划（' + after.date + '）：共 ' + after.total + ' 项')
  for (const item of after.items) {
    console.log('  ' + item.time + '  ' + (item.done ? '[已完成]' : '[待打卡]') + '  ' + item.title)
  }
  console.log('')
  console.log('现在打开 App 的「日程」页就能看到并打卡了')
}

main().catch((error) => {
  console.error('种子脚本失败：' + (error && error.message ? error.message : error))
  process.exitCode = 1
})
