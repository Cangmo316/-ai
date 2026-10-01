/**
 * 比邻AI 数字人 · 捏脸参数端侧纯函数层（规格书 §7）
 *
 * 契约来源：
 *   - parameters-table.json        （params-table-1.0.0，102 条参数定义）
 *   - shape-namespace-map.json     （63 条捏脸参数 / 113 个 shape_* target）
 *
 * 设计约束：
 *   1. 纯函数、零依赖、无 I/O、无全局状态；映射表由调用方注入（可构建期内联）。
 *   2. 端侧**禁止**给 morph 权重传负值：负向一律由 `_dn` target 承担。
 *   3. 形态键命名 `shape_<key>_up` / `shape_<key>_dn`（单向参数只有 `_up`）。
 *   4. 交付/运行期资产中 `shape_*` 已被烘焙进顶点（数量为 0），
 *      因此本层在运行期只用于「参数 → 口型/表情之外的 UI 与校验」，
 *      真正驱动可见形变的是 vis_* / expr_*；详见 README 与交付说明 §18.9。
 */

export const MAP_SCHEMA = 'bilinai.face.namespace-map/1';
export const UP = '_up';
export const DN = '_dn';

/** 示例捏脸预设：与交付期烘焙所用档位逐值一致（BilinAI_FaceRig_60k_delivery_baked.glb） */
export const PRESET_DEMO = Object.freeze({
  face_width: -0.20, face_length: 0.10, cheekbone_height: 0.15, jaw_width: -0.25,
  chin_length: 0.10, forehead_height: 0.05, brow_height: 0.10, eye_size: 0.20,
  eye_tilt: 0.15, eye_height: 0.05, eye_aegyo: 0.35, eye_bag: 0.15,
  nose_bridge_height: 0.20, nose_tip_size: -0.20, nose_tip_upturn: 0.10,
  lip_upper_thickness: 0.15, lip_lower_thickness: 0.25, mouth_width: 0.10,
  philtrum_depth: 0.20, neck_length: 0.05,
});

/**
 * 年龄感联动系数（与 shape_age_overall_up 的构造权重同源，见交付说明 §18.4 第 6 步）
 * 正值 = 随年龄感增强；负值 = 随年龄感减弱（走 _dn 方向）。
 * 注意：两种驱动策略只能选其一，见 resolveAge()。
 */
export const AGE_LINKAGE = Object.freeze({
  forehead_wrinkle: 0.55, frown_line: 0.50, nasolabial: 0.70, crow_feet: 0.40,
  mouth_line: 0.40, neck_wrinkle: 0.50, eye_bag: 0.45, eye_socket_depth: 0.40,
  cheek_fullness: -0.35,
});

export function clamp(v, lo, hi) {
  return v < lo ? lo : (v > hi ? hi : v);
}

/** 软限制：滑杆可拉到端点，但内部非线性压缩（规格书 §3 第 4 条） */
export function softClamp(s, k = 0.82) {
  if (!Number.isFinite(s)) return 0;
  const a = Math.abs(s);
  if (a <= 1) return Math.sign(s) * Math.pow(a, k);
  return Math.sign(s) * Math.pow(a, k);
}

export function shapeTargetName(key, dir) {
  return 'shape_' + key + (dir === DN ? DN : UP);
}

/**
 * @param {object} map  shape-namespace-map.json 解析后的对象
 * @returns 端侧参数 API（纯函数集合）
 */
