/**
 * 比邻AI 数字人 · 端侧「渲染器适配层」（规格书 §7.2 / §7.3 / §7.4）
 *
 * 与 face-params.js（求值层）、face-preset.js（预设层）的分工：
 *   求值层   参数 → shape_* 权重（只管 morph 通道）
 *   适配层   参数 → 四通道指令（morph / bone / material / asset）→ 写进具体模型
 *
 * 设计约束：
 *   1. 适配器本身**不依赖任何渲染器**：模型以鸭子类型的 model 视图注入，
 *      three.js 只是其中一个 `bindThree()` 薄绑定（见文件末尾）。
 *   2. morph 名称 → index **必须**从资产自带的字典取（three.js 的
 *      `mesh.morphTargetDictionary` / glTF extras），**禁止硬编码 index**。
 *   3. 写材质只改属性/uniform，**不得重建材质或重传贴图**（§7.3）。
 *   4. 滑杆拖动节流 ≤ 30 次/秒，且同一帧内复用同一份求值结果（§7.3）。
 *   5. 运行期资产里 shape_* 已被烘焙掉（数量为 0），找不到名字只告警不抛错，
 *      便于同一套代码在编辑期 / 交付期两种资产上复用。
 */

import { parseRangeSpec } from './face-preset.js';

export const ADAPTER_SCHEMA = 'bilinai.face.adapter/1';
export const DEFAULT_THROTTLE_HZ = 30;
/** glTF / Blender 默认以「米」为单位，1 单位 = 1000 mm */
export const MM_PER_UNIT = 1000;

/* ───────────────────────── §7.4 UI 文案（产品红线） ───────────────────────── */

/**
 * 捏脸页必须常驻展示 `aiBadge`（不可遮挡、不可由用户关闭），
 * 保存时必须展示 `saveNotice`；`consentRequired` 在缺授权时阻止保存。
 */
export const UI_COPY = Object.freeze({
  aiBadge: '本形象为 AI 数字人',
  aiBadgeDetail: '基于本人授权素材生成，不是真人实时画面',
  previewHint: '捏脸预览',
  saveNotice: '形象仅用于陪伴对话，不会用于其他用途',
  consentRequired: '需先完成肖像授权后才能保存形象',
  saveTitle: '已保存到面容柜',
  /**
   * 3D 捏脸已按策略变更移除（2026-10-05）：数字人只做「唇形同步 + 招手互动」。
   * 「数字人形象」这个入口**保留**（不删入口、不删页面），点进去给这句提示。
   */
  faceDeveloping: '此功能正在开发中',
});

/* ───────────────────── §7.2 骨骼规则（6 条 bone 通道参数） ───────────────────── */

/**
 * 键必须与 parameters-table.json 中 `ch === 'bone'` 的 6 条参数一一对应
 * （由 face-adapter.test.mjs 断言覆盖，改表即报错）。
 *   mirror: true  → 左右骨取相反符号（L = +v, R = -v），用于「张开 / 外张」类；
 *   mirror: false → 左右骨同号（如耳朵整体上下平移）。
 */
export const BONE_RULES = Object.freeze({
  neck_thickness: { target: 'neck', type: 'scale' },
  head_scale: { target: 'head', type: 'scale' },
  eye_spacing: { target: 'eye', type: 'translate', axis: 'x', mirror: true },
  ear_size: { target: 'ear', type: 'scale' },
  ear_protrusion: { target: 'ear', type: 'rotate', axis: 'y', mirror: true },
  ear_height: { target: 'ear', type: 'translate', axis: 'z', mirror: false },
});

const BONE_SUFFIX = { L: '_L', R: '_R' };

/** `eye.L` / `eye.L/eye.R` → ['eye_L', 'eye_R']；`neck` → ['neck'] */
export function expandBoneTargets(tg) {
  const s = String(tg == null ? '' : tg).trim();
  if (!s) return [];
  const parts = s.split('/').map((x) => x.trim()).filter(Boolean);
  const out = [];
  for (const part of parts) {
    const m = part.match(/^(.*)\.([LR])$/);
    if (m) out.push(m[1] + BONE_SUFFIX[m[2]]);
    else out.push(part);
  }
  return out;
}

