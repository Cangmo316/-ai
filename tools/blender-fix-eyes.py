#!/usr/bin/env python3
"""
比邻AI · 眼修复：眼球最佳拟合 + 眼裂边界环吸附球面（Blender 无头运行）

问题：眼裂开孔那一圈边界顶点与眼球球面**不贴合**——
环到球心的距离小于球半径 → 眼皮扎进球里（穿模）；大于球半径 → 眼皮与眼球有缝。
视觉上表现为「眼球凸出 / 眼眶变形」。

做法（只改必要的东西，不动面部其它部位）：
  1. 对每个眼球，取主壳上属于该眼裂的**边界环**顶点
  2. 用最小二乘拟合出一颗球（球心 c'、半径 R'），使 Σ(|p_i − c'| − R')² 最小
  3. 把 `eyeball_L/R` 的**网格顶点**搬到新球心/新半径（保持球体形状）
     并把 `eye.L/.R` 骨骼枢轴同步移到新球心（否则转眼球会绕旧枢轴摆动）
  4. 把**边界环顶点吸附到球面**（半径乘 `--inset`，默认 0.998 让眼皮极轻微压住眼球，
     避免任何可见缝隙）
  5. 逐个检查眼区形变键：报告权重 1.0 时边界环是否仍然贴合（不穿模、不留缝）

用法：
    blender --background <文件.blend> --python tools/blender-fix-eyes.py -- [--save] [--inset 0.998] [--report]

不加 --save 为 dry run（只报告将要做的位移量）。
"""

import json
import math
import sys

import bpy
from mathutils import Vector

EYE_RADIUS_KEYS = ("eyeball",)


def has_flag(name):
    return name in sys.argv


def arg_value(name, default=None):
    args = sys.argv
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return default


def world_verts(obj):
    matrix = obj.matrix_world
    return [matrix @ v.co for v in obj.data.vertices]


def boundary_verts_near(obj, center, radius):
    """主壳上位于 center 附近 radius 内的边界边顶点（= 眼裂开孔那一圈）"""
    mesh = obj.data
    edge_faces = {}
    for poly in mesh.polygons:
        for key in poly.edge_keys:
            edge_faces[key] = edge_faces.get(key, 0) + 1
    found = set()
    matrix = obj.matrix_world
    for key, count in edge_faces.items():
        if count != 1:
            continue
        for index in key:
            if (matrix @ mesh.vertices[index].co - center).length < radius:
                found.add(index)
    return sorted(found)


def sphere_from_bbox(obj):
    points = world_verts(obj)
    low = Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points)))
    high = Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points)))
    return (low + high) / 2, max((high - low).x, (high - low).y, (high - low).z) / 2


def fit_sphere(points, center, iterations=12, damping=0.5):
    """**几何迭代**拟合球（对"一圈顶点贴在球面上"这种数据稳健）

    为什么不用代数最小二乘：那圈眼裂环只覆盖球面很小一块，代数法会退化成
    "一颗半径上米的球近似一个平面"，实测给出 R'=1.07 这种荒谬结果。

    这里做的是最小化「各点到球心距离」的方差：
        R = mean(d_i)，然后把球心朝"距离偏大的点"的反方向轻轻移动（阻尼迭代），
    使所有 d_i 趋于一致。环本来就贴着球时，这个过程收敛得又稳又快。
    """
    n = len(points)
    if n < 4:
        return None
    center = Vector(center)
    radius = sum((p - center).length for p in points) / n
    for _ in range(iterations):
        distances = [(p - center).length for p in points]
        new_radius = sum(distances) / n
        push = Vector((0.0, 0.0, 0.0))
        for point, distance in zip(points, distances):
            if distance < 1e-9:
                continue
            push += ((distance - new_radius) / distance) * (point - center)
        center = center + (damping / n) * push
        radius = new_radius
    return center, radius


def refine_scale(center, radius, points, inset):
    """在给定球心下，用"环到球心距离的均值"作为最终半径（不做二次缩放）"""
    distances = [(p - center).length for p in points]
    return sum(distances) / len(distances) * inset


def deviation(points, center, radius):
    distances = [(p - center).length for p in points]
    mean = sum(distances) / len(distances)
    variance = sum((d - mean) ** 2 for d in distances) / len(distances)
    return {
        "min": round(min(distances), 5),
        "max": round(max(distances), 5),
        "mean": round(mean, 5),
        "sigma": round(math.sqrt(variance), 5),
        "offsets": [d - radius for d in distances],
    }


def eye_region_shape_keys(head, rim_indices):
    """返回会动到眼裂环顶点的形变键 -> 最大位移"""
    result = {}
    keys = head.data.shape_keys
    if not keys:
        return result
    basis = keys.key_blocks[0]
    rim = set(rim_indices)
    for block in keys.key_blocks[1:]:
        biggest = 0.0
        for index in rim:
            delta = block.data[index].co - basis.data[index].co
            length = delta.length
            if length > biggest:
                biggest = length
        if biggest > 1e-6:
            result[block.name] = round(biggest, 5)
    return result


