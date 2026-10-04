#!/usr/bin/env python3
"""真实开合姿态下的开口量：jaw + chin + lip_lower 三者同向负角（morph 的实际用法）

用法： blender -b <资产> --python blender-env.py --python blender-lip-open-pose.py -- [--json]
"""
import json
import math
import sys

import numpy as np
import bpy


def arg_value(name, default=None):
    args = sys.argv
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return default


mesh_obj = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
count = len(mesh_obj.data.vertices)
rest = np.empty(count * 3, dtype=np.float64)
mesh_obj.data.vertices.foreach_get("co", rest)
rest = rest.reshape(count, 3)

mid = (np.abs(rest[:, 0]) < 0.004) & (rest[:, 1] < -0.065) \
    & (rest[:, 2] > 1.022) & (rest[:, 2] < 1.042)
idx = np.nonzero(mid)[0]
seam = float(np.median(rest[idx, 2]))
up = idx[rest[idx, 2] > seam]
low = idx[rest[idx, 2] <= seam]
print("=" * 84)
print("真实开合姿态 : " + bpy.data.filepath)
print(f"  中线带 {len(idx)}：上唇行 {len(up)} / 下唇行 {len(low)}（缝 z={seam:.4f}）")
print("")
print("  %-10s%-12s%-12s%-12s" % ("下颌角", "上唇Δz", "下唇Δz", "开口增量"))

report = {"file": bpy.data.filepath, "poses": {}}
for degrees in (2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0):
    for bone in arm.pose.bones:
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0.0, 0.0, 0.0)
        bone.location = (0.0, 0.0, 0.0)
    value = math.radians(-degrees)          # 负角才是张嘴（见 morph-build 的 JAW_SIGN 注释）
    for name in ("jaw", "chin", "lip_lower"):
        bone = arm.pose.bones.get(name)
        if bone is not None:
            bone.rotation_mode = "XYZ"
            bone.rotation_euler = (value, 0.0, 0.0)
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    evaluated = mesh_obj.evaluated_get(deps)
    mesh = evaluated.to_mesh()
    co = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    evaluated.to_mesh_clear()
    dz_up = float((co[up, 2] - rest[up, 2]).mean() * 1000)
    dz_low = float((co[low, 2] - rest[low, 2]).mean() * 1000)
    gap = dz_low - dz_up
    print("  %-10.0f%-12.3f%-12.3f%-12.3f" % (degrees, dz_up, dz_low, gap))
    report["poses"][str(int(degrees))] = {"dz_up_mm": round(dz_up, 3),
                                          "dz_low_mm": round(dz_low, 3), "gap_mm": round(gap, 3)}
if "--json" in sys.argv:
    print("LIP_POSE_JSON " + json.dumps(report, ensure_ascii=False))
print("LIP_POSE_OK")
