#!/usr/bin/env python3
"""
比邻AI · 面部骨骼权重（第 2 步：骨相骨骼 → 蒙皮）

用法：
    blender --background <工作.blend> --python tools/blender-env.py \
        --python tools/blender-rig-weights.py -- \
        --out <输出.blend> [--mode analytic|heat|hybrid] [--rounds 3] \
        [--max-influences 4] [--structural-share 0.30] [--report] \
        [--hair-rounds 2] [--hair-factor 0.5] [--hair-hard-level 0.6] [--no-hair-relax]

方法论位置：骨相骨骼（第 1 步，已完成）→ **权重（本脚本）** → 皮相 blendshape → RBF → 质检

三种模式（实测对比后的结论）：
  · `--dark-threshold`：头发遮罩的 albedo 亮度阈值（**按资产标定**：女生 0.16 / 男生 0.09）。
    实测教训：固定 0.16 用在男生身上会把 **76%** 的贴图判成头发（他的贴图整体偏暗、
    块中位 0.12~0.14），结果全部顶点只有 root 有权重。
  · `heat`    —— 全部机能骨用 Blender bone heat。**实测不可用**：这个资产是"全身封闭壳 +
                头发大块 + 口腔薄腔"，bone heat 会把 `jaw`/`tongue`/`neck` 的权重糊到
                相邻表面上（实测相邻两顶点一组是 head+neck、另一组是 jaw+tongue，各 ~0.35），
                下颌转 20° 时嘴周爆出成片尖刺（`_rig_work/pose-jaw-front.png`）。
  · `analytic`（默认）—— 全部骨骼用**解析场**：按解剖锚点定义平滑的区域场
                （高斯团 + 竖直/横向带 + 正面门），天然连续、可控、可复现。
  · `hybrid`  —— 机能骨用解析场，骨相骨用解析场（等价 analytic；保留作对比开关）。

三个必须处理的问题（否则权重看着"对"、一动就烂）：
  1. **头发必须排除**：头发是独立大块，用贴图亮度做遮罩（albedo 近黑 = 头发）。
     只保留**大连通域**，这样画在脸上的**眉毛/睫毛**（也是黑的）不会被误判。
  2. **但遮罩不能是布尔**（本轮实测的根因）：头发壳与头皮/耳根只差 0.3~0.6mm，
     布尔遮罩会让贴在一起的两个顶点场值 1.0 vs 0.0，而网格平滑是沿**拓扑边**走的
     （两片壳之间没有边）→ 平滑扩散不进去 → `jaw` 20.6×、`ear.L` 13.9× 的硬边。
     现在改成"沿拓扑边扩散成连续遮罩"（`soft_hair_mask`，`--hair-rounds/--hair-factor`）。
     ⚠️ 不要用"到最近头发的三维距离"来做（第一版就是这么做，实测把躯干/脖子全判成
     "非皮肤"，`jaw`/`lip_*`/`chin`/`nose` 的顶点数全部掉到 0）。
  3. **名额分配**：bone heat/解析场都可能在一行里留下 5+ 个骨头，
     截断到 4 骨时必须让**骨相骨也拿到名额**（实测：不预留就全被挤成 0 权重）。
"""

import json
import math
import os
import sys

import bpy
import numpy as np

# ── 解剖锚点（世界坐标，Z 向上，正面朝 -Y）——全部来自第 1 步的锚点表 ──
EYE_Z = 1.0686
EYE_X = 0.0269
BROW_Z = 1.0930
LID_UPPER_Z = 1.0810
LID_LOWER_Z = 1.0570
NOSE_Z = 1.0580
LIP_UPPER_Z = 1.0340
LIP_LOWER_Z = 1.0240
CHIN_Z = 1.0180
JAW_TOP_Z = 1.0620
CHEEK_Z = 1.0520
TEMPLE_Z = 1.0960
FOREHEAD_Z = 1.1180
EAR_X, EAR_Z = 0.0550, 1.0720
NECK_LOW_Z, NECK_HIGH_Z = 0.895, 0.995


def arg_value(name, default=None):
    args = sys.argv
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return default


def has_flag(name):
    return name in sys.argv