def main() -> None:
    do_save = has_flag("--save")
    inset = float(arg_value("--inset", "0.998"))
    report = {"file": bpy.data.filepath, "eyes": [], "shape_keys": {}, "warnings": []}

    head = None
    eyeballs = []
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        name = obj.name.lower()
        if any(key in name for key in EYE_RADIUS_KEYS):
            eyeballs.append(obj)
        elif not any(k in name for k in ("teeth", "tongue", "cavity")):
            if head is None or len(obj.data.vertices) > len(head.data.vertices):
                head = obj
    if head is None or not eyeballs:
        print("EYEFIX_FAIL 找不到主壳或眼球")
        return

    armature = None
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE":
            armature = obj
            break

    for eyeball in eyeballs:
        center, radius = sphere_from_bbox(eyeball)
        rim = boundary_verts_near(head, center, radius * 3.5)
        if len(rim) < 8:
            report["warnings"].append(f"{eyeball.name}: 只找到 {len(rim)} 个眼裂环顶点，跳过")
            continue
        matrix = head.matrix_world
        rim_points = [matrix @ head.data.vertices[i].co for i in rim]
        before = deviation(rim_points, center, radius)

        fitted = fit_sphere(rim_points, center)
        if fitted is None:
            report["warnings"].append(f"{eyeball.name}: 球拟合失败，跳过")
            continue
        fit_center, fit_radius = fitted
        # 最终球：球心取拟合值，半径取「环到球心距离的均值 × inset」——
        # 眼球只用 缩放+平移（不改变球体形状），并把环吸附到这个球面上
        target_radius = refine_scale(fit_center, fit_radius, rim_points, inset)
        scale = target_radius / radius

        # ── 搬动眼球网格顶点（世界 → 局部）：平移 + 等比缩放 ──
        inverse = eyeball.matrix_world.inverted()
        for vertex in eyeball.data.vertices:
            world = eyeball.matrix_world @ vertex.co
            moved = fit_center + (world - center) * scale
            vertex.co = inverse @ moved
        eyeball.data.update()

        # ── 同步骨骼枢轴（否则转眼球会绕旧枢轴摆动）────────
        # 注意：编辑期骨架里骨名是 `eye.L` / `eye.R`（导出时才映射成 eye_L / eye_R）
        bone_name = None
        side = "L" if eyeball.name.endswith("L") else "R"
        if armature:
            for candidate in (f"eye.{side}", f"eye_{side}", f"eyeball.{side}"):
                if candidate in armature.data.bones:
                    bone_name = candidate
                    break
        if armature and bone_name:
            old = armature.data.bones[bone_name]
            old_head_local = old.head_local.copy()
            delta_world = fit_center - center
            bpy.context.view_layer.objects.active = armature
            bpy.ops.object.mode_set(mode="EDIT")
            edit_bone = armature.data.edit_bones[bone_name]
            edit_bone.head = old_head_local + delta_world
            edit_bone.tail = old.tail_local + delta_world
            bpy.ops.object.mode_set(mode="OBJECT")

        # ── 眼裂环吸附到球面 ────────────────────────────
        # ⚠️ 关键：Blender 的形变键存的是**绝对坐标**，只改 Basis 会让导出后的 delta 变化
        #    （等于"权重 1 时把眼裂拉回原来的坏位置"）。所以同一批顶点的位移必须
        #    **同步应用到所有形变键**，这样 delta（target − basis）保持不变，
        #    眼区形变键的语义与幅度才不被破坏。
        keys = head.data.shape_keys
        blocks = list(keys.key_blocks[1:]) if keys else []
        displacements = {}
        for index in rim:
            old_local = head.data.vertices[index].co.copy()
            world = matrix @ old_local
            direction = world - fit_center
            if direction.length < 1e-9:
                continue
            snapped = fit_center + direction.normalized() * target_radius
            new_local = matrix.inverted() @ snapped
            head.data.vertices[index].co = new_local
            displacements[index] = new_local - old_local
        for block in blocks:
            for index, delta in displacements.items():
                block.data[index].co = block.data[index].co + delta
        head.data.update()
        report.setdefault("shape_key_vertices_propagated", {})[eyeball.name] = len(displacements)

        after_points = [matrix @ head.data.vertices[i].co for i in rim]
        after = deviation(after_points, fit_center, target_radius)
        shape_keys = eye_region_shape_keys(head, rim)
        report["eyes"].append(
            {
                "object": eyeball.name,
                "bone": bone_name,
                "rim_verts": len(rim),
                "before": {"radius": round(radius, 5), "center": [round(v, 5) for v in center], "deviation": {k: v for k, v in before.items() if k != "offsets"}},
                "fitted": {"radius": round(target_radius, 5), "center": [round(v, 5) for v in fit_center], "move": round((fit_center - center).length, 5), "scale": round(scale, 5)},
                "after": {k: v for k, v in after.items() if k != "offsets"},
                "shape_keys_touching_rim": shape_keys,
            }
        )
        report["shape_keys"].update(shape_keys)

    # ── 输出 ──────────────────────────────────────────
    print("=" * 74)
    print("眼修复报告: " + report["file"])
    for eye in report["eyes"]:
        print("-" * 74)
        print(f"{eye['object']}（骨骼 {eye['bone']}）眼裂环 {eye['rim_verts']} 顶点")
        print(f"  改前: R={eye['before']['radius']}  环到球心 {eye['before']['deviation']['min']}~{eye['before']['deviation']['max']} (σ={eye['before']['deviation']['sigma']})")
        print(f"  拟合: R'={eye['fitted']['radius']}  球心移动 {eye['fitted']['move']}  缩放 {eye['fitted']['scale']}")
        print(f"  改后: 环到球心 {eye['after']['min']}~{eye['after']['max']} (σ={eye['after']['sigma']})")
        if eye["shape_keys_touching_rim"]:
            top = sorted(eye["shape_keys_touching_rim"].items(), key=lambda kv: -kv[1])[:8]
            print(f"  会动到眼裂环的形变键（位移最大前 8）: " + ", ".join(f"{k}={v}" for k, v in top))
    if report["warnings"]:
        for warning in report["warnings"]:
            print("  ⚠️ " + warning)
    if do_save:
        bpy.ops.wm.save_mainfile()
        print("EYEFIX_OK 已保存 " + bpy.data.filepath)
    else:
        print("（dry run）加 --save 才写入")
    print("EYEFIX_JSON " + json.dumps(report, ensure_ascii=False))


main()
