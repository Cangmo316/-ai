/**
 * 比邻AI · 面容预设格式与分享码（规格书 §7.1 / §8）
 *
 * 纯函数、零依赖、无 I/O、不依赖 DOM 与渲染器 —— 可直接在 node 里单测。
 *
 * 代码格式（CODE_VERSION = 1）：
 *   BL1-XXXXX-XXXXX-...       Crockford Base32（去掉 I L O U，避免手抄歧义）
 *
 * 位布局（MSB 优先）：
 *   [4]  codeVersion           分享码格式版本
 *   [8]  paramsVersionHash     paramsVersion 的 FNV-1a 低 8 位
 *   [8]  baseModelHash         baseModelId   的 FNV-1a 低 8 位
 *   [7]  count                 非默认参数个数（0..127）
 *   [102] presence bitmap      按参数表顺序的「该参数是否非默认」位图
 *   [8*count] values           每个非默认参数 8 位量化值
 *   [12] checksum              FNV-1a(前序字节) 低 12 位
 *
 * 长度：ceil((141 + 8n) / 5) 字符 + 每 5 字符一个分隔符 + 前缀 4 字符。
 *       典型预设（n = 15~30）为 66~96 字符；n <= 43 时仍 <= 120 字符。
 */

export const PRESET_SCHEMA_VERSION = 1;
export const CODE_VERSION = 1;
export const CODE_PREFIX = 'BL1-';
export const PARAMS_VERSION_DEFAULT = 'face-params-v1';
export const BASE_MODEL_DEFAULT = 'female_60s_v3';

const B32 = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
const B32_MAP = (() => {
  const m = Object.create(null);
  for (let i = 0; i < 32; i++) m[B32[i]] = i;
  // 易混字符归一
  m.I = 1; m.L = 1; m.O = 0; m.U = 0;
  return m;
})();

/* ────────────────────────── 位操作 ────────────────────────── */

function pushBits(bits, value, n) {
  for (let i = n - 1; i >= 0; i--) bits.push((value >> i) & 1);
}
function readBits(bits, pos, n) {
  let v = 0;
  for (let i = 0; i < n; i++) v = (v << 1) | (bits[pos + i] || 0);
  return v >>> 0;
}
function bitsToBytes(bits) {
  const out = [];
  for (let i = 0; i < bits.length; i += 8) {
    let v = 0;
    for (let j = 0; j < 8; j++) v = (v << 1) | (bits[i + j] || 0);
    out.push(v);
  }
  return out;
}
function bytesToBits(bytes) {
  const bits = [];
  for (const b of bytes) for (let i = 7; i >= 0; i--) bits.push((b >> i) & 1);
  return bits;
}
function bitsToChars(bits) {
  const out = [];
  for (let i = 0; i < bits.length; i += 5) {
    let v = 0;
    for (let j = 0; j < 5; j++) v = (v << 1) | (bits[i + j] || 0);
    out.push(B32[v]);
  }
  return out.join('');
}
function charsToBits(s) {
  const bits = [];
  for (const ch of s) {
    const v = B32_MAP[ch];
    if (v === undefined) return null;
    for (let j = 4; j >= 0; j--) bits.push((v >> j) & 1);
  }
  return bits;
}
function group(chars) {
  const parts = [];
  for (let i = 0; i < chars.length; i += 5) parts.push(chars.slice(i, i + 5));
  return parts.join('-');
}

/* ────────────────────────── 哈希与校验位 ────────────────────────── */

function utf8Bytes(str) {
  const s = String(str == null ? '' : str);
  const out = [];
  for (let i = 0; i < s.length; i++) {
    let c = s.charCodeAt(i);
    if (c < 0x80) out.push(c);
    else if (c < 0x800) { out.push(0xc0 | (c >> 6), 0x80 | (c & 63)); }
    else if (c >= 0xd800 && c <= 0xdbff && i + 1 < s.length) {
      const c2 = s.charCodeAt(++i);
      c = 0x10000 + ((c - 0xd800) << 10) + (c2 - 0xdc00);
      out.push(0xf0 | (c >> 18), 0x80 | ((c >> 12) & 63), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
    } else { out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63)); }
  }
  return out;
}

