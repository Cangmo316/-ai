/**
 * 比邻AI · 智能体角色
 *
 * 两个来源：
 *   1. **内置角色**：默认只有一个「比邻AI」（按需求）。它是兜底陪伴者，
 *      永远在列表里、不可删除——否则老人把角色删光了就没得聊了。
 *   2. **自定义角色**：老人自己创建的，按需求收集六个栏目。
 *
 * 【为什么自定义角色存在本机、按账号隔离】
 * 角色的六个栏目（"你想叫我什么""我们之间的故事"…）是**老人自己的记忆**，
 * 属于隐私内容。原型阶段先只存本机，且 key 带上账号编号，
 * 这样同一台设备上换账号登录不会串号看到别人的角色。
 * 真要跨设备同步再落服务端（届时这六个字段就是一张表的列）。
 *
 * 【为什么所有读接口都返回副本】
 * 与 stores/account.js 同一个原因：本项目打包器会把 store 内联进多个 chunk，
 * 模板里引用模块绑定可能变成 undefined。页面统一用 listRoles() 取副本放进自己的 ref。
 */

/** 内置默认角色（按需求：默认只有这一个） */
export const BUILTIN_ROLES = [
  {
    id: 'p_bilin',
    builtin: true,
    name: '比邻AI',
    desc: '一直在，什么都愿意听你说',
    callMe: '',
    relation: '陪伴助手',
    story: '',
    persona: '',
    frequency: '',
    bindFamily: false,
    familyNumber: '',
    familyName: '',
    avatarColor: '#3C6B58'
  }
]

/**
 * 角色列表变化事件名。
 * 创建页保存后 emit，角色列表页监听并刷新——列表页不依赖 @dcloudio/uni-app 的 onShow
 * （该包不在项目依赖里，全项目也没有页面用过它）。
 */
export const EVENT_ROLES_CHANGED = 'bl:roles-changed'

function emitChanged() {
  try {
    uni.$emit(EVENT_ROLES_CHANGED)
  } catch (e) {
    // 发不出去不影响主流程
  }
}

/** 六个栏目的定义：创建页与详情都读它，改文案只改一处 */
export const ROLE_FIELDS = [
  {
    key: 'callMe',
    label: '1. 你想叫我什么',
    placeholder: '比如：老李、张阿姨、妈',
    hint: '它以后就这么称呼你',
    required: true,
    maxlength: 12
  },
  {
    key: 'relation',
    label: '2. 我们是什么关系',
    placeholder: '比如：儿子、老邻居、一起下棋的朋友',
    hint: '',
    required: true,
    maxlength: 16
  },
  {
    key: 'story',
    label: '3. 我们之间的故事',
    placeholder: '比如：我们在公园下棋认识十几年了',
    hint: '写点你们之间的事，它会更懂怎么跟你聊',
    required: false,
    maxlength: 120,
    multiline: true
  },
  {
    key: 'persona',
    label: '4. 我是一个什么样的人',
    placeholder: '比如：爱热闹、爱下棋、血压有点高',
    hint: '',
    required: false,
    maxlength: 120,
    multiline: true
  },
  {
    key: 'frequency',
    label: '5. 我平时多久给你发一次消息',
    placeholder: '选一个就好',
    hint: '',
    required: true,
    options: ['每天', '隔两三天', '每周', '想起来就发', '很少发']
  }
]

const pad = (value, width) => String(value == null ? '' : value).padStart(width, '0')

/** 存储 key：按账号编号隔离（未登录时用 guest） */
function storageKey() {
  let number = ''
  try {
    const raw = uni.getStorageSync('bl_account_profile')
    if (raw) {
      const account = typeof raw === 'string' ? JSON.parse(raw) : raw
      number = (account && account.number) || ''
    }
  } catch (e) {
    number = ''
  }
  return 'bl_roles_v1_' + (number ? pad(number, 8) : 'guest')
}

function readRaw() {
  try {
    const raw = uni.getStorageSync(storageKey())
    const list = raw ? (typeof raw === 'string' ? JSON.parse(raw) : raw) : []
    return Array.isArray(list) ? list : []
  } catch (e) {
    return []
  }
}

function writeRaw(list) {
  try {
    uni.setStorageSync(storageKey(), JSON.stringify(list))
  } catch (e) {
    // 存不上不影响本次使用
  }
}

let seq = 0
function newId() {
  seq += 1
  return 'r_' + Date.now().toString(36) + '_' + seq
}

/** 自定义角色补齐字段，避免旧数据缺字段导致界面出现 undefined */
function normalize(item) {
  if (!item || !item.callMe) return null
  return {
    id: item.id || newId(),
    builtin: false,
    name: item.name || item.callMe,
    desc: item.desc || '',
    callMe: item.callMe,
    relation: item.relation || '',
    story: item.story || '',
    persona: item.persona || '',
    frequency: item.frequency || '',
    bindFamily: !!item.bindFamily,
    familyNumber: item.familyNumber || '',
    familyName: item.familyName || '',
    avatarColor: item.avatarColor || '#7A6A4F',
    createdAt: item.createdAt || Date.now()
  }
}

