#!/usr/bin/env python3
"""
比邻AI · 眼裂开口（布尔挖洞，让独立眼球成为可见表面）

用法：
    blender --background <带眼球的资产.blend> --python tools/blender-env.py \
        --python tools/blender-eye-aperture.py -- --out <输出.blend> \
            [--cut-radius-mm 9.2] [--report]

**为什么必须挖洞**（实测结论，见任务笔记 §8.22.3）：
  v2 的扫描网格在眼区是**一整片连续凸壳**，没有真正的眼裂开口；
  它的最前缘（y=−0.0665）比眼球球面（y=−0.0617）还靠前 5mm，
  所以眼球被整片壳盖住。任何"推壳/塑形"都只是改壳的形状，眼球都露不出来。

做法：
  1. 用**比眼球略大的球**（默认 9.2mm vs 眼球 8.5mm）对主网格做布尔差集，
     把眼球前方那层壳连同它后面的球内空间一起挖掉 → 得到一个能容纳眼球的凹眼窝；
  2. 挖洞会**新增顶点**，所以：
     · 先把全部形态键的绝对坐标存下来（`key_blocks` 的 `data`）；
     · 删形态键 → 应用布尔 → 对新增顶点用**最近原顶点的 delta** 重建；
     · 权重同理（新增顶点复制最近原顶点的顶点组权重）；
  3. 挖洞后检查"眼球是否成为最前表面"，并把结果打出来。
"""

import json
import os
import sys

import bmesh
import bpy
import numpy as np
from mathutils.kdtree import KDTree


def arg_value(name, default=None):
    args = sys.argv
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return default


def has_flag(name):
    return name in sys.argv


EYEBALL = {"L": {"center": (0.01762, -0.05324, 1.06798), "radius": 0.0085},
           "R": {"center": (-0.01769, -0.05388, 1.06787), "radius": 0.00863}}


def build_cutters(cut_radius_mm):
    cutters = []
    for side, spec in EYEBALL.items():
        mesh = bpy.data.meshes.new("cut_%s" % side)
        obj = bpy.data.objects.new("cut_%s" % side, mesh)
        bpy.context.scene.collection.objects.link(obj)
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=16,
                                  radius=cut_radius_mm / 1000.0)
        bm.to_mesh(mesh)
        bm.free()
        obj.location = spec["center"]
        cutters.append(obj)
    return cutters