def head_mesh():
    return max((o for o in bpy.data.objects if o.type == "MESH"),
               key=lambda o: len(o.data.vertices), default=None)


def armature_object():
    return next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)


def smoothstep(value):
    value = np.clip(value, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


def blob(coords, cx, cz, rx, rz, rx_z=None):
    """平面高斯团（(x,z) 上的椭圆），返回 0~1"""
    dx = (coords[:, 0] - cx) / rx
    dz = (coords[:, 2] - cz) / (rz if rx_z is None else rx_z)
    return np.exp(-(dx * dx + dz * dz) * 1.6)


def front_gate(coords, y_max, softness=0.02):
    """正面门：y < y_max 的区域才有权重（避免权重跑到后脑/头发背面）"""
    return smoothstep((y_max - coords[:, 1]) / softness)


def side_gate(coords, x_min):
    return smoothstep((np.abs(coords[:, 0]) - x_min) / 0.012)


def hair_mask(mesh_obj, dark_threshold=0.16, min_component_share=0.02, sample=1024):
    """用 albedo 亮度识别头发：只保留**大连通域**，脸上的眉毛/睫毛（同样黑）不会被误判"""
    material = None
    for slot in mesh_obj.data.materials:
        if slot is not None and slot.use_nodes:
            material = slot
            break
    if material is None:
        return None, "无材质"
    image = None
    for node in material.node_tree.nodes:
        if node.type == "TEX_IMAGE" and node.image is not None:
            image = node.image
            break
    if image is None:
        return None, "材质里没有贴图节点"
    working = image.copy()
    working.scale(sample, sample)
    pixels = np.empty(sample * sample * 4, dtype=np.float32)
    working.pixels.foreach_get(pixels)
    brightness = pixels.reshape(sample, sample, 4)[:, :, :3].max(axis=2)
    dark = brightness < dark_threshold

    # 连通域（4 邻域），只保留占比足够大的域 = 头发
    labels = np.zeros(dark.shape, dtype=np.int32)
    sizes = [0]
    current = 0
    height, width = dark.shape
    for start_y in range(height):
        row = dark[start_y]
        for start_x in range(width):
            if not row[start_x] or labels[start_y, start_x]:
                continue
            current += 1
            stack = [(start_y, start_x)]
            labels[start_y, start_x] = current
            count = 0
            while stack:
                y, x = stack.pop()
                count += 1
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < height and 0 <= nx < width:
                        if dark[ny, nx] and not labels[ny, nx]:
                            labels[ny, nx] = current
                            stack.append((ny, nx))
            sizes.append(count)
    total = float(sample * sample)
    keep = {index for index, size in enumerate(sizes)
            if index > 0 and size / total >= min_component_share}
    mask_image = np.isin(labels, list(keep)) if keep else np.zeros_like(dark)

    # 采样到顶点
    # ⚠️ UV 是按 **loop**（面角）存的：本资产 999,062 loop vs 499,531 顶点，
    #    直接 foreach_get 到"顶点数"长度的数组会报「阵列长度不匹配」。
    #    这里取每个顶点**第一次出现**的那个 loop 的 UV（顶点在 UV 缝上会被拆开，
    #    取任一侧即可，因为头发/皮肤的判定在缝两侧一致）。
    uv_layer = mesh_obj.data.uv_layers.active
    if uv_layer is None:
        bpy.data.images.remove(working)
        return None, "没有 UV"
    count = len(mesh_obj.data.vertices)
    loop_uvs = np.empty(len(mesh_obj.data.loops) * 2, dtype=np.float32)
    uv_layer.data.foreach_get("uv", loop_uvs)
    loop_uvs = loop_uvs.reshape(-1, 2)
    loops_vertex = np.empty(len(mesh_obj.data.loops), dtype=np.int32)
    mesh_obj.data.loops.foreach_get("vertex_index", loops_vertex)
    unique_vertices, first_loop = np.unique(loops_vertex, return_index=True)
    vertex_uv = np.zeros((count, 2), dtype=np.float32)
    vertex_uv[unique_vertices] = loop_uvs[first_loop]
    px = np.clip((vertex_uv[:, 0] % 1.0) * (sample - 1), 0, sample - 1).astype(np.int32)
    py = np.clip((vertex_uv[:, 1] % 1.0) * (sample - 1), 0, sample - 1).astype(np.int32)
    vertex_mask = mask_image[py, px]
    bpy.data.images.remove(working)
    return vertex_mask, f"头发顶点 {int(vertex_mask.sum())} / {count}（域 {len(keep)} 个）"


def soft_hair_mask(mesh_obj, coords, vertex_hair, rounds=2, factor=0.5,
                   hard_level=0.6, verbose=True):
    """把布尔头发遮罩沿**拓扑边**扩散成连续场，返回 (soft 遮罩, hard 遮罩)

    为什么必须扩散（本轮实测的根因，别再退回布尔遮罩）：
      这个资产里**头发壳与头皮/耳根是两片平行表面，空间只差 0.3~0.6mm**
      （`tools/blender-weight-source.py` 实测：耳根 x≈0.0605~0.0625 之间相邻顶点
      一个判成头发、一个判成皮肤，交替出现）。布尔遮罩让贴在一起的两个顶点
      拿到 1.0 与 0.0 两种场值，而权重平滑是沿**拓扑边**扩散的
      （两片壳之间没有边）→ 平滑扩散不进去 → 权重留下"0.5mm 内差 0.35"的硬边：
        · `ear.L` 12° 时 13.9× 拉伸（0.43mm 的边上 Δw 0.33）
        · `jaw` 20° 时 20.6× 拉伸（0.32mm 的边上 Δw 0.13）
      —— 这才是 §8.7.3 里"jaw 20.6×、ear 13.9×"的真正成因，**不是场的公式写错**。

    ⚠️ 不能用"到最近头发的三维距离"来做这件事（第一版就是这么做，实测失败）：
      头发只长在头上，**躯干离头发 20cm**，距离场会把整条脖子/下巴判成"非皮肤"
      → `jaw`/`lip_*`/`chin`/`nose` 的顶点数全部掉到 0（日志里那排 "⚠️ 无权重"）。
      所以扩散必须**沿拓扑边**（只在真正贴着头发的那几圈顶点上起作用）。

    `hard_level`：hard 遮罩 = `soft < hard_level 归零`，用于骨相骨（避免半个头发
    跟着 `face_width` / `temple` 一起横向位移）。
    """
    count = len(coords)
    hair_values = vertex_hair.astype(np.float64)
    targets, offsets = build_adjacency(mesh_obj)
    soft = hair_values.copy()
    for _ in range(max(0, rounds)):
        soft = smooth_once(soft, targets, offsets, factor)
    hard = np.where(soft >= hard_level, 1.0, 0.0)
    if verbose:
        touched = int(((soft > 1e-6) & (~vertex_hair)).sum())
        print(f"  头发遮罩软扩散：{rounds} 轮 × α{factor}（沿拓扑边）；"
              f"被染上遮罩的皮肤顶点 {touched}；hard 保留 {int(hard.sum())} / "
              f"{int(vertex_hair.sum())}")
    return soft, hard


def analytic_fields(coords, vertex_hair, hair_soft=None):
    """全部 33 骨的解析权重场；返回 {骨名: np.ndarray(顶点数)}（未归一化，0~1）

    `vertex_hair` 是原布尔遮罩（用于骨相骨的 hard 门）；
    `hair_soft` 是沿拓扑边扩散后的连续遮罩（0 = 纯皮肤、1 = 在头发里），
    机能骨场按它软门控，避免头皮/耳根处"0.5mm 落差"。
    """
    x = coords[:, 0]
    z = coords[:, 2]
    if hair_soft is None:
        skin = (~vertex_hair).astype(np.float64)
        skin_hard = skin
    else:
        hair_soft = np.clip(hair_soft, 0.0, 1.0)
        skin = 1.0 - hair_soft
        # 骨相骨用"硬门"：软遮罩超过 0.6 就算头发（否则半个头发会跟着轮廓骨位移）
        skin_hard = np.where(hair_soft >= 0.6, 0.0, 1.0)
    fields = {}

    # ── 竖向三分：root / neck / head ──
    head_zone = smoothstep((z - NECK_LOW_Z) / (NECK_HIGH_Z - NECK_LOW_Z))
    neck_band = smoothstep((z - (NECK_LOW_Z - 0.04)) / 0.06)
    fields["head"] = head_zone
    fields["neck"] = neck_band * (1.0 - head_zone)
    fields["root"] = np.clip(1.0 - head_zone - fields["neck"], 0, 1)

    face_front = front_gate(coords, -0.005, 0.03)     # 只在正面半边生效
    face = face_front * skin * head_zone
    # 骨相骨单独用"硬门"：软遮罩 ≥0.6 的一律算头发，避免半个头发跟着轮廓骨横向位移
    face_hard = face_front * skin_hard * head_zone

    # ── 机能骨 ──
    # ⚠️ `jaw` 必须有**下界**：只写 smoothstep((JAW_TOP_Z - z)/0.030) 会让下颌场一直罩到脖子上，
    #    实测最差边因此落在 z≈1.00、下巴正下方（一个顶点 jaw 0.73、邻居 head 0.68），
    #    下颌转 20° 就撕出 14× 拉伸。下颌区的正确范围是 z ∈ [1.002, 1.062]。
    jaw_band = smoothstep((JAW_TOP_Z - z) / 0.028) * smoothstep((z - 1.002) / 0.018)
    fields["jaw"] = face * jaw_band * smoothstep((0.085 - np.abs(x)) / 0.02)
    fields["chin"] = (face * blob(coords, 0.0, CHIN_Z, 0.030, 0.018)
                      * front_gate(coords, -0.045) * smoothstep((z - 1.002) / 0.014))
    fields["nose"] = face * blob(coords, 0.0, NOSE_Z, 0.017, 0.022) * front_gate(coords, -0.050)
    fields["lip_upper"] = face * blob(coords, 0.0, LIP_UPPER_Z, 0.024, 0.009)
    fields["lip_lower"] = face * blob(coords, 0.0, LIP_LOWER_Z, 0.024, 0.009)
    fields["tongue"] = np.zeros_like(z)               # 原始资产没有舌网格
    for side, sign in (("L", 1.0), ("R", -1.0)):
        fields[f"eye.{side}"] = face * blob(coords, EYE_X * sign, EYE_Z, 0.013, 0.011)
        fields[f"eyelid_upper.{side}"] = face * blob(coords, EYE_X * sign, LID_UPPER_Z, 0.016, 0.007)
        fields[f"eyelid_lower.{side}"] = face * blob(coords, EYE_X * sign, LID_LOWER_Z, 0.016, 0.007)
        fields[f"brow.{side}"] = face * blob(coords, EYE_X * sign * 1.06, BROW_Z, 0.021, 0.008)
        fields[f"ear.{side}"] = (head_zone * skin
                                 * blob(coords, EAR_X * sign, EAR_Z, 0.022, 0.022)
                                 * smoothstep((np.abs(x) - 0.038) / 0.012))

    # ── 骨相骨（粗轮廓捏脸）：范围收紧，避免像 bone heat 那样糊到躯干/头发 ──
    lateral_band = face_hard * smoothstep((np.abs(x) - 0.008) / 0.012)
    fields["face_width"] = (face_hard * np.exp(-(((z - 1.055) / 0.045) ** 2) * 1.4)
                            * smoothstep((np.abs(x) - 0.010) / 0.015))
    fields["face_length"] = face_hard * blob(coords, 0.0, 1.058, 0.045, 0.030)
    fields["forehead_height"] = face_hard * blob(coords, 0.0, FOREHEAD_Z, 0.050, 0.030)
    fields["forehead_width"] = (face_hard * np.exp(-(((z - 1.120) / 0.035) ** 2) * 1.4)
                                * smoothstep((np.abs(x) - 0.010) / 0.015))
    for side, sign in (("L", 1.0), ("R", -1.0)):
        fields[f"cheekbone.{side}"] = face_hard * blob(coords, 0.040 * sign, CHEEK_Z, 0.024, 0.020)
        fields[f"temple.{side}"] = lateral_band * blob(coords, 0.062 * sign, TEMPLE_Z, 0.022, 0.022)
        fields[f"jaw_width.{side}"] = face_hard * blob(coords, 0.048 * sign, 1.026, 0.024, 0.018)
        fields[f"cheek_fat.{side}"] = face_hard * blob(coords, 0.032 * sign, 1.045, 0.028, 0.022)
        fields[f"eye_socket.{side}"] = face_hard * blob(coords, EYE_X * sign, EYE_Z, 0.017, 0.013)
    return fields


def combine_fields(fields, group_names, structural_names):
    """把各骨的场整理成"机能骨矩阵 + 骨相骨矩阵"，并做一次归一化前的裁剪"""
    count = len(next(iter(fields.values())))
    functional_names = [name for name in group_names if name not in structural_names]
    functional = np.zeros((count, len(functional_names)), dtype=np.float64)
    structural = np.zeros((count, len(structural_names)), dtype=np.float64)
    for index, name in enumerate(functional_names):
        if name in fields and name not in ("root", "neck", "head"):
            functional[:, index] = fields[name]
    # 面部各骨从 head 里"借"权重：head 的剩余量 = 1 - 各面骨之和（下限 0）
    borrowed = np.clip(functional.sum(axis=1), 0.0, 1.0)
    for index, name in enumerate(functional_names):
        if name == "head":
            functional[:, index] = fields["head"] * (1.0 - borrowed)
        elif name in ("root", "neck"):
            functional[:, index] = fields[name]
    for index, name in enumerate(structural_names):
        if name in fields:
            structural[:, index] = fields[name]
    return functional, structural


def keep_top(matrix, count):
    if matrix.shape[1] <= count:
        return matrix
    keep = np.argsort(-matrix, axis=1)[:, :count]
    mask = np.zeros_like(matrix, dtype=bool)
    rows = np.arange(matrix.shape[0])[:, None]
    mask[rows, keep] = True
    return np.where(mask, matrix, 0.0)


def normalize(matrix):
    sums = matrix.sum(axis=1)
    sums[sums < 1e-9] = 1.0
    return matrix / sums[:, None]


def build_adjacency(mesh_obj):
    edges = np.empty(len(mesh_obj.data.edges) * 2, dtype=np.int32)
    mesh_obj.data.edges.foreach_get("vertices", edges)
    edges = edges.reshape(-1, 2)
    count = len(mesh_obj.data.vertices)
    sources = np.concatenate([edges[:, 0], edges[:, 1]])
    targets = np.concatenate([edges[:, 1], edges[:, 0]])
    order = np.argsort(sources, kind="stable")
    sources, targets = sources[order], targets[order]
    offsets = np.zeros(count + 1, dtype=np.int64)
    np.add.at(offsets, sources + 1, 1)
    offsets = np.cumsum(offsets)
    return targets, offsets


def smooth_once(matrix, targets, offsets, factor):
    """沿拓扑边做一次邻域平均（矩阵版；任意列数）

    ⚠️ 旧版是 `for row in range(499531)` 的 Python 循环（一次 30~60s，
    本脚本要跑几十次）。现在用 `np.add.reduceat` 在排序好的邻接表上一次性求和，
    再除以度数——同样的结果，快两个数量级。
    """
    was_flat = matrix.ndim == 1
    if was_flat:
        matrix = matrix[:, None]
    counts = np.diff(offsets)
    safe = offsets[:-1]
    sums = np.add.reduceat(matrix[targets], safe, axis=0)
    divisor = np.maximum(counts, 1).astype(matrix.dtype)
    averaged = sums / divisor[:, None]
    empty = counts == 0
    blended = (1.0 - factor) * matrix + factor * averaged
    blended[empty] = matrix[empty]
    return blended[:, 0] if was_flat else blended


def solve_weights(functional, structural, share, max_influences, targets, offsets,
                  rounds, factor):
    """先按名额合成，再交替"平滑 ↔ 截断到 N 骨"

    为什么必须交替：bone heat/解析场都可能让**相邻两顶点落到完全不同的骨对**上
    （实测：一组 head+neck、另一组 jaw+tongue，各 ~0.35）→ 一下颌就撕出尖刺。
    只截断不平滑会固化这种跳变；只平滑不截断又会超过 4 骨上限。
    交替做即可同时满足"连续"与"≤4 骨"。
    """
    slots = 2 if max_influences >= 4 else 1
    total = max_influences
    matrix = np.concatenate([functional, structural], axis=1)
    matrix = normalize(np.where(matrix < 0.02, 0.0, matrix))
    for _ in range(max(1, rounds)):
        matrix = normalize(keep_top(matrix, total))
        matrix = smooth_once(matrix, targets, offsets, factor)
    matrix = normalize(keep_top(matrix, total))
    # 骨相骨的名额兜底：若某顶点骨相骨全被挤掉，用最强的骨相骨替掉**最弱的非零机能骨**
    functional_part = matrix[:, :functional.shape[1]]
    structural_part = matrix[:, functional.shape[1]:]
    lost = (structural_part.sum(axis=1) < 1e-9) & (structural.sum(axis=1) >= 0.25)
    if lost.any():
        best_structural = np.argmax(np.where(structural < 0.03, 0.0, structural), axis=1)
        masked = np.where(functional_part > 1e-9, functional_part, np.inf)
        weakest = np.argmin(masked, axis=1)
        rows = np.nonzero(lost)[0]
        functional_part[rows, weakest[rows]] = 0.0
        for row in rows:
            structural_part[row, best_structural[row]] = share
        matrix = np.concatenate([functional_part, structural_part], axis=1)
    # 最后再截断一次，保证"兜底"不会把影响数顶到 4 以上
    return normalize(keep_top(matrix, total))


def report_matrix(group_names, matrix):
    sums = matrix.sum(axis=1)
    nonzero = (matrix > 1e-5).sum(axis=1)
    per_bone = {}
    for index, name in enumerate(group_names):
        column = matrix[:, index]
        per_bone[name] = {"verts": int((column > 1e-5).sum()),
                          "strong": int((column > 0.5).sum()),
                          "max": round(float(column.max()), 4)}
    return {
        "vertices": int(matrix.shape[0]), "groups": len(group_names),
        "weight_sum": {"min": round(float(sums.min()), 5), "max": round(float(sums.max()), 5),
                       "bad": int((np.abs(sums - 1.0) > 1e-3).sum())},
        "influences": {"max": int(nonzero.max()), "mean": round(float(nonzero.mean()), 2),
                       "over_limit": int((nonzero > 4).sum())},
        "per_bone": per_bone,
    }


def edge_gradient_report(group_names, matrix, edges, coords, min_edge_mm=0.3):
    """每根骨"沿边的权重梯度"（单位：每毫米 Δw）

    这是本轮的**核心判据**：拉伸比 ≈ 1 + Δw × (骨端位移 / 边长)，
    所以只要把"每毫米 Δw"压下来，拉伸自然下来——比"事后多平滑几轮"更根本
    （§8.8 记的"数值残差被 normalize 放大"是同族问题）。
    只统计原长 > `min_edge_mm` 的边（与 `blender-bone-audit.py` 的"有效边"同口径）。
    """
    length_mm = np.linalg.norm(coords[edges[:, 0]] - coords[edges[:, 1]], axis=1) * 1000.0
    valid = length_mm > min_edge_mm
    report = {}
    for index, name in enumerate(group_names):
        column = matrix[:, index]
        delta = np.abs(column[edges[:, 0]] - column[edges[:, 1]])
        if not valid.any():
            report[name] = {"max_per_mm": 0.0, "p999_per_mm": 0.0, "max_delta": 0.0}
            continue
        gradient = delta[valid] / length_mm[valid]
        report[name] = {
            "max_per_mm": round(float(gradient.max()), 4),
            "p999_per_mm": round(float(np.percentile(gradient, 99.9)), 4),
            "max_delta": round(float(delta[valid].max()), 4),
        }
    return report



def write_matrix(mesh_obj, group_names, matrix, levels=2000):
    """按权重分桶批量写回：调用数从 200 万降到 3 万（量化误差 ≤ 0.05%）"""
    all_indices = list(range(matrix.shape[0]))
    for name in group_names:
        if mesh_obj.vertex_groups.get(name) is None:
            mesh_obj.vertex_groups.new(name=name)
    for index, name in enumerate(group_names):
        group = mesh_obj.vertex_groups[name]
        group.remove(all_indices)
        column = matrix[:, index]
        quantized = np.rint(column * levels).astype(np.int32)
        quantized[column <= 1e-5] = 0
        for level in np.unique(quantized):
            if level <= 0:
                continue
            selected = np.nonzero(quantized == level)[0]
            group.add(selected.tolist(), float(level) / levels, "REPLACE")


def bind_armature(mesh_obj, armature):
    """建立蒙皮绑定：父级 + Armature 修改器

    ⚠️ 解析场模式**不会**自动有这个（`parent_set(ARMATURE_AUTO)` 才会顺手加），
    漏掉的话顶点组都在、权重也对，但一摆姿态**整个网格纹丝不动**
    （实测：审计里所有骨"动顶点 = 0、拉伸 = 1.0"，看着像"完美通过"，其实是没绑上）。
    """
    mesh_obj.parent = armature
    mesh_obj.matrix_parent_inverse = armature.matrix_world.inverted()
    modifier = mesh_obj.modifiers.get("Armature")
    if modifier is None:
        modifier = mesh_obj.modifiers.new("Armature", "ARMATURE")
    modifier.object = armature
    modifier.use_vertex_groups = True
    return [m.type for m in mesh_obj.modifiers]


def main():
    out = arg_value("--out")
    mode = arg_value("--mode", "analytic")
    rounds = int(arg_value("--rounds", "3"))
    smooth_factor = float(arg_value("--smooth-factor", "0.55"))
    max_influences = int(arg_value("--max-influences", "4"))
    share = float(arg_value("--structural-share", "0.30"))
    hair_rounds = int(arg_value("--hair-rounds", "2"))
    hair_factor = float(arg_value("--hair-factor", "0.5"))
    hair_hard_level = float(arg_value("--hair-hard-level", "0.6"))
    dark_threshold = float(arg_value("--dark-threshold", "0.16"))
    no_hair_relax = has_flag("--no-hair-relax")
    want_report = has_flag("--report")
    want_gradient = not has_flag("--no-gradient")
    worst_bones = (arg_value("--worst-bones") or "jaw,ear.L,ear.R,lip_lower,lip_upper,head,neck")
    worst_bones = [name for name in worst_bones.split(",") if name]

    import time
    started = time.time()
    mesh_obj = head_mesh()
    armature = armature_object()
    if mesh_obj is None or armature is None:
        print("RIG_WEIGHTS_FAIL 缺少网格或骨架")
        return

    bones = [bone.name for bone in armature.data.bones]
    structural_names = [name for name in bones
                        if name in ("face_width", "face_length", "forehead_height",
                                    "forehead_width") or name.startswith(
                            ("cheekbone", "temple", "jaw_width", "cheek_fat", "eye_socket"))]
    group_names = [name for name in bones if name != "root"] + ["root"]
    for name in group_names:
        if mesh_obj.vertex_groups.get(name) is None:
            mesh_obj.vertex_groups.new(name=name)
    group_names = [group.name for group in mesh_obj.vertex_groups]

    count = len(mesh_obj.data.vertices)
    coord_buffer = np.empty(count * 3, dtype=np.float64)
    mesh_obj.data.vertices.foreach_get("co", coord_buffer)
    coords = coord_buffer.reshape(count, 3)

    report = {"file": bpy.data.filepath, "mesh": mesh_obj.name, "mode": mode,
              "vertices": count, "groups": len(group_names),
              "structural_bones": structural_names}

    if has_flag("--no-hair-mask"):
        vertex_hair, hair_note = None, "已关闭（--no-hair-mask）"
    else:
        vertex_hair, hair_note = hair_mask(mesh_obj, dark_threshold=dark_threshold)
    report["hair_mask"] = hair_note
    if vertex_hair is None:
        vertex_hair = np.zeros(count, dtype=bool)
    # 布尔遮罩 → 沿拓扑边扩散的连续遮罩（见 soft_hair_mask 的文档：
    # 这是 jaw/ear 硬边的真正成因，别再退回布尔遮罩）
    if no_hair_relax:
        hair_soft = None
        report["hair_soft"] = "关闭（--no-hair-relax）"
    else:
        hair_soft, hair_hard = soft_hair_mask(
            mesh_obj, coords, vertex_hair, rounds=hair_rounds, factor=hair_factor,
            hard_level=hair_hard_level)
        report["hair_soft"] = {"rounds": hair_rounds, "factor": hair_factor,
                              "hard_level": hair_hard_level}
    fields = analytic_fields(coords, vertex_hair, hair_soft)
    report["field_bones"] = len(fields)
    functional, structural = combine_fields(fields, group_names, structural_names)
    report["field_seconds"] = round(time.time() - started, 1)

    targets, offsets = build_adjacency(mesh_obj)
    matrix = solve_weights(functional, structural, share, max_influences,
                           targets, offsets, rounds, smooth_factor)
    report["solve_seconds"] = round(time.time() - started, 1)

    # 名字顺序对齐：solve_weights 返回 [机能骨…, 骨相骨…]
    functional_names = [name for name in group_names if name not in structural_names]
    ordered = functional_names + structural_names
    index_of_new = {name: i for i, name in enumerate(ordered)}
    final = np.zeros((count, len(group_names)), dtype=np.float64)
    for index, name in enumerate(group_names):
        final[:, index] = matrix[:, index_of_new[name]]
    report["stats"] = report_matrix(group_names, final)

    edges = np.empty(len(mesh_obj.data.edges) * 2, dtype=np.int32)
    mesh_obj.data.edges.foreach_get("vertices", edges)
    edges = edges.reshape(-1, 2)
    if want_gradient:
        report["edge_gradient"] = edge_gradient_report(group_names, final, edges, coords)

    if out:
        write_matrix(mesh_obj, group_names, final)
        report["modifiers"] = bind_armature(mesh_obj, armature)
        report["write_seconds"] = round(time.time() - started, 1)
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)

    print("=" * 96)
    print("面部权重 : " + bpy.data.filepath + f"   模式 {mode}")
    print(f"  网格 {mesh_obj.name}（{count} 顶点）× {len(group_names)} 组")
    print(f"  头发遮罩：{hair_note}")
    if not no_hair_relax:
        print(f"  头发软边界：沿拓扑边扩散 {hair_rounds} 轮 × α{hair_factor}"
              f"（骨相骨用 hard 门 ≥ {hair_hard_level}）")
    print(f"  解析场：{len(fields)} 根骨；解算 {rounds} 轮「平滑↔截断到 "
          f"{max_influences} 骨」；骨相骨占比 {share}")
    stats = report["stats"]
    print(f"  权重和：min {stats['weight_sum']['min']} / max {stats['weight_sum']['max']}"
          f"  异常顶点 {stats['weight_sum']['bad']}")
    print(f"  影响数：max {stats['influences']['max']} / 平均 {stats['influences']['mean']}"
          f"  超限 {stats['influences']['over_limit']}")
    print("  逐骨（verts / >0.5 / max）：")
    for name, item in stats["per_bone"].items():
        flag = "" if item["verts"] else "   ← ⚠️ 无权重"
        print(f"    {name:<20} {item['verts']:>7} {item['strong']:>7} {item['max']:>7}{flag}")
    if want_gradient:
        print("")
        print(f"  沿边权重梯度（Δw/mm，只算原长 > 0.3mm 的边）—— 拉伸比的直接驱动量：")
        print(f"    {'骨':<20}{'max Δw/mm':>12}{'p99.9':>10}{'max Δw':>10}")
        gradient = report["edge_gradient"]
        for name in worst_bones:
            if name not in gradient:
                continue
            item = gradient[name]
            print(f"    {name:<20}{item['max_per_mm']:>12}{item['p999_per_mm']:>10}"
                  f"{item['max_delta']:>10}")
    if out:
        print("RIG_WEIGHTS_OK 已保存 " + out)
    if want_report:
        print("RIG_WEIGHTS_JSON " + json.dumps(report, ensure_ascii=False))


main()
