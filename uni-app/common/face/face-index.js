/**
 * 比邻AI · 3D 捏脸模块 —— uni-app 侧唯一入口
 * ---------------------------------------------------------------------------
 * 职责：把「引擎无关」的纯逻辑层（face-params / face-preset / care-trim /
 * face-adapter）与参数表、形态键命名表组装成一个开箱即用的门面（facade）。
 *
 * 分层（严格单向依赖，本文件是唯一汇总点）：
 *   parameters-table.js     102 条参数表（morph 63 / material 27 / bone 6 / asset 6）
 *   shape-namespace-map.js  63 个形态参数 → 113 个 shape_* target 的命名空间
 *   face-params.js          参数 → 权重（含软夹取 / 年龄联动 / 等强系数）
 *   face-preset.js          预设序列化 / 分享码 / 面容柜（12 槽）
 *   care-trim.js            康养裁剪（保留 79 / 弱化 20 / 不做 3 / 增强 15）
 *   face-adapter.js         四通道指令（morph / bone / material / asset）+ 30Hz 节流
 *
 * 本文件不做任何 I/O：不读文件、不写 storage、不发网络、不起定时器。
 * 持久化由页面负责（uni.setStorageSync 等），以保持本层可单测、可复用。
 */

import PARAMS_TABLE from './parameters-table.js';
import SHAPE_NAMESPACE_MAP from './shape-namespace-map.js';
import { createFaceParams, MAP_SCHEMA, clamp } from './face-params.js';
import { createFacePreset, createFaceCabinet, PRESET_SCHEMA_VERSION, CODE_VERSION, CODE_PREFIX, CABINET_MAX_SLOTS } from './face-preset.js';
import { createCareTrim } from './care-trim.js';
import {
  UI_COPY, BONE_RULES, ADAPTER_SCHEMA, DEFAULT_THROTTLE_HZ, MM_PER_UNIT,
  expandBoneTargets, expandBoneAliases, createThrottle, createEvalCache, buildCommands,
  createFaceAdapter, bindThree,
} from './face-adapter.js';

export const FACE_INDEX_SCHEMA = 'bilinai.face.index/1';
export const VERSION = 'face-index-1.0.0';

/* ───────────────────────────── 单例（无状态，可全局共享） ───────────────────────────── */

export const table = PARAMS_TABLE;
export const namespaceMap = SHAPE_NAMESPACE_MAP;
export const fp = createFaceParams(SHAPE_NAMESPACE_MAP);
export const preset = createFacePreset(PARAMS_TABLE);
export const care = createCareTrim(PARAMS_TABLE);
export const adapter = createFaceAdapter({});

/**
 * 面容柜工厂。本项目不自带持久化，页面按需把 toJSON() 写进 storage，
 * 启动时用 createCabinet({ json }) 还原。
 */
export function createCabinet(opt) {
  return createFaceCabinet(preset, opt || {});
}

/* ───────────────────────────── 滑杆（最小闭环 3 条） ───────────────────────────── */

/** UI 滑杆以「百分比整数」为单位：双向 -100~100，单向 0~100。 */
export const UI_UNIT = 100;

/**
 * 端侧渲染器**已经接线**的通道。
 *
 * face-three 的 applyCommands → adapter.applyToModel 会把 morph / bone / material
 * 三类指令真正写进模型（bindThree 提供 getBone / getMorph / getMaterial 视图）；
 * 而 `asset` 通道要多档模型资产（眉型 10 款 / 发型 / 服装款式）注册进 assetRegistry，
 * 当前每档只有一套资产 —— 这类参数在面板上标注「等资产」，而不是假装能调。
 *
 * ⚠️ 必须在 sliderMeta 之前声明：sliderMeta 在模块初始化时（SLIDERS = sliderMeta()）
 * 就会读它，放到后面会触发 TDZ（Cannot access before initialization）。
 */
export const WIRED_CHANNELS = Object.freeze(['morph', 'bone', 'material']);
/** 需要额外资产才能生效的通道（面板标注用） */
export const PENDING_CHANNELS = Object.freeze(['asset']);

/**
 * 首批开放的 3 条滑杆（其余 99 条参数由参数表全量支持，UI 逐步开放）。
 * 三条均为康养裁剪「保留」，且覆盖 A 区（脸型）/ C 区（眼）/ G 区（年龄）。
 */
export const SLIDER_KEYS = Object.freeze(['face_width', 'eye_size', 'age_overall']);