/**
 * 骨骼名回退：交付件（8 骨）用 `eye_L` / `ear_L`，编辑件（20 骨）用 `eye.L` / `ear.L`，
 * 两代资产都要能命中，故按 `_L/_R` 与 `.L/.R` 互相补一条候选名。
 * `ear_L` -> [ear_L, ear.L]；`ear.L` -> [ear.L, ear_L]；`head` -> [head]。
 */
export function expandBoneAliases(name) {
  const s = String(name == null ? "" : name).trim();
  if (!s) return [];
  const out = [s];
  const m = s.match(/^(.*)_([LR])$/);
  if (m) out.push(m[1] + "." + m[2]);
  const n = s.match(/^(.*)\.([LR])$/);
  if (n) out.push(n[1] + "_" + n[2]);
  return out;
}

/* ───────────────────────────── §7.3 节流 ───────────────────────────── */

/**
 * 硬上限节流：每秒最多 hz 次（默认 30）。超出的调用被丢弃并计数，
 * 不做尾帧补发——滑杆连续拖动时下一帧本来就会再来一次。
 * now / hz 可注入，便于单测确定性地验证「≤30 次/秒」。
 */
export function createThrottle(fn, opt) {
  const o = opt || {};
  const hz = Math.min(DEFAULT_THROTTLE_HZ, Math.max(1, Math.floor(Number(o.hz) || DEFAULT_THROTTLE_HZ)));
  const minGap = 1000 / hz;
  const now = o.now || (() => Date.now());
  let last = -Infinity;
  let calls = 0;
  let dropped = 0;
  return {
    hz,
    minGap,
    call(arg) {
      const t = now();
      if (t - last < minGap - 1e-9) { dropped += 1; return { applied: false, dropped: true }; }
      last = t;
      calls += 1;
      const result = fn(arg);
      return { applied: true, dropped: false, result };
    },
    stats: () => ({ hz, minGap, calls, dropped }),
    reset: () => { last = -Infinity; calls = 0; dropped = 0; },
  };
}

/** 同一帧内复用求值结果（frameId 由调用方注入，例如 rAF 序号） */
export function createEvalCache(resolve, opt) {
  const o = opt || {};
  const frameId = o.frameId || (() => 0);
  let lastFrame = Symbol('none');
  let cached = null;
  let hits = 0;
  let misses = 0;
  return {
    get(arg) {
      const f = frameId();
      if (f === lastFrame && cached) { hits += 1; return cached; }
      lastFrame = f;
      cached = resolve(arg);
      misses += 1;
      return cached;
    },
    stats: () => ({ hits, misses }),
    reset: () => { lastFrame = Symbol('none'); cached = null; hits = 0; misses = 0; },
  };
}

/* ─────────────────── 参数 → 四通道指令（纯函数，可单测） ─────────────────── */

function paletteNote(p) {
  return p.tg;
}

/**
 * @param {object} table   parameters-table.json（原始表，提供 ch/tg/t/rg）
 * @param {object} preset  createFacePreset(table) 的返回值（提供 normalizeParams / schema）
 * @param {object} fp      createFaceParams(map) 的返回值（提供 applyParams → shape_* 权重）
 * @param {object} params  形如 { face_width: -0.2, eye_size: 0.3 }
 * @returns {object} { morphs, bones, materials, assets, normalized, warnings, channels }
 */
