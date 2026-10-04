#!/usr/bin/env python3
"""
比邻AI · 皮相 blendshape 重建（第 3 步：vis_* 15 + expr_* 8）

用法：
    blender --background <工作.blend> \
        --python tools/blender-env.py \
        --python tools/blender-morph-build.py -- --out <输出.blend> [--report] \
            [--jaw-scale 1.0] [--strain-k 1.0]

设计口径（与交付规范 §4.4 / §17 对齐，但**针对重绑后的 v2 资产**）：

  · 端点通道（vis_*）= **骨骼姿态驱动 + 解析唇形叠加**，与上一代同一套方法论
    （§17.3）：先把 `jaw`（按 viseme 标定的角度）摆好、求值取 delta，
    再叠加解析式唇部塑形场（展宽 / 撮圆 / 前突 / 嘴角上提），最后做
    拉普拉斯平滑与**应变限幅**（§18.4 第 4 条：限幅是消除翻转面的关键）。
  · `vis_silence` = 零位移（同 glTF 静置态）。
  · `expr_blink_L/R`：**左右独立**，用 `eyelid_upper/lower` 骨旋转驱动，
    并按"睑裂半高"缩放压量（眼角自然为 0，避免折痕）。
  · 其余 expr_* 用解析场（嘴角上提/下垂、眉抬/眉压、眯眼、惊讶=下颌开+眉抬+唇撮）。
  · 未移动的顶点**写回 Basis 原值** → glTF 走 sparse accessor（体积关键，见交付规范 §5.4）。

⚠️ v2 资产的已知限制（本轮实测，见任务笔记 §8.15）：
    `node_0` 在口内**没有内腔/上腭/牙齿/舌**——唇缝是两层贴合壳。
    因此 vis_* 的下颌开合幅度按"不露出唇内侧斜面"为上限（默认 ≤ ±0.75 × 8°），
    真正的口内几何（cavity/teeth/tongue）留作独立一轮，不在这里硬凑
    （凑出来的口袋会在张嘴时穿帮，比小开合更糟）。
"""

import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

# ── viseme 标定（下颌角，度）——沿用交付规范的相对关系，绝对幅度按 v2 可开合上限缩放 ──
VISEME_JAW_DEG = {
    "vis_silence": 0.0, "vis_AA": 14.0, "vis_E": 7.0, "vis_I": 4.0, "vis_O": 9.0,
    "vis_U": 5.0, "vis_MBP": 0.0, "vis_FV": 2.0, "vis_L": 8.0, "vis_TH": 5.0,
    "vis_WQ": 4.0, "vis_RR": 6.0, "vis_SS": 3.0, "vis_KK": 6.0, "vis_NN": 3.0,
    # 唇形系数：(展宽, 撮圆, 前突, 嘴角上提, 嘴角下垂)
}
VISEME_LIP = {
    "vis_silence": (0.0, 0.0, 0.0, 0.0, 0.0),
    "vis_AA": (1.0, 0.0, 0.10, 0.0, 0.0),
    "vis_E": (1.6, 0.0, 0.05, 0.0, 0.0),
    "vis_I": (1.8, 0.0, 0.0, 0.10, 0.0),
    "vis_O": (0.0, 1.0, 0.45, 0.0, 0.0),
    "vis_U": (0.0, 1.0, 0.80, 0.0, 0.0),
    "vis_MBP": (-1.2, 0.0, 0.0, 0.0, 0.0),
    "vis_FV": (0.4, 0.0, 0.0, 0.0, 0.0),
    "vis_L": (0.6, 0.0, 0.0, 0.0, 0.0),
    "vis_TH": (0.8, 0.0, 0.20, 0.0, 0.0),
    "vis_WQ": (0.0, 1.2, 0.30, 0.0, 0.0),
    "vis_RR": (0.3, 0.5, 0.10, 0.0, 0.0),
    "vis_SS": (1.2, 0.0, 0.0, 0.10, 0.0),
    "vis_KK": (0.5, 0.2, 0.0, 0.0, 0.0),
    "vis_NN": (0.5, 0.0, 0.0, 0.0, 0.0),
}
# ⚠️ 下唇的开合**不能只转 `jaw`**：实测下唇一个中位顶点由
#   `chin 0.30 + jaw 0.34 + lip_lower 0.32` 共同驱动，只转 jaw 时它只走 ~70%，
#   实测中线开口只有 ~2mm（渲染看几乎是闭嘴）。因此开合姿态里
#   `chin`（与 `lip_lower`）必须**同向跟随** jaw —— 见任务笔记 §8.16。
JAW_FOLLOWERS = {"chin": 1.0, "lip_lower": 1.0}

