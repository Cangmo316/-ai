#!/usr/bin/env python3
"""
比邻AI · 眼球贴图清理（把虹膜图里的"灰棋盘 sclera"换成干净眼白 + 淡淡的血管）

用法：
    blender --background <任意.blend> --python tools/blender-env.py \
        --python tools/blender-eye-texture.py -- --in <虹膜图> --out <输出.png> [--report]

**为什么需要**：v1 的 `eye_iris.png`（256²）里，虹膜盘之外是**浅灰棋盘格**（美术占位图案）。
它贴到眼球上之后，眼白看起来就是"灰格子"——渲染里非常显眼。
本脚本按"离图心的距离"分段重画：
  · 中心盘（半径 < `--iris-ratio`）→ **原样保留**（虹膜 + 瞳孔）
  · 盘外 → **眼白**（接近纯白，带一点点暖色）+ 轻微径向渐变（靠边稍暗，模拟眼球弧度）
  · 盘边缘 → 一圈很淡的暗环（角膜缘过渡），避免虹膜像"贴纸"
"""

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


def smoothstep(value):
    value = np.clip(value, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


def main():
    path_in = arg_value("--in")
    path_out = arg_value("--out")
    iris_ratio = float(arg_value("--iris-ratio", "0.285"))   # 虹膜盘半径 / 图宽
    base = float(arg_value("--sclera", "0.965"))             # 眼白亮度
    edge = float(arg_value("--edge", "0.86"))                # 靠边的暗度
    want_report = has_flag("--report")

    image = bpy.data.images.load(path_in)
    width, height = image.size
    pixels = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    pixels = pixels.reshape(height, width, 4)
    print("=" * 92)
    print("眼球贴图清理 : %s (%dx%d)" % (path_in, width, height))

    ys, xs = np.mgrid[0:height, 0:width]
    cx, cy = (width - 1) / 2.0, (height - 1) / 2.0
    # 注意：Blender 图像是行优先、v 从下往上，这里按几何中心算半径即可
    radius = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2) / (width / 2.0)
    original = pixels[:, :, :3].copy()

    # 虹膜盘内部：保留原图（含虹膜+瞳孔）
    inside = radius <= iris_ratio
    # 盘外：干净眼白（靠边略暗，模拟眼球弧度）
    t = smoothstep((radius - iris_ratio) / max(1.0 - iris_ratio, 1e-6))
    sclera = (base - (base - edge) * t)[:, :, None] * np.array([1.0, 0.985, 0.965])[None, None, :]
    # 角膜缘过渡环（盘外 0~0.02 内压暗一点）
    limbal = np.exp(-((radius - iris_ratio) / 0.018) ** 2) * (radius > iris_ratio)
    sclera = sclera * (1.0 - 0.22 * limbal[:, :, None])
    # 淡淡的血管（只在盘外、靠两侧，很弱）
    vessel = (np.sin(xs * 0.7 + ys * 0.22) * 0.5 + 0.5) * np.clip((radius - iris_ratio) * 4.0, 0, 1)
    vessel = vessel * 0.045 * (1.0 - limbal)
    sclera[:, :, 0] += vessel
    sclera[:, :, 1] -= vessel * 0.35
    sclera[:, :, 2] -= vessel * 0.55

    mixed = np.where(inside[:, :, None], original, np.clip(sclera, 0.0, 1.0))
    pixels[:, :, :3] = mixed
    pixels[:, :, 3] = 1.0

    out_image = bpy.data.images.new("eye_iris_clean", width=width, height=height, alpha=False)
    out_image.pixels.foreach_set(pixels.reshape(-1))
    out_image.filepath_raw = os.path.abspath(path_out)
    out_image.file_format = "PNG"
    out_image.save()
    print("  虹膜盘半径比 %.3f（对应 UV 直径 %.3f）" % (iris_ratio, iris_ratio * 2))
    print("  眼白亮度 %.3f → 边缘 %.3f；角膜缘过渡环 + 极淡血管" % (base, edge))
    print("EYE_TEXTURE_OK 已保存 " + out_image.filepath_raw)
    if want_report:
        print("EYE_TEXTURE_JSON {\"iris_ratio\": %s, \"sclera\": %s, \"edge\": %s}"
              % (iris_ratio, base, edge))


main()
