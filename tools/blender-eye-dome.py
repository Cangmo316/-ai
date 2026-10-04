#!/usr/bin/env python3
"""
比邻AI · 眼区重做 v2：把眼窝内部雕成"凸起眼球穹顶"

用法：
    blender --background <工作.blend> --python tools/blender-eye-dome.py -- \
        --out <输出.blend> [--spec <眼区参数.json>] \
        [--dome-radius-mm 16] [--ramp 0.55] [--dry-run]

为什么不用"独立眼球（球体）"——本轮最重要的技术结论（有实测支撑）：
  见 `tools/blender-eye-rebuild2.py` 的半径扫描：把雕塑上**画出来的眼裂**开孔后取真实拓扑边界环，
  扫描球半径 R=9~69mm、每个 R 都解出最优球心，最优也只在 R=15~16mm 时 σ=0.9~1.5mm
  （判据 <0.3mm）、跨度 5~7.5mm。原因是这个眼窝**横跨脸颊的横向曲率**：
  睑缘环的 Y 跨度 12.9mm，而能覆盖该洞口的球在同一环上最多只能有 6.7mm 的 Y 跨度。
  → 插球必然"一侧外凸穿出眼皮、另一侧形成深坑"。历次修复都栽在这条几何事实上。

v2 的形态：**穹顶（dome）**
  1. 用 PCA 拟合**睑缘平面的法线**（这个眼窝自身倾斜约 34°，必须沿它自己的法线鼓，而不是沿正前方）
  2. 在平面内做球冠：w(r) = sqrt(R²-r²) - sqrt(R²-a²)，r=平面内半径，a=睑缘环的平面内平均半径
  3. 用权重场把**内部**顶点过渡到球冠（q=1 的睑缘一圈权重 0，完全不动）
  4. 贴图 UV 不动 → 美术画好的虹膜/瞳孔落在凸面上，成为真正的 3D 眼球
  5. 不开孔 → 无缝隙/漏光/穿模；凸面 → 高光与体积感正常

眼神（gaze）：穹顶按权重场绑定到 eye.L/eye.R 后，转动眼球骨会带动凸面及其上的虹膜一起移动
（贴图随几何走），因此 gaze 仍然可用；眨眼由交付规范的 expr_blink_L/R 形态键承担。
"""

import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

