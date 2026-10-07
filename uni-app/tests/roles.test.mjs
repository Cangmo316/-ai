/**
 * 智能体角色 · 逻辑回归测试（Node 直接跑，不依赖浏览器）
 *
 * 跑法：node tests/roles.test.mjs
 *
 * 为什么单独写这一份：角色创建页的六个栏目、"绑定家人"开关联动、
 * 编号校验这些是**纯逻辑**，用浏览器模拟点击既慢又不稳（实测 CDP 点 uni-switch
 * 不触发 change）。这里把 uni API mock 掉，直接测真实代码。
 */

// ---- mock uni（stores/roles.js 只用到 storage 与事件）----
const storage = new Map()
const listeners = new Map()
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
  $emit(name, payload) {
    const list = listeners.get(name) || []
    list.forEach((fn) => fn(payload))
  },
  $on(name, fn) {
    if (!listeners.has(name)) listeners.set(name, [])
    listeners.get(name).push(fn)
  },
  $off(name, fn) {
    const list = listeners.get(name) || []
    listeners.set(name, list.filter((item) => item !== fn))
  }
}

const {
  BUILTIN_ROLES,
  EVENT_ROLES_CHANGED,
  ROLE_FIELDS,
  addRole,
  clearCustomRoles,
  countCustom,
  findRole,
  listRoles,
  removeRole
} = await import('../stores/roles.js')

let failed = 0
const check = (label, condition, extra = '') => {
  if (condition) {
    console.log('  PASS  ' + label)
  } else {
    failed += 1
    console.log('  FAIL  ' + label + (extra ? '  → ' + extra : ''))
  }
}

/* ---------------------------------------------------------- 内置角色 */
console.log('内置角色：')
check('默认只有 1 个内置角色', BUILTIN_ROLES.length === 1)
check('内置角色是「比邻AI」', BUILTIN_ROLES[0].name === '比邻AI')
check('内置角色标记为 builtin', BUILTIN_ROLES[0].builtin === true)

/* ---------------------------------------------------------- 六个栏目 */
console.log('\n栏目定义（按需求 1–6）：')
const labels = ROLE_FIELDS.map((f) => f.label)
check('第 1 栏：你想叫我什么', labels[0].indexOf('你想叫我什么') !== -1, labels[0])
check('第 2 栏：我们是什么关系', labels[1].indexOf('我们是什么关系') !== -1, labels[1])
check('第 3 栏：我们之间的故事', labels[2].indexOf('我们之间的故事') !== -1, labels[2])
check('第 4 栏：我是一个什么样的人', labels[3].indexOf('我是一个什么样的人') !== -1, labels[3])
check('第 5 栏：多久发一次消息', labels[4].indexOf('多久给你发一次消息') !== -1, labels[4])
check('共 5 个文字/选择栏（第 6 栏是开关，不在 ROLE_FIELDS 里）', ROLE_FIELDS.length === 5, String(ROLE_FIELDS.length))
check('第 5 栏有选项', Array.isArray(ROLE_FIELDS[4].options) && ROLE_FIELDS[4].options.length >= 3)

/* ---------------------------------------------------------- 未登录隔离 */
console.log('\n未登录时（key 用 guest）：')
clearCustomRoles()
check('初始没有自定义角色', countCustom() === 0)
check('列表只有内置角色', listRoles().length === 1)

/* ---------------------------------------------------------- 必填校验 */
console.log('\n必填校验：')
let r = addRole({ relation: '棋友', frequency: '每天' })
check('缺「你想叫我什么」被拦', r.ok === false && r.field === 'callMe', JSON.stringify(r))
r = addRole({ callMe: '老李', frequency: '每天' })
check('缺「我们是什么关系」被拦', r.ok === false && r.field === 'relation', JSON.stringify(r))
r = addRole({ callMe: '老李', relation: '棋友' })
check('缺「多久发一次」被拦', r.ok === false && r.field === 'frequency', JSON.stringify(r))

