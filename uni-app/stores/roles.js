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
    // 它对你的称呼 —— 通话页开场白里的「XXX」就是它（见 vision.vue 的 opener）
    callYou: '',
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
 * 内置角色（「比邻AI」）的可编辑覆盖项，按账号隔离。
 *
 * 为什么单独存一份、而不是把它塞进自定义列表：
 * 内置角色**永远是同一个 id（p_bilin）、不可删除**，页面按需求要能进「人物设置」
 * 改它（题目与创建新角色页一致，但**没有"是否绑定家人"**）。如果把它写进
 * 自定义列表，就得处理"删了会怎样""重名怎么办"这些本来不存在的问题。
 */
const BUILTIN_OVERRIDE_KEY = 'bl_role_builtin_v1'

function builtinKey() {
  return BUILTIN_OVERRIDE_KEY + '_' + accountSuffix()
}

/** 读内置角色的覆盖值（没设置过就是空对象） */
export function readBuiltinProfile() {
  try {
    const raw = uni.getStorageSync(builtinKey())
    const obj = raw ? (typeof raw === 'string' ? JSON.parse(raw) : raw) : null
    return obj && typeof obj === 'object' ? obj : {}
  } catch (e) {
    return {}
  }
}

/** 保存内置角色的设置。只接受白名单字段，避免把 id/builtin 这类写坏。 */
export function saveBuiltinProfile(input) {
  const src = input || {}
  const next = {
    callMe: String(src.callMe || '').trim(),
    callYou: String(src.callYou || '').trim(),
    relation: String(src.relation || '').trim(),
    story: String(src.story || '').trim(),
    persona: String(src.persona || '').trim(),
    frequency: String(src.frequency || '').trim()
  }
  try {
    uni.setStorageSync(builtinKey(), JSON.stringify(next))
  } catch (e) {
    return { ok: false, reason: '存不上，稍后再试' }
  }
  emitChanged()
  return { ok: true }
}

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

/** 栏目定义：创建页与详情都读它，改文案只改一处 */
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
    // 2026-10 新增：这一项决定**通话页开场白里的称呼**
    //（「XXX，你好，你想跟我聊些什么？」里的 XXX），所以排在"故事"之前，
    //  后面的题目顺延。老数据没有这个字段，normalize 会补成空串。
    key: 'callYou',
    label: '3. 你想我怎么称呼你？',
    placeholder: '比如：李大爷、王阿姨、老张',
    hint: '通话时会这么叫你',
    required: false,
    maxlength: 12
  },
  {
    key: 'story',
    label: '4. 我们之间的故事',
    placeholder: '比如：我们在公园下棋认识十几年了',
    hint: '写点你们之间的事，它会更懂怎么跟你聊',
    required: false,
    maxlength: 120,
    multiline: true
  },
  {
    key: 'persona',
    label: '5. 我是一个什么样的人',
    placeholder: '比如：爱热闹、爱下棋、血压有点高',
    hint: '',
    required: false,
    maxlength: 120,
    multiline: true
  },
  {
    key: 'frequency',
    label: '6. 我平时多久给你发一次消息',
    placeholder: '选一个就好',
    hint: '',
    required: true,
    options: ['每天', '隔两三天', '每周', '想起来就发', '很少发']
  }
]

const pad = (value, width) => String(value == null ? '' : value).padStart(width, '0')

/** 当前账号编号后缀（未登录时 guest）—— 角色的存储 key 都按它隔离 */
function accountSuffix() {
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
  return number ? pad(number, 8) : 'guest'
}

/** 存储 key：按账号编号隔离（未登录时用 guest） */
function storageKey() {
  return 'bl_roles_v1_' + accountSuffix()
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
    callYou: item.callYou || '',
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

/** 内置角色 + 用户设置过的覆盖值（没设置过就是原样） */
function builtinWithProfile() {
  const profile = readBuiltinProfile()
  return BUILTIN_ROLES.map((r) => Object.assign({}, r, {
    callMe: profile.callMe || r.callMe,
    callYou: profile.callYou || r.callYou,
    relation: profile.relation || r.relation,
    story: profile.story || r.story,
    persona: profile.persona || r.persona,
    frequency: profile.frequency || r.frequency
  }))
}

/* ------------------------------------------------------------------ 读接口 */

/** 全部角色：内置在前，自定义在后。返回副本，页面放进自己的 ref。 */
export function listRoles() {
  const custom = readRaw().map(normalize).filter(Boolean)
  return builtinWithProfile().concat(custom)
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
/**
 * 校验并构造一个自定义角色的字段（addRole / updateRole 共用）。
 * 校验必须在这里做：页面的即时校验只是提前反馈，最终以这里为准。
 *
 * @returns {{ok:false, reason:string, field:string} | {ok:true, fields:object}}
 */
function buildCustomFields(input) {
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

  return {
    ok: true,
    fields: {
      name: callMe,
      // 卡片副标题：关系 + 多久发一次，一眼知道这是谁
      desc: relation + (frequency ? ' · ' + frequency + '给你发消息' : ''),
      callMe,
      callYou: String((input && input.callYou) || '').trim(),
      relation,
      story: String((input && input.story) || '').trim(),
      persona: String((input && input.persona) || '').trim(),
      frequency,
      bindFamily,
      familyNumber: bindFamily ? familyNumber : '',
      familyName: bindFamily ? String((input && input.familyName) || '').trim() : ''
    }
  }
}

export function addRole(input) {
  const built = buildCustomFields(input)
  if (!built.ok) return built

  const list = readRaw().map(normalize).filter(Boolean)
  const role = normalize(Object.assign({ id: newId(), createdAt: Date.now() }, built.fields))
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

/**
 * 修改一个**自定义**角色（人物设置页用）。
 *
 * 与 addRole 的区别：保留原 id 与 createdAt，不新增条目。
 * 内置角色不走这里 —— 它没有 id 可改（永远是 p_bilin），用的是 saveBuiltinProfile。
 *
 * @returns {{ok:boolean, reason?:string, field?:string, role?:object}}
 */
export function updateRole(id, input) {
  const target = String(id || '')
  if (!target) return { ok: false, reason: '缺少角色 id' }

  const built = buildCustomFields(input)
  if (!built.ok) return built

  const list = readRaw().map(normalize).filter(Boolean)
  const index = list.findIndex((r) => r.id === target)
  if (index < 0) return { ok: false, reason: '没找到这个角色' }

  const prev = list[index]
  // 直接构造结果（不经 normalize）：normalize 会给缺 id 的数据生成新 id，
  // 这里必须**保留原 id 与 createdAt**，否则等于"改一次就多一个角色"
  const role = Object.assign({}, built.fields, {
    id: prev.id,
    builtin: false,
    avatarColor: prev.avatarColor || '#7A6A4F',
    createdAt: prev.createdAt || Date.now()
  })
  list[index] = role
  writeRaw(list)
  emitChanged()
  return { ok: true, role }
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