/** FNV-1a 32 位 */
export function fnv1a32(input) {
  const bytes = typeof input === 'string' ? utf8Bytes(input) : input;
  let h = 0x811c9dc5 >>> 0;
  for (const b of bytes) { h ^= b; h = Math.imul(h, 0x01000193) >>> 0; }
  return h >>> 0;
}
export function hash8(input) { return fnv1a32(input) & 0xff; }
export function checksumHex8(input) { return fnv1a32(input).toString(16).padStart(8, '0'); }

/* ────────────────────────── 范围解析与量化 ────────────────────────── */

/**
 * 把参数表的 `rg`（范围字符串）解析成可量化区间。
 * 支持：`-1~+1` `0~1` `+/-8 deg` `+/-3 mm` `0.85~1.15` `10 款` `色板 8 档` `0 款（本档不做）`
 */
export function parseRangeSpec(rg, type) {
  const s = String(rg == null ? '' : rg).trim();
  const num = (x) => Number(String(x).replace(/[^0-9.+-]/g, ''));
  let m = s.match(/^([+-]?[\d.]+)\s*[~～]\s*([+-]?[\d.]+)$/);
  if (m) return { kind: 'cont', lo: num(m[1]), hi: num(m[2]) };
  m = s.match(/^\+\/-\s*([\d.]+)/);
  if (m) { const r = num(m[1]); return { kind: 'cont', lo: -r, hi: r }; }
  m = s.match(/(\d+)\s*(?:款|档)/);
  if (m) {
    const n = Number(m[1]);
    return { kind: 'enum', n: n > 0 ? n : 1, discrete: n > 0 };
  }
  if (type === 'color' || type === 'enum' || type === 'scale') return { kind: 'enum', n: 1, discrete: false };
  return { kind: 'cont', lo: 0, hi: 1 };
}

function quantizeOne(rg, value) {
  if (rg.kind === 'enum') {
    let i = Math.round(Number(value) || 0);
    if (i < 0) i = 0;
    if (i > rg.n - 1) i = rg.n - 1;
    return i;
  }
  const span = rg.hi - rg.lo;
  let v = Number(value);
  if (!Number.isFinite(v)) v = rg.lo;
  if (v < rg.lo) v = rg.lo;
  if (v > rg.hi) v = rg.hi;
  return span === 0 ? 0 : Math.round(((v - rg.lo) / span) * 255);
}

function dequantizeOne(rg, level) {
  if (rg.kind === 'enum') return Math.min(level, rg.n - 1);
  return Math.round((rg.lo + (level / 255) * (rg.hi - rg.lo)) * 1e6) / 1e6;
}

function defaultOf(p, rg) {
  const d = Number(p.dv);
  if (Number.isFinite(d)) return rg.kind === 'enum' ? Math.round(d) : d;
  return rg.kind === 'enum' ? 0 : 0;
}

/* ────────────────────────── 主体 ────────────────────────── */

/**
 * @param {object} table  parameters-table.json（含 params 数组，元素有 k/ch/t/rg/dv）
 */
