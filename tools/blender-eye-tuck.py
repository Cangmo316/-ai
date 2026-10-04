#!/usr/bin/env python3
"""
比邻AI · 眼内角"外来壳"回推（低成本修眼睛杂色）

用法：
    blender --background <资产.blend> \
        --python tools/blender-env.py \
        --python tools/blender-eye-tuck.py -- --out <输出.blend> [--push-mm 2.5] [--report]

问题（实测，见任务笔记 §8.26）：每只眼内侧角有 **15~16 个顶点**
（由 `eye_socket.*` + `face_width` + `face_length` 驱动）比眼球穹顶表面**靠前 1.4~2.1mm**，
正面看就是压在虹膜上的"杂色皮瓣"。

做法（**不动权重**）：
  1. 以 `eye.L/R` 骨枢轴为穹顶球心，取"eye 权重 > 0.15 的顶点到球心的中位距离"为半径；
  2. 选出"在球体内、比球心更靠前、且 eye 权重 < 0.05"的顶点 = 外来壳；
  3. 给它们一个沿 +Y（往头内）的位移场，峰值 `--push-mm`，
     权重核用"到穹顶中心的距离"做软边（保证隔壁顶点平滑跟随，不撕裂）；
  4. **位移同时写进 Basis 与全部形态键**：这样每个形态键的 delta（相对 Basis）保持不变，
     说话/表情时的局部形变行为完全不变，只是这层皮瓣整体退到穹顶之后；
  5. 权重不动：`eye_socket.*` 仍然是它的主控骨，眼球转动/眼窝调节照旧生效。

为什么这么做而不是删面/改权重：这三个坑本轮都试过或评估过（见 §8.26）——
删面会留洞、改权重会牵连 `eye_socket` 的语义、重跑整条管线代价太大。
"""

import json
import os
import sys

import bpy
import numpy as np


def arg_value(name, default=None):
    args = sys.argv
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return default


def has_flag(name):
    return name in sys.argv


def main():
    out = arg_value("--out")
    push_mm = float(arg_value("--push-mm", "2.5"))
    want_report = has_flag("--report")
    edge_extra_mm = float(arg_value("--edge-extra-mm", "1.5"))

    mesh_obj = max((o for o in bpy.data.objects if o.type == "MESH"),
                   key=lambda o: len(o.data.vertices))
    armature = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = mesh_obj.data
    count = len(mesh.vertices)
    co = np.empty(count * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(count, 3).copy()

    def group_weights(name):
        weights = np.zeros(count)
        group = mesh_obj.vertex_groups.get(name)
        if group is None:
            return weights
        for vertex in mesh.vertices:
            for element in vertex.groups:
                if element.group == group.index:
                    weights[vertex.index] = element.weight
                    break
        return weights

    total_push = np.zeros((count, 3))
    report = {"file": bpy.data.filepath, "push_mm": push_mm, "eyes": {}}
    for side in ("L", "R"):
        bone = armature.data.bones.get("eye.%s" % side)
        if bone is None:
            continue
        center = np.array((armature.matrix_world @ bone.matrix_local).translation)
        eye_w = group_weights("eye.%s" % side)
        strong = eye_w > 0.15
        if strong.sum() < 5:
            report["eyes"][side] = {"skipped": "eye 权重 >0.15 的顶点不足"}
            continue
        radius = float(np.median(np.linalg.norm(co[strong] - center, axis=1)))
        distance = np.linalg.norm(co - center, axis=1)
        inside = distance < radius
        in_front = co[:, 1] < center[1]
        stray = inside & in_front & (eye_w < 0.05)
        if stray.sum() == 0:
            report["eyes"][side] = {"skipped": "没有外来壳"}
            continue
        # 软边：外来壳自身 1.0，其外 `edge_extra_mm` 内线性收到 0
        soft = np.clip((radius + edge_extra_mm / 1000.0 - distance)
                       / max(edge_extra_mm / 1000.0, 1e-6), 0.0, 1.0)
        soft = np.where(stray, 1.0, soft * 0.6)          # 邻居最多跟 60%，避免过度连带
        soft[~inside & ~stray] = 0.0
        # ⚠️ **穹顶自身（eye 权重高）绝对不动**：第一版让它按 60% 跟随，
        #    结果穹顶表面被一起往后带（参考面自己动了），皮瓣相对位移只从 2.08mm 降到 1.08mm。
        soft[strong] = 0.0
        push = np.zeros((count, 3))
        push[:, 1] = soft * (push_mm / 1000.0)            # +Y = 往头内
        total_push += push
        moved = int((soft > 0.01).sum())
        report["eyes"][side] = {
            "center": [round(float(v), 4) for v in center],
            "radius_mm": round(radius * 1000, 2),
            "stray_vertices": int(stray.sum()),
            "affected_vertices": moved,
        }
        print(f"  eye.{side}: 球心 {np.round(center, 4).tolist()} 半径 {radius * 1000:.2f}mm  "
              f"外来壳 {int(stray.sum())} 个 / 带动邻居共 {moved} 个")

    affected = np.linalg.norm(total_push, axis=1) > 1e-9
    report["affected_total"] = int(affected.sum())
    if not affected.any():
        print("EYE_TUCK_FAIL 没有可回推的顶点")
        return

    # ── 位移写进 Basis 与全部形态键（delta 不变）──
    keys = mesh.shape_keys
    if keys is None:
        print("EYE_TUCK_FAIL 网格没有形态键")
        return
    block_names = [b.name for b in keys.key_blocks]
    for block in keys.key_blocks:
        positions = np.empty(count * 3, dtype=np.float64)
        block.data.foreach_get("co", positions)
        positions = positions.reshape(count, 3)
        positions[affected] += total_push[affected]
        block.data.foreach_set("co", positions.reshape(-1).astype(np.float32))
    for block in keys.key_blocks:
        block.value = 0.0
    # 网格顶点本身（无形态键时的基准）也要跟着走，保持一致
    new_co = co.copy()
    new_co[affected] += total_push[affected]
    mesh.vertices.foreach_set("co", new_co.reshape(-1).astype(np.float64))
    mesh.update()

    report["shape_keys_shifted"] = len(block_names)
    report["max_push_mm"] = round(float(np.linalg.norm(total_push, axis=1).max() * 1000), 3)
    print(f"  已把位移写进 Basis + {len(block_names) - 1} 个形态键"
          f"（最大 {report['max_push_mm']}mm，共 {report['affected_total']} 个顶点）")

    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("EYE_TUCK_OK 已保存 " + out)
    if want_report:
        print("EYE_TUCK_JSON " + json.dumps(report, ensure_ascii=False))


main()
