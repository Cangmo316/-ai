#!/usr/bin/env python3
"""从上一代（v1）资产里量出"独立眼球"的参数：球心 / 半径 / 虹膜 UV 圈 / 面数 / 权重

用法：blender -b <v1.blend> --python blender-env.py --python tools/blender-eyeball-survey.py -- [--json]
"""
import json
import sys

import numpy as np
import bpy

want_json = "--json" in sys.argv
print("=" * 92)
print("v1 眼球勘察 : " + bpy.data.filepath)
print("  对象：" + ", ".join("%s(%s,%dv)" % (o.name, o.type, len(o.data.vertices) if o.type == "MESH" else 0)
                            for o in bpy.data.objects))
report = {"file": bpy.data.filepath, "objects": [], "eyeballs": []}
for obj in bpy.data.objects:
    if obj.type != "MESH":
        continue
    count = len(obj.data.vertices)
    co = np.empty(count * 3, dtype=np.float64)
    obj.data.vertices.foreach_get("co", co)
    co = co.reshape(count, 3)
    entry = {"name": obj.name, "verts": count, "polys": len(obj.data.polygons),
             "materials": [m.name if m else None for m in obj.data.materials],
             "bbox": [[round(float(v), 4) for v in (co[:, i].min(), co[:, i].max())] for i in range(3)]}
    uv_names = [layer.name for layer in obj.data.uv_layers]
    entry["uv"] = uv_names
    # 用 bbox 中心 + 半径判断是不是眼球（球体特征：三维跨度接近）
    size = co.max(axis=0) - co.min(axis=0)
    if count > 32 and size.min() > 1e-4 and size.max() / max(size.min(), 1e-9) < 1.25:
        center = (co.max(axis=0) + co.min(axis=0)) / 2
        radius = float(size.mean() / 2)
        entry["sphere_like"] = {"center": [round(float(v), 5) for v in center],
                                "radius_mm": round(radius * 1000, 2)}
        # 虹膜 UV 圈：把 UV 分成"靠中心"和"靠外"，报中心簇的 UV 范围
        if uv_names:
            layer = obj.data.uv_layers.active
            loops = np.empty(len(obj.data.loops) * 2, dtype=np.float32)
            layer.data.foreach_get("uv", loops)
            loops = loops.reshape(-1, 2)
            vindex = np.empty(len(obj.data.loops), dtype=np.int32)
            obj.data.loops.foreach_get("vertex_index", vindex)
            uniq, first = np.unique(vindex, return_index=True)
            vuv = np.zeros((count, 2), dtype=np.float32)
            vuv[uniq] = loops[first]
            # 朝前方的顶点（-Y 方向）对应的 UV = 虹膜所在
            front = co[:, 1] < (center[1] - radius * 0.55)
            if front.any():
                iris_uv = vuv[front]
                entry["iris_uv"] = {
                    "u": [round(float(iris_uv[:, 0].min()), 4), round(float(iris_uv[:, 0].max()), 4)],
                    "v": [round(float(iris_uv[:, 1].min()), 4), round(float(iris_uv[:, 1].max()), 4)],
                    "count": int(front.sum()),
                }
            entry["sclera_uv"] = {
                "u": [round(float(vuv[:, 0].min()), 4), round(float(vuv[:, 0].max()), 4)],
                "v": [round(float(vuv[:, 1].min()), 4), round(float(vuv[:, 1].max()), 4)],
            }
        # 权重
        groups = {}
        for vertex in obj.data.vertices:
            for element in vertex.groups:
                name = obj.vertex_groups[element.group].name
                groups[name] = groups.get(name, 0) + 1
        entry["groups"] = groups
    report["objects"].append(entry)
    print("  %-16s %5dv %5df  材质=%s  UV=%s%s" % (
        obj.name, count, len(obj.data.polygons), entry["materials"], uv_names,
        ("  球心=%s r=%.2fmm" % (entry["sphere_like"]["center"], entry["sphere_like"]["radius_mm"]))
        if "sphere_like" in entry else ""))
    if "iris_uv" in entry:
        print("        虹膜 UV u%s v%s（%d 顶点）；整球 UV u%s v%s；权重 %s" % (
            entry["iris_uv"]["u"], entry["iris_uv"]["v"], entry["iris_uv"]["count"],
            entry["sclera_uv"]["u"], entry["sclera_uv"]["v"], entry["groups"]))
if want_json:
    print("EYEBALL_JSON " + json.dumps(report, ensure_ascii=False))
print("EYEBALL_SURVEY_OK")
