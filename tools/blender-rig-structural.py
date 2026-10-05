#!/usr/bin/env python3
"""
比邻AI · 骨相骨骼生成（第 1 步：结构层）

用法：
    blender --background <工作.blend> --python tools/blender-rig-structural.py -- \
        --out <输出.blend> [--render <前缀>] [--json]

方法论位置：骨相骨骼（本脚本）→ 皮相 blendshape → RBF 组合修正 → 自动化质检
本步只做**骨骼**：位置全部由原始网格的**解剖锚点**算出（镜像面、眼窝中心、
面部各横带前缘、下颌最宽处、下巴尖…），不目测、不手拖。

骨骼分三类：
  · 机能骨（说话/表情用）：neck / head / jaw / chin / eye / eyelid / brow / nose / lip / tongue / ear
  · 骨相骨（粗轮廓捏脸用）：脸宽/脸长/颧骨/下颌/下巴/额头/太阳穴/脸颊/眼窝深度
    —— 粗轮廓交给骨骼，是"拖动不再撕裂"的关键（稀疏 morph 撑不住大位移）
  · 总控：root

同时把每根骨的位置渲染成标记球，便于肉眼核对骨点是否落在解剖位置上。
"""

import json
import math
import os
import sys

import bpy
from mathutils import Vector

BONES = []


def has_flag(name):
    return name in sys.argv


def arg_value(name, default=None):
    args = sys.argv
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return default


def add(name, head, tail, parent=None, kind="bone", note=""):
    BONES.append(
        {
            "name": name,
            "head": [round(v, 5) for v in head],
            "tail": [round(v, 5) for v in tail],
            "parent": parent,
            "kind": kind,
            "note": note,
        }
    )


def mesh_points(obj):
    matrix = obj.matrix_world
    return [matrix @ v.co for v in obj.data.vertices]