EXPR_NAMES = ["expr_blink_L", "expr_blink_R", "expr_smile", "expr_frown",
              "expr_surprise", "expr_squint", "expr_brow_up", "expr_brow_down"]

# ── 幅度常量（米）——按 v2 资产实测尺寸标定（嘴半宽 ~24mm、睑裂半高 ~7.7mm）──
AMP_SPREAD = 0.0022      # 展宽：嘴角最大外移
AMP_ROUND = 0.0026       # 撮圆：嘴角内收 + 唇外移
AMP_PROTRUDE = 0.0024    # 前突：唇面沿 -Y
AMP_CORNER_UP = 0.0026   # 嘴角上提
AMP_CORNER_DOWN = 0.0022  # 嘴角下垂
AMP_BROW = 0.0024        # 眉抬/眉压
AMP_SQUINT_LOWER = 0.0014  # 下眼睑上抬
AMP_SQUINT_UPPER = 0.0006  # 上眼睑微降
BLINK_LID_FRACTION = 0.98  # 眨眼闭合比例
SMOOTH_ROUNDS = 2
SMOOTH_FACTOR = 0.45


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


def build_adjacency(mesh_obj):
    edges = np.empty(len(mesh_obj.data.edges) * 2, dtype=np.int32)
    mesh_obj.data.edges.foreach_get("vertices", edges)
    edges = edges.reshape(-1, 2)
    # 无向唯一边（去重、方向规范化）—— 应变限幅必须用唯一无向边，
    # 否则同一条边会被处理两次，边长变化每轮翻倍，限幅反而发散。
    edges = np.unique(np.sort(edges, axis=1), axis=0)
    count = len(mesh_obj.data.vertices)
    sources = np.concatenate([edges[:, 0], edges[:, 1]])
    targets = np.concatenate([edges[:, 1], edges[:, 0]])
    order = np.argsort(sources, kind="stable")
    sources, targets = sources[order], targets[order]
    offsets = np.zeros(count + 1, dtype=np.int64)
    np.add.at(offsets, sources + 1, 1)
    return targets, np.cumsum(offsets), edges


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


def read_normals(mesh_obj, count):
    normals = np.zeros(count * 3, dtype=np.float64)
    mesh_obj.data.vertices.foreach_get("normal", normals)
    return normals.reshape(count, 3)


def smooth_delta(delta, targets, offsets, mask, rounds, factor):
    """只对 mask 内顶点做邻域平滑（保持稀疏，§18.4 第 3 条）"""
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
    """把"沿边的位移差"限制到 `k × 边长`（应变限幅，交付规范 §18.4 第 4 条）

    ⚠️ **本轮连续踩的两个坑**（都写进任务笔记，别再重犯）：
      1. 第一版用"按超限量把两端各拉回一半"的式子，实测**反向发散**：
         原始 6.99× 的键限幅后变 41.69×，k=0.3 更炸到 1525×。
      2. 第二版改成主动集平均后**更炸**（1e23×）——根因是边表里每条无向边
         出现了两次（a→b 与 b→a），一轮里同一条边被处理两遍，
         边长变化每轮翻倍。修法：边表先去重 + 方向规范化（见 build_adjacency）。
    现在是收敛的**欠松弛**迭代：每轮只把超限边的位移差按 α/2 各让一半，
    α<1 保证不会过冲；迭代到没有超限边或到轮数上限。mask 外的顶点不动。
    """
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
        # 非受影响端不动（保证形态键只改它该改的地方）
        free_a = ~mask[ea]
        working[ea[free_a]] += correction[free_a]
        free_b = ~mask[eb]
        working[eb[free_b]] -= correction[free_b]
    return working


def axis_rotation(pivot, axis, degrees):
    """绕任意轴旋转的 3×3 矩阵（Rodrigues）"""
    axis = axis / max(np.linalg.norm(axis), 1e-12)
    angle = math.radians(degrees)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    cross = np.array([[0.0, -axis[2], axis[1]],
                      [axis[2], 0.0, -axis[0]],
                      [-axis[1], axis[0], 0.0]])
    rotation = cos_a * np.eye(3) + sin_a * cross + (1.0 - cos_a) * np.outer(axis, axis)
    return rotation