function rangeSpecToBounds(c) {
  // care.slider 是「裁剪后」的滑杆区间（形如 '-1~+1' / '0~1'），优先于参数表原区间。
  const spec = String(c.slider || c.tableRange || '').trim();
  const m = spec.match(/^(-?[0-9.]+)\s*~\s*\+?(-?[0-9.]+)$/);
  if (!m) return { paramMin: 0, paramMax: 1 };
  const lo = Number(m[1]);
  const hi = Number(m[2]);
  if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) return { paramMin: 0, paramMax: 1 };
  return { paramMin: lo, paramMax: hi };
}

/**
 * 滑杆元数据：UI 需要的全部信息一次给齐（不暴露内部结构）。
 * @param {string[]} [keys] 不传则用 SLIDER_KEYS
 * @returns {Array<object>}
 */
export function sliderMeta(keys) {
  const list = (keys && keys.length ? keys : SLIDER_KEYS);
  return list.map((key) => {
    const c = care.describeParam(key);
    // 注意：命名空间映射表只覆盖 morph 通道的 63 条参数；bone / material / asset
    // 通道的参数在这里取不到描述（fp.describeParam 返回 null），targets 记为空数组。
    const p = fp.describeParam(key);
    const b = rangeSpecToBounds(c);
    const uMin = Math.round(b.paramMin * UI_UNIT);
    const uMax = Math.round(b.paramMax * UI_UNIT);
    const defParam = Number(c.default) || 0;
    return {
      key, name: c.cn, zone: c.zone, channel: c.channel, type: c.type,
      trim: c.trim, trimmed: Boolean(c.sliderTightened),
      wired: WIRED_CHANNELS.indexOf(c.channel) >= 0,
      pendingReason: WIRED_CHANNELS.indexOf(c.channel) >= 0 ? '' : '等资产',
      trimReason: c.reason || '',
      paramMin: b.paramMin, paramMax: b.paramMax,
      uMin, uMax, step: 1, unit: UI_UNIT,
      defParam, defU: Math.round(defParam * UI_UNIT),
      bidirectional: b.paramMin < 0,
      targets: p ? p.targets.slice() : [],
    };
  });
}

/** key → 元数据，避免在模板里反复查表。 */
export const SLIDERS = sliderMeta();
export const SLIDER_BY_KEY = Object.freeze(SLIDERS.reduce((acc, m) => { acc[m.key] = m; return acc; }, {}));

/* ─────────────────── 全量滑杆（按参数表 10 个分区组织，捏脸面板的目录） ─────────────────── */

/**
 * 面板分区：按参数表的 10 个分区组织滑杆。
 * 适老裁剪判定「不做」的参数（战斗/异族妆容、纹身、胡须等）**不出现在面板里**
 * —— has 由 care.visibleParams() 决定，页面不自己过滤。
 */
export function sliderGroups(opt) {
  const o = opt || {};
  const zones = (table && table.zones) || {};
  const order = (o.zones && o.zones.length ? o.zones : Object.keys(zones));
  const byZone = new Map();
  for (const key of care.visibleParams()) {
    const c = care.describeParam(key);
    if (!c) continue;
    if (!byZone.has(c.zone)) byZone.set(c.zone, []);
    byZone.get(c.zone).push(key);
  }
  return order.filter((z) => byZone.has(z)).map((z) => {
    const keys = byZone.get(z);
    const sliders = sliderMeta(keys);
    return {
      zone: z,
      name: zones[z] || z,
      keys,
      sliders,
      count: keys.length,
      wired: sliders.filter((s) => s.wired).length,
      pending: sliders.filter((s) => !s.wired).length,
    };
  });
}

/** 面板目录（分区 → 滑杆）。页面只消费它，不自己拼参数表。 */
export const SLIDER_GROUPS = Object.freeze(sliderGroups());
/** 面板里全部可调参数的键（顺序 = 分区顺序）。 */
export const GROUPED_KEYS = Object.freeze(SLIDER_GROUPS.reduce((acc, g) => acc.concat(g.keys), []));
/** 全量 key → 元数据（含面板外参数，供回填与校验使用）。 */
export const SLIDER_BY_KEY_ALL = Object.freeze(
  sliderMeta([...GROUPED_KEYS, ...care.hiddenParams()]).reduce((acc, m) => { acc[m.key] = m; return acc; }, {})
);

/** 面板总览：给页头一行文案用（共 N 条 / 开放 M 条 / K 条等资产）。 */
export function panelSummary() {
  const wired = SLIDER_GROUPS.reduce((a, g) => a + g.wired, 0);
  const pending = SLIDER_GROUPS.reduce((a, g) => a + g.pending, 0);
  const stats = care.stats();
  return {
    total: stats.total,
    open: GROUPED_KEYS.length,
    wired,
    pending,
    dropped: stats.hidden,
    softened: stats.soften,
    zones: SLIDER_GROUPS.length,
  };
}

