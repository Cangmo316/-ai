#!/usr/bin/env python3
"""
比邻AI · 按原型图配色生成虹膜贴图（琥珀色 + 高光点 + 深色角膜缘）

用法：
    blender --background <任意.blend> --python tools/blender-env.py \
        --python tools/blender-iris-art.py -- --out <输出.png> \
            [--radius-ratio 0.42] [--report]

参考：`3D建模/05_模型原型T-pose图/常服女/正面.png`（原型图）的眼部——
大而亮的**琥珀/蜂蜜色虹膜**、瞳孔深棕、中央偏上有一枚**亮高光点**、
外圈一圈**深色角膜缘环**、虹膜内有**放射状纤维纹**。

为什么不用 v1 的 `eye_iris.png`：那张的虹膜偏暗偏灰、且盘外是灰棋盘，
放上去之后眼睛像"玻璃球"。这里按原型图重新画一张。
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


def mix(a, b, t):
    return a * (1.0 - t) + b * t


def main():
    path_out = arg_value("--out")
    iris_ratio = float(arg_value("--radius-ratio", "0.42"))
    size = int(arg_value("--size", "512"))
    want_report = has_flag("--report")

    ys, xs = np.mgrid[0:size, 0:size].astype(np.float64)
    center = (size - 1) / 2.0
    dx = (xs - center) / center          # -1..1
    dy = (ys - center) / center
    radius = np.sqrt(dx ** 2 + dy ** 2)  # 1.0 = 半图宽
    angle = np.arctan2(dy, dx)

    iris_r = iris_ratio / 0.5 * 0.5      # 虹膜盘半径（以"1.0 = 半图宽"为单位）
    pupil_r = iris_r * 0.40

    # ── 基底：眼白（带一点暖色 + 边缘微暗）──
    sclera_t = smoothstep((radius - iris_r) / max(1.0 - iris_r, 1e-6))
    color = np.zeros((size, size, 3))
    # 眼白：暖白（原型图的眼白是暖白，不是冷灰）；边缘略暗但保持亮
    for channel, value in enumerate((1.0, 0.985, 0.955)):
        color[:, :, channel] = value - (value - 0.90) * sclera_t

    # ── 虹膜：琥珀/蜂蜜色，带放射状纤维纹 ──
    inside = radius <= iris_r
    radial = np.clip(radius / max(iris_r, 1e-6), 0, 1)
    # 纤维：角度方向的高频 + 径向渐变
    # ⚠️ 第一版配色偏"洗白的棕"（与原型图对照后改）：原型图是**饱和琥珀**，
    #    外圈不能压成灰褐；角膜缘只要一条细深环（原 12% 太宽）。
    fiber = 0.5 + 0.5 * np.sin(angle * 34.0 + np.sin(angle * 7.0) * 1.2)
    fiber = mix(0.78, 1.0, fiber * 0.5 + 0.35)
    amber_inner = np.array([0.90, 0.62, 0.24])     # 蜂蜜（亮）
    amber_outer = np.array([0.62, 0.34, 0.11])     # 琥珀（饱和）
    t_radial = smoothstep(radial * 1.05)
    iris = np.zeros((size, size, 3))
    for channel in range(3):
        iris[:, :, channel] = mix(amber_inner[channel], amber_outer[channel], t_radial)
    iris *= fiber[:, :, None]
    # 角膜缘环：只压最外 6%，且不全黑
    limbal = smoothstep((radial - 0.94) / 0.06)
    iris *= (1.0 - 0.42 * limbal[:, :, None])
    # 瞳孔：深棕近黑（原型图瞳孔占虹膜约 1/3）
    pupil_ratio = pupil_r / max(iris_r, 1e-6)
    pupil = radial <= pupil_ratio
    pupil_soft = smoothstep((radial - pupil_ratio) / 0.05)
    for channel, value in enumerate((0.055, 0.04, 0.035)):
        iris[:, :, channel] = mix(value, iris[:, :, channel], pupil_soft)
    iris = np.where(pupil[:, :, None], np.array([0.055, 0.04, 0.035])[None, None, :], iris)

    color = np.where(inside[:, :, None], iris, color)

    # ── 高光点：中央偏上偏外一枚亮点（原型图里有）──
    # ⚠️ 高光必须落在**虹膜上、瞳孔外**（第一版放在 (0.10,-0.10) 落进瞳孔里，像个白点）
    hscale = iris_ratio * 0.62
    for (hx, hy, hr, strength) in ((hscale * 0.55, -hscale * 0.62, 0.055, 1.0),
                                   (-hscale * 0.72, hscale * 0.40, 0.032, 0.5)):
        hd = np.sqrt((dx - hx) ** 2 + (dy - hy) ** 2)
        glow = np.exp(-(hd / hr) ** 2) * strength
        color = color * (1.0 - glow[:, :, None]) + glow[:, :, None] * 1.0

    pixels = np.ones((size, size, 4), dtype=np.float32)
    pixels[:, :, :3] = np.clip(color, 0.0, 1.0)
    image = bpy.data.images.new("iris_art", width=size, height=size, alpha=False)
    image.pixels.foreach_set(pixels.reshape(-1))
    image.filepath_raw = os.path.abspath(path_out)
    image.file_format = "PNG"
    image.save()
    print("=" * 92)
    print("虹膜贴图（按原型图配色）: %dx%d  虹膜盘半径比 %.2f  瞳孔比 %.2f"
          % (size, size, iris_ratio, pupil_r / max(iris_r, 1e-6)))
    print("  配色：蜂蜜内圈 (0.72,0.45,0.16) → 深棕外圈 (0.42,0.22,0.07) + 放射纹 + 角膜缘环 + 高光")
    print("IRIS_ART_OK 已保存 " + image.filepath_raw)
    if want_report:
        print("IRIS_ART_JSON {\"size\": %d, \"iris_ratio\": %s}" % (size, iris_ratio))


main()
