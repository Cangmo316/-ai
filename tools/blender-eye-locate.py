#!/usr/bin/env python3
"""
比邻AI · 从"画上去的眼睛"定位真实眼位 / 量眼裂开口

用法：
    # A. 自动量眼位与眼裂（默认模式）
    blender --background <文件.blend> --python tools/blender-eye-locate.py -- \
        --out <前缀> [--center x,y,z] [--scale 0.045] [--resolution 1800] [--threshold 0.42]

    # B. 裁小图并叠网格（人眼核对用）
    blender --background <文件.blend> --python tools/blender-eye-locate.py -- \
        --render <已有.png> --out <前缀> --center x,y,z --scale 0.045 \
        --crop x0,y0,x1,y1 --grid-mm 2

为什么需要它：
  这个雕塑的眼睛是**贴图画上去的**（眼白/虹膜/瞳孔/睫毛全在 albedo 里），叠在雕刻出来的睑缘环上。
  所以"眼位"不能拿 `eye.L` 顶点组形心代替 —— 那只是**眼皮皮肤**的形心
  （实测 x=0.0349，而画出来的眼球中心在 x≈0.027）→ 上一轮把球放在 x=0.0250 附近其实相差不多，
  真正的问题是**球太小（直径 14.2mm）填不满画出来的眼裂（约 18mm 宽）**。

做法：正交正视渲染 → 在窗口内找"亮且不偏暖"的连通域（=眼白/眼球）→ 主轴分析得到
      眼位中心、眼裂长短轴、倾角；再反投影回 (x, z) 并射线求表面 Y。

⚠️ Blender 的 image.pixels 是**自下而上**的，本文件在读入时统一翻转，
   否则反投影出的 Z 会上下颠倒（实测会把眼球算到下颌去）。
"""

import json
import math
import sys

import bpy
import numpy as np
from mathutils import Vector


def arg_value(name, default=None):
    args = sys.argv
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return default


def head_mesh():
    return max((o for o in bpy.data.objects if o.type == "MESH"),
               key=lambda o: len(o.data.vertices), default=None)


def render_front(out_path, center, scale, resolution):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.color_type = "TEXTURE"
    shading.show_cavity = False
    shading.show_object_outline = False

    camera_data = bpy.data.cameras.new("locate_cam")
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = scale
    camera = bpy.data.objects.new("locate_cam", camera_data)
    bpy.context.collection.objects.link(camera)
    scene.camera = camera

    target = bpy.data.objects.new("locate_target", None)
    target.location = Vector(center)
    bpy.context.collection.objects.link(target)

    camera.location = Vector(center) + Vector((0, -1, 0)) * (scale * 3)
    track = camera.constraints.new("TRACK_TO")
    track.target = target
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"
    scene.render.filepath = out_path
    bpy.ops.render.render(write_still=True)


def load_pixels(path):
    """读回像素，翻成"第 0 行 = 图像顶部"（Blender 内部是自下而上）"""
    image = bpy.data.images.load(path, check_existing=False)
    width, height = image.size
    buffer = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(buffer)
    return np.flipud(buffer.reshape(height, width, 4)), width, height


def unproject(px, py, width, height, center, scale):
    """正交正视反投影到 (x, z)：图像右 = +X，图像下 = -Z"""
    per_px = scale / width
    return (center[0] + (px - (width - 1) / 2.0) * per_px,
            center[2] - (py - (height - 1) / 2.0) * per_px)


def surface_y(obj, x, z):
    matrix = obj.matrix_world
    inverse = matrix.inverted()
    direction = (inverse.to_3x3() @ Vector((0, 1, 0))).normalized()
    ok, location, _normal, _index = obj.ray_cast(inverse @ Vector((x, -0.30, z)), direction,
                                                distance=0.6)
    return None if not ok else (matrix @ location).y


