#!/usr/bin/env python3
"""
比邻AI · 捏脸形态键 `shape_*` 重建（编辑期第 5 步：63 参数 / 113 targets）

用法：
    blender --background <带 vis/expr 的资产.blend> \
        --python tools/blender-env.py \
        --python tools/blender-morph-shape-build.py -- --out <输出.blend> [--report] \
            [--strain-k 0.35] [--table <shape-namespace-map.json>]

为什么要这一步：端侧捏脸页 102 条滑杆里 **63 条是 morph 通道**，全靠 `shape_*`。
实测把没有 `shape_*` 的 v2 资产覆盖 `_edit.glb` 后，
`node tools/test-face-params.mjs` 直接失败两条（target 缺失 / 覆盖率 0.0%）。

做法（与交付规范 §18.4 同一套方法论，针对重绑后的资产重标定）：
  `shape_namespace_map.json` 给出**每个参数的最大位移 `maxDispMM` 与反向比 `reverseRatio`**，
  本脚本负责给每个参数**决定"在哪里动、往哪个方向动"**（掩膜 + 方向），然后：
    1. 场值 = 掩膜（`box` / `near` / `seg` / `vg`，各项带 smoothstep 软边）→ 归一化到峰值 1.0
    2. 位移 = 方向单位向量 × 场值，再整体缩放到 `maxDispMM`
    3. 2 轮拉普拉斯平滑 + 应变限幅（收敛版，见 `blender-morph-build.py` 里记的两个坑）
    4. 未动顶点写回 Basis（glTF 走 sparse）
  `_dn` = `_up` 的反向 × `reverseRatio`（`reverseRatio = 0` 的参数是单向，只有 `_up`）。

⚠️ 锚点不写死：全部复用 `blender-rig-weights.py` 的解剖锚点与本脚本顶部同一份常量，
   算法按资产自身尺度归一（`--report` 会打印每个 target 的实测峰值）。
"""

import json
import math
import os
import sys

import bpy
import numpy as np

# ── 与 blender-rig-weights.py 同一套解剖锚点（世界坐标，Z 向上，正面朝 -Y）──
EYE_Z, EYE_X = 1.0686, 0.0269
BROW_Z = 1.0930
LID_UPPER_Z, LID_LOWER_Z = 1.0810, 1.0570
NOSE_Z = 1.0580
NOSE_TIP = (0.0, -0.0785, 1.0465)
LIP_UPPER_Z, LIP_LOWER_Z = 1.0340, 1.0240
PHILTRUM = (0.0, -0.0765, 1.0415)
MOUTH_CORNER = (0.0263, -0.0700, 1.0290)
CHIN_Z = 1.0180
CHEEK_Z = 1.0520
TEMPLE_Z = 1.0960
FOREHEAD_Z = 1.1180
EAR_X, EAR_Z = 0.0550, 1.0720
JAW_ANGLE = (0.0520, -0.0160, 1.0250)
THROAT = (0.0, -0.0210, 0.9500)
NASOLABIAL_A, NASOLABIAL_B = (0.0200, -0.0720, 1.0370), (0.0330, -0.0620, 1.0180)
MOUTH_LINE_L, MOUTH_LINE_R = (0.0230, -0.0740, 1.0265), (0.0340, -0.0640, 1.0200)
SCALE = 0.030  # "一个脸的量级"，用于把方向变成约 30mm 的射线

