/**
 * 特殊计划 · 逻辑回归测试（Node 直接跑，不依赖浏览器）
 *
 * 跑法：node tests/special.test.mjs
 *
 * 为什么单独写：特殊计划与日常计划的差别就在「日期」这一层语义上
 * （见 stores/special.js 的说明），日期校验、排序、"今天算不算生效"、
 * 提醒调度只在指定那天排——这些都是**纯逻辑**，值得钉住。
 * 用浏览器点日期既慢又不稳（实测 CDP 点 uni 组件常不触发 change）。
 */

// ---- mock uni（stores/special.js 与 daily.js 只用到 storage）----
const storage = new Map()
globalThis.uni = {
  getStorageSync(key) {
    return storage.has(key) ? storage.get(key) : ''
  },
  setStorageSync(key, value) {
    storage.set(key, value)
  },
  removeStorageSync(key) {
    storage.delete(key)
  },
  $emit() {},
  $on() {},
  $off() {}
}

const {
  SPECIAL_KEY,
  NAME_MAX,
  addSpecialPlan,
  clearSpecialPlans,
  closeSpecialForever,
  closureNote,
  dateText,
  effectiveEnabled,
  initSpecial,
  isToday,
  normalizeDate,
  rangeText,
  relativeText,
  removeSpecialPlan,
  reopenSpecial,
  special
} = await import('../stores/special.js')

const { dayKey } = await import('../stores/daily.js')

let passed = 0
let failed = 0

function check(name, condition, detail) {
  if (condition) {
    passed += 1
    console.log('  ✓ ' + name)
  } else {
    failed += 1
    console.log('  ✗ ' + name + (detail ? '  → ' + detail : ''))
  }
}

function eq(name, actual, expected) {
  check(name, actual === expected, 'got ' + JSON.stringify(actual) + ', want ' + JSON.stringify(expected))
}

/** 每次用例前把 store 与存储清空，避免互相影响 */
function reset() {
  special.ready = false
  special.items = []
  storage.clear()
}

const TODAY = dayKey(new Date())
const tomorrow = dayKey(new Date(Date.now() + 86400000))
const dayAfter = dayKey(new Date(Date.now() + 2 * 86400000))

/* ══════════════════════════════════════════════════ 1. 日期校验 */

console.log('\n=== 1. 日期校验（normalizeDate）===')
eq('正常日期通过', normalizeDate('2026-10-08'), '2026-10-08')
eq('空值返回空', normalizeDate(''), '')
eq('格式不对返回空', normalizeDate('2026/10/08'), '')
eq('缺位返回空', normalizeDate('2026-10'), '')
eq('不存在的日期返回空（2月31日）', normalizeDate('2026-02-31'), '')
eq('闰年 2月29日 通过', normalizeDate('2028-02-29'), '2028-02-29')
eq('非闰年 2月29日 返回空', normalizeDate('2027-02-29'), '')
eq('非法月份返回空', normalizeDate('2026-13-01'), '')

/* ══════════════════════════════════════════════════ 2. 新增校验 */

console.log('\n=== 2. 新增校验（addSpecialPlan）===')
reset()
initSpecial()

let res = addSpecialPlan({ name: '', date: tomorrow, fromH: 8, fromM: 0, toH: 9, toM: 0 })
check('没写名称 → 拒绝', !res.ok, JSON.stringify(res))
check('拒绝原因是人话', /名称/.test(res.reason || ''), res.reason)

res = addSpecialPlan({ name: '体检', date: '', fromH: 8, fromM: 0, toH: 9, toM: 0 })
check('没选日期 → 拒绝', !res.ok, JSON.stringify(res))
check('拒绝原因提到日期', /日期/.test(res.reason || ''), res.reason)

res = addSpecialPlan({ name: '体检', date: '2026-02-31', fromH: 8, fromM: 0, toH: 9, toM: 0 })
check('日期不存在 → 拒绝', !res.ok, JSON.stringify(res))

res = addSpecialPlan({
  name: '这个名称实在是太长了超过二十个字肯定不行啊啊啊',
  date: tomorrow, fromH: 8, fromM: 0, toH: 9, toM: 0
})
check('名称超过上限 → 拒绝', !res.ok, JSON.stringify(res))

// 边界：刚好等于上限应当通过（上限是"最多 NAME_MAX 个字"，不是"少于"）
res = addSpecialPlan({
  name: '一二三四五六七八九十一二三四五六七八九十',
  date: tomorrow, fromH: 8, fromM: 0, toH: 9, toM: 0
})
check('名称刚好 ' + NAME_MAX + ' 字 → 通过', res.ok, JSON.stringify(res))

res = addSpecialPlan({ name: '体检', date: tomorrow, fromH: 8, fromM: 0, toH: 9, toM: 0 })
check('正常添加 → 成功', res.ok, JSON.stringify(res))
eq('日期被正确保存', res.item && res.item.date, tomorrow)
eq('默认开启提醒', res.item && res.item.enabled, true)
check('没有 skipped 字段（只有 enabled 一个关闭状态）', res.item && res.item.skipped === undefined)

/* ══════════════════════════════════════════════════ 3. 排序与持久化 */