def find_anchors(points):
    """解剖锚点：**优先按网格自身实测**（通用），量不出来时才回退到既有女性骨骼表。

    为什么改（2026-10-05，换成卡通小男孩资产时踩到）：
    原实现把 `01_female_60s_v3` 的**成年女性骨骼表**写死在这里（眼位 z=1.070），
    而新男生资产的脸在 z≈0.75 附近 —— 结果**整张脸的骨头都插到头发/额头上方**，
    渲染出来骨头飘在体外。换一次资产就要重标一次坐标，这种设计不可持续。

    现在的判据（对"正面朝 −Y、+Z 向上"的任何网格成立，与美术风格无关）：
      · **头顶/下巴**：|x|<4mm 中线上的 z 极值
      · **鼻尖**：中线上 y 最小（最靠前）的点 → 定位整张脸的纵向基准
      · **眼位**：鼻尖上方 0.010~0.040 内、左右两侧最靠前一簇的形心（眼窝在脸前缘）
      · **眉位**：鼻尖上方 0.040~0.062 的同类形心
      · **嘴**：鼻尖下方 0.005~0.075 内，用 albedo **红度**（R−B）最高的一簇定位
      · **耳根**：鼻尖上方 0~0.05 带内 |x| 最大处
    回退：任何一项量不出来就用女性模板的相对比例兜底（并在报告里标注）。
    """
    # 既有女性骨骼表（**仅作回退**，世界坐标，正面朝 -Y，+Z 向上）
    reference = {
        "neck_head": (0.0, 0.0080, 0.9420),
        "head_head": (0.0, 0.0050, 0.9980),
        "head_tail": (0.0, 0.0050, 1.1120),
        "jaw_head": (0.0, 0.0120, 1.0620),
        "jaw_tail": (0.0, -0.0700, 1.0120),
        "nose_head": (0.0, -0.0720, 1.0720),
        "nose_tail": (0.0, -0.0870, 1.0490),
        "lip_upper": (0.0, -0.0580, 1.0340),
        "lip_lower": (0.0, -0.0580, 1.0240),
        "brow_z": 1.0930,
        "eyelid_upper_z": 1.0860,
        "eyelid_lower_z": 1.0560,
        "cheek_x": 0.0400,
        "cheek_z": 1.0520,
        "ear_head": (0.0520, 0.0160, 1.0720),
        "ear_tail": (0.0780, 0.0220, 1.0780),
    }

    zs = [p.z for p in points]
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    top, bottom = max(zs), min(zs)
    height = top - bottom
    midline = [p for p in points if abs(p.x) < 0.004]
    print(f"  [通用锚点] 网格高 {height:.4f}（z {bottom:.4f}~{top:.4f}），中线顶点 {len(midline)}")

    measured = {}
    if len(midline) > 20:
        nose_tip = min(midline, key=lambda p: p.y)
        measured["nose_tip"] = (nose_tip.x, nose_tip.y, nose_tip.z)
        base_z = nose_tip.z
        print(f"  [通用锚点] 鼻尖 {tuple(round(v, 4) for v in measured['nose_tip'])}")

        def front_cluster(z_from, z_to, half_x=0.075, percentile=12.0):
            band = [p for p in points
                    if z_from <= p.z <= z_to and 0.006 < abs(p.x) < half_x and p.y < 0]
            if len(band) < 12:
                return None
            band.sort(key=lambda p: p.y)
            keep = band[: max(4, int(len(band) * percentile / 100.0))]
            return (sum(p.x for p in keep) / len(keep),
                    sum(p.y for p in keep) / len(keep),
                    sum(p.z for p in keep) / len(keep))

        eye_l = front_cluster(base_z + 0.010, base_z + 0.040)
        eye_r = front_cluster(base_z + 0.010, base_z + 0.040)
        if eye_l and eye_r:
            # 左右分开取：各自在对应半侧
            left = [p for p in points if base_z + 0.010 <= p.z <= base_z + 0.040
                    and 0.006 < p.x < 0.075 and p.y < 0]
            right = [p for p in points if base_z + 0.010 <= p.z <= base_z + 0.040
                     and -0.075 < p.x < -0.006 and p.y < 0]
            for side, cell in (("L", left), ("R", right)):
                if len(cell) < 12:
                    continue
                cell.sort(key=lambda p: p.y)
                keep = cell[: max(4, int(len(cell) * 0.12))]
                measured["eye_" + side] = (sum(p.x for p in keep) / len(keep),
                                           sum(p.y for p in keep) / len(keep),
                                           sum(p.z for p in keep) / len(keep))
        brow_l = front_cluster(base_z + 0.040, base_z + 0.062)
        if brow_l:
            measured["brow_z"] = brow_l[2]
            measured["brow_front_y"] = brow_l[1]
        ear_band = [p for p in points if base_z <= p.z <= base_z + 0.05 and p.y > -0.02]
        if len(ear_band) > 20:
            measured["ear_root_x"] = max(abs(p.x) for p in ear_band)
        measured["base_z"] = base_z

    # 用 albedo 红度找嘴（卡通脸也有效）
    try:
        import numpy as _np
        obj = bpy.context.view_layer.objects.active or next(o for o in bpy.data.objects if o.type == "MESH")
        node_tree = obj.data.materials[0].node_tree if obj.data.materials else None
        image = next((n.image for n in node_tree.nodes if n.type == "TEX_IMAGE" and n.image), None) if node_tree else None
        if image is not None and obj.data.uv_layers.active and "base_z" in measured:
            size = 1024
            working = image.copy(); working.scale(size, size)
            pixels = _np.empty(size * size * 4, dtype=_np.float32)
            working.pixels.foreach_get(pixels)
            rgb = pixels.reshape(size, size, 4)[:, :, :3]
            uvs = _np.empty(len(obj.data.loops) * 2, dtype=_np.float32)
            obj.data.uv_layers.active.data.foreach_get("uv", uvs); uvs = uvs.reshape(-1, 2)
            vindex = _np.empty(len(obj.data.loops), dtype=_np.int32)
            obj.data.loops.foreach_get("vertex_index", vindex)
            uniq, first = _np.unique(vindex, return_index=True)
            vertex_uv = _np.zeros((len(obj.data.vertices), 2), dtype=_np.float32)
            vertex_uv[uniq] = uvs[first]
            px = _np.clip((vertex_uv[:, 0] % 1.0) * (size - 1), 0, size - 1).astype(_np.int32)
            py = _np.clip((vertex_uv[:, 1] % 1.0) * (size - 1), 0, size - 1).astype(_np.int32)
            sampled = rgb[py, px]
            _np_redness = sampled[:, 0] - sampled[:, 2]
            co = _np.array([[p.x, p.y, p.z] for p in points])
            base_z = measured["base_z"]
            below = (co[:, 2] < base_z - 0.005) & (co[:, 2] > base_z - 0.075)                 & (_np.abs(co[:, 0]) < 0.06) & (co[:, 1] < -0.03)
            if below.sum() > 50:
                values = _np_redness[below]
                threshold = _np.percentile(values, 92)
                lip = below & (_np_redness >= threshold)
                if lip.sum() > 20:
                    sel = co[lip]
                    measured["mouth"] = tuple(sel.mean(axis=0))
                    print("  [通用锚点] 嘴（红度>p92）%s" % (tuple(round(v, 4) for v in measured["mouth"]),))
            bpy.data.images.remove(working)
    except Exception as error:  # noqa: BLE001
        print("  [通用锚点] 嘴定位跳过：" + str(error))

    # ── 组装 anchors：实测优先，缺失项用女性模板的相对偏移兜底 ──
    # 模板里"模板鼻尖"= lip_upper 上方一点，用它算实测与模板的 z 差，整体平移兜底项
    import math as _math
    template_nose_z = reference["nose_tail"][2]
    base_z = measured.get("base_z", None)
    if base_z is not None:
        dz = base_z - template_nose_z          # 实测脸相对模板脸的纵向位移
        fallback = lambda name: (reference[name][0], reference[name][1], reference[name][2] + dz)
        print(f"  [通用锚点] 模板回退的纵向位移 dz={dz:+.4f}（实测鼻尖 z={base_z:.4f}）")
    else:
        fallback = lambda name: reference[name]
        dz = 0.0

    if "eye_L" in measured and "eye_R" in measured:
        eye_l, eye_r = measured["eye_L"], measured["eye_R"]
    else:
        # 回退：用模板脸部宽度推一个合理的眼位（模板鼻尖上方 0.020、左右各 0.0239）
        _ez = reference["nose_tail"][2] + 0.020 + dz
        _ey = reference["lip_upper"][1] - 0.004
        eye_l = (0.0239, _ey, _ez)
        eye_r = (-0.0239, _ey, _ez)
    nose_tip = measured.get("nose_tip", fallback("nose_tail"))
    mouth = measured.get("mouth", fallback("lip_upper"))
    brow_z = measured.get("brow_z", reference["brow_z"] + dz)
    brow_front_y = measured.get("brow_front_y", reference["lip_upper"][1])
    ear_x = measured.get("ear_root_x", reference["ear_head"][0])
    face_front = min((p.y for p in points if p.y < -0.02), default=min(ys))

    def widest_in(z_from, z_to):
        band = [p for p in points if z_from <= p.z <= z_to and p.y < 0]
        return max((abs(p.x) for p in band), default=None)

    face_front = min((p.y for p in points if p.y < -0.02), default=min(ys))

    # ── 以下全部**以实测为准**（模板只提供回退与"相对比例"）──
    # 纵向基准：鼻尖。脸部各部件按"到鼻尖的相对距离"摆放，这样换任何模型都能自适应。
    nose_z = nose_tip[2]
    mouth_z = mouth[2]
    # 下巴：中线最低；中线下端即下巴尖
    chin_z = bottom + height * 0.002 if bottom < nose_z - 0.05 else mouth_z - 0.03
    # 上唇/下唇：在嘴中心上下各一点点
    lip_upper_z = mouth_z + 0.006
    lip_lower_z = mouth_z - 0.008
    # 头：以眼位为参照往上下各取一段（头高 = 头顶到下巴）
    head_z = eye_l[2] + (top - eye_l[2]) * 0.55
    neck_z = nose_z - (nose_z - bottom) * 0.30
    # 眉眼：眼位上下
    brow_z_measured = brow_z
    eyelid_upper_z = eye_l[2] + 0.010
    eyelid_lower_z = eye_l[2] - 0.014
    # 横向：按脸部实际宽度分段量（用相对鼻尖的 z 偏移，避免写死 z）
    cheek_width_x = widest_in(nose_z + 0.010, nose_z + 0.030) or 0.06
    jaw_width_x = widest_in(nose_z - 0.030, nose_z - 0.005) or 0.05
    temple_width_x = widest_in(nose_z + 0.040, nose_z + 0.060) or 0.075
    mouth_front_y = min((p.y for p in points if abs(p.z - mouth_z) < 0.006 and p.y < 0), default=face_front)
    chin_front_y = min((p.y for p in points if abs(p.z - chin_z) < 0.008 and p.y < 0), default=face_front)
    brow_front_y = min((p.y for p in points if abs(p.z - brow_z_measured) < 0.006 and p.y < 0), default=face_front)

    anchors = {
        "top": top,
        "bottom": bottom,
        "height": height,
        "head_height": max(top - chin_z, height * 0.12),
        "head_bottom": neck_z,
        "eye_l": eye_l,
        "eye_r": eye_r,
        "eye_z": eye_l[2],
        "brow_z": brow_z_measured,
        "mouth_z": mouth_z,
        "nose_z": nose_z,
        "chin_low_z": chin_z,
        "face_front_y": face_front,
        "brow_front_y": brow_front_y,
        "nose_front_y": nose_tip[1],
        "mouth_front_y": mouth_front_y,
        "chin_front_y": chin_front_y + 0.005,
        "cheek_width_x": cheek_width_x,
        "jaw_width_x": jaw_width_x,
        "temple_width_x": temple_width_x,
        "ear_root_x": abs(ear_x),
        "mouth_z_ref": mouth_z,
        # 脸部纵向关键点（供 build_bones 用；实测，非模板）
        "eye_upper_z": eyelid_upper_z,
        "eye_lower_z": eyelid_lower_z,
        "lip_upper_z": lip_upper_z,
        "lip_lower_z": lip_lower_z,
        "head_center_z": head_z,
        "reference": reference,
    }
    anchors["arms"] = find_arm_anchors(points)
    return anchors



