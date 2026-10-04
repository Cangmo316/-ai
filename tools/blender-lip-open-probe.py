"""切开后：中线唇区逐顶点位移与开口（位置口径，全部在切开后的网格上重新取）"""
import math
import sys

import numpy as np
import bpy

OPEN = float(([a for a in sys.argv if a.startswith("--open=")] or ["--open=20"])[0].split("=")[1])

mesh_obj = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
count = len(mesh_obj.data.vertices)
rest = np.empty(count * 3, dtype=np.float64)
mesh_obj.data.vertices.foreach_get("co", rest)
rest = rest.reshape(count, 3)


def weights_of(name):
    out = np.zeros(count)
    group = mesh_obj.vertex_groups.get(name)
    if group is None:
        return out
    index = group.index
    for vertex in mesh_obj.data.vertices:
        for element in vertex.groups:
            if element.group == index:
                out[vertex.index] = element.weight
                break
    return out


jaw_w = weights_of("jaw")
head_w = weights_of("head")
chin_w = weights_of("chin")
lip_w = weights_of("lip_lower")
chain = jaw_w + chin_w + lip_w

# 中线唇区（位置口径，切开后）
band = (np.abs(rest[:, 0]) < 0.004) & (rest[:, 1] < -0.065) \
    & (rest[:, 2] > 1.020) & (rest[:, 2] < 1.044)
idx = np.nonzero(band)[0]
seam = float(np.median(rest[idx, 2])) if len(idx) else 1.030
print("中线带 %d 顶点；缝 z=%.4f" % (len(idx), seam))
print("  %-8s%-9s%-9s%-9s%-9s%-9s" % ("z", "y", "jaw", "head", "chain", "x"))
for v in idx[np.argsort(rest[idx, 2])]:
    print("  %-8.4f%-9.4f%-9.3f%-9.3f%-9.3f%-9.4f" % (
        rest[v, 2], rest[v, 1], jaw_w[v], head_w[v], chain[v], rest[v, 0]))

# 下颌 0 / OPEN 度
for degrees in (0.0, OPEN):
    for bone in arm.pose.bones:
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0.0, 0.0, 0.0)
    if degrees:
        bone = arm.pose.bones.get("jaw")
        if bone is not None:
            bone.rotation_euler = (math.radians(degrees), 0.0, 0.0)
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    evaluated = mesh_obj.evaluated_get(deps)
    mesh = evaluated.to_mesh()
    co = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    evaluated.to_mesh_clear()
    disp = np.linalg.norm(co[idx] - rest[idx], axis=1) * 1000
    up = idx[rest[idx, 2] > seam + 0.0004]
    low = idx[rest[idx, 2] < seam - 0.0004]
    open_mm = (co[up, 2].min() - co[low, 2].max()) * 1000 if len(up) and len(low) else float("nan")
    print("\n下颌 %.0f°：中线带位移 max %.3fmm 均值 %.3fmm；开口 %.3fmm" % (
        degrees, disp.max(), disp.mean(), open_mm))
print("LIP_OPEN2_OK")