export function buildCommands(table, preset, fp, params, opt) {
  const o = opt || {};
  const warnings = [];
  const morphs = {};
  const bones = {};
  const materials = {};
  const assets = {};
  let normalized = {};

  if (fp && typeof fp.applyParams === 'function') {
    // parameters-table 是 morph/material/bone/asset 四通道混编，
    // 而 face-params 只认 morph 通道的键。这里先按 fp.hasKey 过滤，
    // 否则它的严格模式会对 bone/material/asset 键抛「未知参数」。
    const src0 = params || {};
    let morphParams = src0;
    if (typeof fp.hasKey === 'function') {
      morphParams = {};
      for (const k of Object.keys(src0)) if (fp.hasKey(k)) morphParams[k] = src0[k];
    }
    const r = fp.applyParams(morphParams, o.applyOpt);
    for (const t of Object.keys(r.targets)) morphs[t] = r.targets[t];
    for (const w of (r.warnings || [])) warnings.push(w);
    normalized = r.normalized;
  }

  const src = Object.assign({}, params || {});
  if (preset && typeof preset.normalizeParams === 'function') {
    const n = preset.normalizeParams(src, { warnMissing: true });
    for (const w of n.warnings) warnings.push(w);
    normalized = Object.assign({}, normalized, n.params);
  }

  const items = (table && Array.isArray(table.params)) ? table.params : [];
  const byKey = new Map(items.map((p) => [p.k, p]));
  const hz = o.mmPerUnit || MM_PER_UNIT;

  /** 按 BONE_RULES 展开成「每根骨一份指令」 */
  function pushBone(key, value, rule, raw) {
    const rg = parseRangeSpec(raw.rg, raw.t);
    const names = expandBoneTargets(raw.tg);
    const v = Number(value);
    if (!Number.isFinite(v)) return;
    names.forEach((name, i) => {
      const sign = (rule.mirror && names.length === 2 && i === 1) ? -1 : 1;
      const e = bones[name] || (bones[name] = {});
      if (rule.type === 'scale') e.scale = v;
      else if (rule.type === 'translate') {
        e.translateMM = e.translateMM || {};
        e.translateMM[rule.axis || 'x'] = sign * v;
        e.translateUnits = e.translateUnits || {};
        e.translateUnits[rule.axis || 'x'] = (sign * v) / hz;
      } else if (rule.type === 'rotate') {
        e.rotateDeg = e.rotateDeg || {};
        e.rotateDeg[rule.axis || 'x'] = sign * v;
      }
      if (rg.kind !== 'cont') warnings.push(key + ' 区间 ' + raw.rg + ' 未识别为连续量');
    });
  }

  for (const key of Object.keys(src)) {
    const raw = byKey.get(key);
    if (!raw) continue;
    const value = src[key];
    if (raw.ch === 'bone') {
      const rule = BONE_RULES[key];
      if (!rule) { warnings.push('bone 通道参数 ' + key + ' 无 BONE_RULES 规则，已跳过'); continue; }
      pushBone(key, value, rule, raw);
    } else if (raw.ch === 'material') {
      if (raw.t === 'color' || raw.t === 'enum') materials[paletteNote(raw)] = { palette: Math.round(Number(value) || 0), rg: raw.rg };
      else materials[raw.tg] = Number(value);
    } else if (raw.ch === 'asset') {
      if (raw.t === 'weight') assets[raw.tg] = { weight: true, value: Number(value) };
      else assets[raw.tg] = { option: Math.round(Number(value) || 0), rg: raw.rg };
    }
  }

  return {
    morphs, bones, materials, assets, normalized, warnings,
    channels: { morphs: Object.keys(morphs).length, bones: Object.keys(bones).length, materials: Object.keys(materials).length, assets: Object.keys(assets).length },
  };
}

/* ────────────────────────── 模型视图（鸭子类型） ────────────────────────── */

/**
 * model 视图接口（由 bindThree 或测试用假模型提供）：
 *   getBone(name)          -> { scale:{set}, rotation:{}, position:{set} } | null
 *   getMorph(name)         -> { dictionary:{name:index}, influences:[] } | null
 *   getMaterial(name)      -> object | null
 *   getAssetNode(slot, opt)-> { visible:boolean } | null
 */
