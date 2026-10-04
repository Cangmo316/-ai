#!/usr/bin/env python3
"""
比邻AI · 眼窝按眼球球面塑形（把盖在眼球上的皮壳压到球面之后）

用法：
    blender --background <带眼球的资产.blend> --python tools/blender-env.py \
        --python tools/blender-eye-socket-conform.py -- --out <输出.blend> \
            [--clearance-mm 0.35] [--fade 1.6] [--report]

**为什么是"按球面塑形"而不是"整体推 +Y"**（实测教训）：
  · v2 的扫描网格在眼区是**一整片连续凸壳**，没有真正的眼裂开口；
  · 只沿 +Y 推（`blender-eye-socket-scoop.py`）只是把凸壳压平/压凹，
    眼球依然被壳盖住或只露一小块（实测渲染里就是"脏壳 + 一块亮斑"）；
  · 正确做法：对每个"在眼球球面前方"的壳顶点，沿**它自己到球心的方向**
    把它放到球面上再退 `clearance-mm`——眼窝就成为一个贴合眼球的凹面，
    眼球自然成为可见表面。

位移**同时写进 Basis 与全部形态键**（各键 delta 不变）。
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
    clearance_mm = float(arg_value("--clearance-mm", "0.35"))
    fade = float(arg_value("--fade", "1.6"))
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

    delta = np.zeros((count, 3))
    print("=" * 92)
    print("眼窝按球面塑形 : " + bpy.data.filepath)
    report = {"file": bpy.data.filepath, "clearance_mm": clearance_mm, "eyes": {}}
    for side, spec in EYEBALL.items():
        center = np.array(spec["center"])
        radius = spec["radius"]
        eye_w = weights_of("eye.%s" % side)
        rel = co - center
        distance = np.linalg.norm(rel, axis=1)
        inside_zone = (distance < radius * fade) & (eye_w < 0.12)
        # 目标位置：沿"球心→顶点"方向，落到球面 + clearance
        direction = rel / np.maximum(distance[:, None], 1e-9)
        target_distance = radius + clearance_mm / 1000.0
        target = center + direction * target_distance
        # 只处理"当前比目标更靠前"的（也就是已经盖在眼球上的）
        to_move = inside_zone & (co[:, 1] < target[:, 1])
        # 只沿 +Y 推（保持 x/z 不动，避免眼型走形）；推量 = 目标 y - 当前 y
        need = np.where(to_move, target[:, 1] - co[:, 1], 0.0)
        # 沿半径衰减：贴着眼球 1.0 → fade×半径 0
        falloff = np.array([1.0 - smoothstep((d / radius - 1.0) / max(fade - 1.0, 1e-6))
                            for d in distance])
        move_y = need * falloff
        moved = int((move_y > 1e-9).sum())
        if moved:
            delta[:, 1] = np.maximum(delta[:, 1], move_y)
        print("  eye.%s：区域 %d、需压 %d 个（最大 %.2fmm）"
              % (side, int(inside_zone.sum()), moved,
                 float(move_y.max() * 1000) if moved else 0.0))
        report["eyes"][side] = {"zone": int(inside_zone.sum()), "moved": moved,
                                "max_mm": round(float(move_y.max() * 1000), 2) if moved else 0.0}

    affected = np.linalg.norm(delta, axis=1) > 1e-9
    if not affected.any():
        print("CONFORM_FAIL 没有需要压的顶点")
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
    report["max_mm"] = round(float(np.linalg.norm(delta, axis=1).max() * 1000), 2)
    print("  共压 %d 个顶点（最大 %.2fmm），位移已写进 Basis + %d 个形态键"
          % (report["affected"], report["max_mm"], len(keys.key_blocks) - 1))

    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("CONFORM_OK 已保存 " + out)
    if want_report:
        print("CONFORM_JSON " + json.dumps(report, ensure_ascii=False))


main()
