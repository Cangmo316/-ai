#!/usr/bin/env python3
"""
比邻AI · 从正视图渲染里定位眼窝（Blender 内读像素，快）

用法：
    blender --background --python tools/find-eye-anchor.py -- \
        --image <正视图.png> --center-z <帧中心Z> --ortho <正交宽度>

为什么不用"头部高度比例"定位眼睛：原始网格的"头顶"包含头发体积，
比例法会把眼睛算高约 4cm（实测）。眼窝是暗斑，用几何证据定位才可靠：
正交正视图里的像素坐标可按相机参数**线性反投影**回世界 X/Z。
"""

import sys

import bpy


def arg_value(name, default=None):
    args = sys.argv
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return default


def main() -> None:
    path = arg_value("--image")
    center_z = float(arg_value("--center-z", "0"))
    ortho = float(arg_value("--ortho", "1"))
    top_ratio = float(arg_value("--top-ratio", "0.28"))
    bottom_ratio = float(arg_value("--bottom-ratio", "0.62"))
    threshold = float(arg_value("--dark", "0.16"))  # 亮度阈值（0~1，线性）
    # 只在面部中央带里找：两侧头发比眼窝更暗，不设这个限制会整片命中头发
    x_limit = float(arg_value("--x-limit", "0.05"))

    image = bpy.data.images.load(path)
    width, height = image.size
    pixels = list(image.pixels)  # RGBA，行序自下而上
    y0 = int(height * (1 - bottom_ratio))
    y1 = int(height * (1 - top_ratio))

    def luminance(x, y):
        index = (y * width + x) * 4
        r, g, b = pixels[index], pixels[index + 1], pixels[index + 2]
        return 0.299 * r + 0.587 * g + 0.114 * b

    buckets = {"L": [], "R": []}
    for y in range(max(0, y0), min(height, y1)):
        for x in range(width):
            wx = (x / width - 0.5) * ortho
            if abs(wx) > x_limit:
                continue
            if luminance(x, y) < threshold:
                buckets["L" if x < width / 2 else "R"].append((x, y))

    def to_world(x, y):
        wx = (x / width - 0.5) * ortho
        wz = center_z + (y / height - 0.5) * ortho
        return round(wx, 5), round(wz, 5)

    print("=" * 70)
    print(f"眼窝定位: {path}  {width}x{height}  帧中心Z={center_z} 正交宽={ortho}")
    print(f"搜索带 y={max(0, y0)}..{min(height, y1)}（图像坐标自下而上）  亮度阈值 {threshold}")
    suggestions = {}
    for side, points in buckets.items():
        if not points:
            print(f"  [{side}] 没有暗斑（提高阈值再试）")
            continue
        cx = sum(p[0] for p in points) / len(points)
        cy = sum(p[1] for p in points) / len(points)
        wx, wz = to_world(cx, cy)
        suggestions[side] = (wx, wz)
        print(f"  [{side}] 暗斑 {len(points)} px  质心像素({cx:.1f},{cy:.1f})  → 世界 X={wx}  Z={wz}")
    if len(suggestions) == 2:
        lx, lz = suggestions["L"]
        rx, rz = suggestions["R"]
        print(f"EYE_ANCHOR --eye-lx {lx} --eye-lz {lz} --eye-rx {rx} --eye-rz {rz}")
    print("=" * 70)


main()
