/**
 * 密码规则回归测试
 *
 * 跑法：node tests/password.test.mjs
 * 规则：8–16 位，只能是数字或字母（见 common/password.js）
 *
 * 为什么留这个文件：密码规则是「注册 / 登录 / 找回密码」共用的常识性约束，
 * 以后有人改 common/password.js 时，这里会立刻报出被破坏的边界。
 */

import { passwordProblem, passwordValid, PASSWORD_RULE_TEXT } from '../common/password.js'

const CASES = [
  // [输入, 说明, 是否应当被拦截]
  ['',                    '空',            true],
  ['a',                   '1 位',          true],
  ['1234567',             '7 位数字',       true],
  ['12345678',            '8 位数字',       false],
  ['abcdefgh',            '8 位字母',       false],
  ['AbCd1234',            '8 位大小写混合',   false],
  ['1234567890123456',    '16 位（上限）',   false],
  ['12345678901234567',   '17 位（超长）',   true],
  ['abc defg',            '含空格',         true],
  ['abcd123!',            '含符号',         true],
  ['abcd-1234',           '含连字符',       true],
  ['密码12345678',         '含中文',         true],
  ['12abCD56',            '数字字母混合',    false],
  ['00000000',            '全零（8 位）',   false],
  ['        ',            '全空格',         true]
]

let failed = 0
console.log('规则文案:', PASSWORD_RULE_TEXT)
console.log('')

for (const [value, desc, shouldBlock] of CASES) {
  const msg = passwordProblem(value)
  const blocked = msg !== ''
  const ok = blocked === shouldBlock
  if (!ok) failed += 1
  const shown = blocked ? '拦截 → ' + msg : '合法'
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${desc.padEnd(16, '　')} ${shown}`)
}

// passwordValid 必须与 passwordProblem 完全一致
const mismatch = CASES.filter(([v]) => passwordValid(v) !== (passwordProblem(v) === ''))
if (mismatch.length) {
  failed += 1
  console.log('\n  FAIL  passwordValid 与 passwordProblem 判定不一致:', mismatch.map((m) => m[1]).join(', '))
}

console.log('')
if (failed) {
  console.log(`  ${failed} 个用例不符合预期 [FAIL]`)
  process.exit(1)
}
console.log(`  全部 ${CASES.length} 个用例通过 [PASS]`)