def main():
    out = arg_value("--out")
    cut_radius_mm = float(arg_value("--cut-radius-mm", "9.2"))
    want_report = has_flag("--report")

    mesh_obj = max((o for o in bpy.data.objects if o.type == "MESH" and o.data.shape_keys is not None),
                   key=lambda o: len(o.data.vertices))
    mesh = mesh_obj.data
    before_count = len(mesh.vertices)
    before_tris = sum(len(p.vertices) - 2 for p in mesh.polygons)
    print("=" * 92)
    print("眼裂开口（布尔挖洞） : " + bpy.data.filepath)
    print("  输入：%d 顶点 / %d 三角面 / %d 形态键"
          % (before_count, before_tris, len(mesh.shape_keys.key_blocks) - 1))

    base = np.empty(before_count * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", base)
    base = base.reshape(before_count, 3)

    # ── 1) 备份形态键（绝对坐标）与权重 ──
    key_data = {}
    for block in mesh.shape_keys.key_blocks:
        positions = np.empty(before_count * 3, dtype=np.float64)
        block.data.foreach_get("co", positions)
        key_data[block.name] = positions.reshape(before_count, 3) - base
    group_names = [g.name for g in mesh_obj.vertex_groups]
    group_index = {g.index: g.name for g in mesh_obj.vertex_groups}
    vertex_weights = [dict() for _ in range(before_count)]
    for vertex in mesh.vertices:
        for element in vertex.groups:
            name = group_index.get(element.group)
            if name:
                vertex_weights[vertex.index][name] = element.weight

    # ── 2) 删形态键（布尔不能带形态键）──
    bpy.context.view_layer.objects.active = mesh_obj
    mesh_obj.select_set(True)
    bpy.ops.object.shape_key_remove(all=True)
    print("  已删形态键（挖洞后按最近原顶点重建 delta）")

    # ── 3) 布尔差集挖洞 ──
    cutters = build_cutters(cut_radius_mm)
    for cutter in cutters:
        modifier = mesh_obj.modifiers.new("EyeCut_%s" % cutter.name, "BOOLEAN")
        modifier.operation = "DIFFERENCE"
        modifier.object = cutter
        modifier.solver = "EXACT"
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        bpy.data.objects.remove(cutter, do_unlink=True)
    mesh = mesh_obj.data
    after_count = len(mesh.vertices)
    after_tris = sum(len(p.vertices) - 2 for p in mesh.polygons)
    print("  布尔后：%d 顶点 / %d 三角面（新增 %+d 顶点 / %+d 面）"
          % (after_count, after_tris, after_count - before_count, after_tris - before_tris))

    # ── 4) 新顶点按最近原顶点补权重与 delta ──
    after = np.empty(after_count * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", after)
    after = after.reshape(after_count, 3)
    tree = KDTree(before_count)
    for index in range(before_count):
        tree.insert(base[index], index)
    tree.balance()
    new_index = []
    for index in range(after_count):
        _, nearest, distance = tree.find(after[index])
        new_index.append(nearest)
    new_index = np.array(new_index, dtype=np.int32)
    reused = int((new_index != np.arange(after_count)).sum())
    print("  新顶点复用最近原顶点的权重/delta：%d 个（其余为原顶点）" % reused)

    # 权重：先清空再按映射写回（每个顶点只写最近原顶点那一份，避免叠加）
    for group in list(mesh_obj.vertex_groups):
        group.remove([v.index for v in mesh.vertices])
    for index in range(after_count):
        source = vertex_weights[int(new_index[index])]
        for name, weight in source.items():
            group = mesh_obj.vertex_groups.get(name) or mesh_obj.vertex_groups.new(name=name)
            group.add([index], float(weight), "REPLACE")

    # 形态键：Basis + 各键（delta 按最近原顶点取）
    basis = mesh_obj.shape_key_add(name="Basis", from_mix=False)
    basis.data.foreach_set("co", after.reshape(-1).astype(np.float32))
    for name, delta in key_data.items():
        block = mesh_obj.shape_key_add(name=name, from_mix=False)
        positions = after + delta[new_index]
        block.data.foreach_set("co", positions.reshape(-1).astype(np.float32))
    for block in mesh.shape_keys.key_blocks:
        block.value = 0.0
    print("  形态键重建：%d 个" % (len(mesh.shape_keys.key_blocks) - 1))

    # ── 5) 检查眼球是否成为可见表面 ──
    report = {"file": bpy.data.filepath, "cut_radius_mm": cut_radius_mm,
              "before": {"verts": before_count, "tris": before_tris},
              "after": {"verts": after_count, "tris": after_tris},
              "reused": reused, "eyes": {}}
    for side, spec in EYEBALL.items():
        center = np.array(spec["center"])
        radius = spec["radius"]
        rel = after - center
        distance = np.linalg.norm(rel, axis=1)
        front = rel[:, 1] < 0
        shell = (distance < radius * 1.5) & front
        # 壳体在眼球前方的顶点（会挡住眼球）
        blocked = 0
        worst = 0.0
        for index in np.nonzero(shell)[0]:
            y_surface = center[1] - np.sqrt(max(radius ** 2 -
                                                (after[index, 0] - center[0]) ** 2 -
                                                (after[index, 2] - center[2]) ** 2, 0.0))
            if after[index, 1] < y_surface - 5e-5:
                blocked += 1
                worst = max(worst, (y_surface - after[index, 1]) * 1000)
        print("  eye.%s：眼球前方仍有 %d 个壳顶点（最靠前 %.2fmm）" % (side, blocked, worst))
        report["eyes"][side] = {"blocking": blocked, "worst_mm": round(worst, 2)}

    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("APERTURE_OK 已保存 " + out)
    if want_report:
        print("APERTURE_JSON " + json.dumps(report, ensure_ascii=False))


main()
