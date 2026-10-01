/**
 * 康养场景裁剪标注（规格书 §9 / 自检 §10.13）
 * 纯函数、零依赖、无 I/O：对 parameters-table.json 的 102 条参数逐条标注
 * 「保留 / 弱化 / 不做」，必要时给出「保留并强化」与收敛后的滑杆区间。
 *
 * 裁剪原则（来自规格书 §9，可补充、不可反向）：
 *   弱化：面部脂肪、下巴前突、鼻尖上翘、修容/高光强度；眼睛倾斜、外眼角、瞳孔颜色（收敛到自然区间）
 *   保留并强化：年龄感相关（皱纹、白发比例、皮肤质感）、肤色、发型、胡须
 *   不做：战斗/异族妆容、纹身、兽耳、极端体型、伤疤类
 *   默认值红线：一键打开要像「同年龄段的普通人」，不能是网红脸或游戏角色脸
 */

export const TRIM_KEEP = '保留';
export const TRIM_SOFTEN = '弱化';
export const TRIM_DROP = '不做';
export const TRIM_LEGEND = {
  [TRIM_KEEP]: '保留：正常开放，滑杆沿用参数表区间',
  [TRIM_SOFTEN]: '弱化：保留能力但收敛区间，避免「改脸型追审美」或妆容过重的暗示',
  [TRIM_DROP]: '不做：本档不开放（无资产或场景不需要），滑杆隐藏',
};