console.log('\n=== 3. 排序与持久化 ===')
reset()
initSpecial()
addSpecialPlan({ name: '远的', date: dayAfter, fromH: 10, fromM: 0, toH: 11, toM: 0 })
addSpecialPlan({ name: '近的', date: tomorrow, fromH: 14, fromM: 0, toH: 15, toM: 0 })
addSpecialPlan({ name: '今天的', date: TODAY, fromH: 16, fromM: 0, toH: 17, toM: 0 })
eq('按日期升序：今天 → 明天 → 后天', special.items.map((i) => i.name).join(','), '今天的,近的,远的')

const raw = storage.get(SPECIAL_KEY)
check('已落本地存储', typeof raw === 'string' && raw.length > 10, String(raw).slice(0, 60))

// 重新加载：验证持久化 + normalize 容错
special.ready = false
special.items = []
initSpecial()
eq('重载后条数一致', special.items.length, 3)
eq('重载后顺序一致', special.items.map((i) => i.name).join(','), '今天的,近的,远的')

// 脏数据容错
storage.set(SPECIAL_KEY, JSON.stringify([
  { id: 'ok1', name: '好的', date: tomorrow, fromH: 8, fromM: 0, toH: 9, toM: 0 },
  { id: 'bad1', name: '没日期', fromH: 8, fromM: 0, toH: 9, toM: 0 },
  { id: 'bad2', date: tomorrow },
  null
]))
special.ready = false
special.items = []
initSpecial()
eq('没有日期的脏数据被丢掉', special.items.length, 1)
eq('保留的那条是对的', special.items[0] && special.items[0].name, '好的')

/* ══════════════════════════════════════════════════ 4. 生效判断 */

console.log('\n=== 4. 生效判断（effectiveEnabled / isToday）===')
reset()
initSpecial()
const todayPlan = addSpecialPlan({ name: '今天的事', date: TODAY, fromH: 8, fromM: 0, toH: 9, toM: 0 }).item
const futurePlan = addSpecialPlan({ name: '明天的事', date: tomorrow, fromH: 8, fromM: 0, toH: 9, toM: 0 }).item

check('今天的计划：已开启 → 生效', effectiveEnabled(todayPlan))
check('今天的计划：isToday 为真', isToday(todayPlan))
check('明天的计划：isToday 为假', !isToday(futurePlan))

closeSpecialForever(todayPlan.id)
check('关掉后不生效', !effectiveEnabled(todayPlan))
eq('卡片副标题说明已关闭', closureNote(todayPlan), '已关掉提醒，想开就点右边的开关')

reopenSpecial(todayPlan.id)
check('重新打开后生效', effectiveEnabled(todayPlan))
eq('重新打开后没有副标题', closureNote(todayPlan), '')

// 一条特殊计划只落一天，所以「关掉」是唯一的关闭状态，
// 不存在"跳过某天但不影响以后"（那样会与关掉完全同义）。这里钉住这个设计。
check('没有 skipped 这个字段（已删掉，避免两个同义状态）', todayPlan.skipped === undefined)
check('关掉不影响同一条计划的日期数据', todayPlan.date === TODAY)
check('关掉别的计划不会连带（明天那条仍生效）', effectiveEnabled(futurePlan))

/* ══════════════════════════════════════════════════ 5. 文案 */

console.log('\n=== 5. 展示文案 ===')
reset()
eq('时间段文案', rangeText({ fromH: 8, fromM: 0, toH: 9, toM: 30 }), '08:00 — 09:30')
eq('个位数补零', rangeText({ fromH: 7, fromM: 5, toH: 9, toM: 0 }), '07:05 — 09:00')

const withWeek = dateText('2026-10-08')
check('日期带星期', /10月8日 周/.test(withWeek), withWeek)
check('跨年时带年份', /^2027年/.test(dateText('2027-01-01')), dateText('2027-01-01'))
eq('日期格式坏掉时原样返回', dateText('坏数据'), '坏数据')

eq('今天 → 今天', relativeText(TODAY), '今天')
eq('明天 → 明天', relativeText(tomorrow), '明天')
check('后天 → 还有 2 天', /还有 2 天/.test(relativeText(dayAfter)), relativeText(dayAfter))
const yesterday = dayKey(new Date(Date.now() - 86400000))
check('昨天 → 已过 1 天', /已过 1 天/.test(relativeText(yesterday)), relativeText(yesterday))
eq('日期不合法时返回空', relativeText('乱写'), '')

/* ══════════════════════════════════════════════════ 6. 删除 */

console.log('\n=== 6. 删除 ===')
reset()
initSpecial()
const one = addSpecialPlan({ name: '要删的', date: tomorrow, fromH: 8, fromM: 0, toH: 9, toM: 0 }).item
const two = addSpecialPlan({ name: '留着的', date: dayAfter, fromH: 8, fromM: 0, toH: 9, toM: 0 }).item
eq('删之前 2 条', special.items.length, 2)
check('删除返回 true', removeSpecialPlan(one.id))
eq('删之后 1 条', special.items.length, 1)
eq('留下的是另一条', special.items[0].id, two.id)
check('删不存在的 id 返回 false', !removeSpecialPlan('nope'))

clearSpecialPlans()
eq('清空后 0 条', special.items.length, 0)

/* ══════════════════════════════════════════════════ 汇总 */

console.log('\n' + '─'.repeat(46))
if (failed === 0) {
  console.log('  全部 ' + passed + ' 个用例通过 [PASS]')
} else {
  console.log('  通过 ' + passed + ' 个，失败 ' + failed + ' 个 [FAIL]')
}
process.exit(failed === 0 ? 0 : 1)
