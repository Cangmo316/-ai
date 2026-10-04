#!/usr/bin/env python3
"""
比邻AI · 眼窝掏空 v2（只推"确实挡住眼球"的顶点，且沿半径平滑衰减）

用法：
    blender --background <带眼球的资产.blend> --python tools/blender-env.py \
        --python tools/blender-eye-socket-scoop.py -- --out <输出.blend> \
            [--clearance-mm 1.0] [--fade 2.2] [--report]

**为什么需要**：参考图（v1 交付件）里眼睛是鼓起的独立眼球。v2 用"雕穹顶"，
眼窝那层皮肤壳的最前缘（y=−0.0665）比按 v1 参数装的眼球球面（y=−0.0617）**还靠前 5mm**，
把眼球整体挡住。

⚠️ 第一版的坑（实测）：按"球心前方 + eye 权重低"选点会**把眼睑/睫毛一起推进去**，
结果是"眼球凸出眼眶、眼皮消失"。而且 `--clearance-mm` 越大推得越多（方向与直觉相反）。

本版做法：
  1. 对每个候选顶点（球心附近 + 不属于眼球本体），算出"刚好落到眼球表面之后
     `clearance-mm`"所需的最小位移 `need = y_target - y`；
  2. 只推 `need > 0` 的（**已经躲在后面的顶点一个都不动**，所以眼睑不被牵连）；
  3. 位移再乘一个**沿半径的平滑衰减** `smoothstep`：贴着眼球中心处 1.0，
     到 `--fade`× 半径处降到 0——这样从凹眼窝过渡到正常脸面是连续的。
  4. 位移**同时写进 Basis 与全部形态键**（各键 delta 不变）。
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


EYEBALL = {"L": {"center": (0.01762, -0.05324, 1.06798), "radius": 0.0085},
           "R": {"center": (-0.01769, -0.05388, 1.06787), "radius": 0.00863}}


def smoothstep(value):
    value = min(max(value, 0.0), 1.0)
    return value * value * (3.0 - 2.0 * value)


def main():
    out = arg_value("--out")
    clearance_mm = float(arg_value("--clearance-mm", "1.0"))
    fade = float(arg_value("--fade", "2.2"))
    want_report = has_flag("--report")

    mesh_obj = max((o for o in bpy.data.objects if o.type == "MESH" and o.data.shape_keys is not None),
                   key=lambda o: len(o.data.vertices))
    mesh = mesh_obj.data
    count = len(mesh.vertices)
    co = np.empty(count * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(count, 3)

    def weights_of(name):
        result = np.zeros(count)
        group = mesh_obj.vertex_groups.get(name)
        if group is None:
            return result
        index = group.index
        for vertex in mesh.vertices:
            for element in vertex.groups:
                if element.group == index:
                    result[vertex.index] = element.weight
                    break
        return result

    total_push = np.zeros(count)
    print("=" * 92)
    print("眼窝掏空 v2 : " + bpy.data.filepath)
    report = {"file": bpy.data.filepath, "clearance_mm": clearance_mm, "fade": fade, "eyes": {}}
    for side, spec in EYEBALL.items():
        center = np.array(spec["center"])
        radius = spec["radius"]
        eye_w = weights_of("eye.%s" % side)
        rel = co - center
        distance = np.linalg.norm(rel, axis=1)
        # 眼球球面在 y 方向的"最前沿"：球心 y - 半径；再留 clearance
        y_target = center[1] - radius + clearance_mm / 1000.0
        need = y_target - co[:, 1]                       # 需要往 +Y 推多少
        candidate = (distance < radius * fade) & (eye_w < 0.12) & (need > 0)
        # 沿半径衰减：贴着眼球处 1.0 → fade×半径处 0
        fade_weight = np.array([1.0 - smoothstep((d / radius - 1.0) / max(fade - 1.0, 1e-6))
                                for d in distance])
        push = np.where(candidate, need * fade_weight, 0.0)
        pushed = int((push > 1e-9).sum())
        if pushed:
            worst = float(push.max() * 1000)
            total_push = np.maximum(total_push, push)
        else:
            worst = 0.0
        print("  eye.%s：候选 %d → 实际推 %d 个（最大 %.2fmm），目标 y=%.4f"
              % (side, int(candidate.sum()), pushed, worst, y_target))
        report["eyes"][side] = {"candidates": int(candidate.sum()), "pushed": pushed,
                                "worst_mm": round(worst, 2),
                                "y_target": round(float(y_target), 5)}

    affected = total_push > 1e-9
    if not affected.any():
        print("SCOOP_FAIL 没有需要推的顶点")
        return
    keys = mesh.shape_keys
    for block in keys.key_blocks:
        positions = np.empty(count * 3, dtype=np.float64)
        block.data.foreach_get("co", positions)
        positions = positions.reshape(count, 3)
        positions[affected, 1] += total_push[affected]
        block.data.foreach_set("co", positions.reshape(-1).astype(np.float32))
    for block in keys.key_blocks:
        block.value = 0.0
    new_co = co.copy()
    new_co[affected, 1] += total_push[affected]
    mesh.vertices.foreach_set("co", new_co.reshape(-1).astype(np.float64))
    mesh.update()
    report["affected"] = int(affected.sum())
    report["max_push_mm"] = round(float(total_push.max() * 1000), 2)
    print("  共推 %d 个顶点（最大 %.2fmm），位移已写进 Basis + %d 个形态键"
          % (report["affected"], report["max_push_mm"], len(keys.key_blocks) - 1))

    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("SCOOP_OK 已保存 " + out)
    if want_report:
        print("SCOOP_JSON " + json.dumps(report, ensure_ascii=False))


main()
