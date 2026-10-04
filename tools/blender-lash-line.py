#!/usr/bin/env python3
"""
比邻AI · 眼睑睫毛线（在上/下睑缘做一圈细几何，贴合原型图的"深色睫毛线 + 淡粉卧蚕"）

用法：
    blender --background <资产.blend> --python tools/blender-env.py \
        --python tools/blender-lash-line.py -- --out <输出.blend> \
            [--thickness-mm 0.35] [--width-mm 0.5] [--report]

**为什么**：原型图 `05_模型原型T-pose图/常服女/正面.png` 的眼睛最显眼的特征是
**上睑一条深色睫毛线**（下睑还有一道淡粉卧蚕）。v2 的睑缘是皮肤本色，所以眼睛"没有神"。

做法：沿眼裂口边缘（`<side>` 的睑缘环）生成一圈**薄环带**网格：
  · 位置 = 睑缘顶点 + 一条朝眼内/眼外的短法向偏移，做成贴着睑缘的细带；
  · 上睑带材质 = 深色睫毛（近黑棕）；下睑带材质 = 淡粉（卧蚕）；
  · 权重与睑缘同源（靠 KDTree 取最近睑缘顶点的顶点组），保证眨眼/表情跟随。
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


EYE = {"L": {"center": (0.01762, -0.05324, 1.06798), "radius": 0.011},
       "R": {"center": (-0.01769, -0.05388, 1.06787), "radius": 0.011}}


def make_material(name, color, roughness=0.55):
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name=name)
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    output.location = (300, 0)
    shader = tree.nodes.new("ShaderNodeBsdfPrincipled")
    shader.location = (0, 0)
    shader.inputs["Base Color"].default_value = (color[0], color[1], color[2], 1.0)
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Metallic"].default_value = 0.0
    tree.links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    return material


def main():
    out = arg_value("--out")
    thickness = float(arg_value("--thickness-mm", "0.35"))
    width = float(arg_value("--width-mm", "0.55"))
    want_report = has_flag("--report")

    mesh_obj = max((o for o in bpy.data.objects if o.type == "MESH" and o.data.shape_keys is not None),
                   key=lambda o: len(o.data.vertices))
    armature = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    mesh = mesh_obj.data
    count = len(mesh.vertices)
    co = np.empty(count * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(count, 3)

    # 顶点权重快照（给新几何按最近顶点复制）
    group_index = {g.index: g.name for g in mesh_obj.vertex_groups}
    weights = [dict() for _ in range(count)]
    for vertex in mesh.vertices:
        for element in vertex.groups:
            name = group_index.get(element.group)
            if name:
                weights[vertex.index][name] = element.weight

    upper_material = make_material("M_LashUpper", (0.045, 0.030, 0.028), 0.45)
    lower_material = make_material("M_LashLower", (0.62, 0.42, 0.40), 0.60)
    print("=" * 92)
    print("眼睑睫毛线 : " + bpy.data.filepath)
    report = {"file": bpy.data.filepath, "thickness_mm": thickness, "width_mm": width, "eyes": {}}
    created = []
    for side, spec in EYE.items():
        center = np.array(spec["center"])
        rel = co - center
        distance = np.linalg.norm(rel, axis=1)
        # 睑缘环：距球心 9~16mm、在眼球前方
        rim = (distance > 0.008) & (distance < 0.017)
        rim_index = np.nonzero(rim)[0]
        if len(rim_index) < 8:
            print("  eye.%s 睑缘顶点太少（%d），跳过" % (side, len(rim_index)))
            continue
        rim_co = co[rim_index]
        upper = rim_co[:, 2] > center[2]
        # 沿"球心→顶点"方向的切向：把带子放在睑缘内侧（朝眼内 = 朝球心）
        for label, mask, material, toward in (("upper", upper, upper_material, +1.0),
                                              ("lower", ~upper, lower_material, -1.0)):
            sel = rim_index[mask]
            if len(sel) < 4:
                continue
            points = co[sel]
            direction = points - center
            direction /= np.maximum(np.linalg.norm(direction, axis=1)[:, None], 1e-9)
            # 带子的两条边：外缘（沿原位置）与内缘（朝球心偏移 thickness）
            outer = points + direction * (width / 2000.0)
            inner = points + direction * (width / 2000.0) - direction * (thickness / 1000.0)
            strip = np.vstack([outer, inner])
            mesh_new = bpy.data.meshes.new("lash_%s_%s" % (side, label))
            obj = bpy.data.objects.new("lash_%s_%s" % (side, label), mesh_new)
            bpy.context.scene.collection.objects.link(obj)
            bm = bmesh.new()
            verts = [bm.verts.new(v) for v in strip]
            bm.verts.ensure_lookup_table()
            n = len(sel)
            for i in range(n - 1):
                try:
                    bm.faces.new((verts[i], verts[i + 1], verts[n + i + 1], verts[n + i]))
                except ValueError:
                    pass
            bm.to_mesh(mesh_new)
            bm.free()
            mesh_new.materials.append(material)
            # 权重：按最近睑缘顶点复制
            tree = KDTree(len(sel))
            for slot, index in enumerate(sel):
                tree.insert(co[index], slot)
            tree.balance()
            for vertex in mesh_new.vertices:
                _, slot, _ = tree.find(vertex.co)
                source = weights[int(sel[slot])]
                for name, weight in source.items():
                    group = obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name)
                    group.add([vertex.index], float(weight), "REPLACE")
            if armature is not None:
                modifier = obj.modifiers.new("Armature", "ARMATURE")
                modifier.object = armature
                obj.parent = armature
            created.append(obj.name)
            print("  eye.%s %s 睫毛带：%d 顶点 / %d 面（厚 %.2fmm 宽 %.2fmm）"
                  % (side, label, len(mesh_new.vertices), len(mesh_new.polygons), thickness, width))
        report["eyes"][side] = {"rim": int(len(rim_index))}
    report["created"] = created
    if not created:
        print("LASH_FAIL 没有生成任何睫毛带")
        return
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("LASH_OK 已保存 " + out)
    if want_report:
        print("LASH_JSON " + json.dumps(report, ensure_ascii=False))


main()
