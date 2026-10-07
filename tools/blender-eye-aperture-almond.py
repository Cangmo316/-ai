#!/usr/bin/env python3
"""
比邻AI · 眼裂口重雕（按原型图的**杏仁轮廓**放样切割体，替换布尔球的圆洞）

用法：
    blender --background <资产.blend> --python tools/blender-env.py \
        --python tools/blender-eye-aperture-almond.py -- --out <输出.blend> \
            [--half-w-mm 10.0] [--upper-mm 3.1] [--lower-mm -2.5] [--tilt-deg 6]
            [--y-offset-mm 0] [--report]

**为什么不用布尔球**（上一轮的问题）：布尔球挖出来的是**正圆洞**，
所以眼裂是"圆眼"；原型图是**细长杏仁**（内眼角尖、外眼角上挑、上睑弧大下睑弧小）。
这里按参数生成一个**杏仁透镜形（两段圆弧夹出的 lens）**截面，沿 +Y 放样成实体，
再对脸部做布尔差集 → 挖出的洞就是杏仁形。

参数（相对 `eye.L/eye.R` 枢轴，单位 mm）：
  · `--half-w-mm`  水平半宽（内→外眼角）
  · `--upper-mm`   上睑最高点（相对枢轴 z 的偏移）
  · `--lower-mm`   下睑最低点（负值）
  · `--tilt-deg`   外眼角上挑角
  · `--y-offset-mm` 截面在 Y 上的位置（负数往脸内推）
"""

import json
import math
import os
import sys

import bmesh
import bpy
import numpy as np


def arg_value(name, default=None):
    args = sys.argv
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return default


def has_flag(name):
    return name in sys.argv


EYE = {"L": {"center": (0.01762, -0.05324, 1.06798), "side": 1.0},
       "R": {"center": (-0.01769, -0.05388, 1.06787), "side": -1.0}}


def almond_outline(half_w, upper, lower, tilt_rad, segments):
    """两段圆弧夹出的杏仁轮廓：上弧（高 upper）与下弧（低 lower），两端在 ±half_w 收尖。
    返回 [(x, z), ...] 逆时针闭合环（相对枢轴的 x/z 偏移，米）。"""
    points = []
    # 上弧：从内眼角到外眼角（用椭圆弧的一半，但相位错开让两端收尖）
    for index in range(segments + 1):
        t = index / segments                 # 0 → 1（内 → 外）
        theta = math.pi * t                  # 0..pi
        x = -half_w + 2 * half_w * t
        z = upper * math.sin(theta)          # 两端为 0 → 自然收尖
        points.append((x, z))
    # 下弧：从外眼角回内眼角
    for index in range(1, segments):
        t = index / segments
        x = half_w - 2 * half_w * t
        z = lower * math.sin(math.pi * t)
        points.append((x, z))
    # 外眼角上挑：整体绕内眼角轻微旋转
    rotated = []
    for x, z in points:
        cos_t, sin_t = math.cos(tilt_rad), math.sin(tilt_rad)
        rotated.append((x * cos_t - z * sin_t, x * sin_t + z * cos_t))
    return rotated