DEFAULT_SPEC = {
    "L": {"center": [0.0269, 1.0686], "half_w": 0.0094, "half_h": 0.0077, "tilt_deg": -4.0},
    "R": {"center": [-0.0269, 1.0686], "half_w": 0.0094, "half_h": 0.0077, "tilt_deg": 4.0},
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


def head_mesh():
    return max((o for o in bpy.data.objects if o.type == "MESH"),
               key=lambda o: len(o.data.vertices), default=None)


def smoothstep(value):
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def normalized_radius(dx, dz, spec):
    """椭圆归一化半径 q：q=1 正好落在眼裂边界上"""
    tilt = math.radians(spec["tilt_deg"])
    ex = dx * math.cos(tilt) + dz * math.sin(tilt)
    ez = -dx * math.sin(tilt) + dz * math.cos(tilt)
    return math.hypot(ex / spec["half_w"], ez / spec["half_h"])


def collect(obj, spec):
    matrix = obj.matrix_world
    cx, cz = spec["center"]
    interior, rim = [], []
    for vertex in obj.data.vertices:
        point = matrix @ vertex.co
        if point.y > 0.0:
            continue
        dx, dz = point.x - cx, point.z - cz
        if abs(dx) > 0.022 or abs(dz) > 0.019:
            continue
        q = normalized_radius(dx, dz, spec)
        if q < 1.0:
            interior.append((vertex.index, point, q))
        elif q < 1.10:
            rim.append(point)
    return interior, rim


def fit_plane(points):
    """PCA 拟合平面：返回 (质心, 单位法线，法线朝 -Y 即脸的前方)"""
    array = np.array([[p.x, p.y, p.z] for p in points])
    centroid = array.mean(axis=0)
    centered = array - centroid
    _values, vectors = np.linalg.eigh(centered.T @ centered)
    normal = vectors[:, 0]                     # 最小特征值 → 法线
    if normal[1] > 0:                          # 朝前（-Y）
        normal = -normal
    _values, vectors = np.linalg.eigh(centered.T @ centered)
    normal = normal / np.linalg.norm(normal)
    residuals = centered @ normal
    return centroid, normal, float(np.sqrt((residuals ** 2).mean()))


def analyze_eye(obj, spec, side, dome_radius, ramp, dry):
    interior, rim = collect(obj, spec)
    if len(interior) < 30 or len(rim) < 30:
        return {"side": side, "error": f"内部 {len(interior)} / 边界 {len(rim)} 顶点不足"}
    centroid, normal, plane_sigma = fit_plane(rim)
    normal_vector = Vector((float(normal[0]), float(normal[1]), float(normal[2])))
    centroid_vector = Vector((float(centroid[0]), float(centroid[1]), float(centroid[2])))

    def in_plane(point):
        delta = point - centroid_vector
        height = delta.dot(normal_vector)
        radial = delta - normal_vector * height
        return radial.length, height

    rim_radii = [in_plane(point)[0] for point in rim]
    cap_radius = float(np.mean(rim_radii))          # a：睑缘环在平面内的平均半径
    rim_heights = [in_plane(point)[1] for point in rim]
    base = math.sqrt(max(1e-9, dome_radius ** 2 - cap_radius ** 2))

    def dome_height(radial):
        inside = max(0.0, dome_radius ** 2 - radial ** 2)
        return math.sqrt(inside) - base

    moved = 0
    max_shift = 0.0
    shifts = []
    if not dry:
        for index, point, q in interior:
            weight = smoothstep((1.0 - q) / max(1e-6, ramp))
            if weight <= 0.0:
                continue
            radial, height = in_plane(point)
            target = dome_height(radial)
            shift = (target - height) * weight
            if abs(shift) < 1e-7:
                continue
            vertex = obj.data.vertices[index]
            vertex.co = vertex.co + normal_vector * shift
            moved += 1
            shifts.append(shift)
            max_shift = max(max_shift, abs(shift))
        obj.data.update()

    apex = dome_height(0.0)
    # 球心（世界坐标）：球面方程 (w+base)² + r² = R² → 球心在平面法线方向 w = -base 处
    dome_center = centroid_vector - normal_vector * base
    samples = [{"radial_mm": round(cap_radius * k / 8.0 * 1000, 2),
                "dome_height_mm": round(dome_height(cap_radius * k / 8.0) * 1000, 3)}
               for k in range(9)]
    return {
        "side": side,
        "spec": spec,
        "interior_vertices": len(interior),
        "rim_vertices": len(rim),
        "plane_normal": [round(float(v), 5) for v in normal_vector],
        "plane_tilt_deg": round(math.degrees(math.acos(min(1.0, abs(float(normal_vector.y))))), 2),
        "plane_sigma_mm": round(plane_sigma * 1000, 3),
        "cap_radius_mm": round(cap_radius * 1000, 2),
        "rim_height_span_mm": round((max(rim_heights) - min(rim_heights)) * 1000, 2),
        "dome_radius_mm": round(dome_radius * 1000, 2),
        "dome_apex_mm": round(apex * 1000, 3),
        "dome_center": [round(float(v), 6) for v in dome_center],
        "moved_vertices": moved,
        "max_shift_mm": round(max_shift * 1000, 3),
        "shift_mean_mm": round(float(np.mean(shifts)) * 1000, 3) if shifts else 0.0,
        "dome_profile": samples,
    }


def apply_transforms(objects):
    """把对象变换**烘进网格/骨架**，使"局部坐标 == 世界坐标"

    ⚠️ 这是本资产一个极容易踩的坑：原始 FBX 导入的网格带着一个 -90° 绕 X 的旋转
    （局部 `co` 里 **Y 是身高**、Z 是进深），而骨骼的 `head_local` 是**世界制**（Z 是身高）。
    只要有一处用 `foreach_get("co")` 拿局部坐标去和骨骼位置比，就会整体差 90°
    （实测：骨相骨高斯场算出的最近距离是 0.96 米 —— 全落到身体外面，权重全 0）。
    绑定/导出前统一烘掉，之后所有工具都能直接用 `co`。
    """
    applied = []
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        if obj is None:
            continue
        matrix = obj.matrix_world
        is_identity = all(abs(matrix[i][j] - (1.0 if i == j else 0.0)) < 1e-9
                          for i in range(4) for j in range(4))
        if is_identity:
            continue
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        obj.select_set(False)
        applied.append(obj.name)
    return applied


def clean_helpers():
    """删掉第 1 步骨骼定位留下的 `mk_*` 标记球与工具相机

    ⚠️ 不删的话它们会被一起导出（实测：眼区渲染里出现红色菱形就是它们），
    而且会污染三角面预算与材质数量。
    """
    removed = []
    for obj in list(bpy.data.objects):
        name = obj.name
        if name.startswith("mk_") or name in ("rig_cam", "survey_cam", "probe_cam",
                                              "macro_cam", "macro_target", "rig_target"):
            removed.append(name)
            bpy.data.objects.remove(obj, do_unlink=True)
    for material in list(bpy.data.materials):
        if material.name == "MarkerMat" and material.users == 0:
            bpy.data.materials.remove(material)
            removed.append("material:MarkerMat")
    return removed


def move_eye_bones(dome_centers):
    """把 `eye.L/eye.R` 的枢轴移到穹顶的球心（gaze 必须绕球心转）

    原先这两根骨位于 (±0.0349, -0.0584, 1.0701) —— 那是 **eye.L 顶点组（眼皮皮肤）的形心**，
    不是眼球中心；绕它转会把眼球"甩"出去，也是上一轮眼神不对的一个来源。
    """
    armature = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if armature is None:
        return {}
    moved = {}
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="EDIT")
    for side, center in dome_centers.items():
        bone = armature.data.edit_bones.get(f"eye.{side}")
        if bone is None:
            continue
        head = Vector(center)
        bone.head = head
        bone.tail = head + Vector((0, -0.036, 0))
        moved[f"eye.{side}"] = [round(v, 6) for v in head]
    bpy.ops.object.mode_set(mode="OBJECT")
    return moved