/** 全部滑杆的默认 UI 值（0 / 0 / 0）。 */
export function defaultValues(keys) {
  const list = (keys && keys.length ? keys : SLIDER_KEYS);
  const out = {};
  for (const k of list) {
    const m = SLIDER_BY_KEY_ALL[k] || sliderMeta([k])[0];
    out[k] = m.defU;
  }
  return out;
}

/** UI 整数 → 参数域值（夹取到该滑杆的裁剪区间）。 */
export function uToParam(meta, u) {
  const n = Number(u);
  const v = Number.isFinite(n) ? n : meta.defU;
  const clamped = clamp(v, meta.uMin, meta.uMax);
  return clamp(clamped / meta.unit, meta.paramMin, meta.paramMax);
}

/** 参数域值 → UI 整数（用于把已保存的预设回填到滑杆）。 */
export function paramToU(meta, p) {
  const n = Number(p);
  const v = Number.isFinite(n) ? n : meta.defParam;
  return Math.round(clamp(v, meta.paramMin, meta.paramMax) * meta.unit);
}

/** UI 值集合 → 参数域集合（只取已开放滑杆）。 */
export function paramsOf(values, keys) {
  const list = (keys && keys.length ? keys : SLIDER_KEYS);
  const src = values || {};
  const out = {};
  for (const k of list) {
    const m = SLIDER_BY_KEY_ALL[k] || sliderMeta([k])[0];
    out[k] = uToParam(m, Object.prototype.hasOwnProperty.call(src, k) ? src[k] : m.defU);
  }
  return out;
}

/** 参数域集合 → UI 值集合（paramsOf 的逆运算，用于回填滑杆）。 */
export function valuesOf(params, keys) {
  const list = (keys && keys.length ? keys : SLIDER_KEYS);
  const src = params || {};
  const out = {};
  for (const k of list) {
    const m = SLIDER_BY_KEY_ALL[k] || sliderMeta([k])[0];
    out[k] = paramToU(m, Object.prototype.hasOwnProperty.call(src, k) ? src[k] : m.defParam);
  }
  return out;
}

/* ───────────────────────────── 预览驱动 ───────────────────────────── */

/**
 * 把形态键权重压成「给 CSS 预览用的净驱动量」，避免页面直接认识 shape_* 名字。
 *   faceWidth  ∈ [-1, 1]  正=脸变宽，负=脸变窄
 *   eyeSize    ∈ [-1, 1]  正=眼变大，负=眼变小
 *   age        ∈ [ 0, 1]  越大越显年龄
 */
export function previewDrivers(weights) {
  const w = weights || {};
  const g = (n) => (typeof w[n] === 'number' ? w[n] : 0);
  const widthUp = g('shape_face_width_up');
  const widthDn = g('shape_face_width_dn');
  const eyeUp = g('shape_eye_size_up');
  const eyeDn = g('shape_eye_size_dn');
  const ageUp = g('shape_age_overall_up');
  return {
    widthUp, widthDn, eyeUp, eyeDn, ageUp,
    faceWidth: clamp(widthUp - widthDn, -1, 1),
    eyeSize: clamp(eyeUp - eyeDn, -1, 1),
    age: clamp(ageUp, 0, 1),
  };
}


/* ───────────────────────────── 告警过滤 ───────────────────────────── */

/** buildCommands 的「缺参补默认」告警后缀（按参数表逐条生成，UI 场景下是噪声）。 */
const MISSING_SUFFIX = ' 缺失，已补默认值';

/**
 * UI 侧告警过滤。buildCommands 面向「整表 102 条」的批处理场景，会对未传参数
 * 逐条告警「参数 X 缺失，已补默认值」；而 UI 每次只驱动几条滑杆，那 99 条提示
 * 会淹没真正的告警（区间未识别、bone 规则缺失、morph 不存在等）。
 * 语义：只丢弃「本次没被驱动」的参数缺失告警；被驱动却仍报缺失（真异常）以及
 * 所有非缺失类告警（区间未识别 / 骨骼规则缺失 / morph 不存在）一律原样透出。
 */
export function uiWarnings(list, activeKeys) {
  const active = new Set(activeKeys || []);
  const out = [];
  for (const w of (list || [])) {
    const s = String(w);
    if (s.indexOf('参数 ') === 0) {
      const i = s.indexOf(MISSING_SUFFIX);
      if (i > 3 && !active.has(s.slice(3, i))) continue;
    }
    out.push(w);
  }
  return out;
}