def largest_blob_mask(mask):
    """返回最大连通域的布尔掩码（4 邻域 BFS；窗口规模 10^4~10^5，够快）"""
    height, width = mask.shape
    labels = np.zeros((height, width), dtype=np.int32)
    current = 0
    sizes = [0]
    for start_y in range(height):
        for start_x in range(width):
            if not mask[start_y, start_x] or labels[start_y, start_x]:
                continue
            current += 1
            stack = [(start_y, start_x)]
            labels[start_y, start_x] = current
            count = 0
            while stack:
                y, x = stack.pop()
                count += 1
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < height and 0 <= nx < width:
                        if mask[ny, nx] and not labels[ny, nx]:
                            labels[ny, nx] = current
                            stack.append((ny, nx))
            sizes.append(count)
    best = int(np.argmax(sizes[1:])) + 1 if len(sizes) > 1 else 0
    return labels == best, (sizes[best] if best else 0), len(sizes) - 1


def analyze_eye(obj, pixels, width, height, center, scale, window, threshold):
    x0, y0, x1, y1 = window
    sub = pixels[y0:y1, x0:x1, :3]
    value = sub.max(axis=2)
    warmth = sub[:, :, 0] - sub[:, :, 2]
    mask = (value > threshold) & (np.abs(warmth) < 0.12)
    blob, area, blob_count = largest_blob_mask(mask)
    if area < 50:
        return {"error": f"窗口内眼白像素太少（{area}）", "threshold": threshold,
                "window": window, "blob_count": blob_count}
    coords = np.argwhere(blob)
    ys = coords[:, 0].astype(np.float64)
    xs = coords[:, 1].astype(np.float64)
    mean_x, mean_y = xs.mean(), ys.mean()
    cov = np.cov(np.vstack([xs - mean_x, ys - mean_y]))
    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    order = np.argsort(eigenvalues)[::-1]
    major = eigenvectors[:, order[0]]
    minor = eigenvectors[:, order[1]]
    proj_major = (xs - mean_x) * major[0] + (ys - mean_y) * major[1]
    proj_minor = (xs - mean_x) * minor[0] + (ys - mean_y) * minor[1]
    per_px = scale / width
    px, py = x0 + mean_x, y0 + mean_y
    world_x, world_z = unproject(px, py, width, height, center, scale)
    return {
        "threshold": threshold,
        "window": window,
        "blob_count": blob_count,
        "area_px": int(area),
        "centroid_px": [round(px, 2), round(py, 2)],
        "world_xz": [round(world_x, 5), round(world_z, 5)],
        "surface_y": None if surface_y(obj, world_x, world_z) is None
        else round(surface_y(obj, world_x, world_z), 5),
        "major_extent_mm": round(float(np.ptp(proj_major)) * per_px * 1000, 2),
        "minor_extent_mm": round(float(np.ptp(proj_minor)) * per_px * 1000, 2),
        "tilt_deg": round(math.degrees(math.atan2(major[1], major[0])), 2),
        "bbox_px": [int(x0 + xs.min()), int(y0 + ys.min()),
                    int(x0 + xs.max()), int(y0 + ys.max())],
        "px_per_mm": round(1.0 / per_px / 1000.0, 3),
    }


def save_crop(source_path, out_path, box, per_px, grid_mm):
    """裁小图并叠网格线（每格 grid_mm 毫米），便于人眼读坐标"""
    pixels, _width, _height = load_pixels(source_path)
    x0, y0, x1, y1 = box
    crop = pixels[y0:y1, x0:x1, :].copy()
    step = grid_mm / 1000.0 / per_px
    for k in range(int(crop.shape[1] / step) + 1):
        x = int(round(k * step))
        if 0 <= x < crop.shape[1]:
            crop[:, x, 0], crop[:, x, 1], crop[:, x, 2] = 1.0, 0.15, 0.15
    for k in range(int(crop.shape[0] / step) + 1):
        y = int(round(k * step))
        if 0 <= y < crop.shape[0]:
            crop[y, :, 0], crop[y, :, 1], crop[y, :, 2] = 1.0, 0.15, 0.15
    height_px, width_px = crop.shape[0], crop.shape[1]
    image = bpy.data.images.new("crop", width_px, height_px, alpha=True)
    image.pixels.foreach_set(np.flipud(crop).reshape(-1))
    image.filepath_raw = out_path
    image.file_format = "PNG"
    image.save()
    return out_path