def bone_pivot_axis(armature, bone_name):
    """骨的世界枢轴与旋转轴（`pose.bones[].rotation_euler` 的 X 轴）"""
    bone = armature.data.bones[bone_name]
    matrix = armature.matrix_world @ bone.matrix_local
    pivot = np.array(matrix.translation)
    axis = np.array((matrix.to_3x3() @ Vector((1.0, 0.0, 0.0))))
    return pivot, axis / max(np.linalg.norm(axis), 1e-12)


def posed_delta(mesh_obj, armature, poses):
    """把骨骼摆到 `poses`（{骨: 角度}），返回求值后的顶点位移（米）"""
    for bone in armature.pose.bones:
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0.0, 0.0, 0.0)
        bone.location = (0.0, 0.0, 0.0)
        bone.scale = (1.0, 1.0, 1.0)
    for name, degrees in poses.items():
        pose_bone = armature.pose.bones.get(name)
        if pose_bone is None:
            continue
        pose_bone.rotation_mode = "XYZ"
        pose_bone.rotation_euler = (math.radians(degrees), 0.0, 0.0)
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = mesh_obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    count = len(mesh.vertices)
    buffer = np.empty(count * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", buffer)
    positions = buffer.reshape(count, 3).copy()
    evaluated.to_mesh_clear()
    return positions


def clear_pose(armature):
    for bone in armature.pose.bones:
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0.0, 0.0, 0.0)
        bone.location = (0.0, 0.0, 0.0)
        bone.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()


# ────────────────────────── 解析场（嘴 / 眉 / 眼） ──────────────────────────

class Fields:
    """把资产自身的解剖尺度量出来，所有幅度按它标定（不写死 mm）"""

    def __init__(self, co, weights, jaw_w, head_w):
        self.co = co
        mouth = (np.abs(co[:, 0]) < 0.030) & (co[:, 1] < -0.062) & (co[:, 1] > -0.098) \
            & (co[:, 2] > 1.010) & (co[:, 2] < 1.048)
        jaw_band = mouth & (jaw_w > 0.15)
        self.mouth_mask = mouth
        self.jaw = jaw_w
        self.head = head_w
        if jaw_band.any():
            self.mouth_center = np.array([
                float(co[jaw_band, 0].mean()),
                float(co[jaw_band, 1].mean()),
                float(co[jaw_band, 2].mean())])
        else:
            self.mouth_center = np.array([0.0, -0.078, 1.024])
        self.mouth_half_width = float(np.percentile(np.abs(co[mouth, 0]), 98)) if mouth.any() else 0.024
        self.lip_front_y = float(co[mouth, 1].min()) if mouth.any() else -0.088
        self.eye_center = {}
        self.lid_top = {}
        self.lid_bottom = {}
        for side, sign in (("L", 1.0), ("R", -1.0)):
            eye = weights.get("eye.%s" % side)
            upper = weights.get("eyelid_upper.%s" % side)
            lower = weights.get("eyelid_lower.%s" % side)
            if eye is None:
                continue
            eye_mask = eye > 0.10
            self.eye_center[side] = (np.array([float(co[eye_mask, 0].mean()),
                                               float(co[eye_mask, 1].mean()),
                                               float(co[eye_mask, 2].mean())])
                                     if eye_mask.any()
                                     else np.array([0.027 * sign, -0.055, 1.069]))
            self.lid_top[side] = upper if upper is not None else np.zeros(len(co))
            self.lid_bottom[side] = lower if lower is not None else np.zeros(len(co))

    def gaussian(self, center_x, center_z, rx, rz):
        dx = (self.co[:, 0] - center_x) / rx
        dz = (self.co[:, 2] - center_z) / rz
        return np.exp(-(dx * dx + dz * dz) * 1.6)

    def mouth_mask_soft(self):
        """嘴部软遮罩：以 asset 自身量出的嘴中心与半宽为尺度"""
        return (self.gaussian(self.mouth_center[0] * 0.5, self.mouth_center[2],
                              self.mouth_half_width * 1.15, 0.017)
                * smoothstep((self.co[:, 1] - (-0.050)) / -0.030)
                * smoothstep((0.045 - np.abs(self.co[:, 0])) / 0.012))