def main():
    out = arg_value("--out")
    spec_path = arg_value("--spec")
    dome_radius = float(arg_value("--dome-radius-mm", "16")) / 1000.0
    ramp = float(arg_value("--ramp", "0.55"))
    dry = has_flag("--dry-run")
    keep_helpers = has_flag("--keep-helpers")
    spec = DEFAULT_SPEC
    if spec_path and os.path.exists(spec_path):
        with open(spec_path, encoding="utf-8") as handle:
            spec = json.load(handle)

    obj = head_mesh()
    if obj is None:
        print("EYE_DOME_FAIL 没有网格")
        return

    armature_object = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    report = {"file": bpy.data.filepath, "mesh": obj.name, "eyes": []}
    if not dry:
        report["transforms_applied"] = apply_transforms([obj, armature_object])
    dome_centers = {}
    for side in ("L", "R"):
        entry = analyze_eye(obj, spec[side], side, dome_radius, ramp, dry)
        report["eyes"].append(entry)
        if "dome_center" in entry:
            dome_centers[side] = entry["dome_center"]
    if not dry:
        report["eye_bones_moved"] = move_eye_bones(dome_centers)
        report["removed_helpers"] = [] if keep_helpers else clean_helpers()

    print("=" * 96)
    print("眼区 v2 穹顶 : " + bpy.data.filepath + ("   [dry-run]" if dry else ""))
    for eye in report["eyes"]:
        print("")
        if "error" in eye:
            print(f"--- [{eye['side']}] {eye['error']}")
            continue
        print(f"--- [{eye['side']}] 眼裂椭圆 中心{eye['spec']['center']} "
              f"半宽 {eye['spec']['half_w'] * 1000:.1f}mm 半高 {eye['spec']['half_h'] * 1000:.1f}mm "
              f"倾角 {eye['spec']['tilt_deg']}°")
        print(f"    睑缘平面：法线 {eye['plane_normal']}  相对正前方倾斜 "
              f"{eye['plane_tilt_deg']}°  平面拟合 σ={eye['plane_sigma_mm']}mm")
        print(f"              平面内平均半径 a={eye['cap_radius_mm']}mm  "
              f"睑缘点离平面高度跨度 {eye['rim_height_span_mm']}mm")
        print(f"    穹顶：R={eye['dome_radius_mm']}mm → 顶点凸起 {eye['dome_apex_mm']}mm")
        print(f"    位移：{eye['moved_vertices']} 个顶点，最大 {eye['max_shift_mm']}mm，"
              f"平均 {eye['shift_mean_mm']}mm")
        print(f"    穹顶剖面（半径 → 凸起高度）：")
        print("      " + "  ".join(f"{s['radial_mm']:g}mm:{s['dome_height_mm']:g}"
                                  for s in eye["dome_profile"]))
    if out and not dry:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("EYE_DOME_OK 已保存 " + out)
    print("EYE_DOME_JSON " + json.dumps(report, ensure_ascii=False))


main()