/* ───────────────────────────── 主流程 ───────────────────────────── */
/**
 * 一次算全：UI 值 → 参数 → 四通道指令 → 权重 → 预览驱动 → 分享码。
 * 页面只需调用本函数，不要自己拆通道。
 */
export function computeView(values, opt) {
  const o = opt || {};
  const keys = o.keys || SLIDER_KEYS;
  const params = paramsOf(values, keys);
  // buildCommands 内部已按通道分流，并把 fp/preset 的告警汇总好
  const cmds = buildCommands(PARAMS_TABLE, preset, fp, params, o.applyOpt);
  const share = preset.encodeShareCode(params);
  return {
    schema: FACE_INDEX_SCHEMA,
    values: valuesOf(params, keys),
    params,
    normalized: cmds.normalized,
    weights: cmds.morphs,
    drivers: previewDrivers(cmds.morphs),
    cmds,
    channels: cmds.channels,
    share,
    warnings: uiWarnings(cmds.warnings, keys),
  };
}

/** 随机一套 UI 值（区间内均匀，含端点）。 */
export function randomValues(keys, rnd) {
  const list = (keys && keys.length ? keys : SLIDER_KEYS);
  const r = typeof rnd === 'function' ? rnd : Math.random;
  const out = {};
  for (const k of list) {
    const m = SLIDER_BY_KEY_ALL[k] || sliderMeta([k])[0];
    out[k] = Math.round(m.uMin + r() * (m.uMax - m.uMin));
  }
  return out;
}

/**
 * 生成可持久化的预设（含分享码）。
 * @returns {object} { params, preset, share, warnings }
 */
export function buildSave(values, opt) {
  const o = opt || {};
  const keys = o.keys || SLIDER_KEYS;
  const params = paramsOf(values, keys);
  const built = preset.buildPreset(params, { name: o.name, presetId: o.presetId, createdAt: o.createdAt });
  const share = preset.encodeShareCode(params);
  const warnings = share.warnings.concat(built.warnings);
  return { params, preset: built.preset, share, warnings };
}

/** 从分享码 / 预设对象还原 UI 值（失败返回 null）。 */
export function loadSave(input, opt) {
  const o = opt || {};
  const keys = o.keys || SLIDER_KEYS;
  if (typeof input === 'string' && input.trim().indexOf(CODE_PREFIX) === 0) {
    const r = preset.decodeShareCode(input.trim());
    if (!r.ok) return { ok: false, error: r.error, values: null, params: null };
    return { ok: true, error: null, values: valuesOf(r.params, keys), params: r.params };
  }
  const r = preset.parsePreset(input);
  if (!r.ok) return { ok: false, error: r.error, values: null, params: null };
  return { ok: true, error: null, values: valuesOf(r.params, keys), params: r.params };
}

/* ───────────────────────────── 规格书红线（§7.4）───────────────────────────── */

/**
 * UI 红线文案。aiBadge / aiBadgeDetail 必须常驻展示且不可关闭；
 * consentRequired 在未完成肖像授权时阻止保存；saveNotice 在保存成功后展示。
 * 直接 re-export，禁止在页面里另写一份文案。
 */
export const FACE_UI_COPY = UI_COPY;

/* ───────────────────────────── 再导出（页面统一从本文件 import）───────────────────────────── */

export {
  UI_COPY, BONE_RULES, ADAPTER_SCHEMA, DEFAULT_THROTTLE_HZ, MM_PER_UNIT,
  expandBoneTargets, expandBoneAliases, createThrottle, createEvalCache, buildCommands,
  createFaceAdapter, bindThree,
  MAP_SCHEMA, PRESET_SCHEMA_VERSION, CODE_VERSION, CODE_PREFIX, CABINET_MAX_SLOTS,
};

export { createFaceParams, createFacePreset, createFaceCabinet, createCareTrim };

export default {
  schema: FACE_INDEX_SCHEMA, version: VERSION,
  table, namespaceMap, fp, preset, care, adapter,
  SLIDERS, SLIDER_BY_KEY, sliderMeta, defaultValues,
  SLIDER_GROUPS, GROUPED_KEYS, SLIDER_BY_KEY_ALL, sliderGroups, panelSummary,
  WIRED_CHANNELS, PENDING_CHANNELS,
  uToParam, paramToU, paramsOf, valuesOf, previewDrivers,
  computeView, randomValues, buildSave, loadSave, createCabinet,
  UI_COPY,
};