def lip_fields(fields, coeff):
    """解析唇形场：返回位移场（米）；coeff = (展宽, 撮圆, 前突, 嘴角上提, 嘴角下垂)"""
    spread, round_, protrude, corner_up, corner_down = coeff
    co = fields.co
    count = len(co)
    delta = np.zeros((count, 3), dtype=np.float64)
    if abs(spread) < 1e-6 and abs(round_) < 1e-6 and abs(protrude) < 1e-6 \
            and abs(corner_up) < 1e-6 and abs(corner_down) < 1e-6:
        return delta
    mask = fields.mouth_mask_soft()
    # 嘴角：|x| 靠外、靠近嘴中心 z
    corner = (np.exp(-(((np.abs(co[:, 0]) - fields.mouth_half_width * 0.95) / 0.008) ** 2))
              * np.exp(-(((co[:, 2] - fields.mouth_center[2]) / 0.009) ** 2))
              * smoothstep((co[:, 1] + 0.050) / -0.025))
    # 唇面：靠近唇红（y 靠前）
    lip_surface = np.exp(-(((co[:, 1] - fields.lip_front_y) / 0.006) ** 2)) * mask
    sign_x = np.sign(co[:, 0])
    if abs(spread) > 1e-6:
        delta[:, 0] += sign_x * corner * AMP_SPREAD * spread
        # 唇中线也跟着展宽一点（否则只有嘴角动，像被捏住）
        delta[:, 0] += sign_x * lip_surface * AMP_SPREAD * 0.35 * max(spread, 0.0)
    if abs(round_) > 1e-6:
        delta[:, 0] -= sign_x * corner * AMP_ROUND * round_
        delta[:, 1] -= np.exp(-(((co[:, 1] - fields.lip_front_y) / 0.010) ** 2)) \
            * mask * AMP_ROUND * 0.55 * round_
    if abs(protrude) > 1e-6:
        delta[:, 1] -= lip_surface * AMP_PROTRUDE * protrude
    if abs(corner_up) > 1e-6:
        delta[:, 2] += corner * AMP_CORNER_UP * corner_up
    if abs(corner_down) > 1e-6:
        delta[:, 2] -= corner * AMP_CORNER_DOWN * corner_down
    return delta


def brow_field(fields, amount, weights):
    """眉抬（amount>0）/ 眉压（amount<0）：按 brow.L/R 权重场作用"""
    count = len(fields.co)
    delta = np.zeros((count, 3), dtype=np.float64)
    if abs(amount) < 1e-6:
        return delta
    for side in ("L", "R"):
        weight = weights.get("brow.%s" % side)
        if weight is None:
            continue
        # 只作用在权重较强的区域（避免整片额头一起动）
        strength = smoothstep(weight / 0.35)
        delta[:, 2] += strength * AMP_BROW * amount
        delta[:, 1] -= strength * AMP_BROW * 0.15 * amount
    return delta


def squint_field(fields, weights):
    """眯眼：下眼睑上抬 + 上眼睑微降"""
    count = len(fields.co)
    delta = np.zeros((count, 3), dtype=np.float64)
    for side in ("L", "R"):
        lower = weights.get("eyelid_lower.%s" % side)
        upper = weights.get("eyelid_upper.%s" % side)
        if lower is not None:
            strength = smoothstep(lower / 0.30)
            delta[:, 2] += strength * AMP_SQUINT_LOWER
        if upper is not None:
            strength = smoothstep(upper / 0.45)
            delta[:, 2] -= strength * AMP_SQUINT_UPPER
    return delta


def blink_delta(mesh_obj, armature, fields, side, lid_fraction, rest):
    """眨眼：按上下眼睑骨旋转驱动 + 睑裂半高缩放（眼角自然为 0）

    为什么不用纯解析场：上一代的结论是"眼睑闭合要按眼球球面做前向避让"，
    而 v2 的眼球是**雕出来的穹顶**（§8.6），骨旋转正好是绕穹顶球心的，
    天然不穿插 —— 因此这里直接用骨驱动，再按睑裂半高压缩眼角。
    """
    upper_name = "eyelid_upper.%s" % side
    lower_name = "eyelid_lower.%s" % side
    posed_upper = posed_delta(mesh_obj, armature, {upper_name: 26.0})
    posed_lower = posed_delta(mesh_obj, armature, {lower_name: -14.0})
    delta = (posed_upper - rest) * lid_fraction * 0.75 \
        + (posed_lower - rest) * lid_fraction * 0.75
    clear_pose(armature)
    return delta


