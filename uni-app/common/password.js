/**
 * 比邻AI · 账号密码规则
 *
 * 规则（按需求）：**8–16 位，只能是数字或字母**。
 *
 * 为什么单独成文件而不是写在注册页里：
 * 注册、登录、以后可能的「找回密码 / 修改密码」都要用同一套规则。
 * 规则散在多处必然走样——之前登录页就写着「至少 6 位」，和注册页的 8 位矛盾了。
 *
 * 这里只做纯函数校验，不碰 uni API，便于单独验证（见 pages/pwtest）。
 */

export const PASSWORD_MIN = 8
export const PASSWORD_MAX = 16
/** 只允许数字和字母 */
const PASSWORD_RE = /^[0-9A-Za-z]+$/

/** 给老人看的一句话规则说明 */
export const PASSWORD_RULE_TEXT = PASSWORD_MIN + '–' + PASSWORD_MAX + ' 位数字或字母'

/**
 * 校验密码是否符合规则。
 * @param {string} value
 * @returns {string} 空串 = 合法；否则返回一句可直接展示给老人的说明
 */
export function passwordProblem(value) {
  const v = String(value == null ? '' : value)
  if (!v) return '请输入密码'
  if (v.length < PASSWORD_MIN) return '密码至少 ' + PASSWORD_MIN + ' 位'
  if (v.length > PASSWORD_MAX) return '密码最多 ' + PASSWORD_MAX + ' 位'
  if (!PASSWORD_RE.test(v)) return '密码只能用数字或字母，不能有空格或符号'
  return ''
}

/** 是否合法（布尔版，给"边输边提示"之类场景用） */
export function passwordValid(value) {
  return passwordProblem(value) === ''
}