/* ---------------------------------------------------------- 绑定家人 */
console.log('\n绑定家人（第 6 栏）：')
r = addRole({ callMe: '老李', relation: '棋友', frequency: '每天', bindFamily: true })
check('开关打开但没填编号 → 被拦', r.ok === false && r.field === 'familyNumber', JSON.stringify(r))
r = addRole({ callMe: '老李', relation: '棋友', frequency: '每天', bindFamily: true, familyNumber: '123' })
check('编号不足 8 位 → 被拦', r.ok === false && r.field === 'familyNumber', JSON.stringify(r))
r = addRole({ callMe: '老李', relation: '棋友', frequency: '每天', bindFamily: true, familyNumber: 'abcdefgh' })
check('编号非数字 → 被拦', r.ok === false && r.field === 'familyNumber', JSON.stringify(r))
r = addRole({ callMe: '老李', relation: '棋友', frequency: '每天', bindFamily: false })
check('开关关闭时不要求编号', r.ok === true, JSON.stringify(r))
check('开关关闭时编号被清空', r.ok && r.role.familyNumber === '', r.ok ? r.role.familyNumber : '')
// 上面那次是**合法创建**，会真的存进去。这里清掉，
// 否则后面的计数用例会被它带偏（第一版就踩了这个坑）
clearCustomRoles()

/* ---------------------------------------------------------- 正常创建 */
console.log('\n完整创建：')
check('创建前没有自定义角色', countCustom() === 0, String(countCustom()))
let eventCount = 0
const onChange = () => { eventCount += 1 }
uni.$on(EVENT_ROLES_CHANGED, onChange)

const created = addRole({
  callMe: '老李',
  relation: '棋友',
  story: '我们在公园下棋认识十几年了',
  persona: '爱下棋、爱热闹',
  frequency: '每天',
  bindFamily: true,
  familyNumber: '00000000',
  familyName: '比邻AI'
})
check('创建成功', created.ok === true, JSON.stringify(created))
check('发出「角色变化」事件', eventCount === 1, String(eventCount))
check('六个字段都存下来了',
  created.ok &&
  created.role.callMe === '老李' &&
  created.role.relation === '棋友' &&
  created.role.story === '我们在公园下棋认识十几年了' &&
  created.role.persona === '爱下棋、爱热闹' &&
  created.role.frequency === '每天',
  created.ok ? JSON.stringify(created.role) : '')
check('绑定家人信息存下来了',
  created.ok && created.role.bindFamily === true &&
  created.role.familyNumber === '00000000' && created.role.familyName === '比邻AI')
check('卡片副标题自动生成（关系 + 频率）',
  created.ok && created.role.desc.indexOf('棋友') !== -1 && created.role.desc.indexOf('每天') !== -1,
  created.ok ? created.role.desc : '')
check('列表变成 2 个（内置 + 自定义）', listRoles().length === 2, String(listRoles().length))
check('内置角色仍在第一位', listRoles()[0].id === 'p_bilin')
check('findRole 能按 id 找到', created.ok && findRole(created.role.id) !== null)

/* ---------------------------------------------------------- 删除 */
console.log('\n删除：')
const bad = removeRole('不存在的id')
check('删不存在的角色返回失败', bad.ok === false)
const removed = removeRole(created.ok ? created.role.id : '')
check('删除自定义角色成功', removed.ok === true)
check('删除后列表只剩内置', listRoles().length === 1, String(listRoles().length))
// 事件次数：创建 1 次 + 删除 1 次。
// （clearCustomRoles() 在创建之前调用，且不参与这里的计数——
//   它在"必填校验"段末尾被调用来复位状态）
check('创建与删除各发一次事件', eventCount === 2, String(eventCount))

/* ---------------------------------------------------------- 持久化 */
console.log('\n持久化：')
addRole({ callMe: '张阿姨', relation: '老邻居', frequency: '每周' })
const rawKey = [...storage.keys()].find((k) => k.indexOf('bl_roles_v1_') === 0)
check('写进了带账号后缀的 storage key', !!rawKey, String(rawKey))
check('key 用 guest（未登录）', rawKey === 'bl_roles_v1_guest', String(rawKey))
const stored = JSON.parse(storage.get(rawKey))
check('storage 里是数组且含 1 条', Array.isArray(stored) && stored.length === 1, String(stored && stored.length))

// 换账号登录后应该看不到 guest 的角色
storage.set('bl_account_profile', JSON.stringify({ name: '比邻AI', number: '00000000' }))
check('切换账号后看不到上一个账号的角色', countCustom() === 0, String(countCustom()))
const rawKey2 = 'bl_roles_v1_00000000'
check('新账号用带编号的 key', (() => {
  addRole({ callMe: '我儿子', relation: '儿子', frequency: '每天' })
  return storage.has(rawKey2)
})(), rawKey2)

// 切回未登录应还能看到 guest 的角色（数据没被破坏）
storage.delete('bl_account_profile')
check('切回未登录仍能看到 guest 的角色', countCustom() === 1, String(countCustom()))

console.log('')
if (failed) {
  console.log(`  ${failed} 个用例失败 [FAIL]`)
  process.exit(1)
}
console.log('  全部用例通过 [PASS]')