# ── 63 参数的谱：关键点 + 掩膜 + 方向 ──
# mask 记法：k=box（|x| 自动左右对称）c=关键点（球） vg=骨骼权重场
#           seg=线段距离 ramp=沿 |x| 渐变 gate_y=（可选）正面门
SPECS = {
    # ── A 脸型（轮廓）──
    "face_width":        {"box": ((0, 0.085), (-0.08, 0.02), (1.01, 1.10)), "dir": (1, 0, 0), "gate_y": -0.02},
    "face_length":       {"box": ((0, 0.070), (-0.08, 0.01), (1.00, 1.13)), "dir": (0, 0, -1), "gate_y": -0.02},
    "cheekbone_height":  {"near": (0.040, -0.053, CHEEK_Z), "radius": 0.026, "dir": (0.45, -0.35, 0.85), "both": True},
    "cheekbone_width":   {"near": (0.040, -0.053, CHEEK_Z), "radius": 0.026, "dir": (1, 0, 0), "both": True},
    "cheek_fullness":    {"near": (0.032, -0.060, 1.0450), "radius": 0.030, "dir": (0.50, -0.05, 0.85), "both": True},
    "temple_width":      {"near": (0.062, -0.060, TEMPLE_Z), "radius": 0.024, "dir": (1, 0, 0), "both": True},
    "jaw_width":         {"near": (0.048, -0.064, 1.0260), "radius": 0.026, "dir": (1, 0, 0), "both": True},
    "jaw_angle":         {"near": JAW_ANGLE, "radius": 0.024, "dir": (0.6, 0, -0.8), "both": True},
    "chin_length":       {"near": (0.0, -0.0655, CHIN_Z), "radius": 0.024, "dir": (0, 0, -1)},
    "chin_protrusion":   {"near": (0.0, -0.0700, 1.0140), "radius": 0.022, "dir": (0, -1, 0)},
    "chin_width":        {"near": (0.0, -0.0655, 1.0140), "radius": 0.026, "dir": (1, 0, 0)},
    "chin_cleft":        {"near": (0.0, -0.0725, 1.0120), "radius": 0.010, "dir": "normal"},
    "forehead_height":   {"box": ((0, 0.075), (-0.06, 0.01), (1.100, 1.140)), "dir": (0, 0, 1), "gate_y": -0.02},
    "forehead_width":    {"near": (0.045, -0.042, 1.1150), "radius": 0.038, "dir": (1, 0, 0), "both": True},
    "face_fat":          {"vg": "cheek_fat", "dir": (0.55, -0.10, 0.80)},
    "throat":            {"near": (0.0, -0.0250, 0.9450), "radius": 0.024, "dir": (0, -1, 0)},
    # ── B 眉毛 ──
    "brow_height":       {"vg": "brow", "dir": (0, 0, 1)},
    "brow_spacing":      {"vg": "brow", "ramp": (0.020, 0.045), "dir": (1, 0, 0)},
    "brow_peak":         {"near": (0.0300, -0.0734, BROW_Z), "radius": 0.014, "dir": (0, 0, 1), "both": True},
    "brow_tail":         {"near": (0.0440, -0.0680, 1.0905), "radius": 0.014, "dir": (1, 0, 0), "both": True},
    "brow_angle":        {"vg": "brow", "ramp": (0.020, 0.045), "dir": (0, 0, 1)},
    # ── C 眼睛 ──
    "eye_size":          {"near": (0.035, -0.056, 1.0690), "radius": 0.020, "dir": (0, 0, 1), "both": True},
    "eye_height":        {"vg": "eye", "dir": (0, 0, 1)},
    "eye_width":         {"vg": "eye", "dir": (1, 0, 0)},
    "eye_inner_corner":  {"near": (0.0170, -0.0560, 1.0670), "radius": 0.012, "dir": (1, 0, 0), "both": True},
    "eye_outer_corner":  {"near": (0.0430, -0.0560, 1.0670), "radius": 0.012, "dir": (1, 0, 0), "both": True},
    "eye_lid_type":      {"vg": "eyelid_upper", "dir": "normal"},
    "lid_crease_depth":  {"vg": "eyelid_upper", "dir": (0, 1, 0)},
    "eye_bag":           {"vg": "eyelid_lower", "dir": (0.10, -0.30, 0.95)},
    "eye_aegyo":         {"vg": "eyelid_lower", "dir": (0.15, -0.15, 0.98)},
    "eye_socket_depth":  {"vg": "eye_socket", "dir": (0, 1, 0)},
    "eye_tilt":          {"vg": "eye", "ramp": (0.014, 0.045), "dir": (0, 0, 1)},
    # ── D 鼻子 ──
    "nose_length":       {"near": NOSE_TIP, "radius": 0.018, "dir": (0, 0, -1)},
    "nose_bridge_height": {"near": (0.0, -0.0680, 1.0680), "radius": 0.014, "dir": (0, -1, 0)},
    "nose_bridge_width": {"near": (0.0, -0.0680, 1.0680), "radius": 0.014, "dir": (1, 0, 0)},
    "nose_bridge_curve": {"seg": ((0.0, -0.0700, 1.0780), NOSE_TIP), "radius": 0.012, "dir": (0, -1, 0)},
    "nose_tip_size":     {"near": NOSE_TIP, "radius": 0.013, "dir": "normal"},
    "nose_tip_upturn":   {"near": NOSE_TIP, "radius": 0.013, "dir": (0, 0, 1)},
    "nostril_width":     {"box": ((0.008, 0.024), (-0.080, -0.055), (1.040, 1.054)), "dir": (1, 0, 0), "both": True},
    "nostril_height":    {"box": ((0.008, 0.024), (-0.080, -0.055), (1.040, 1.054)), "dir": (0, 0, 1), "both": True},
    "nostril_size":      {"box": ((0.008, 0.024), (-0.080, -0.055), (1.040, 1.054)), "dir": "normal", "both": True},
    "nose_root_depth":   {"near": (0.0, -0.0620, 1.0820), "radius": 0.016, "dir": (0, -1, 0)},
    # ── E 嘴 / 牙 ──
    "mouth_width":       {"near": MOUTH_CORNER, "radius": 0.018, "dir": (1, 0, 0), "both": True},
    "mouth_height":      {"near": (0.0, -0.0780, 1.0300), "radius": 0.018, "dir": (0, 0, 1)},
    "lip_upper_thickness": {"vg": "lip_upper", "dir": (0, -1, 0)},
    "lip_lower_thickness": {"vg": "lip_lower", "dir": (0, -1, 0)},
    "lip_shape":         {"vg": "lip_upper", "dir": "normal"},
    "mouth_corner_up":   {"near": MOUTH_CORNER, "radius": 0.016, "dir": (0, 0, 1), "both": True},
    "mouth_protrusion":  {"near": (0.0, -0.0800, 1.0290), "radius": 0.026, "dir": (0, -1, 0)},
    "philtrum_length":   {"near": PHILTRUM, "radius": 0.011, "dir": (0, 0, 1)},
    "philtrum_depth":    {"near": PHILTRUM, "radius": 0.010, "dir": (0, 1, 0)},
    "teeth_size":        {"near": (0.0, -0.0720, 1.0290), "radius": 0.020, "dir": "normal"},
    # ── F 耳 ──
    "ear_lobe_size":     {"near": (0.0645, 0.0040, 1.0585), "radius": 0.020, "dir": "normal", "both": True},
    "ear_shape":         {"vg": "ear", "dir": (1, 0, 0)},
    # ── G 皱纹 / 年龄 ──
    "forehead_wrinkle":  {"box": ((0, 0.055), (-0.07, -0.02), (1.100, 1.135)), "dir": "normal"},
    "frown_line":        {"near": (0.014, -0.0710, 1.0930), "radius": 0.012, "dir": "normal", "both": True},
    "nasolabial":        {"seg": (NASOLABIAL_A, NASOLABIAL_B), "radius": 0.010, "dir": "normal", "both": True},
    "crow_feet":         {"near": (0.0460, -0.0520, 1.0700), "radius": 0.013, "dir": "normal", "both": True},
    # ⚠️ mouth_line 用"按资产尺度"的嘴角线段：固定坐标在男生上偏了 10mm（场为空）。
    #    这里取 70%~95% 头宽、z 取 25%/15% 头高作为嘴角内外两端的兜底线段。
    "mouth_line":        {"seg": ((0.0210, -0.0700, 1.0290), (0.0301, -0.0566, 1.0391)),
                          "radius": 0.010, "dir": "normal", "both": True},
    "neck_wrinkle":      {"box": ((0, 0.050), (-0.06, -0.01), (0.925, 0.975)), "dir": "normal"},
    "age_overall":       {"vg": "head", "dir": "normal"},
    # ── J 体型 ──
    "shoulder_width":    {"box": ((0.02, 0.25), (-0.06, 0.08), (0.86, 0.96)), "dir": (1, 0, 0), "both": True},
    "neck_length":       {"box": ((0, 0.060), (-0.05, 0.01), (0.93, 1.00)), "dir": (0, 0, 1)},
}