def walk_rim(obj, pixels, width, height, center, scale, eye_xz, angles, warm_limit,
             r_max_mm, verbose_angles=()):
    """从眼心沿 angles 方向向外走，找**第一个偏暖像素**（=皮肤）= 睑缘环

    为什么用"偏暖"：眼白是中性亮灰、虹膜是暗棕、睫毛/刘海是纯黑、眼窝阴影偏暗，
    而眼睑皮肤明显偏暖（R 显著大于 B）。实测皮肤 warmth=R-B 稳定高于 0.09，
    眼区内部（眼白/瞳孔/睫毛阴影）低于它 → 这是最省事又稳的判据。
    """
    per_px = scale / width
    cx_px = (width - 1) / 2.0 + (eye_xz[0] - center[0]) / per_px
    cy_px = (height - 1) / 2.0 - (eye_xz[1] - center[2]) / per_px
    ring = []
    diagnostics = {}
    for angle in angles:
        theta = math.radians(angle)
        cosine, sine = math.cos(theta), math.sin(theta)
        found = None
        trace = []
        px = py = None
        for k in range(int(r_max_mm / 0.25) + 1):
            r_mm = k * 0.25
            px = cx_px + cosine * r_mm / 1000.0 / per_px
            py = cy_px - sine * r_mm / 1000.0 / per_px
            ix, iy = int(round(px)), int(round(py))
            if not (0 <= ix < width and 0 <= iy < height):
                break
            red, green, blue = (float(pixels[iy, ix, 0]), float(pixels[iy, ix, 1]),
                                float(pixels[iy, ix, 2]))
            warmth = red - blue
            value = max(red, green, blue)
            trace.append((r_mm, round(warmth, 3), round(value, 3)))
            if warmth > warm_limit and value > 0.18:
                found = (r_mm, warmth, value)
                break
        if found is not None and px is not None:
            world_x, world_z = unproject(px, py, width, height, center, scale)
            surface = surface_y(obj, world_x, world_z)
            ring.append({
                "deg": round(angle, 1),
                "r_mm": round(found[0], 2),
                "warmth": round(found[1], 3),
                "x": round(world_x, 6),
                "z": round(world_z, 6),
                "surface_y": None if surface is None else round(surface, 6),
            })
        if angle in verbose_angles:
            diagnostics[angle] = trace[:70]
    return ring, diagnostics