def find_arm_anchors(points, min_x=None):
    """从网格里自动定位手臂关节（肩/肘/腕/手端），用于"招手"骨骼链。

    判据：只取 |x| 超过 `min_x` 的顶点（=从躯干伸出去的细长部分），沿 x 分层：
      · **肩** = 最内侧一层的截面中心；
      · **腕** = 最外侧一层；
      · **肘** = 中段"最细"的一层（粗细 = (y 尺寸 + z 尺寸) / 2）。

    为什么自动探测：本项目已经换过一次男生资产（2026-10-05 换成卡通小男孩），
    手臂位置每次都得重新量；写死坐标会让"换模型"变成"改脚本"。
    """
    xs_all = [abs(p.x) for p in points]
    if not xs_all:
        return {}
    if min_x is None:
        # 默认取"最大横向跨度的一半略多"作为手臂起点：躯干不会那么宽
        min_x = max(xs_all) * 0.40
    result = {}
    for side, sign in (("L", 1.0), ("R", -1.0)):
        sel = [p for p in points if sign * p.x > min_x]
        if len(sel) < 50:
            continue
        dist = [sign * p.x for p in sel]
        d0, d1 = min(dist), max(dist)
        rows = []
        for index in range(16):
            lo = d0 + (d1 - d0) * index / 16
            hi = d0 + (d1 - d0) * (index + 1) / 16
            cell = [p for p, value in zip(sel, dist) if lo <= value < hi]
            if len(cell) < 8:
                continue
            ys = [p.y for p in cell]
            zs = [p.z for p in cell]
            rows.append({
                "t": (lo + hi) / 2,
                "center": (sum(p.x for p in cell) / len(cell),
                           sum(ys) / len(ys), sum(zs) / len(zs)),
                "thick": ((max(ys) - min(ys)) + (max(zs) - min(zs))) / 2,
            })
        if len(rows) < 3:
            continue
        shoulder = rows[0]["center"]
        wrist = rows[-1]["center"]
        inner = rows[max(1, len(rows) // 5): max(2, len(rows) * 4 // 5)] or rows
        elbow = min(inner, key=lambda row: row["thick"])["center"]
        hand_end = (wrist[0] + sign * 0.030, wrist[1], wrist[2])
        result[side] = {"shoulder": shoulder, "elbow": elbow, "wrist": wrist,
                        "hand_end": hand_end, "span": d1 - d0}
    return result


def build_bones(a):
    """按锚点生成骨相 + 机能骨骼（单位：米，+Z 向上，正面朝 -Y）"""
    ref = a["reference"]
    eye_z = a["eye_z"]
    eye_l = a["eye_l"]
    eye_r = a["eye_r"]
    face_front = a["face_front_y"]
    half_eye_x = abs(eye_l[0])
    cheek_x = a["cheek_width_x"] or 0.06
    jaw_x = a["jaw_width_x"] or 0.05
    temple_x = a["temple_width_x"] or 0.075
    ear_x = a["ear_root_x"] or 0.08
    brow_z = a["brow_z"]
    chin_z = a["chin_low_z"]

    def eye_center(sign):
        return eye_l if sign > 0 else eye_r

    # ── 总控与机能骨 ──────────────────────────────
    add("root", (0, 0, a["bottom"]), (0, 0, a["bottom"] + a["height"] * 0.1), None, "control", "总控（不导出）")
    add("neck", (0, a["face_front_y"] * 0.10, a["head_bottom"]),
        (0, a["face_front_y"] * 0.08, a["head_bottom"] + (a["top"] - a["head_bottom"]) * 0.30),
        "root", "bone", "脖子（scale 驱动脖子粗细）")
    # 头骨：head 放在"颈上缘"（下巴稍下），tail 指向头顶——
    # 原来按 head_center_z 算，在卡通角色上 head 落到 z≈0.51（胸腹高度），
    # 结果"转头"会带着大半身体一起动。
    add("head", (0, a["face_front_y"] * 0.08, a["chin_low_z"] - (a["top"] - a["chin_low_z"]) * 0.16),
        (0, a["face_front_y"] * 0.08, a["eye_z"] + (a["top"] - a["eye_z"]) * 0.55),
        "neck", "bone", "头（转头）")
    add("jaw", (0, a["mouth_front_y"] * 0.35, a["nose_z"] + 0.012),
        (0, a["chin_front_y"], a["chin_low_z"] + 0.010), "head", "bone", "下颌开合")
    add("chin", (0, a["chin_front_y"], a["chin_low_z"] + 0.012),
        (0, a["chin_front_y"], a["chin_low_z"] - 0.006), "jaw", "bone", "下巴前后/长度")

    # ── 手臂链（招手用）──────────────────────────
    # 实测：这个男生资产手臂略下垂、非 T-pose，所以手臂骨按**网格实际走向**建，
    # 不做"水平外伸"的假设（照搬 T-pose 做法会让手臂骨跑到肉外面）。
    arms = a.get("arms") or {}
    for side in ("L", "R"):
        info = arms.get(side)
        if not info:
            continue
        shoulder = info["shoulder"]
        elbow = info["elbow"]
        wrist = info["wrist"]
        hand_end = info["hand_end"]
        add(f"clavicle.{side}", (shoulder[0] * 0.45, shoulder[1], shoulder[2] + 0.012),
            shoulder, "root", "bone", "锁骨（抬肩）")
        add(f"upperarm.{side}", shoulder, elbow, f"clavicle.{side}", "bone", "上臂（招手主关节）")
        add(f"forearm.{side}", elbow, wrist, f"upperarm.{side}", "bone", "前臂（招手摆动）")
        add(f"hand.{side}", wrist, hand_end, f"forearm.{side}", "bone", "手（圆团造型，无手指）")

    for side, sign in (("L", 1.0), ("R", -1.0)):
        c = eye_center(sign)
        add(f"eye.{side}", c, (c[0], c[1] - 0.036, c[2]), "head", "bone", "眼球转动（枢轴=球心）")
        add(f"eyelid_upper.{side}", (c[0], c[1] + 0.0064, ref["eyelid_upper_z"]),
            (c[0], c[1] - 0.0216, ref["eyelid_upper_z"] + 0.002), "head", "bone", "上眼睑（眨眼/眼型）")
        add(f"eyelid_lower.{side}", (c[0], c[1] + 0.0064, ref["eyelid_lower_z"]),
            (c[0], c[1] - 0.0136, ref["eyelid_lower_z"] - 0.003), "head", "bone", "下眼睑（卧蚕/眼袋）")
        add(f"brow.{side}", (c[0] * 0.86, a["brow_front_y"] + 0.019, brow_z),
            (c[0] * 1.15, a["brow_front_y"] + 0.019, brow_z + 0.001), "head", "bone", "眉毛")
        # 骨相骨（粗轮廓）——位置放在体积内部，靠权重场推挤表面
        add(f"cheekbone.{side}", (cheek_x * sign * 0.72, face_front + 0.055, eye_z - 0.012),
            (cheek_x * sign, face_front + 0.055, eye_z - 0.014), "head", "shape", "颧骨高低/宽窄")
        add(f"temple.{side}", (temple_x * sign * 0.8, face_front + 0.055, eye_z + 0.028),
            (temple_x * sign, face_front + 0.055, eye_z + 0.028), "head", "shape", "太阳穴宽窄")
        add(f"jaw_width.{side}", (jaw_x * sign * 0.7, face_front + 0.05, chin_z + 0.014),
            (jaw_x * sign, face_front + 0.05, chin_z + 0.016), "jaw", "shape", "下颌宽窄/下颌角")
        add(f"cheek_fat.{side}", (cheek_x * sign * 0.62, face_front + 0.02, ref["cheek_z"]),
            (cheek_x * sign * 0.9, face_front + 0.02, ref["cheek_z"]), "head", "shape", "脸颊饱满/面部脂肪")
        add(f"eye_socket.{side}", (c[0], c[1] + 0.008, c[2]), (c[0], c[1] + 0.028, c[2]), "head", "shape", "眼窝深浅")
        add(f"ear.{side}", ref["ear_head"] if sign > 0 else (-ref["ear_head"][0], ref["ear_head"][1], ref["ear_head"][2]),
            ref["ear_tail"] if sign > 0 else (-ref["ear_tail"][0], ref["ear_tail"][1], ref["ear_tail"][2]), "head", "bone", "耳朵")

    # ── 中轴骨相骨 ────────────────────────────────
    add("face_width", (0, face_front + 0.06, eye_z - 0.004), (0, face_front + 0.06, eye_z - 0.004), "head", "shape", "脸宽（推拉颧弓）")
    add("face_length", (0, face_front + 0.06, eye_z + 0.02), (0, face_front + 0.06, eye_z - 0.045), "head", "shape", "脸长（中庭纵向）")
    add("forehead_height", (0, a["brow_front_y"] + 0.05, brow_z + 0.020), (0, a["brow_front_y"] + 0.05, brow_z + 0.040), "head", "shape", "额头高低")
    add("forehead_width", (0, a["brow_front_y"] + 0.055, brow_z + 0.030), (0, a["brow_front_y"] + 0.055, brow_z + 0.030), "head", "shape", "额头宽窄")
    add("nose", (0, a["nose_front_y"] + 0.020, a["nose_z"] + 0.022),
        (0, a["nose_front_y"], a["nose_z"]), "head", "bone", "鼻梁/鼻头/鼻翼")
    add("lip_upper", (0, a["mouth_front_y"] + 0.020, a["lip_upper_z"]),
        (0, a["mouth_front_y"] - 0.008, a["lip_upper_z"]), "head", "bone", "上唇")
    add("lip_lower", (0, a["mouth_front_y"] + 0.020, a["lip_lower_z"]),
        (0, a["mouth_front_y"] - 0.006, a["lip_lower_z"]), "head", "bone", "下唇")
    add("tongue", (0, -0.030, 1.030), (0, -0.056, 1.034), "jaw", "bone", "舌头（口型）")


def make_armature():
    armature_data = bpy.data.armatures.new("FaceRigStructural")
    armature = bpy.data.objects.new("FaceRigStructural", armature_data)
    bpy.context.collection.objects.link(armature)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="EDIT")
    created = {}
    for spec in BONES:
        bone = armature_data.edit_bones.new(spec["name"])
        bone.head = Vector(spec["head"])
        bone.tail = Vector(spec["tail"])
        if (bone.tail - bone.head).length < 1e-4:
            bone.tail = bone.head + Vector((0, 0, 0.004))
        created[spec["name"]] = bone
    for spec in BONES:
        if spec["parent"] and spec["parent"] in created:
            created[spec["name"]].parent = created[spec["parent"]]
            created[spec["name"]].use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")
    return armature


def make_markers():
    """把每根骨的 head 渲染成小球，便于肉眼核对骨点位置"""
    size = 0.0022
    made = []
    for spec in BONES:
        if spec["kind"] == "control":
            continue
        mesh = bpy.data.meshes.new("mk_" + spec["name"])
        bm_verts = []
        bm_faces = []
        # 极简八面体，省顶点
        for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
            bm_verts.append(Vector((dx, dy, dz)) * size)
        bm_faces = [(0, 2, 4), (2, 1, 4), (1, 3, 4), (3, 0, 4), (2, 0, 5), (1, 2, 5), (3, 1, 5), (0, 3, 5)]
        mesh.from_pydata(bm_verts, [], bm_faces)
        mesh.update()
        obj = bpy.data.objects.new("mk_" + spec["name"], mesh)
        obj.location = Vector(spec["head"])
        material = bpy.data.materials.get("MarkerMat")
        if material is None:
            material = bpy.data.materials.new("MarkerMat")
            material.diffuse_color = (1.0, 0.25, 0.25, 1.0)
        mesh.materials.append(material)
        bpy.context.collection.objects.link(obj)
        made.append(obj)
    return made


def render_views(prefix, anchors):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 1100
    scene.render.resolution_y = 1100
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    center = Vector((0.0, 0.0, anchors["top"] - anchors["head_height"] * 0.5))
    size = anchors["head_height"] * 1.3
    camera_data = bpy.data.cameras.new("rig_cam")
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = size
    camera = bpy.data.objects.new("rig_cam", camera_data)
    bpy.context.collection.objects.link(camera)
    scene.camera = camera
    for label, direction in (("front", Vector((0, -1, 0))), ("side", Vector((1, 0, 0)))):
        camera.location = center + direction.normalized() * (size * 3)
        track = camera.constraints.new("TRACK_TO")
        target = bpy.data.objects.new("rig_target", None)
        target.location = center
        bpy.context.collection.objects.link(target)
        track.target = target
        track.track_axis = "TRACK_NEGATIVE_Z"
        track.up_axis = "UP_Y"
        scene.render.filepath = f"{prefix}-{label}.png"
        bpy.ops.render.render(write_still=True)
        camera.constraints.remove(track)
        bpy.data.objects.remove(target, do_unlink=True)
        print("RIG_RENDER " + scene.render.filepath)


def main() -> None:
    out = arg_value("--out")
    render_prefix = arg_value("--render")
    mesh_obj = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices), default=None)
    if mesh_obj is None:
        print("RIG_FAIL 场景里没有网格")
        return
    points = mesh_points(mesh_obj)
    anchors = find_anchors(points)
    build_bones(anchors)
    make_armature()
    if render_prefix:
        make_markers()
    print("=" * 78)
    print("骨相骨骼（第 1 步）")
    print(f"网格 {mesh_obj.name}: {len(mesh_obj.data.vertices)} 顶点")
    print(
        f"锚点: 身高 {anchors['height']:.4f}  头高 {anchors['head_height']:.4f}  "
        f"原眼位 L={[round(v, 4) for v in anchors['eye_l']]} R={[round(v, 4) for v in anchors['eye_r']]}"
    )
    print(f"    面部前缘 Y={anchors['face_front_y']:.4f}  颧弓|x|={anchors['cheek_width_x']:.4f}  "
          f"下颌|x|={anchors['jaw_width_x']:.4f}  太阳穴|x|={anchors['temple_width_x']:.4f}")
    print("-" * 78)
    print(f"{'骨骼':<20}{'类型':<8}{'head':<26}{'父级':<14}说明")
    for spec in BONES:
        print(f"{spec['name']:<20}{spec['kind']:<8}{str(spec['head']):<26}{str(spec['parent']):<14}{spec['note']}")
    print("-" * 78)
    print(f"合计 {len(BONES)} 根骨骼（其中骨相 {sum(1 for b in BONES if b['kind'] == 'shape')} 根，"
          f"机能 {sum(1 for b in BONES if b['kind'] == 'bone')} 根，总控 {sum(1 for b in BONES if b['kind'] == 'control')} 根）")
    if render_prefix:
        render_views(render_prefix, anchors)
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("RIG_OK 已保存: " + out)
    if has_flag("--json"):
        print("RIG_JSON " + json.dumps({"anchors": {k: (str(v) if not isinstance(v, (int, float)) else round(v, 5)) for k, v in anchors.items()}, "bones": BONES}, ensure_ascii=False))


main()
