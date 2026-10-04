#!/usr/bin/env python3
"""
比邻AI · 眼型整形（把圆眼裂改成原型图的细长杏仁眼）

用法：
    blender --background <资产.blend> --python tools/blender-env.py \
        --python tools/blender-eye-shape.py -- --out <输出.blend> \
            [--lid-drop-mm 1.2] [--outer-out-mm 0.8] [--report]

**为什么**：原型图 `3D建模/05_模型原型T-pose图/常服女/正面.png` 是**细长杏仁眼**——
上睑几乎水平、盖住虹膜上缘约 1/4；而 v2 的眼裂是**圆眼**、上睑高拱、露白多。
形状来自扫描网格的眼睑脊，所以要动网格。

做法（只动眼裂周边那两圈，带平滑衰减）：
  1. **上睑脊**沿法线/竖直向下压 `--lid-drop-mm` → 眼裂变矮；
  2. **外眼角**沿 +X 向外、轻微向上 → 眼裂变长、外眼角上挑（原型图有明显上挑）；
  3. 位移**同时写进 Basis 与全部形态键**（各键 delta 不变）。
"""

import json
import os
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


def has_flag(name):
    return name in sys.argv


EYE = {"L": {"center": (0.01762, -0.05324, 1.06798), "radius": 0.011},
       "R": {"center": (-0.01769, -0.05388, 1.06787), "radius": 0.011}}


def smoothstep(value):
    value = np.clip(value, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


def main():
    out = arg_value("--out")
    lid_drop = float(arg_value("--lid-drop-mm", "1.2"))
    outer_out = float(arg_value("--outer-out-mm", "0.8"))
    outer_up = float(arg_value("--outer-up-mm", "0.4"))
    want_report = has_flag("--report")

    mesh_obj = max((o for o in bpy.data.objects if o.type == "MESH" and o.data.shape_keys is not None),
                   key=lambda o: len(o.data.vertices))
    mesh = mesh_obj.data
    count = len(mesh.vertices)
    co = np.empty(count * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(count, 3)

    delta = np.zeros((count, 3))
    print("=" * 92)
    print("眼型整形（圆眼 → 杏仁眼） : " + bpy.data.filepath)
    report = {"file": bpy.data.filepath, "lid_drop_mm": lid_drop,
              "outer_out_mm": outer_out, "eyes": {}}
    for side, spec in EYE.items():
        center = np.array(spec["center"])
        sign = 1.0 if side == "L" else -1.0
        rel = co - center
        distance = np.linalg.norm(rel, axis=1)
        # 只处理眼裂口边缘那一圈（距球心 9~16mm、在眼球前）
        rim = (distance > 0.009) & (distance < 0.016)
        upper = rim & (co[:, 2] > center[2] + 0.0015)      # 上睑侧
        outer = rim & (sign * (co[:, 0] - center[0]) > 0.006)  # 外眼角侧
        # 上睑：沿 -Z 压（越靠眼裂中心衰减越大 → 平滑过渡到眼眶）
        for index in np.nonzero(upper)[0]:
            t = smoothstep(1.0 - abs(distance[index] - 0.0125) / 0.0035)
            delta[index, 2] -= lid_drop / 1000.0 * t
        # 外眼角：+X 向外、轻微 +Z 上挑
        for index in np.nonzero(outer)[0]:
            t = smoothstep((sign * (co[index, 0] - center[0]) - 0.006) / 0.010)
            delta[index, 0] += sign * outer_out / 1000.0 * t
            delta[index, 2] += outer_up / 1000.0 * t
        print("  eye.%s：上睑脊 %d 个（下压 %.2fmm）、外眼角 %d 个（外移 %.2fmm / 上挑 %.2fmm）"
              % (side, int(upper.sum()), lid_drop, int(outer.sum()), outer_out, outer_up))
        report["eyes"][side] = {"upper": int(upper.sum()), "outer": int(outer.sum())}

    affected = np.linalg.norm(delta, axis=1) > 1e-9
    if not affected.any():
        print("EYE_SHAPE_FAIL 没有命中顶点")
        return
    keys = mesh.shape_keys
    for block in keys.key_blocks:
        positions = np.empty(count * 3, dtype=np.float64)
        block.data.foreach_get("co", positions)
        positions = positions.reshape(count, 3)
        positions[affected] += delta[affected]
        block.data.foreach_set("co", positions.reshape(-1).astype(np.float32))
    for block in keys.key_blocks:
        block.value = 0.0
    new_co = co.copy()
    new_co[affected] += delta[affected]
    mesh.vertices.foreach_set("co", new_co.reshape(-1).astype(np.float64))
    mesh.update()
    report["affected"] = int(affected.sum())
    print("  共改 %d 个顶点；位移已写进 Basis + %d 个形态键"
          % (report["affected"], len(keys.key_blocks) - 1))
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("EYE_SHAPE_OK 已保存 " + out)
    if want_report:
        print("EYE_SHAPE_JSON " + json.dumps(report, ensure_ascii=False))


main()
