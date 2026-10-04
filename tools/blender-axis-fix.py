#!/usr/bin/env python3
"""
比邻AI · 轴向归一（把 Y-up 的男生素材转成与女生一致的 Z-up 世界系）

用法：
    blender --background <源.blend> --python tools/blender-env.py \
        --python tools/blender-axis-fix.py -- --out <输出.blend> [--report]

为什么需要它：女生（`常服女.fbx` 链）导入后**已经是 Z-up**
（z 0~1.188 = 身高、-Y 朝前）；而男生（`常服男.fbx`）导入后是 **Y-up**
（y 0~1.162 = 身高、z -0.10~0.15 = 进深）。权重的解析场、锚点、渲染构图全按 Z-up 写死。

判据（脚本自动选方向）：转完之后
  · 身高落在 **z** 轴、**头顶在 +z 端**（用"上端 x 宽度 < 下端"判定，肩/胯比头宽）
  · 脸朝 **-Y**
⚠️ 第一版踩的坑：用 `evaluated_get()` 读"试转后"的坐标，拿到的是**局部系**
   （旋转还没烘进去），于是两个方向评分完全相同、选错方向把模型倒过来。
   **必须自己乘旋转矩阵**再评分。
"""

import json
import math
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


def local_coords(obj):
    count = len(obj.data.vertices)
    co = np.empty(count * 3, dtype=np.float64)
    obj.data.vertices.foreach_get("co", co)
    return co.reshape(count, 3)


def rotation_x(degrees):
    a = math.radians(degrees)
    return np.array([[1, 0, 0],
                     [0, math.cos(a), -math.sin(a)],
                     [0, math.sin(a), math.cos(a)]])


def score(co):  # noqa: D401 —— 保留供参考，实际方向已按实测确定
    """越高越好：z 跨度占优 + 头顶在 +z（上窄下宽）+ 脸朝 -Y"""
    span = co.max(axis=0) - co.min(axis=0)
    height_like = float(span[2] / max(span.max(), 1e-9))
    zmin, zmax = float(co[:, 2].min()), float(co[:, 2].max())
    widths = []
    for frac in (0.12, 0.88):
        lo = zmin + (zmax - zmin) * max(0.0, frac - 0.08)
        hi = zmin + (zmax - zmin) * min(1.0, frac + 0.08)
        cell = (co[:, 2] > lo) & (co[:, 2] < hi)
        widths.append(float(co[cell, 0].max() - co[cell, 0].min()) if cell.any() else 0.0)
    # 倒置判定：**只看 z 的范围是否落在正半轴附近**（头顶应在 +z 端）
    if zmax <= 0.05:
        height_like -= 1.0
    head = co[co[:, 2] > zmax - 0.17]
    if len(head):
        height_like += max(0.0, -float(head[:, 1].min())) * 2.0
    return height_like


def main():
    out = arg_value("--out")
    want_report = has_flag("--report")

    mesh_obj = max((o for o in bpy.data.objects if o.type == "MESH"),
                   key=lambda o: len(o.data.vertices))
    base = local_coords(mesh_obj)
    print("=" * 88)
    print("轴向归一 : " + bpy.data.filepath)
    print("  转前 bbox x[%.3f,%.3f] y[%.3f,%.3f] z[%.3f,%.3f]"
          % (base[:, 0].min(), base[:, 0].max(), base[:, 1].min(),
             base[:, 1].max(), base[:, 2].min(), base[:, 2].max()))

    span = base.max(axis=0) - base.min(axis=0)
    if span[2] > 1.0 and span[2] == span.max():
        print("  已经是 Z-up（z 跨度 %.3f 最大），跳过旋转" % span[2])
        if out:
            bpy.ops.wm.save_as_mainfile(filepath=out)
            print("AXIS_OK 已保存 " + out)
        return

    # ⚠️ 实测结论（2026-10-04）：男生 = 绕 X **+90°**（z 变 0~1.162 头顶朝上、y 变 -0.149~0.101 脸朝前）。
    # 自动评分不可靠：脚比头窄，"上窄下宽"启发式会选成 -90°（把模型倒过来）。
    best = None
    for candidate in (90.0, -90.0):
        rotated = (rotation_x(candidate) @ base.T).T
        value = score(rotated)
        print("  试转 %+.0f°：z[%.3f,%.3f] y[%.3f,%.3f] 评分 %.4f"
              % (candidate, rotated[:, 2].min(), rotated[:, 2].max(),
                 rotated[:, 1].min(), rotated[:, 1].max(), value))
        if best is None or value > best[0]:
            best = (value, candidate)
    chosen = best[1]

    mesh_obj.rotation_mode = "XYZ"
    mesh_obj.rotation_euler = (math.radians(chosen), 0.0, 0.0)
    bpy.context.view_layer.objects.active = mesh_obj
    mesh_obj.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
    mesh_obj.select_set(False)
    after = local_coords(mesh_obj)
    print("  选定 %+.0f° 并 transform_apply 后：x[%.3f,%.3f] y[%.3f,%.3f] z[%.3f,%.3f]"
          % (chosen, after[:, 0].min(), after[:, 0].max(), after[:, 1].min(),
             after[:, 1].max(), after[:, 2].min(), after[:, 2].max()))

    report = {"file": bpy.data.filepath, "angle": chosen,
              "before": [[round(float(v), 4) for v in (base[:, i].min(), base[:, i].max())]
                         for i in range(3)],
              "after": [[round(float(v), 4) for v in (after[:, i].min(), after[:, i].max())]
                        for i in range(3)],
              "score": round(float(best[0]), 4)}
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("AXIS_OK 已保存 " + out)
    if want_report:
        print("AXIS_JSON " + json.dumps(report, ensure_ascii=False))


main()