def main():
    out = arg_value("--out")
    half_w = float(arg_value("--half-w-mm", "10.0")) / 1000.0
    upper = float(arg_value("--upper-mm", "3.1")) / 1000.0
    lower = float(arg_value("--lower-mm", "-2.5")) / 1000.0
    tilt = math.radians(float(arg_value("--tilt-deg", "6.0")))
    y_offset = float(arg_value("--y-offset-mm", "0")) / 1000.0
    segments = int(arg_value("--segments", "24"))
    depth = float(arg_value("--depth-mm", "30.0")) / 1000.0
    want_report = has_flag("--report")

    mesh_obj = max((o for o in bpy.data.objects if o.type == "MESH" and o.data.shape_keys is not None),
                   key=lambda o: len(o.data.vertices))
    before = {"verts": len(mesh_obj.data.vertices),
              "tris": sum(len(p.vertices) - 2 for p in mesh_obj.data.polygons)}
    print("=" * 92)
    print("眼裂口重雕（杏仁轮廓） : " + bpy.data.filepath)
    print("  输入 %d 顶点 / %d 三角面" % (before["verts"], before["tris"]))
    print("  杏仁参数：半宽 %.2fmm / 上 %.2fmm / 下 %.2fmm / 上挑 %.1f° / Y 偏移 %.2fmm"
          % (half_w * 1000, upper * 1000, lower * 1000, math.degrees(tilt), y_offset * 1000))

    # ── 备份形态键 delta 与权重（布尔会加顶点）──
    mesh = mesh_obj.data
    count = len(mesh.vertices)
    base = np.empty(count * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", base)
    base = base.reshape(count, 3)
    key_delta = {}
    for block in mesh.shape_keys.key_blocks:
        positions = np.empty(count * 3, dtype=np.float64)
        block.data.foreach_get("co", positions)
        key_delta[block.name] = positions.reshape(count, 3) - base
    group_index = {g.index: g.name for g in mesh_obj.vertex_groups}
    vertex_weights = [dict() for _ in range(count)]
    for vertex in mesh.vertices:
        for element in vertex.groups:
            name = group_index.get(element.group)
            if name:
                vertex_weights[vertex.index][name] = element.weight

    bpy.context.view_layer.objects.active = mesh_obj
    mesh_obj.select_set(True)
    bpy.ops.object.shape_key_remove(all=True)

    # ── 生成两个杏仁切割体并做布尔差集 ──
    created = []
    for side, spec in EYE.items():
        center = np.array(spec["center"])
        sign = spec["side"]
        outline = almond_outline(half_w, upper, lower, tilt, segments)
        mesh_cut = bpy.data.meshes.new("almond_%s" % side)
        cut = bpy.data.objects.new("almond_%s" % side, mesh_cut)
        bpy.context.scene.collection.objects.link(cut)
        bm = bmesh.new()
        # 截面 1（脸前）与截面 2（脸内），沿 +Y 放样成棱柱
        front, back = [], []
        for (x, z) in outline:
            front.append(bm.verts.new((center[0] + sign * x,
                                       center[1] + y_offset,
                                       center[2] + z)))
        bm.verts.ensure_lookup_table()
        for (x, z) in outline:
            back.append(bm.verts.new((center[0] + sign * x,
                                      center[1] + y_offset + depth,
                                      center[2] + z)))
        bm.verts.ensure_lookup_table()
        n = len(outline)
        for index in range(n):
            nxt = (index + 1) % n
            bm.faces.new((front[index], front[nxt], back[nxt], back[index]))
        bm.faces.new(tuple(reversed(front)))
        bm.faces.new(tuple(back))
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(mesh_cut)
        bm.free()
        created.append(cut)
        modifier = mesh_obj.modifiers.new("EyeAlmond_%s" % side, "BOOLEAN")
        modifier.operation = "DIFFERENCE"
        modifier.object = cut
        modifier.solver = "EXACT"
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        bpy.data.objects.remove(cut, do_unlink=True)
        print("  eye.%s 杏仁切割体：%d 顶点截面，已做布尔差集" % (side, n))

    mesh = mesh_obj.data
    after_count = len(mesh.vertices)
    after_tris = sum(len(p.vertices) - 2 for p in mesh.polygons)
    print("  布尔后：%d 顶点 / %d 三角面（%+d / %+d）"
          % (after_count, after_tris, after_count - before["verts"], after_tris - before["tris"]))

    # ── 新顶点按最近原顶点补权重与 delta ──
    after = np.empty(after_count * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", after)
    after = after.reshape(after_count, 3)
    from mathutils.kdtree import KDTree
    tree = KDTree(count)
    for index in range(count):
        tree.insert(base[index], index)
    tree.balance()
    nearest = np.array([tree.find(after[i])[1] for i in range(after_count)], dtype=np.int32)

    for group in list(mesh_obj.vertex_groups):
        group.remove([v.index for v in mesh.vertices])
    for index in range(after_count):
        for name, weight in vertex_weights[int(nearest[index])].items():
            group = mesh_obj.vertex_groups.get(name) or mesh_obj.vertex_groups.new(name=name)
            group.add([index], float(weight), "REPLACE")

    basis = mesh_obj.shape_key_add(name="Basis", from_mix=False)
    basis.data.foreach_set("co", after.reshape(-1).astype(np.float32))
    for name, delta in key_delta.items():
        block = mesh_obj.shape_key_add(name=name, from_mix=False)
        positions = after + delta[nearest]
        block.data.foreach_set("co", positions.reshape(-1).astype(np.float32))
    for block in mesh.shape_keys.key_blocks:
        block.value = 0.0
    print("  形态键重建：%d 个" % (len(mesh.shape_keys.key_blocks) - 1))

    report = {"file": bpy.data.filepath,
              "almond": {"half_w_mm": half_w * 1000, "upper_mm": upper * 1000,
                         "lower_mm": lower * 1000, "tilt_deg": round(math.degrees(tilt), 2)},
              "before": before, "after": {"verts": after_count, "tris": after_tris}}
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("ALMOND_OK 已保存 " + out)
    if want_report:
        print("ALMOND_JSON " + json.dumps(report, ensure_ascii=False))


main()