export function createFaceParams(map) {
  if (!map || !Array.isArray(map.params)) throw new Error('face-params: 映射表无效（缺少 params 数组）');
  if (map.schema !== MAP_SCHEMA) throw new Error('face-params: 映射表 schema 不匹配：' + map.schema);
  const byKey = new Map();
  const targetIndex = new Map();
  for (const p of map.params) {
    byKey.set(p.key, p);
    for (const t of [p.target_up, p.target_dn]) if (t) targetIndex.set(t, p.key);
  }
  const VERSION = map.paramsTableVersion || 'unknown';

  function describeParam(key) {
    const p = byKey.get(key);
    if (!p) return null;
    return {
      key: p.key, cn: p.cn, zone: p.zone, mesh: p.mesh,
      slider: p.slider, min: p.slider === '0~1' ? 0 : -1, max: 1,
      default: p.default, maxDispMM: p.maxDispMM, reverseRatio: p.reverseRatio,
      bidirectional: !!p.target_dn,
      targets: [p.target_up, p.target_dn].filter(Boolean),
      weightRule: p.weight_rule,
    };
  }

  function listParams() { return map.params.map((p) => p.key); }
  function listTargets() {
    const out = [];
    for (const p of map.params) for (const t of [p.target_up, p.target_dn]) if (t) out.push(t);
    return out;
  }

  /** 单参数 → 权重（严格遵守「不得为负」） */
  function weightsFor(key, slider, opt) {
    const o = opt || {};
    const p = byKey.get(key);
    if (!p) throw new Error('face-params: 未知参数 ' + key);
    let s = Number(slider);
    if (!Number.isFinite(s)) s = 0;
    const warnings = [];
    const lo = p.slider === '0~1' ? 0 : -1;
    if (s < lo) { warnings.push(key + ' 超出下限 ' + lo + '，已夹取'); s = lo; }
    if (s > 1) { warnings.push(key + ' 超出上限 1，已夹取'); s = 1; }
    if (o.soft) s = softClamp(s, o.softK === undefined ? 0.82 : o.softK);
    s = clamp(s, -1, 1);
    let wUp = Math.max(0, s);
    let wDn = Math.max(0, -s);
    if (!p.target_dn && wDn > 0) { warnings.push(key + ' 为单向参数（' + p.slider + '），负值无效已丢弃'); wDn = 0; }
    if (o.equalize && p.maxDispMM > 0) {
      const ref = o.refDispMM === undefined ? 3.0 : o.refDispMM;
      const f = ref / p.maxDispMM;
      wUp *= f; wDn *= f;
    }
    const targets = {};
    if (wUp > 0) targets[p.target_up] = wUp;
    if (wDn > 0) targets[p.target_dn] = wDn;
    return { key: p.key, slider: s, targets, warnings };
  }

  /**
   * 参数集合 → 驱动器权重表
   * @param {object} params  形如 { face_width: 0.3, age_overall: 0.2 }
   * @param {object} [opt]   { soft, softK, equalize, refDispMM, ageStrategy, strict }
   * @returns {object} { targets:{name:weight}, normalized:{key:slider}, warnings:[], version }
   */
  function applyParams(params, opt) {
    const o = opt || {};
    const strict = o.strict !== false;
    const warnings = [];
    const normalized = {};
    const targets = {};
    const ageStrategy = o.ageStrategy || 'target';

    let src = {};
    for (const k of Object.keys(params || {})) {
      if (!byKey.has(k)) {
        const msg = '未知参数 ' + k;
        if (strict) throw new Error('face-params: ' + msg);
        warnings.push(msg);
        continue;
      }
      src[k] = params[k];
    }
    src = applyLinkage(src, ageStrategy);

    for (const key of Object.keys(src)) {
      const r = weightsFor(key, src[key], o);
      for (const w of r.warnings) warnings.push(w);
      normalized[key] = r.slider;
      for (const t of Object.keys(r.targets)) targets[t] = r.targets[t];
    }
    for (const key of Object.keys(targets)) {
      if (targets[key] < 0) throw new Error('face-params: 出现负权重 ' + key);
    }
    return { targets, normalized, warnings, version: VERSION, ageStrategy };
  }

  /**
   * 年龄感联动。两种策略互斥（二选一，否则会「双重驱动」同一位移）：
   *   - 'target'     （推荐/默认）：age_overall 只驱动 shape_age_overall_up，
   *                   该 target 在 Blender 侧已按 §18.4 的组合权重做好；
   *                   分项滑杆只由用户自己拖动。
   *   - 'components'：把 age_overall 权重置 0，改为抬升各分项滑杆（UI 可见）。
   */
  function applyLinkage(params, strategy) {
    const st = strategy || 'target';
    const out = Object.assign({}, params);
    const age = clamp(Number(out.age_overall) || 0, 0, 1);
    if (st === 'components' && age > 0) {
      out.age_overall = 0;
      for (const k of Object.keys(AGE_LINKAGE)) {
        const c = AGE_LINKAGE[k];
        const cur = Number(out[k]) || 0;
        out[k] = c >= 0 ? Math.max(cur, c * age) : Math.min(cur, c * age);
      }
    }
    return out;
  }

  /** 视觉等强系数：使各参数「一单位滑杆」的位移量可比（默认参照 3 mm） */
  function equalizeFactor(key, refDispMM) {
    const p = byKey.get(key);
    if (!p) throw new Error('face-params: 未知参数 ' + key);
    const ref = refDispMM === undefined ? 3.0 : refDispMM;
    return p.maxDispMM > 0 ? ref / p.maxDispMM : 1;
  }

  /** 反向目标幅度比（_dn = reverseRatio × _up），用于 UI 预览或强度换算 */
  function reverseRatio(key) {
    const p = byKey.get(key);
    if (!p) throw new Error('face-params: 未知参数 ' + key);
    return p.reverseRatio;
  }

  function stats() {
    const bi = map.params.filter((p) => !!p.target_dn).length;
    return { params: map.params.length, targets: listTargets().length, bidirectional: bi, unidirectional: map.params.length - bi, version: VERSION };
  }

  return {
    version: VERSION,
    describeParam, listParams, listTargets, weightsFor, applyParams,
    applyLinkage, equalizeFactor, reverseRatio, stats,
    hasKey: (k) => byKey.has(k),
    keyOfTarget: (t) => targetIndex.get(t) || null,
  };
}