export function createFacePreset(table) {
  if (!table || !Array.isArray(table.params)) throw new Error('face-preset: 参数表无效（缺少 params 数组）');
  const schema = table.params.map((p) => {
    const rg = parseRangeSpec(p.rg, p.t);
    return {
      key: p.k, cn: p.cn, zone: p.z, channel: p.ch, type: p.t,
      range: rg, rg: p.rg, default: defaultOf(p, rg),
    };
  });
  const byKey = new Map(schema.map((p) => [p.key, p]));
  const N = schema.length;
  const TABLE_VERSION = table.version || 'unknown';

  function normalizeParams(raw, opt) {
    const o = opt || {};
    const warnings = [];
    const out = {};
    const src = raw && typeof raw === 'object' ? raw : {};
    for (const k of Object.keys(src)) {
      if (!byKey.has(k)) {
        if (o.strict) throw new Error('face-preset: 未知参数 ' + k);
        warnings.push('未知参数 ' + k + ' 已忽略');
      }
    }
    for (const p of schema) {
      if (!Object.prototype.hasOwnProperty.call(src, p.key)) {
        out[p.key] = p.default;
        if (o.warnMissing) warnings.push('参数 ' + p.key + ' 缺失，已补默认值 ' + p.default);
        continue;
      }
      let v = Number(src[p.key]);
      if (!Number.isFinite(v)) { warnings.push('参数 ' + p.key + ' 不是数值，已取默认值'); out[p.key] = p.default; continue; }
      const rg = p.range;
      if (rg.kind === 'enum') {
        v = Math.round(v);
        if (v < 0 || v > rg.n - 1) { warnings.push('参数 ' + p.key + ' 超出枚举范围，已夹取'); v = Math.min(Math.max(v, 0), rg.n - 1); }
      } else if (v < rg.lo || v > rg.hi) {
        warnings.push('参数 ' + p.key + ' 超出范围 ' + p.rg + '，已夹取');
        v = Math.min(Math.max(v, rg.lo), rg.hi);
      }
      out[p.key] = v;
    }
    return { params: out, warnings };
  }

  function isDefault(p, v) {
    return p.range.kind === 'enum' ? Math.round(v) === p.default : Math.abs(v - p.default) < 1e-9;
  }

  function encodeShareCode(params, opt) {
    const o = opt || {};
    const { params: norm, warnings } = normalizeParams(params, { strict: o.strict });
    const paramsVersion = o.paramsVersion || PARAMS_VERSION_DEFAULT;
    const baseModelId = o.baseModelId || BASE_MODEL_DEFAULT;

    const bitmap = new Array(N).fill(0);
    const levels = [];
    for (let i = 0; i < N; i++) {
      const p = schema[i];
      if (isDefault(p, norm[p.key])) continue;
      bitmap[i] = 1;
      levels.push(quantizeOne(p.range, norm[p.key]));
    }
    if (levels.length > 127) throw new Error('face-preset: 非默认参数过多（' + levels.length + ' > 127），请改用预设文件');

    const bits = [];
    pushBits(bits, CODE_VERSION, 4);
    pushBits(bits, hash8(paramsVersion), 8);
    pushBits(bits, hash8(baseModelId), 8);
    pushBits(bits, levels.length, 7);
    for (let i = 0; i < N; i++) bits.push(bitmap[i]);
    for (const lv of levels) pushBits(bits, lv, 8);

    const sum = fnv1a32(bitsToBytes(bits)) & 0xfff;
    pushBits(bits, sum, 12);

    // §8.2：assets 随 params 一并进码（见 extractAssets 注释）。
    // 若调用方另传 assets，只做一致性校验，不改变编码结果 —— params 是唯一真源。
    const assets = extractAssets(norm);
    if (o.assets && typeof o.assets === 'object') {
      for (const k of Object.keys(o.assets)) {
        if (!Object.prototype.hasOwnProperty.call(assets, k)) {
          warnings.push('assets 里的 ' + k + ' 不是资产通道参数，已忽略');
          continue;
        }
        const given = Number(o.assets[k]);
        if (Number.isFinite(given) && Math.abs(given - Number(assets[k])) > 1e-9) {
          warnings.push('assets.' + k + '=' + o.assets[k] + ' 与 params.' + k + '=' + assets[k] + ' 不一致，以 params 为准');
        }
      }
    }

    const code = CODE_PREFIX + group(bitsToChars(bits));
    return { code, count: levels.length, warnings, length: code.length, assets };
  }

  function decodeShareCode(code, opt) {
    const o = opt || {};
    const raw = String(code == null ? '' : code).trim().toUpperCase();
    const body = raw.replace(/^BL\d-/, '').replace(/[^0-9A-Z]/g, '');
    if (!raw.startsWith('BL')) return fail('分享码应以 BL 开头，请检查是否复制完整');
    const verChar = raw.slice(2, 3);
    if (verChar !== '1') return fail('分享码格式版本 ' + verChar + ' 暂不支持，请升级到最新版 App');
    const bits = charsToBits(body);
    if (!bits) return fail('分享码含非法字符，请检查是否抄错');

    const needed = 4 + 8 + 8 + 7 + N + 12;
    if (bits.length < needed) return fail('分享码长度不足，可能被截断');

    let pos = 0;
    const codeVer = readBits(bits, pos, 4); pos += 4;
    if (codeVer !== CODE_VERSION) return fail('分享码内部版本不匹配（' + codeVer + '）');
    const pvHash = readBits(bits, pos, 8); pos += 8;
    const bmHash = readBits(bits, pos, 8); pos += 8;
    const count = readBits(bits, pos, 7); pos += 7;
    const bitmap = [];
    for (let i = 0; i < N; i++) { bitmap.push(bits[pos + i] || 0); }
    pos += N;
    if (count > Math.floor((bits.length - pos - 12) / 8)) return fail('分享码内容不完整，可能被截断');

    const levels = [];
    for (let i = 0; i < count; i++) { levels.push(readBits(bits, pos, 8)); pos += 8; }

    const sumPos = pos;
    const given = readBits(bits, sumPos, 12);
    const expect = fnv1a32(bitsToBytes(bits.slice(0, sumPos))) & 0xfff;
    if (given !== expect) return fail('分享码校验位不匹配，可能抄错了字符（校验 ' + given.toString(16) + ' != ' + expect.toString(16) + '）');

    const params = {};
    for (const p of schema) params[p.key] = p.default;
    let li = 0;
    for (let i = 0; i < N; i++) {
      if (!bitmap[i]) continue;
      params[schema[i].key] = dequantizeOne(schema[i].range, levels[li++]);
    }

    const warnings = [];
    if (o.paramsVersion && hash8(o.paramsVersion) !== pvHash) warnings.push('分享码的 paramsVersion 与当前资产不一致，可能有个别参数丢失');
    if (o.baseModelId && hash8(o.baseModelId) !== bmHash) warnings.push('分享码基于不同的基准模型，比例可能略有偏差');
    const exact = {}; for (const k of Object.keys(params)) if (!isDefault(byKey.get(k), params[k])) exact[k] = params[k];
    return { ok: true, params, nonDefault: exact, count, warnings, error: null, assets: extractAssets(params) };

    function fail(msg) { return { ok: false, params: null, nonDefault: null, count: 0, warnings: [], error: msg, assets: null }; }
  }

  function canonical(preset) {
    const keys = Object.keys(preset.params).sort();
    const body = {
      schemaVersion: preset.schemaVersion,
      baseModelId: preset.baseModelId,
      paramsVersion: preset.paramsVersion,
      params: keys.map((k) => [k, preset.params[k]]),
    };
    return JSON.stringify(body);
  }

  function buildPreset(params, opt) {
    const o = opt || {};
    const { params: norm, warnings } = normalizeParams(params, { strict: o.strict });
    const preset = {
      schemaVersion: PRESET_SCHEMA_VERSION,
      presetId: o.presetId || null,
      name: o.name || '未命名面容',
      baseModelId: o.baseModelId || BASE_MODEL_DEFAULT,
      paramsVersion: o.paramsVersion || PARAMS_VERSION_DEFAULT,
      params: norm,
      assets: o.assets || extractAssets(norm),
      createdAt: o.createdAt || new Date().toISOString(),
      createdBy: o.createdBy || 'family',
      consentRecordId: o.consentRecordId || null,
    };
    preset.presetId = preset.presetId || 'fp_' + checksumHex8(canonical(preset)).slice(0, 12);
    preset.checksum = checksumHex8(canonical(preset));
    return { preset, warnings };
  }

  /**
   * 资产通道快照（规格书 §8.2 的 `assets`）。
   *
   * 本项目参数表里，「资产选择」本身就是 asset 通道参数（brow_shape / lash_length /
   * hairstyle / bangs / beard_type / beard_density），因此 assets ⊆ params：
   * 分享码的 bitmap + levels 已经把资产选择一并压缩传输，无需再单独占一段比特
   * （单独一段需 +48 bit ≈ +8 字符，会把 n=43 从 120 顶到 128，违反 §8.2 第 ③ 条）。
   * 这里把它显式解出来，是为了让编解码两端都能拿到、并做一致性校验，
   * 而不是让调用方另存一份 assets 与 params 打架。
   */
  function extractAssets(params) {
    const out = {};
    for (const p of schema) if (p.channel === 'asset') out[p.key] = params[p.key];
    return out;
  }

  function parsePreset(input, opt) {
    const o = opt || {};
    const warnings = [];
    let obj = input;
    if (typeof input === 'string') {
      try { obj = JSON.parse(input); }
      catch (e) { return { ok: false, preset: null, params: null, warnings, error: '预设文件不是合法 JSON：' + e.message }; }
    }
    if (!obj || typeof obj !== 'object') return { ok: false, preset: null, params: null, warnings, error: '预设内容为空' };
    for (const f of ['schemaVersion', 'baseModelId', 'paramsVersion']) {
      if (obj[f] === undefined || obj[f] === null) return { ok: false, preset: null, params: null, warnings, error: '预设缺少必需字段 ' + f };
    }
    const sv = Number(obj.schemaVersion);
    if (sv > PRESET_SCHEMA_VERSION) return { ok: false, preset: null, params: null, warnings, error: '这份数据太新（schemaVersion=' + sv + '），请升级 App 后再导入' };
    if (sv < PRESET_SCHEMA_VERSION) warnings.push('预设为旧版 schemaVersion=' + sv + '，已按 v' + PRESET_SCHEMA_VERSION + ' 迁移（缺失参数补默认值）');

    if (obj.checksum) {
      const expect = checksumHex8(canonical(obj));
      if (String(obj.checksum).toLowerCase() !== expect) {
        return { ok: false, preset: null, params: null, warnings, error: '预设校验位不匹配，文件可能被改动或损坏（期望 ' + expect + '）' };
      }
    } else warnings.push('预设没有 checksum，完整性无法校验');

    if (o.baseModelId && obj.baseModelId !== o.baseModelId) warnings.push('预设基于 ' + obj.baseModelId + '，当前资产为 ' + o.baseModelId + '，比例可能不一致');
    if (o.paramsVersion && obj.paramsVersion !== o.paramsVersion) warnings.push('预设的参数表版本为 ' + obj.paramsVersion + '，当前为 ' + o.paramsVersion + '（能迁移的参数已迁移）');

    const { params, warnings: nw } = normalizeParams(obj.params || obj.values || {}, { strict: false, warnMissing: sv < PRESET_SCHEMA_VERSION });
    for (const w of nw) warnings.push(w);
    return { ok: true, preset: obj, params, warnings, error: null };
  }

  function estimateShareCodeLength(count) {
    const bits = 141 + 8 * count;
    const chars = Math.ceil(bits / 5);
    return CODE_PREFIX.length + chars + (Math.ceil(chars / 5) - 1);
  }

  function isShareCode(s) {
    const t = String(s == null ? '' : s).trim().toUpperCase();
    if (!/^BL1-[0-9A-HJKMNP-TV-Z-]+$/.test(t)) return false;
    return decodeShareCode(t).ok;
  }

  return {
    tableVersion: TABLE_VERSION,
    schemaVersion: PRESET_SCHEMA_VERSION,
    codeVersion: CODE_VERSION,
    paramCount: N,
    schema,
    describeParam: (k) => byKey.get(k) || null,
    listParams: () => schema.map((p) => p.key),
    normalizeParams, buildPreset, parsePreset,
    encodeShareCode, decodeShareCode,
    estimateShareCodeLength, isShareCode,
    checksumHex8, fnv1a32, parseRangeSpec,
  };
}