/* ------------------------------------------------------------------ 读接口 */

/** 全部角色：内置在前，自定义在后。返回副本，页面放进自己的 ref。 */
export function listRoles() {
  const custom = readRaw().map(normalize).filter(Boolean)
  return BUILTIN_ROLES.map((r) => Object.assign({}, r)).concat(custom)
}

export function findRole(id) {
  return listRoles().find((r) => r.id === id) || null
}

export function countCustom() {
  return readRaw().map(normalize).filter(Boolean).length
}

/* ------------------------------------------------------------------ 写接口 */

/**
 * 新建角色。返回 { ok, reason?, role? }。
 * 六栏的必填校验在这里做，页面的即时校验只是提前反馈。
 */
export function addRole(input) {
  const callMe = String((input && input.callMe) || '').trim()
  const relation = String((input && input.relation) || '').trim()
  const frequency = String((input && input.frequency) || '').trim()

  if (!callMe) return { ok: false, reason: '还没填「你想叫我什么」', field: 'callMe' }
  if (!relation) return { ok: false, reason: '还没填「我们是什么关系」', field: 'relation' }
  if (!frequency) return { ok: false, reason: '还没选多久发一次消息', field: 'frequency' }

  // 绑定家人时必须填编号：开关打开却不填，等于绑了个空
  const bindFamily = !!(input && input.bindFamily)
  const familyNumber = String((input && input.familyNumber) || '').trim()
  if (bindFamily) {
    if (!familyNumber) return { ok: false, reason: '请输入家人ID', field: 'familyNumber' }
    if (!/^\d{8}$/.test(familyNumber)) {
      return { ok: false, reason: '家人ID 是 8 位数字', field: 'familyNumber' }
    }
  }

  const list = readRaw().map(normalize).filter(Boolean)
  const role = normalize({
    id: newId(),
    name: callMe,
    // 卡片副标题：关系 + 多久发一次，一眼知道这是谁
    desc: relation + (frequency ? ' · ' + frequency + '给你发消息' : ''),
    callMe,
    relation,
    story: String((input && input.story) || '').trim(),
    persona: String((input && input.persona) || '').trim(),
    frequency,
    bindFamily,
    familyNumber: bindFamily ? familyNumber : '',
    familyName: bindFamily ? String((input && input.familyName) || '').trim() : '',
    createdAt: Date.now()
  })
  list.push(role)
  writeRaw(list)
  emitChanged()
  return { ok: true, role }
}

/** 删除自定义角色（内置角色删不掉） */
export function removeRole(id) {
  const list = readRaw().map(normalize).filter(Boolean)
  const next = list.filter((r) => r.id !== id)
  if (next.length === list.length) return { ok: false, reason: '没找到这个角色' }
  writeRaw(next)
  emitChanged()
  return { ok: true }
}

/** 清空自定义角色（设置页/排查用） */
export function clearCustomRoles() {
  writeRaw([])
  emitChanged()
  return true
}

/* ---------------------------------------------------- 给「对话」栏目用 */

/** 内置角色的开场白（会话列表里显示的那句话） */
const BUILTIN_INTRO = '我是比邻 能陪你聊天、提醒吃药、还能帮你给家里人发消息'

/**
 * 把一个角色转成「对话」栏目需要的人设。
 *
 * 会话列表每行显示：名字（角色名）+ 一句话。自定义角色没有现成的一句话，
 * 就用老人自己填的**关系 + 故事**拼出来——这样列表里一眼能认出"这是谁"，
 * 也让老人填的六个栏目真的被用上，不是存起来就完了。
 *
 * @param {object} role listRoles() 里的一项
 */
export function roleToPersona(role) {
  if (!role) return null
  if (role.builtin) {
    return {
      id: role.id,
      name: role.name,
      builtin: true,
      relation: role.relation || '陪伴助手',
      intro: BUILTIN_INTRO,
      avatarColor: role.avatarColor || '#3C6B58'
    }
  }
  // 自定义角色：尽力拼一句自然的开场白
  const parts = []
  if (role.story) parts.push(role.story)
  else if (role.relation) parts.push('我是你的' + role.relation)
  if (role.frequency) parts.push('你说过' + role.frequency + '会来找我说话')
  const intro = parts.length ? parts.join('，') : (role.relation ? '我是你的' + role.relation : '我们聊聊吧')

  return {
    id: role.id,
    name: role.name,
    builtin: false,
    relation: role.relation || '',
    intro,
    avatarColor: role.avatarColor || '#7A6A4F'
  }
}

/** 对话栏目要展示的全部人设（内置在前，自定义在后） */
export function listPersonas() {
  return listRoles().map(roleToPersona).filter(Boolean)
}

/** 会话预览文案：优先用最近一条消息，没有就用开场白 */
export function personaIntroOf(id) {
  const persona = listPersonas().find((p) => p.id === id)
  return persona ? persona.intro : ''
}