export function createFaceAdapter(opt) {
  const o = opt || {};
  let applied = 0;
  const warns = [];
  let lastCommands = null;

  function writeMorphs(model, morphs) {
    for (const name of Object.keys(morphs)) {
      const handle = model.getMorph(name);
      if (!handle || !handle.dictionary) { warns.push('资产中不存在 morph ' + name + '（运行期 shape_* 已烘焙，属预期）'); continue; }
      const idx = handle.dictionary[name];
      if (typeof idx !== 'number') { warns.push('morph 字典缺少 ' + name + '，跳过'); continue; }
      handle.influences[idx] = morphs[name];
    }
  }

  function writeBones(model, bones) {
    for (const name of Object.keys(bones)) {
      const bone = model.getBone(name);
      if (!bone) { warns.push('资产中不存在骨骼 ' + name); continue; }
      const cmd = bones[name];
      if (cmd.scale !== undefined && bone.scale && typeof bone.scale.set === 'function') bone.scale.set(cmd.scale, cmd.scale, cmd.scale);
      if (cmd.translateUnits) {
        for (const ax of Object.keys(cmd.translateUnits)) {
          if (!bone.position || typeof bone.position.set !== 'function') continue;
          const cur = typeof bone.position[ax] === 'number' ? bone.position[ax] : 0;
          const base = (bone.__rest && typeof bone.__rest[ax] === 'number') ? bone.__rest[ax] : 0;
          bone.position[ax] = base + cmd.translateUnits[ax];
          void cur;
        }
      }
      if (cmd.rotateDeg) {
        for (const ax of Object.keys(cmd.rotateDeg)) {
          if (!bone.rotation) continue;
          const base = (bone.__restRot && typeof bone.__restRot[ax] === 'number') ? bone.__restRot[ax] : 0;
          bone.rotation[ax] = base + cmd.rotateDeg[ax] * Math.PI / 180;
        }
      }
    }
  }

  function writeMaterials(model, materials) {
    for (const name of Object.keys(materials)) {
      const mat = model.getMaterial(name);
      if (!mat) { warns.push('资产中不存在材质/材质参数 ' + name); continue; }
      const v = materials[name];
      if (v && typeof v === 'object' && v.palette !== undefined) {
        const pal = (o.palettes && o.palettes[name]) || null;
        mat.paletteIndex = v.palette;
        if (pal && pal[v.palette] !== undefined) {
          if (mat.color && typeof mat.color.set === 'function') mat.color.set(pal[v.palette]);
          else mat.color = pal[v.palette];
        }
      } else if (mat.color && typeof mat.color.set === 'function' && typeof v === 'string') {
        mat.color.set(v);
      } else {
        mat[name] = v;
      }
    }
  }

  function writeAssets(model, assets) {
    for (const slot of Object.keys(assets)) {
      const v = assets[slot];
      // 资产槽有两类语义：枚举型（选第几款 → 切 visible）与权重型（0~1 → 交给 setAssetWeight）。
      // 权重型不能当槽位下标用，否则会静默落到 list[0.2] === undefined。
      if (v && typeof v === 'object' && v.weight === true) {
        if (typeof model.setAssetWeight === 'function') model.setAssetWeight(slot, v.value);
        else warns.push('资产权重通道 ' + slot + ' 需要 setAssetWeight，当前模型视图未提供，已跳过');
        continue;
      }
      const option = (v && typeof v === 'object') ? v.option : v;
      const node = model.getAssetNode(slot, option);
      if (!node) { warns.push('资产槽 ' + slot + ' 无可用节点（option=' + option + '）'); continue; }
      if (model.setAssetActive) model.setAssetActive(slot, option);
      else node.visible = option !== 0;
    }
  }

  const applyToModel = (model, cmds) => {
    if (!model) throw new Error('face-adapter: applyToModel 需要模型视图');
    writeMorphs(model, cmds.morphs || {});
    writeBones(model, cmds.bones || {});
    writeMaterials(model, cmds.materials || {});
    writeAssets(model, cmds.assets || {});
    applied += 1;
    lastCommands = cmds;
    return { ok: true, applied, channels: cmds.channels, warnings: cmds.warnings || [] };
  };

  return {
    schema: ADAPTER_SCHEMA,
    applyToModel,
    buildCommands: (table, preset, fp, params, o2) => buildCommands(table, preset, fp, params, o2),
    /** 一步到位：参数 → 指令 → 写进模型 */
    applyParams(model, table, preset, fp, params, o2) {
      const cmds = buildCommands(table, preset, fp, params, o2);
      return applyToModel(model, cmds);
    },
    lastCommands: () => lastCommands,
    stats: () => ({ applied, warnings: warns.length }),
    warnings: () => warns.slice(),
    reset: () => { applied = 0; warns.length = 0; lastCommands = null; },
  };
}

