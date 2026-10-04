#!/usr/bin/env python3
"""
比邻AI · 眼裂前表面分层探针（找出虹膜外那圈"脏环"是哪一层）

用法：
    blender --background <资产.blend> --python tools/blender-env.py \
        --python tools/blender-eye-layers.py -- [--json]

做法：以 `eye.L` 枢轴为球心做**径向剖面**——把"正前方一小锥内"的顶点按
到球心的距离分箱，报每一层出现在哪些半径上、由哪个骨驱动、法线朝向。
眼睛正常时应当是"一层穹顶"，实测女生是多层交错（渲染里表现为虹膜外的一圈脏环）。
"""

import json
import sys

import numpy as np
import bpy


def main():
    want_json = "--json" in sys.argv
    mesh_obj = max((o for o in bpy.data.objects if o.type == "MESH"),
                   key=lambda o: len(o.data.vertices))
    mesh = mesh_obj.data
    count = len(mesh.vertices)
    co = np.empty(count * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(count, 3)
    normals = np.empty(count * 3, dtype=np.float64)
    mesh.vertices.foreach_get("normal", normals)
    normals = normals.reshape(count, 3)

    report = {"file": bpy.data.filepath, "eyes": {}}
    for side, center in (("L", (0.0176, -0.0532, 1.0680)), ("R", (-0.0177, -0.0539, 1.0679))):
        c = np.array(center)
        rel = co - c
        distance = np.linalg.norm(rel, axis=1)
        forward = rel[:, 1]          # -Y 是脸朝前
        # 正前方锥：与 -Y 夹角 < 40°，且距离 < 20mm
        cos = -forward / np.maximum(distance, 1e-9)
        cone = (cos > np.cos(np.radians(40))) & (distance < 0.020)
        idx = np.nonzero(cone)[0]
        print("=" * 92)
        print("EYE.%s 正前方 40° 锥内顶点 %d" % (side, len(idx)))
        # 按 y（前伸量）分箱看层
        order = idx[np.argsort(co[idx, 1])]
        print("  %-8s%-10s%-10s%-9s%-9s%-8s" % ("y(mm)", "距球心", "nx", "ny", "nz", "主骨"))
        detail = []
        for index in order:
            best = ("?", 0.0)
            for group in mesh.vertices[index].groups:
                if group.weight > best[1]:
                    best = (mesh_obj.vertex_groups[group.group].name, group.weight)
            detail.append({"v": int(index), "y": round(float(co[index, 1]), 5),
                           "r": round(float(distance[index] * 1000), 2),
                           "n": [round(float(v), 2) for v in normals[index]],
                           "bone": best[0], "w": round(float(best[1]), 2)})
        for row in detail[:26]:
            print("  %-8.1f%-10.2f%-10.2f%-9.2f%-9.2f%s(%.2f)" % (
                row["y"] * 1000, row["r"], row["n"][0], row["n"][1], row["n"][2],
                row["bone"], row["w"]))
        ys = np.array([row["y"] for row in detail]) * 1000
        if len(ys) > 3:
            print("  前伸量跨度 %.2f ~ %.2f mm（跨度大 = 多层交错）" % (ys.min(), ys.max()))
        report["eyes"][side] = {"cone": int(len(idx)), "rows": detail}
    if want_json:
        print("EYE_LAYERS_JSON " + json.dumps(report, ensure_ascii=False))
    print("EYE_LAYERS_OK")


main()
