#!/usr/bin/env python3
"""
比邻AI · 唇缝开口探针 v2（可靠口径）

用法：
    blender --background <资产.blend> \
        --python tools/blender-env.py \
        --python tools/blender-lip-open-probe.py -- [--open 20] [--x-tol 0.004] [--json]

**为什么换口径**（本轮踩了三次）：唇缝是**交错层**，"上唇行最低 z − 下唇行最高 z"
这类极值差会被两层的互相穿插主导，读数没有几何意义
（实测改权重后中线位移 24mm，这个标量却从 +1.80 变 −1.96）。

可靠口径：把中线一带顶点按**静置 z** 分成上唇行 / 下唇行，分别报形变后的**平均 z 位移**：
  · 下唇行 Δz 越负 = 下唇越往下走；上唇行 Δz 越接近 0 = 上唇越稳
  · **可见开口增量 = 下唇行 Δz − 上唇行 Δz**（两者都向下时，差值即"多张开多少"）
判据：下颌 8° 开口增量 > 4mm、14° > 8mm。
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


def main():
    open_degrees = float(arg_value("--open", "20"))
    x_tol = float(arg_value("--x-tol", "0.004"))
    want_json = "--json" in sys.argv

    mesh_obj = max((o for o in bpy.data.objects if o.type == "MESH"),
                   key=lambda o: len(o.data.vertices))
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

    chain = weights_of("jaw") + weights_of("chin") + weights_of("lip_lower")

    mid = (np.abs(rest[:, 0]) < x_tol) & (rest[:, 1] < -0.065) \
        & (rest[:, 2] > 1.022) & (rest[:, 2] < 1.042)
    idx = np.nonzero(mid)[0]
    if len(idx) < 6:
        print("LIP_OPEN_FAIL 中线带顶点太少（%d）" % len(idx))
        return
    seam = float(np.median(rest[idx, 2]))
    up = idx[rest[idx, 2] > seam]
    low = idx[rest[idx, 2] <= seam]
    print("=" * 88)
    print("唇缝开口探针 : " + bpy.data.filepath)
    print(f"  中线带 {len(idx)} 顶点（缝 z={seam:.4f}）：上唇行 {len(up)} / 下唇行 {len(low)}")
    print(f"  下颌链权重均值：上唇行 {chain[up].mean():.3f} / 下唇行 {chain[low].mean():.3f}")
    print("")
    print("  %-8s%-11s%-11s%-11s%-11s" % ("下颌角", "上唇Δz", "下唇Δz", "开口增量", "最大位移"))

    report = {"file": bpy.data.filepath, "seam_z": round(seam, 4),
              "rows": {"up": int(len(up)), "low": int(len(low))},
              "chain": {"up": round(float(chain[up].mean()), 3),
                        "low": round(float(chain[low].mean()), 3)},
              "angles": {}}
    for degrees in (0.0, 4.0, 8.0, 14.0, open_degrees):
        for bone in arm.pose.bones:
            bone.rotation_mode = "XYZ"
            bone.rotation_euler = (0.0, 0.0, 0.0)
        if degrees:
            jaw = arm.pose.bones.get("jaw")
            if jaw is not None:
                jaw.rotation_euler = (math.radians(degrees), 0.0, 0.0)
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
        disp = float(np.linalg.norm(co[idx] - rest[idx], axis=1).max() * 1000)
        print("  %-8.0f%-11.3f%-11.3f%-11.3f%-11.3f" % (degrees, dz_up, dz_low, gap, disp))
        report["angles"][str(int(degrees))] = {"dz_up_mm": round(dz_up, 3),
                                               "dz_low_mm": round(dz_low, 3),
                                               "gap_mm": round(gap, 3),
                                               "max_disp_mm": round(disp, 3)}
    print("")
    print(f"  判据：下颌 8° 开口增量 > 4mm（实测 "
          f"{report['angles'].get('8', {}).get('gap_mm', 0)}mm）"
          f" / 14° > 8mm（实测 {report['angles'].get('14', {}).get('gap_mm', 0)}mm）")
    if want_json:
        print("LIP_OPEN_JSON " + json.dumps(report, ensure_ascii=False))
    print("LIP_OPEN_OK")


main()