def main():
    out = arg_value("--out")
    jaw_scale = float(arg_value("--jaw-scale", "0.62"))
    strain_k = float(arg_value("--strain-k", "1.0"))
    want_report = has_flag("--report")

    mesh_obj = head_mesh()
    armature = armature_object()
    if mesh_obj is None or armature is None:
        print("MORPH_BUILD_FAIL 缺少网格或骨架")
        return

    count = len(mesh_obj.data.vertices)
    buffer = np.empty(count * 3, dtype=np.float64)
    mesh_obj.data.vertices.foreach_get("co", buffer)
    co = buffer.reshape(count, 3).copy()
    normals = read_normals(mesh_obj, count)

    bone_names = [bone.name for bone in armature.data.bones]
    weights = {}
    for name in ("jaw", "head", "lip_upper", "lip_lower",
                 "brow.L", "brow.R", "eye.L", "eye.R",
                 "eyelid_upper.L", "eyelid_upper.R",
                 "eyelid_lower.L", "eyelid_lower.R"):
        if name in bone_names:
            weights[name] = read_group_weights(mesh_obj, name, count)
    fields = Fields(co, weights, weights.get("jaw", np.zeros(count)),
                    weights.get("head", np.zeros(count)))

    targets, offsets, edges = build_adjacency(mesh_obj)
    rest_length = np.linalg.norm(co[edges[:, 0]] - co[edges[:, 1]], axis=1)

    print("=" * 96)
    print("皮相 blendshape 重建 : " + bpy.data.filepath)
    print(f"  网格 {mesh_obj.name}  {count} 顶点")
    print(f"  嘴中心 {np.round(fields.mouth_center, 4).tolist()}  "
          f"半宽 {fields.mouth_half_width * 1000:.2f}mm  唇最前 y {fields.lip_front_y * 1000:.2f}mm")
    print(f"  下颌幅度缩放 {jaw_scale}（v2 口内无内腔，开合上限按此保守设定）")

    # 建形态键容器（保留已有键：同名覆盖）
    if mesh_obj.data.shape_keys is None:
        mesh_obj.shape_key_add(name="Basis", from_mix=False)
    basis = mesh_obj.data.shape_keys.key_blocks[0]

    def write_key(name, delta):
        """把 delta 写进形态键；未动顶点写回 Basis（保证 glTF sparse）"""
        block = mesh_obj.data.shape_keys.key_blocks.get(name)
        if block is None:
            block = mesh_obj.shape_key_add(name=name, from_mix=False)
        moved = np.linalg.norm(delta, axis=1) > 1e-7
        positions = co.copy()
        positions[moved] += delta[moved]
        flat = positions.reshape(-1).astype(np.float32)
        block.data.foreach_set("co", flat)
        block.value = 0.0
        return int(moved.sum())

    report = {"file": bpy.data.filepath, "mesh": mesh_obj.name, "vertices": count,
              "jaw_scale": jaw_scale, "strain_k": strain_k, "morphs": {}}

    # ── 1) vis_* ──
    for name, degrees in VISEME_JAW_DEG.items():
        coeff = VISEME_LIP[name]
        delta = np.zeros((count, 3), dtype=np.float64)
        if abs(degrees) > 1e-6:
            angle = degrees * jaw_scale
            poses = {"jaw": angle}
            for follower, ratio in JAW_FOLLOWERS.items():
                if follower in weights:
                    poses[follower] = angle * ratio
            posed = posed_delta(mesh_obj, armature, poses)
            delta += posed - co
            clear_pose(armature)
        delta += lip_fields(fields, coeff)
        mask = np.linalg.norm(delta, axis=1) > 1e-9
        delta = smooth_delta(delta, targets, offsets, mask, SMOOTH_ROUNDS, SMOOTH_FACTOR)
        delta = strain_limit(delta, edges, rest_length, mask, strain_k)
        moved = write_key(name, delta)
        max_mm = float(np.linalg.norm(delta, axis=1).max() * 1000)
        report["morphs"][name] = {"moved": moved, "max_mm": round(max_mm, 3),
                                  "jaw_deg": round(degrees * jaw_scale, 2)}

    # ── 2) expr_* ──
    # 眨眼（左右独立）
    for side in ("L", "R"):
        delta = blink_delta(mesh_obj, armature, fields, side, BLINK_LID_FRACTION, co)
        mask = np.linalg.norm(delta, axis=1) > 1e-9
        delta = smooth_delta(delta, targets, offsets, mask, 1, 0.35)
        delta = strain_limit(delta, edges, rest_length, mask, strain_k)
        moved = write_key("expr_blink_%s" % side, delta)
        report["morphs"]["expr_blink_%s" % side] = {
            "moved": moved, "max_mm": round(float(np.linalg.norm(delta, axis=1).max() * 1000), 3)}

    # 微笑 / 苦笑
    for name, coeff in (("expr_smile", (0.9, 0.0, 0.10, 1.0, 0.0)),
                        ("expr_frown", (-0.3, 0.0, 0.0, 0.0, 1.0))):
        delta = lip_fields(fields, coeff)
        mask = np.linalg.norm(delta, axis=1) > 1e-9
        delta = smooth_delta(delta, targets, offsets, mask, SMOOTH_ROUNDS, SMOOTH_FACTOR)
        delta = strain_limit(delta, edges, rest_length, mask, strain_k)
        moved = write_key(name, delta)
        report["morphs"][name] = {"moved": moved,
                                  "max_mm": round(float(np.linalg.norm(delta, axis=1).max() * 1000), 3)}

    # 惊讶 = 下颌开 + 眉抬 + 唇撮
    surprise_jaw = 8.0 * jaw_scale
    posed = posed_delta(mesh_obj, armature, {"jaw": surprise_jaw})
    delta = posed - co
    clear_pose(armature)
    delta += lip_fields(fields, (0.0, 0.8, 0.35, 0.0, 0.0))
    delta += brow_field(fields, 1.0, weights)
    mask = np.linalg.norm(delta, axis=1) > 1e-9
    delta = smooth_delta(delta, targets, offsets, mask, SMOOTH_ROUNDS, SMOOTH_FACTOR)
    delta = strain_limit(delta, edges, rest_length, mask, strain_k)
    moved = write_key("expr_surprise", delta)
    report["morphs"]["expr_surprise"] = {
        "moved": moved, "max_mm": round(float(np.linalg.norm(delta, axis=1).max() * 1000), 3),
        "jaw_deg": round(surprise_jaw, 2)}

    # 眯眼
    delta = squint_field(fields, weights)
    mask = np.linalg.norm(delta, axis=1) > 1e-9
    delta = smooth_delta(delta, targets, offsets, mask, 1, 0.35)
    delta = strain_limit(delta, edges, rest_length, mask, strain_k)
    moved = write_key("expr_squint", delta)
    report["morphs"]["expr_squint"] = {
        "moved": moved, "max_mm": round(float(np.linalg.norm(delta, axis=1).max() * 1000), 3)}

    # 眉抬 / 眉压
    for name, amount in (("expr_brow_up", 1.0), ("expr_brow_down", -1.0)):
        delta = brow_field(fields, amount, weights)
        mask = np.linalg.norm(delta, axis=1) > 1e-9
        delta = smooth_delta(delta, targets, offsets, mask, SMOOTH_ROUNDS, SMOOTH_FACTOR)
        delta = strain_limit(delta, edges, rest_length, mask, strain_k)
        moved = write_key(name, delta)
        report["morphs"][name] = {"moved": moved,
                                  "max_mm": round(float(np.linalg.norm(delta, axis=1).max() * 1000), 3)}

    # 收尾：所有键 value = 0；Basis 保持静置
    for block in mesh_obj.data.shape_keys.key_blocks:
        block.value = 0.0
    names = [b.name for b in mesh_obj.data.shape_keys.key_blocks]
    report["key_names"] = names
    report["counts"] = {"total": len(names) - 1,
                        "vis": len([n for n in names if n.startswith("vis_")]),
                        "expr": len([n for n in names if n.startswith("expr_")]),
                        "shape": len([n for n in names if n.startswith("shape_")])}

    print("")
    print(f"  {'形态键':<20}{'动顶点':>9}{'最大位移mm':>12}{'下颌角':>8}")
    for name, item in report["morphs"].items():
        print(f"  {name:<20}{item['moved']:>9}{item['max_mm']:>12}{item.get('jaw_deg', 0):>8}")
    print("")
    print(f"  形态键合计 {report['counts']['total']}"
          f"（vis {report['counts']['vis']} / expr {report['counts']['expr']} / "
          f"shape {report['counts']['shape']}）")

    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("MORPH_BUILD_OK 已保存 " + out)
    if want_report:
        print("MORPH_BUILD_JSON " + json.dumps(report, ensure_ascii=False))


main()