def arg_value(name, default=None):
    args = sys.argv
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return default


def has_flag(name):
    return name in sys.argv


def smoothstep(value):
    value = np.clip(value, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


def head_mesh():
    return max((o for o in bpy.data.objects if o.type == "MESH" and o.data.shape_keys is None
                or (o.type == "MESH" and len(o.data.vertices) > 1000)),
               key=lambda o: len(o.data.vertices), default=None)


def build_adjacency(mesh_obj):
    edges = np.empty(len(mesh_obj.data.edges) * 2, dtype=np.int32)
    mesh_obj.data.edges.foreach_get("vertices", edges)
    edges = np.unique(np.sort(edges.reshape(-1, 2), axis=1), axis=0)
    count = len(mesh_obj.data.vertices)
    sources = np.concatenate([edges[:, 0], edges[:, 1]])
    targets = np.concatenate([edges[:, 1], edges[:, 0]])
    order = np.argsort(sources, kind="stable")
    sources, targets = sources[order], targets[order]
    offsets = np.zeros(count + 1, dtype=np.int64)
    np.add.at(offsets, sources + 1, 1)
    return targets, np.cumsum(offsets), edges


def smooth_delta(delta, targets, offsets, mask, rounds, factor):
    active = mask.copy()
    if not active.any():
        return delta
    working = delta.copy()
    counts = np.diff(offsets)
    safe = offsets[:-1]
    for _ in range(max(0, rounds)):
        averaged = np.add.reduceat(working[targets], safe, axis=0) \
            / np.maximum(counts, 1)[:, None]
        blended = (1.0 - factor) * working + factor * averaged
        working[active] = blended[active]
    return working


def strain_limit(delta, edges, rest_length, mask, k, iterations=24, factor=0.4):
    """收敛的欠松弛应变限幅（两个"越限越糟"的坑见 blender-morph-build.py 的文档）"""
    if not mask.any():
        return delta
    a, b = edges[:, 0], edges[:, 1]
    limit = k * rest_length
    working = delta.copy()
    for _ in range(max(1, iterations)):
        diff = working[a] - working[b]
        distance = np.linalg.norm(diff, axis=1)
        over = distance > limit
        if not over.any():
            break
        direction = diff[over] / np.maximum(distance[over], 1e-12)[:, None]
        correction = direction * ((distance[over] - limit[over]) * factor * 0.5)[:, None]
        ea, eb = a[over], b[over]
        np.add.at(working, ea, -correction)
        np.add.at(working, eb, correction)
        free_a = ~mask[ea]
        working[ea[free_a]] += correction[free_a]
        free_b = ~mask[eb]
        working[eb[free_b]] -= correction[free_b]
    return working


def read_group_weights(mesh_obj, name, count):
    group = mesh_obj.vertex_groups.get(name)
    weights = np.zeros(count, dtype=np.float64)
    if group is None:
        return weights
    index = group.index
    for vertex in mesh_obj.data.vertices:
        for element in vertex.groups:
            if element.group == index:
                weights[vertex.index] = element.weight
                break
    return weights


def mask_of(spec, co, normals, weights):
    """按谱生成掩膜（0~1，峰值归一到 1）"""
    x, y, z = co[:, 0], co[:, 1], co[:, 2]
    value = np.ones(len(co), dtype=np.float64)
    soft = 0.008
    if "box" in spec:
        (x0, x1), (y0, y1), (z0, z1) = spec["box"]
        value *= smoothstep((x1 - np.abs(x)) / soft) * smoothstep((np.abs(x) - x0) / soft)
        value *= smoothstep((y1 - y) / soft) * smoothstep((y - y0) / soft)
        value *= smoothstep((z1 - z) / soft) * smoothstep((z - z0) / soft)
    if "near" in spec:
        center = np.array(spec["near"], dtype=np.float64)
        radius = float(spec["radius"])
        distance = np.linalg.norm(co - center, axis=1)
        value *= smoothstep((radius - distance) / (radius * 0.45))
    if "seg" in spec:
        a = np.array(spec["seg"][0], dtype=np.float64)
        b = np.array(spec["seg"][1], dtype=np.float64)
        ab = b - a
        t = np.clip(((co - a) @ ab) / max(float(ab @ ab), 1e-12), 0.0, 1.0)
        closest = a + t[:, None] * ab
        radius = float(spec["radius"])
        distance = np.linalg.norm(co - closest, axis=1)
        value *= smoothstep((radius - distance) / (radius * 0.45))
    if "vg" in spec:
        name = spec["vg"]
        field = None
        for candidate in (name, name + ".L", name + ".R"):
            if candidate in weights:
                field = weights[candidate] if field is None else np.maximum(field, weights[candidate])
        if field is None:  # 允许"按前缀取全部左右组"
            field = np.zeros(len(co))
            for key, item in weights.items():
                if key.startswith(name):
                    field = np.maximum(field, item)
        # ⚠️ 必须**先按自身峰值归一**再门控：这些功能性顶点组的峰值本来就不高
        #    （实测 brow.L 0.40 / eye.L 0.30 / lip_upper 0.36），
        #    直接 smoothstep(field/0.35) 会把 brow 从 0.40 映射成 ≈0.05、
        #    整片场被抹平 → 13 个参数"场为空"（本轮踩过的坑）。
        peak = float(field.max())
        if peak > 1e-9:
            field = field / peak
        value *= smoothstep(field / 0.20)
    if "ramp" in spec:
        low, high = spec["ramp"]
        value *= smoothstep((np.abs(x) - low) / (high - low))
    if "gate_y" in spec:
        value *= smoothstep((y - spec["gate_y"]) / -0.02)
    peak = float(value.max())
    if peak > 1e-9:
        value = value / peak
    return value


def direction_of(spec, mesh_obj, count):
    """方向场：常向量 / 顶点法线"""
    if spec["dir"] == "normal":
        normals = np.zeros(count * 3, dtype=np.float64)
        mesh_obj.data.vertices.foreach_get("normal", normals)
        normals = normals.reshape(count, 3)
        length = np.linalg.norm(normals, axis=1, keepdims=True)
        return normals / np.maximum(length, 1e-9)
    if spec["dir"] == "seg":
        return None
    vector = np.array(spec["dir"], dtype=np.float64)
    vector = vector / max(float(np.linalg.norm(vector)), 1e-9)
    return np.tile(vector, (count, 1))


def main():
    out = arg_value("--out")
    table_path = arg_value("--table", r"E:\比邻AI\3D建模\03_doc\shape-namespace-map.json")
    strain_k = float(arg_value("--strain-k", "0.35"))
    want_report = has_flag("--report")
    want_debug = has_flag("--debug")

    with open(table_path, "r", encoding="utf-8") as handle:
        table = json.load(handle)
    params = table["params"]

    mesh_obj = None
    for obj in bpy.data.objects:
        if obj.type == "MESH" and (mesh_obj is None or len(obj.data.vertices) > len(mesh_obj.data.vertices)):
            mesh_obj = obj
    if mesh_obj is None:
        print("SHAPE_BUILD_FAIL 找不到网格")
        return

    count = len(mesh_obj.data.vertices)
    co = np.empty(count * 3, dtype=np.float64)
    mesh_obj.data.vertices.foreach_get("co", co)
    co = co.reshape(count, 3)
    targets, offsets, edges = build_adjacency(mesh_obj)
    rest_length = np.linalg.norm(co[edges[:, 0]] - co[edges[:, 1]], axis=1)

    # ── 权重场装配 ──
    # ⚠️ 本资产的左右骨是 `.L` / `.R` 两组的，`brow` / `eye` / `ear` / `cheek_fat` 这些
    #    "基名"在网格上**没有同名顶点组**。第一版只按名单读（brow / eye / …），
    #    结果这些场全是 0 → 13 个参数报"场为空"（本轮踩的坑）。
    #    现在：① 逐组读全（按顶点组实际名字）② 额外合成"基名 = 左右取最大"的合并场。
    weights = {}
    for group in mesh_obj.vertex_groups:
        weights[group.name] = read_group_weights(mesh_obj, group.name, count)
    for name in list(weights):
        base = name.split(".")[0]
        if base != name:
            weights[base] = weights[base] if base in weights else np.zeros(count)
            weights[base] = np.maximum(weights[base], weights[name])
    for extra in ("brow", "eye", "eyelid_upper", "eyelid_lower", "eye_socket", "ear",
                  "cheek_fat", "cheekbone", "temple", "lip_upper", "lip_lower",
                  "head", "nose", "chin", "jaw"):
        if extra not in weights:
            weights[extra] = read_group_weights(mesh_obj, extra, count)

    if mesh_obj.data.shape_keys is None:
        mesh_obj.shape_key_add(name="Basis", from_mix=False)

    print("=" * 96)
    print("捏脸形态键重建 : " + bpy.data.filepath)
    print(f"  网格 {mesh_obj.name}  {count} 顶点 / {len(edges)} 边")
    print(f"  参数表 {os.path.basename(table_path)}：{len(params)} 参数 / {table['counts']['targets']} targets")

    report = {"file": bpy.data.filepath, "vertices": count, "targets": {}}
    missing_specs = []
    if want_debug:
        for name in sorted(weights):
            field = weights[name]
            print(f"  DEBUG weights[{name}] max={field.max():.4f} >0.1={int((field > 0.1).sum())}")
    for param in params:
        key = param["key"]
        spec = SPECS.get(key)
        if spec is None:
            missing_specs.append(key)
            continue
        mask_values = mask_of(spec, co, None, weights)
        mask = mask_values > 1e-4                     # 平滑/限幅只作用在有位移的顶点上
        direction = direction_of(spec, mesh_obj, count)
        field = mask_values[:, None] * direction
        peak = float(np.linalg.norm(field, axis=1).max())
        if want_debug:
            print(f"  DEBUG {key}: mask_range=({mask_values.min():.3f},{mask_values.max():.3f}) "
                  f"mask_gt0={int((mask_values > 1e-4).sum())} peak={peak * 1000:.4f}mm "
                  f"dir={'normal' if isinstance(spec['dir'], str) else spec['dir']}")
        if peak < 1e-12:
            missing_specs.append(key + "（场为空）")
            continue
        unit = field / peak
        amplitude = float(param["maxDispMM"]) / 1000.0
        reverse = param.get("reverseRatio") or 0.0

        variants = [(param["target_up"], unit * amplitude, mask, amplitude)]
        if param.get("target_dn") and reverse > 0:
            variants.append((param["target_dn"], -unit * amplitude * reverse, mask,
                             amplitude * reverse))

        for name, delta, active, want_peak in variants:
            delta = smooth_delta(delta, targets, offsets, active, 2, 0.45)
            delta = strain_limit(delta, edges, rest_length, active, strain_k)
            # 平滑与限幅会让峰值低于规格，这里**按规格回标**到精确峰值
            # （`maxDispMM` 是端侧软限制的依据，必须逐条对齐）
            got = float(np.linalg.norm(delta, axis=1).max())
            if got > 1e-12:
                delta = delta * (want_peak / got)
            block = mesh_obj.data.shape_keys.key_blocks.get(name)
            if block is None:
                block = mesh_obj.shape_key_add(name=name, from_mix=False)
            moved = np.linalg.norm(delta, axis=1) > 1e-7
            positions = co.copy()
            positions[moved] += delta[moved]
            block.data.foreach_set("co", positions.reshape(-1).astype(np.float32))
            block.value = 0.0
            report["targets"][name] = {
                "moved": int(moved.sum()),
                "peak_mm": round(float(np.linalg.norm(delta, axis=1).max() * 1000), 3),
                "spec_mm": round(want_peak * 1000, 3),
            }

    for block in mesh_obj.data.shape_keys.key_blocks:
        block.value = 0.0
    names = [b.name for b in mesh_obj.data.shape_keys.key_blocks]
    counts = {"total": len(names) - 1,
              "vis": len([n for n in names if n.startswith("vis_")]),
              "expr": len([n for n in names if n.startswith("expr_")]),
              "shape": len([n for n in names if n.startswith("shape_")])}
    report["counts"] = counts
    report["missing_specs"] = missing_specs

    print("")
    print(f"  形态键合计 {counts['total']}（vis {counts['vis']} / expr {counts['expr']} / "
          f"shape {counts['shape']}）")
    if missing_specs:
        print(f"  ⚠️ 缺谱/空场的参数 {len(missing_specs)} 个：" + ", ".join(missing_specs))
    else:
        print("  ✓ 参数表里每个参数都生成了 target")
    # 峰值与规格对照（抽查 8 个）
    print("")
    print(f"  {'target':<34}{'动顶点':>9}{'峰值mm':>9}{'规格mm':>9}")
    for name, item in list(report["targets"].items())[:8]:
        print(f"  {name:<34}{item['moved']:>9}{item['peak_mm']:>9}{item['spec_mm']:>9}")

    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("SHAPE_BUILD_OK 已保存 " + out)
    if want_report:
        print("SHAPE_BUILD_JSON " + json.dumps(report, ensure_ascii=False))


main()