/** key -> [裁剪, 是否强化, 理由, 收敛后滑杆?] */
const ROWS = {
  face_width: [TRIM_KEEP, 0, '脸宽属自然个体差异，不做极端化'],
  face_length: [TRIM_KEEP, 0, '脸长同属自然骨相差异'],
  cheekbone_height: [TRIM_KEEP, 0, '颧骨高低属自然骨相'],
  cheekbone_width: [TRIM_KEEP, 0, '颧骨宽窄属自然骨相'],
  cheek_fullness: [TRIM_KEEP, 0, '脸颊饱满属自然个体差异'],
  temple_width: [TRIM_KEEP, 0, '太阳穴宽窄属自然骨相'],
  jaw_width: [TRIM_KEEP, 0, '下颌宽窄属自然骨相'],
  jaw_angle: [TRIM_KEEP, 0, '下颌角属自然骨相'],
  chin_length: [TRIM_KEEP, 0, '下巴长度属自然骨相'],
  chin_protrusion: [TRIM_SOFTEN, 0, '规格书点名弱化：下巴前突有「改脸型追审美」的强暗示', '-0.5~+0.5'],
  chin_width: [TRIM_KEEP, 0, '下巴宽窄属自然骨相'],
  chin_cleft: [TRIM_KEEP, 0, '下巴沟为个体特征，不是审美改造项'],
  forehead_height: [TRIM_KEEP, 0, '额头高低属自然骨相'],
  forehead_width: [TRIM_KEEP, 0, '额头宽窄属自然骨相'],
  face_fat: [TRIM_SOFTEN, 0, '规格书点名弱化：面部脂肪', '-0.5~+0.5'],
  neck_thickness: [TRIM_KEEP, 0, '骨骼缩放已内建 ±15% 收敛，不做极端体型'],
  throat: [TRIM_KEEP, 0, '喉结为个体特征，默认 0 不主动造型'],
  brow_shape: [TRIM_KEEP, 0, '眉型属自然个体差异'],
  brow_density: [TRIM_KEEP, 0, '眉毛浓密度为个体差异'],
  brow_height: [TRIM_KEEP, 0, '眉高属自然位置差异'],
  brow_spacing: [TRIM_KEEP, 0, '眉间距属自然位置差异'],
  brow_peak: [TRIM_KEEP, 0, '眉峰高度属自然眉形差异'],
  brow_tail: [TRIM_KEEP, 0, '眉尾长短属自然眉形差异'],
  brow_angle: [TRIM_KEEP, 0, '眉倾斜属自然眉形差异'],
  brow_color: [TRIM_KEEP, 0, '眉色限定在自然色板内'],
  eye_size: [TRIM_KEEP, 0, '眼睛大小属自然五官差异'],
  eye_height: [TRIM_KEEP, 0, '眼睛高低属自然位置差异'],
  eye_width: [TRIM_KEEP, 0, '眼睛宽度属自然五官差异'],
  eye_spacing: [TRIM_KEEP, 0, '眼距为骨骼平移 ±3 mm，已内建收敛'],
  eye_inner_corner: [TRIM_KEEP, 0, '内眼角属自然眼型差异'],
  eye_outer_corner: [TRIM_SOFTEN, 0, '规格书点名弱化：外眼角，保留但收敛到自然区间', '-0.5~+0.5'],
  eye_lid_type: [TRIM_KEEP, 0, '单双眼皮为个体差异，非审美改造'],
  lid_crease_depth: [TRIM_KEEP, 0, '眼皮褶皱深度属自然差异'],
  eye_bag: [TRIM_KEEP, 0, '眼袋与年龄感正相关，老人形象需要'],
  eye_aegyo: [TRIM_SOFTEN, 0, '卧蚕偏年轻化审美，老人形象补充弱化', '0~0.4'],
  eye_socket_depth: [TRIM_KEEP, 0, '眼窝深浅随年龄自然加深，保留'],
  eye_tilt: [TRIM_SOFTEN, 0, '规格书点名弱化：眼睛倾斜，保留但收敛到自然区间', '-0.5~+0.5'],
  pupil_size: [TRIM_KEEP, 0, '瞳孔大小 0~1，属自然生理差异'],
  iris_size: [TRIM_KEEP, 0, '虹膜大小属自然生理差异'],
  pupil_color: [TRIM_SOFTEN, 0, '规格书点名弱化：瞳孔颜色，收敛到自然色板', '自然色板 4 档（去异色）'],
  lash_length: [TRIM_KEEP, 0, '睫毛长度属自然差异'],
  lash_density: [TRIM_KEEP, 0, '睫毛浓密度属自然差异'],
  eye_wetness: [TRIM_KEEP, 0, '眼球湿润度影响「有神」，保留'],
  nose_length: [TRIM_KEEP, 0, '鼻长属自然骨相'],
  nose_bridge_height: [TRIM_KEEP, 0, '鼻梁高度属自然骨相'],
  nose_bridge_width: [TRIM_KEEP, 0, '鼻梁宽度属自然骨相'],
  nose_bridge_curve: [TRIM_KEEP, 0, '鼻梁弧度属自然骨相'],
  nose_tip_size: [TRIM_KEEP, 0, '鼻头大小属自然骨相'],
  nose_tip_upturn: [TRIM_SOFTEN, 0, '规格书点名弱化：鼻尖上翘', '-0.5~+0.5'],
  nostril_width: [TRIM_KEEP, 0, '鼻翼宽度属自然骨相'],
  nostril_height: [TRIM_KEEP, 0, '鼻翼高低属自然骨相'],
  nostril_size: [TRIM_KEEP, 0, '鼻孔大小属自然骨相'],
  nose_root_depth: [TRIM_KEEP, 0, '鼻根深浅属自然骨相'],
  mouth_width: [TRIM_KEEP, 0, '嘴巴宽度属自然五官差异'],
  mouth_height: [TRIM_KEEP, 0, '嘴巴高度属自然五官差异'],
  lip_upper_thickness: [TRIM_KEEP, 0, '上唇厚度属自然五官差异'],
  lip_lower_thickness: [TRIM_KEEP, 0, '下唇厚度属自然五官差异'],
  lip_shape: [TRIM_KEEP, 0, '唇形属自然五官差异'],
  mouth_corner_up: [TRIM_KEEP, 0, '嘴角上扬影响亲和感，保留（老人形象宜略带笑意）'],
  mouth_protrusion: [TRIM_KEEP, 0, '嘴巴前突属自然骨相'],
  philtrum_length: [TRIM_KEEP, 0, '人中长度属自然五官差异'],
  philtrum_depth: [TRIM_KEEP, 0, '人中深浅属自然五官差异'],
  teeth_size: [TRIM_KEEP, 0, '牙齿大小属个体差异'],
  teeth_color: [TRIM_KEEP, 0, '牙齿颜色限定自然白，不做美白色板'],
  lip_color: [TRIM_KEEP, 0, '唇色限定自然粉色板'],
  ear_size: [TRIM_KEEP, 0, '耳朵大小属自然骨相'],
  ear_protrusion: [TRIM_KEEP, 0, '外张角度 ±8 度，已内建收敛'],
  ear_height: [TRIM_KEEP, 0, '耳位高低属自然骨相'],
  ear_lobe_size: [TRIM_KEEP, 0, '耳垂大小属自然骨相'],
  ear_shape: [TRIM_KEEP, 0, '耳廓形状属自然骨相'],
  skin_tone: [TRIM_KEEP, 1, '规格书点名保留并强化：肤色，是「像我爸妈」的关键'],
  skin_texture: [TRIM_KEEP, 1, '规格书点名保留并强化：皮肤质感（要看着舒服，不是磨皮成塑料）'],
  oiliness: [TRIM_SOFTEN, 0, '老年皮肤偏干，油光属反直觉，收敛到低值区间', '0~0.4'],
  forehead_wrinkle: [TRIM_KEEP, 1, '规格书点名保留并强化：皱纹（年龄感核心）'],
  frown_line: [TRIM_KEEP, 1, '规格书点名保留并强化：皱纹（年龄感核心）'],
  nasolabial: [TRIM_KEEP, 1, '规格书点名保留并强化：皱纹（年龄感核心）'],
  crow_feet: [TRIM_KEEP, 1, '规格书点名保留并强化：皱纹（年龄感核心）'],
  mouth_line: [TRIM_KEEP, 1, '规格书点名保留并强化：皱纹（年龄感核心）'],
  neck_wrinkle: [TRIM_KEEP, 1, '规格书点名保留并强化：皱纹（年龄感核心）'],
  age_overall: [TRIM_KEEP, 1, '规格书点名保留并强化：年龄感'],
  age_spot: [TRIM_KEEP, 1, '规格书点名保留并强化：年龄感相关（老年斑）'],
  dark_circle: [TRIM_KEEP, 1, '规格书点名保留并强化：年龄感相关（黑眼圈）'],
  eyeshadow_color: [TRIM_SOFTEN, 0, '不做战斗/异族妆容；仅保留自然色淡妆', '色板 4 档（自然色）'],
  eyeshadow_strength: [TRIM_SOFTEN, 0, '不做战斗/异族妆容；淡妆强度收敛', '0~0.35'],
  eyeliner_width: [TRIM_SOFTEN, 0, '不做战斗/异族妆容；眼线收敛为细线', '0~0.35'],
  eyeliner_color: [TRIM_SOFTEN, 0, '不做战斗/异族妆容；颜色收敛到自然色', '色板 2 档（自然黑/深棕）'],
  blush_color: [TRIM_SOFTEN, 0, '不做战斗/异族妆容；腮红仅自然色', '色板 4 档（自然色）'],
  blush_strength: [TRIM_SOFTEN, 0, '不做战斗/异族妆容；腮红强度收敛', '0~0.35'],
  blush_position: [TRIM_SOFTEN, 0, '不做战斗/异族妆容；位置收敛为苹果肌', '1 档（苹果肌）'],
  contour_strength: [TRIM_SOFTEN, 0, '规格书点名弱化：修容强度', '0~0.3'],
  highlight_strength: [TRIM_SOFTEN, 0, '规格书点名弱化：高光强度', '0~0.3'],
  makeup_preset: [TRIM_SOFTEN, 0, '不做战斗/异族妆容；方案收敛为「不化妆/日常淡妆」', '2 档（不化妆/日常淡妆）'],
  hairstyle: [TRIM_KEEP, 1, '规格书点名保留并强化：发型'],
  hair_color: [TRIM_KEEP, 1, '规格书点名保留并强化：发色'],
  bangs: [TRIM_KEEP, 1, '规格书点名保留并强化：发型相关（刘海）'],
  white_hair_ratio: [TRIM_KEEP, 1, '规格书点名保留并强化：白发比例（规格书键名 hair_gray_ratio 的同义实现）'],
  beard_type: [TRIM_DROP, 0, '本档无胡须资产（0 款）。与规格书「胡须保留并强化」存在张力：建议补齐资产后转为保留'],
  beard_density: [TRIM_DROP, 0, '依赖胡须资产，本档不做'],
  beard_color: [TRIM_DROP, 0, '依赖胡须资产，本档不做'],
  shoulder_width: [TRIM_SOFTEN, 0, '不做极端体型；肩宽收敛，避免体型改造暗示', '-0.4~+0.4'],
  neck_length: [TRIM_KEEP, 0, '脖子长度属自然骨相差异'],
  head_scale: [TRIM_SOFTEN, 0, '不做极端体型；头身比收敛，防止卡通化/大头娃娃', '0.96~1.04'],
};