/* ────────────────────── 多套面容（面容柜，规格书 §8.4） ────────────────────── */

export const CABINET_SCHEMA_VERSION = 1;
/** 上限 12 套：默认 / 节日 / 正式 + 备用，足够覆盖家属场景又不会把 UI 撑爆 */
export const CABINET_MAX_SLOTS = 12;
export const CABINET_ID_PREFIX = 'fc_';

function cabinetCanonical(obj) {
  return JSON.stringify({
    schemaVersion: obj.schemaVersion,
    cabinetId: obj.cabinetId,
    activeSlotId: obj.activeSlotId,
    slots: obj.slots.map((s) => [s.presetId, s.name, s.checksum]),
  });
}

/**
 * 一个老人账号可存多套面容，但**同一时刻只有一套生效**。
 * @param {object} fp createFacePreset(table) 的返回值
 */
export function createFaceCabinet(fp, opt) {
  if (!fp || typeof fp.buildPreset !== 'function' || typeof fp.parsePreset !== 'function') {
    throw new Error('face-preset: createFaceCabinet 需要一个 createFacePreset 的返回值');
  }
  const o = opt || {};
  const slots = [];
  let activeSlotId = null;
  const paramCount = fp.paramCount;

  function describe(slot) {
    if (!slot) return null;
    return {
      slotId: slot.slotId, name: slot.name, checksum: slot.checksum, createdAt: slot.createdAt,
      paramCount, isActive: slot.slotId === activeSlotId,
    };
  }
  function need(slotId) {
    const s = slots.find((x) => x.slotId === slotId);
    if (!s) throw new Error('face-preset: 面容不存在 ' + slotId);
    return s;
  }
  function makeSlot(spec) {
    const { preset, warnings } = fp.buildPreset(spec.params || {}, {
      name: spec.name, presetId: spec.slotId, baseModelId: spec.baseModelId, paramsVersion: spec.paramsVersion,
      assets: spec.assets, createdAt: spec.createdAt, createdBy: spec.createdBy, consentRecordId: spec.consentRecordId,
    });
    return { slot: { slotId: preset.presetId, name: preset.name, preset, checksum: preset.checksum, createdAt: preset.createdAt }, warnings };
  }

  /**
   * slotId 直接复用 preset.presetId。未显式指定时 presetId 由参数指纹派生，
   * 于是「同参数的两套面容」（典型场景就是复制面容）会撞到同一个 id。
   * 这里给派生 id 加递增序号后缀，保证同一柜内 slotId 唯一；显式指定的 id 仍严格查重。
   */
  function deriveUniqueSlotId(base) {
    if (!slots.some((x) => x.slotId === base)) return base;
    let n = 2;
    let cand = base + '-' + n;
    while (slots.some((x) => x.slotId === cand)) { n += 1; cand = base + '-' + n; }
    return cand;
  }

  function addSlot(spec) {
    const s = typeof spec === 'string' ? { name: spec } : (spec || {});
    if (slots.length >= CABINET_MAX_SLOTS) throw new Error('face-preset: 面容数量已达上限 ' + CABINET_MAX_SLOTS + ' 套');
    const explicitId = s.slotId || null;
    let built = makeSlot({ name: s.name || ('面容 ' + (slots.length + 1)), params: s.params, slotId: explicitId });
    if (explicitId) {
      if (slots.some((x) => x.slotId === built.slot.slotId)) throw new Error('face-preset: slotId 已存在 ' + explicitId);
    } else {
      const uid = deriveUniqueSlotId(built.slot.slotId);
      if (uid !== built.slot.slotId) built = makeSlot({ name: built.slot.name, params: s.params, slotId: uid });
    }
    const slot = built.slot;
    slots.push(slot);
    if (!activeSlotId) activeSlotId = slot.slotId;   // 第一套自动生效
    return { slot: describe(slot), warnings: built.warnings };
  }

  function updateSlot(slotId, params) {
    const s = need(slotId);
    const { slot } = makeSlot({ name: s.name, params, slotId: null });
    s.preset = slot.preset;
    s.checksum = slot.checksum;
    return describe(s);
  }

  function renameSlot(slotId, name) {
    if (typeof name !== 'string' || !name.trim()) throw new Error('face-preset: 面容名称不能为空');
    const s = need(slotId);
    s.name = name.trim();
    s.preset.name = s.name;      // name 不参与 checksum，改名不影响完整性
    return describe(s);
  }

  function duplicateSlot(slotId, name) {
    const s = need(slotId);
    return addSlot({ name: name || (s.name + ' 副本'), params: s.preset.params });
  }

  function removeSlot(slotId) {
    const s = need(slotId);
    if (slots.length === 1) throw new Error('face-preset: 至少要保留一套面容');
    if (s.slotId === activeSlotId) throw new Error('face-preset: 不能删除当前生效的面容，请先切换到其它面容');
    slots.splice(slots.indexOf(s), 1);
    return { removed: s.slotId, activeSlotId };
  }

  function activate(slotId) {
    const s = need(slotId);
    activeSlotId = s.slotId;     // 只有一套生效：单一 activeSlotId，天然互斥
    return describe(s);
  }

  function toJSON() {
    const obj = {
      schemaVersion: CABINET_SCHEMA_VERSION,
      cabinetId: o.cabinetId || null,
      activeSlotId,
      slots: slots.map((s) => s.preset),
      createdAt: o.createdAt || new Date().toISOString(),
    };
    obj.cabinetId = obj.cabinetId || (CABINET_ID_PREFIX + checksumHex8(cabinetCanonical(obj)).slice(0, 8));
    obj.checksum = checksumHex8(cabinetCanonical(obj));
    return obj;
  }

  function load(input) {
    let obj = input;
    if (typeof input === 'string') {
      try { obj = JSON.parse(input); } catch (e) { return { ok: false, error: '面容柜不是合法 JSON：' + e.message }; }
    }
    if (!obj || typeof obj !== 'object' || !Array.isArray(obj.slots)) return { ok: false, error: '面容柜内容为空或缺少 slots' };
    const sv = Number(obj.schemaVersion);
    if (!Number.isFinite(sv)) return { ok: false, error: '面容柜缺少 schemaVersion' };
    if (sv > CABINET_SCHEMA_VERSION) return { ok: false, error: '这份面容柜太新（schemaVersion=' + sv + '），请升级 App 后再导入' };
    if (obj.checksum !== undefined && String(obj.checksum).toLowerCase() !== checksumHex8(cabinetCanonical(obj))) {
      return { ok: false, error: '面容柜校验位不匹配，文件可能被改动或损坏' };
    }
    if (obj.slots.length > CABINET_MAX_SLOTS) return { ok: false, error: '面容套数 ' + obj.slots.length + ' 超过上限 ' + CABINET_MAX_SLOTS };
    const warnings = [];
    const next = [];
    for (const sp of obj.slots) {
      const r = fp.parsePreset(sp);
      if (!r.ok) return { ok: false, error: '第 ' + (next.length + 1) + ' 套面容无法导入：' + r.error };
      for (const w of r.warnings) warnings.push('「' + (sp.name || '未命名') + '」' + w);
      next.push({ slotId: r.preset.presetId, name: r.preset.name, preset: r.preset, checksum: r.preset.checksum, createdAt: r.preset.createdAt });
    }
    slots.length = 0;
    for (const s of next) slots.push(s);
    const wantActive = obj.activeSlotId && slots.some((x) => x.slotId === obj.activeSlotId);
    if (obj.activeSlotId && !wantActive) warnings.push('生效面容 ' + obj.activeSlotId + ' 不在列表内，已回退到第一套');
    activeSlotId = wantActive ? obj.activeSlotId : (slots.length ? slots[0].slotId : null);
    return { ok: true, error: null, warnings, slots: slots.length, activeSlotId };
  }

  function check() {
    const errors = [];
    const actives = slots.filter((s) => s.slotId === activeSlotId);
    if (slots.length && actives.length !== 1) errors.push('生效面容数量应为 1，实为 ' + actives.length);
    if (!slots.length && activeSlotId !== null) errors.push('空柜不应有生效面容');
    if (new Set(slots.map((s) => s.slotId)).size !== slots.length) errors.push('slotId 重复');
    return { ok: errors.length === 0, errors, slots: slots.length, activeCount: actives.length };
  }

  const cabinet = {
    schemaVersion: CABINET_SCHEMA_VERSION,
    maxSlots: CABINET_MAX_SLOTS,
    paramCount,
    addSlot, updateSlot, renameSlot, duplicateSlot, removeSlot, activate, load, check, toJSON,
    listSlots: () => slots.map(describe),
    stats: () => ({ slots: slots.length, maxSlots: CABINET_MAX_SLOTS, activeSlotId, paramCount, activeCount: slots.filter((s) => s.slotId === activeSlotId).length }),
    activeSlotId: () => activeSlotId,
    activeSlot: () => describe(slots.find((s) => s.slotId === activeSlotId)),
    getSlot: (slotId) => describe(slots.find((s) => s.slotId === slotId)),
    activeParams: () => {
      const s = slots.find((x) => x.slotId === activeSlotId);
      return s ? Object.assign({}, s.preset.params) : null;
    },
    activePreset: () => {
      const s = slots.find((x) => x.slotId === activeSlotId);
      return s ? s.preset : null;
    },
  };

  if (o.json) {
    const r = cabinet.load(o.json);
    if (!r.ok) throw new Error('face-preset: 面容柜导入失败 —— ' + r.error);
  }
  return cabinet;
}