def main():
    out_prefix = arg_value("--out", "eye-locate")
    scale = float(arg_value("--scale", "0.045"))
    resolution = int(arg_value("--resolution", "1800"))
    existing = arg_value("--render")
    crop = arg_value("--crop")
    threshold = float(arg_value("--threshold", "0.42"))
    center_raw = arg_value("--center")
    center = ([float(v) for v in center_raw.split(",")] if center_raw
              else [0.0, -0.0584, 1.0690])

    obj = head_mesh()
    if obj is None:
        print("EYE_LOCATE_FAIL 没有网格")
        return

    path = existing or (out_prefix + "-front.png")
    if not existing:
        render_front(path, center, scale, resolution)
        print("EYE_LOCATE_RENDER " + path)

    per_px = scale / resolution
    if crop:
        box = [int(v) for v in crop.split(",")]
        out_path = out_prefix + "-crop.png"
        save_crop(path, out_path, box, per_px, float(arg_value("--grid-mm", "2")))
        print(f"EYE_LOCATE_CROP {out_path}  左下角像素 x={box[0]} y={box[1]}  "
              f"每格 {arg_value('--grid-mm', '2')}mm  {round(1 / per_px / 1000, 3)} px/mm")
        print("EYE_LOCATE_JSON " + json.dumps(
            {"crop": out_path, "box": box, "center": center, "scale": scale,
             "px_per_mm": round(1 / per_px / 1000, 3)}, ensure_ascii=False))
        return

    pixels, width, height = load_pixels(path)

    # ---- 模式 C：从眼心向外走，量睑缘环（供开眼裂/拟合球心用）----
    rim_x = arg_value("--eye-x")
    if rim_x:
        eye_x = float(rim_x)
        eye_z = float(arg_value("--eye-z", "1.0686"))
        angles = [float(v) for v in arg_value("--angles",
                                              ",".join(str(a) for a in range(0, 360, 10))).split(",")]
        warm_limit = float(arg_value("--warm", "0.09"))
        r_max = float(arg_value("--r-max", "15"))
        verbose = tuple(float(v) for v in arg_value("--verbose-angles", "0,90,180,270").split(","))
        ring, diagnostics = walk_rim(obj, pixels, width, height, center, scale,
                                     (eye_x, eye_z), angles, warm_limit, r_max, verbose)
        radii = [point["r_mm"] for point in ring]
        summary = {
            "eye_xz": [eye_x, eye_z], "warm_limit": warm_limit,
            "points": len(ring), "r_mm": {
                "min": min(radii) if radii else None,
                "max": max(radii) if radii else None,
                "mean": round(sum(radii) / len(radii), 2) if radii else None,
            },
            "ring": ring,
        }
        out_json = out_prefix + "-rim.json"
        with open(out_json, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=1)
        print("=" * 96)
        print(f"睑缘环测量（眼心 xz={eye_x, eye_z}，warmth>{warm_limit}，r_max={r_max}mm）")
        print(f"  命中 {len(ring)}/{len(angles)} 个方向；r {summary['r_mm']} mm")
        print("   角度     r(mm)  warmth   world_x    world_z   表面Y")
        for point in ring:
            print(f"  {point['deg']:>5}  {point['r_mm']:>7}  {point['warmth']:>6}  "
                  f"{point['x']:>9} {point['z']:>9}  {point['surface_y']}")
        for angle, trace in diagnostics.items():
            print(f"  [诊断 {angle}°] (r_mm, warmth, value)：" +
                  " ".join(f"({t[0]:g},{t[1]:g},{t[2]:g})" for t in trace))
        print("EYE_LOCATE_RIM " + out_json)
        return

    half_px = int(0.011 / per_px)          # 窗口 ±11mm（避开刘海与颧骨）
    cx_px = (width - 1) / 2.0
    cy_px = (height - 1) / 2.0
    report = {"render": path, "center": center, "scale": scale, "resolution": resolution,
              "px_per_mm": round(1 / per_px / 1000, 3), "eyes": []}
    # 两眼在图像里的横向位置：按世界 x 的估计值各给一个窗口
    for side, guess_x in (("L", 0.027), ("R", -0.027)):
        window_cx = cx_px + (guess_x - center[0]) / 1000.0 / per_px
        window = [max(0, int(window_cx - half_px)), max(0, int(cy_px - half_px)),
                  min(width, int(window_cx + half_px)), min(height, int(cy_px + half_px))]
        entry = analyze_eye(obj, pixels, width, height, center, scale, window, threshold)
        entry["side"] = side
        report["eyes"].append(entry)

    print("=" * 96)
    print("眼位/眼裂测量（贴图上画出来的眼球）：" + path)
    print(f"正交比例 {scale}m/{resolution}px → {report['px_per_mm']} px/mm；中心 {center}")
    print(f"判定：亮度 > {threshold} 且 |R-B| < 0.12 的连通域（= 眼白/眼球，可排除暖色皮肤与黑发）")
    for eye in report["eyes"]:
        print("")
        if "error" in eye:
            print(f"--- [{eye['side']}] {eye['error']}（窗口 {eye['window']}）")
            continue
        print(f"--- [{eye['side']}] 眼位中心 (x,z)=({eye['world_xz'][0]}, {eye['world_xz'][1]})  "
              f"表面 Y={eye['surface_y']}")
        print(f"    眼裂：长轴 {eye['major_extent_mm']}mm / 短轴 {eye['minor_extent_mm']}mm / "
              f"倾角 {eye['tilt_deg']}°  面积 {eye['area_px']}px  连通域 {eye['blob_count']} 个")
        print(f"    像素质心 {eye['centroid_px']}  包围盒 {eye['bbox_px']}")
    print("EYE_LOCATE_JSON " + json.dumps(report, ensure_ascii=False))


main()