/** 默认值红线：这些键的默认值必须是「普通人中性值」 */
const NEUTRAL_DEFAULTS = {
  makeup_preset: '不化妆',
  eyeshadow_strength: 0, eyeliner_width: 0, blush_strength: 0, contour_strength: 0, highlight_strength: 0,
  forehead_wrinkle: 0, frown_line: 0, nasolabial: 0, crow_feet: 0, mouth_line: 0, neck_wrinkle: 0,
  age_overall: 0, age_spot: 0, white_hair_ratio: 0, oiliness: null,
};

/**
 * @param {object} table parameters-table.json
 */
export function createCareTrim(table) {
  if (!table || !Array.isArray(table.params)) throw new Error('care-trim: 参数表无效（缺少 params 数组）');
  const schema = table.params.map((p) => {
    const row = ROWS[p.k];
    if (!row) throw new Error('care-trim: 参数 ' + p.k + ' 未标注康养裁剪');
    const [trim, boost, reason, slider] = row;
    return {
      key: p.k, cn: p.cn, zone: p.z, channel: p.ch, type: p.t,
      trim, boost: boost === 1, reason,
      slider: slider || p.rg, sliderTightened: Boolean(slider),
      tableRange: p.rg, default: p.dv,
    };
  });
  const byKey = new Map(schema.map((p) => [p.key, p]));
  for (const k of Object.keys(ROWS)) {
    if (!byKey.has(k)) throw new Error('care-trim: 标注了参数表里不存在的键 ' + k);
  }

  function describeParam(k) { return byKey.get(k) || null; }
  function trimOf(k) { const d = byKey.get(k); return d ? d.trim : null; }
  function pick(f) { return schema.filter(f).map((p) => p.key); }

  function stats() {
    const c = { [TRIM_KEEP]: 0, [TRIM_SOFTEN]: 0, [TRIM_DROP]: 0 };
    for (const p of schema) c[p.trim]++;
    return {
      total: schema.length,
      keep: c[TRIM_KEEP], soften: c[TRIM_SOFTEN], drop: c[TRIM_DROP],
      boost: schema.filter((p) => p.boost).length,
      hidden: c[TRIM_DROP], visible: c[TRIM_KEEP] + c[TRIM_SOFTEN],
      sliderTightened: schema.filter((p) => p.sliderTightened).length,
      open: false,
    };
  }

  function markdownTable() {
    const esc = (s) => String(s).replace(/\|/g, '\\|');
    return schema.map((p) => '| ' + [
      p.zone, p.key, esc(p.cn), p.channel, p.trim + (p.boost ? '（并强化）' : ''),
      esc(p.sliderTightened ? p.slider + ' ← 原 ' + p.tableRange : p.slider),
      esc(p.reason),
    ].join(' | ') + ' |').join('\n');
  }

  return {
    version: table.version || 'unknown',
    paramCount: schema.length,
    schema,
    describeParam, trimOf, listParams: () => schema.map((p) => p.key),
    params: () => schema.slice(),
    boosts: () => pick((p) => p.boost),
    softenedParams: () => pick((p) => p.trim === TRIM_SOFTEN),
    hiddenParams: () => pick((p) => p.trim === TRIM_DROP),
    visibleParams: () => pick((p) => p.trim !== TRIM_DROP),
    keepParams: () => pick((p) => p.trim === TRIM_KEEP),
    neutralDefaults: () => Object.assign({}, NEUTRAL_DEFAULTS),
    stats, markdownTable,
  };
}

export default createCareTrim;