/* ────────────────────── three.js 薄绑定（§7.2 点名的 API） ────────────────────── */

/**
 * 把 three.js 的 Object3D 视图化成适配器认识的 model。
 * 用到的 three.js API（规格书 §7.2 点名）：
 *   SkinnedMesh.skeleton.bones      → 骨骼（按 name 取，不按 index）
 *   Mesh.morphTargetDictionary      → morph 名称 → index
 *   Mesh.morphTargetInfluences      → morph 权重数组
 *   Material.color.set / .roughness → 材质属性（改属性，不重建材质）
 *   Object3D.visible                → 资产槽位切换
 */
export function bindThree(root, opt) {
  const o = opt || {};
  const bones = new Map();
  const meshes = [];
  const materials = new Map();
  const assetNodes = new Map();
  const slotActive = new Map();

  const registry = o.assetRegistry || {};
  for (const slot of Object.keys(registry)) {
    const list = registry[slot] || [];
    assetNodes.set(slot, list);
    list.forEach((n, i) => { if (n) n.visible = (i === 0); });
  }

  const visit = (obj) => {
    if (!obj) return;
    if (obj.isBone) bones.set(obj.name, obj);
    if (obj.isSkinnedMesh && obj.skeleton && Array.isArray(obj.skeleton.bones)) {
      for (const b of obj.skeleton.bones) if (b && b.name) bones.set(b.name, b);
    }
    if (obj.isMesh) meshes.push(obj);
    if (obj.material) {
      const list = Array.isArray(obj.material) ? obj.material : [obj.material];
      for (const m of list) if (m && m.name) materials.set(m.name, m);
    }
    const kids = obj.children || [];
    for (const c of kids) visit(c);
  };
  visit(root);

  const slotOfName = (name) => {
    for (const slot of Object.keys(registry)) {
      const list = registry[slot] || [];
      const i = list.findIndex((n) => n && n.name === name);
      if (i >= 0) return { slot, index: i };
    }
    return null;
  };

  return {
    getBone: (name) => {
      const list = expandBoneAliases(name);
      for (let i = 0; i < list.length; i += 1) {
        const b = bones.get(list[i]);
        if (b) return b;
      }
      return null;
    },
    getMorph: (name) => {
      for (const mesh of meshes) {
        const d = mesh.morphTargetDictionary;
        if (d && Object.prototype.hasOwnProperty.call(d, name)) return { dictionary: d, influences: mesh.morphTargetInfluences };
      }
      return null;
    },
    getMaterial: (name) => materials.get(name) || null,
    getAssetNode: (slot, option) => {
      const list = assetNodes.get(slot);
      if (!list) return null;
      return list[option] || null;
    },
    setAssetActive: (slot, option) => {
      const list = assetNodes.get(slot) || [];
      list.forEach((n, i) => { if (n) n.visible = (i === option); });
      slotActive.set(slot, option);
    },
    stats: () => ({
      bones: bones.size, meshes: meshes.length, materials: materials.size,
      morphNames: meshes.reduce((a, m) => a + (m.morphTargetDictionary ? Object.keys(m.morphTargetDictionary).length : 0), 0),
      slots: assetNodes.size,
    }),
    _slotOfName: slotOfName,
  };
}

export default {
  ADAPTER_SCHEMA, DEFAULT_THROTTLE_HZ, MM_PER_UNIT, UI_COPY, BONE_RULES,
  expandBoneTargets, expandBoneAliases, createThrottle, createEvalCache, buildCommands, createFaceAdapter, bindThree,
};