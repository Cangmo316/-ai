#!/usr/bin/env python3
"""
比邻AI · 眼区重做 v2（按"画上去的眼睛"开眼裂 + 按开孔环拟合眼球，不动皮肤顶点）

用法：
    blender --background <工作.blend> --python tools/blender-eye-rebuild2.py -- \
        --out <输出.blend> [--render <前缀>] [--eyeball-from <含眼球的.blend>] \
        [--spec <眼区参数.json>] [--ball-scale 1.02] [--overlap-mm 0.6] [--dry-run]

v1 为什么必须推翻（三条，都有实测）：
  1. **球太小**：雕塑上画出来的眼裂约 18.8×15.8mm，而上一轮的球直径只有 **14.2mm**
     → 两侧眼角必然漏出洞。我上一轮还"把睑缘环吸到球面上"，等于把洞口的皮肤
     往里面拽 → 拉出硬折痕（越修越坏）。
  2. **眼位来源错了**：`eye.L` 顶点组形心 (x=0.0349) 是**眼皮皮肤**的形心，
     不是眼位；画上去的眼球中心在 **x≈0.0269**。我按皮肤形心把球搬到 0.0349，
     反而偏了 ~8mm。
  3. **`rim_y` 取到睫毛尖**：搜索盒里"最靠前的点"是刘海/睫毛，球被推到脸前。

v2 的正确做法：
  1. 用**贴图渲染量出来的眼裂椭圆**（中心/长短轴/倾角）在雕塑上开孔
     —— 开孔边界就是美术画出来的眼裂边界（不再自己猜）
  2. 开孔后，取**网格的真实边界环**（拓扑边界，不是启发式检测）
  3. 用**定半径球拟合**（R 由眼裂半宽定，只解球心）把球贴合到这个环上
  4. **一律不动皮肤顶点**：靠"球的位置与大小"去适配洞口，而不是把洞口拽到球上
  5. 输出量化验收：覆盖比（R/ρ_max）、最差台阶（球面比睑缘靠后多少）、是否外凸
"""

import json
import math
import os
import sys

import bmesh
import bpy
from mathutils import Vector

# 贴图渲染量出来的眼裂（见 tools/blender-eye-locate.py 的测量输出）
DEFAULT_SPEC = {
    "L": {"center": [0.0269, 1.0686], "half_w": 0.0094, "half_h": 0.0077, "tilt_deg": -4.0},
    "R": {"center": [-0.0269, 1.0686], "half_w": 0.0094, "half_h": 0.0077, "tilt_deg": 4.0},
}


def arg_value(name, default=None):
    args = sys.argv
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return default


def has_flag(name):
    return name in sys.argv


def head_mesh():
    return max((o for o in bpy.data.objects if o.type == "MESH"),
               key=lambda o: len(o.data.vertices), default=None)


def cut_aperture(obj, spec, y_window, dry):
    """按椭圆开孔；只删"平面在椭圆内 且 Y 落在眼窝深度带内"的面

    Y 窗口写反会导致"一个面都没删"的静默失败（v1 踩过），所以这里同时返回候选数。
    """
    matrix = obj.matrix_world
    cx, cz = spec["center"]
    half_w, half_h = spec["half_w"], spec["half_h"]
    tilt = math.radians(spec["tilt_deg"])
    doomed = []
    candidates = 0
    for poly in obj.data.polygons:
        centroid = Vector((0, 0, 0))
        for index in poly.vertices:
            centroid += matrix @ obj.data.vertices[index].co
        centroid /= len(poly.vertices)
        if centroid.y > 0:
            continue
        dx = centroid.x - cx
        dz = centroid.z - cz
        ex = dx * math.cos(tilt) + dz * math.sin(tilt)
        ez = -dx * math.sin(tilt) + dz * math.cos(tilt)
        if (ex / half_w) ** 2 + (ez / half_h) ** 2 > 1.0:
            continue
        candidates += 1
        if y_window[0] <= centroid.y <= y_window[1]:
            doomed.append(poly.index)
    if dry or not doomed:
        return {"candidates": candidates, "removed": 0}
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.faces[i] for i in doomed], context="FACES")
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return {"candidates": candidates, "removed": len(doomed)}


def eye_ring(obj, spec, radius_limit):
    """取眼区附近的**拓扑边界环**（开孔后的洞口边）"""
    matrix = obj.matrix_world
    mesh = obj.data
    counts = {}
    for poly in mesh.polygons:
        for key in poly.edge_keys:
            counts[key] = counts.get(key, 0) + 1
    cx, cz = spec["center"]
    points = []
    for (a, b), count in counts.items():
        if count != 1:
            continue
        for index in (a, b):
            point = matrix @ mesh.vertices[index].co
            if point.y > 0.02:
                continue
            if math.hypot(point.x - cx, point.z - cz) > radius_limit:
                continue
            points.append(point)
    # 去重（边界边共享顶点）
    unique = {}
    for point in points:
        unique[(round(point.x, 6), round(point.y, 6), round(point.z, 6))] = point
    return list(unique.values())


def fit_center_fixed_radius(points, radius, iterations=80):
    """定半径、自由球心：迭代重心法（比代数最小二乘稳，后者在小片球面上会给出 1 米半径）"""
    center = Vector((sum(p.x for p in points) / len(points),
                     sum(p.y for p in points) / len(points) + radius * 0.5,
                     sum(p.z for p in points) / len(points)))
    barycenter = Vector((sum(p.x for p in points) / len(points),
                         sum(p.y for p in points) / len(points),
                         sum(p.z for p in points) / len(points)))
    for _ in range(iterations):
        normal_sum = Vector((0, 0, 0))
        for point in points:
            delta = point - center
            length = delta.length
            if length > 1e-9:
                normal_sum += delta / length
        center = barycenter - normal_sum / len(points) * radius
    return center


def scan_radius(ring):
    """扫描球半径，找让"睑缘环到球心距离"最一致的 R

    这是"能不能用球"的**判定性测试**：若存在某个 R 使残差 σ 很小（< 0.3mm），
    球就是几何上成立的方案；若最优 σ 也有好几毫米，说明这个眼窝根本不是球面，
    插球必然出现"一侧外凸、另一侧深坑"，必须换形态（穹顶/移动睑缘）。
    """
    radii = []
    for step in range(0, 121):
        radius = 0.0090 + step * 0.0005           # 9.0mm → 69.0mm
        center = fit_center_fixed_radius(ring, radius)
        distances = [(p - center).length for p in ring]
        mean = sum(distances) / len(distances)
        sigma = math.sqrt(sum((d - mean) ** 2 for d in distances) / len(distances))
        # 覆盖率：正面投影下，洞口是否全部落在球的轮廓圆内
        projections = [math.hypot(p.x - center.x, p.z - center.z) for p in ring]
        radii.append({
            "R_mm": round(radius * 1000, 2),
            "sigma_mm": round(sigma * 1000, 3),
            "coverage": round(radius / max(projections), 4),
            "center": [round(v, 6) for v in center],
            "step_spread_mm": round((max(distances) - min(distances)) * 1000, 2),
        })
    best = min((item for item in radii if item["coverage"] >= 1.0),
               key=lambda item: item["sigma_mm"], default=None)
    return radii, best


def fit_sphere_fixed_axis(ring, axis_x, axis_z, radius):
    """把球的 (x,z) 轴固定在眼裂中心，只用闭式解求深度 y_c

    为什么不再自由拟合球心：自由拟合会把球心挪离眼裂中心（实测挪了 1.7mm），
    于是眼裂一侧的边界点落到球面之外（ρ > R）→ 投影上直接漏洞。
    球是旋转对称的，把轴钉在眼裂中心、只解深度，才是"球去适配洞口"的正确自由度。

    闭式解：球面在 (x,z) 处的 Y 为 y_c - sqrt(R² - ρ²)，令其等于该边界点的 Y：
            y_c = Y_i + sqrt(R² - ρ_i²)，取所有边界点的均值（最小二乘）。
    """
    values = []
    for point in ring:
        rho = math.hypot(point.x - axis_x, point.z - axis_z)
        if rho >= radius:
            continue
        values.append(point.y + math.sqrt(radius * radius - rho * rho))
    if not values:
        return None
    return sum(values) / len(values)


def evaluate_fit(ring, center, radius, axis_x, axis_z):
    """验收指标：覆盖比 / 台阶分布 / 是否外凸（全部相对**眼裂中轴**度量）"""
    projections = []
    steps = []
    for point in ring:
        rho = math.hypot(point.x - axis_x, point.z - axis_z)
        projections.append(rho)
        if rho < radius:
            ball_y = center[1] - math.sqrt(radius * radius - rho * rho)
            steps.append((ball_y - point.y) * 1000.0)
        else:
            steps.append(None)
    covered = [s for s in steps if s is not None]
    return {
        "rho_max_mm": round(max(projections) * 1000, 2),
        "rho_mean_mm": round(sum(projections) / len(projections) * 1000, 2),
        "coverage_ratio": round(radius / max(projections), 4),
        "step_min_mm": round(min(covered), 2) if covered else None,
        "step_max_mm": round(max(covered), 2) if covered else None,
        "step_mean_mm": round(sum(covered) / len(covered), 2) if covered else None,
        "uncovered_points": sum(1 for s in steps if s is None),
        "protrudes": bool(covered and min(covered) < -0.05),
    }


def ring_profile(ring, axis_x, axis_z):
    """睑缘环的极坐标剖面（角度 / 半径 / Y），用来判断眼窝到底像不像球"""
    profile = []
    for point in ring:
        dx = point.x - axis_x
        dz = point.z - axis_z
        profile.append({
            "deg": round(math.degrees(math.atan2(dz, dx)), 1),
            "rho_mm": round(math.hypot(dx, dz) * 1000, 2),
            "y": round(point.y, 6),
        })
    profile.sort(key=lambda item: item["deg"])
    ys = [item["y"] for item in profile]
    return profile, {"y_min": min(ys), "y_max": max(ys),
                     "y_span_mm": round((max(ys) - min(ys)) * 1000, 2)}


def ensure_eyeball(source_blend, name):
    for obj in bpy.data.objects:
        if obj.type == "MESH" and obj.name.startswith(name):
            return obj
    if not source_blend or not os.path.exists(source_blend):
        return None
    with bpy.data.libraries.load(source_blend, link=False) as (src, dst):
        dst.objects = [n for n in src.objects if n.startswith(name)]
    for obj in dst.objects:
        if obj is not None:
            bpy.context.scene.collection.objects.link(obj)
            return obj
    return None


def place_ball(obj, center, radius):
    """把球对象缩放/平移到目标位置（球心 = 网格数据的包围盒中心）"""
    matrix = obj.matrix_world
    low = Vector((1e9, 1e9, 1e9))
    high = Vector((-1e9, -1e9, -1e9))
    for vertex in obj.data.vertices:
        point = matrix @ vertex.co
        for k in range(3):
            low[k] = min(low[k], point[k])
            high[k] = max(high[k], point[k])
    current_center = (low + high) / 2
    current_radius = max((high - low).x, (high - low).y, (high - low).z) / 2
    if current_radius <= 0:
        return None
    scale = radius / current_radius
    obj.scale = (obj.scale[0] * scale, obj.scale[1] * scale, obj.scale[2] * scale)
    bpy.context.view_layer.update()
    matrix = obj.matrix_world
    low = Vector((1e9, 1e9, 1e9))
    high = Vector((-1e9, -1e9, -1e9))
    for vertex in obj.data.vertices:
        point = matrix @ vertex.co
        for k in range(3):
            low[k] = min(low[k], point[k])
            high[k] = max(high[k], point[k])
    now_center = (low + high) / 2
    obj.location = obj.location + (Vector(center) - now_center)
    bpy.context.view_layer.update()
    return {"scale": round(scale, 5),
            "from_radius_mm": round(current_radius * 1000, 2),
            "to_radius_mm": round(radius * 1000, 2)}


def main():
    out = arg_value("--out")
    render_prefix = arg_value("--render")
    source_blend = arg_value("--eyeball-from")
    ball_scale = float(arg_value("--ball-scale", "1.02"))
    overlap = float(arg_value("--overlap-mm", "0.6")) / 1000.0
    dry = has_flag("--dry-run")
    spec_path = arg_value("--spec")
    spec = DEFAULT_SPEC
    if spec_path and os.path.exists(spec_path):
        with open(spec_path, encoding="utf-8") as handle:
            spec = json.load(handle)

    obj = head_mesh()
    if obj is None:
        print("EYE_REBUILD2_FAIL 没有网格")
        return

    report = {"file": bpy.data.filepath, "mesh": obj.name, "eyes": []}
    for side in ("L", "R"):
        entry = {"side": side, "spec": spec[side]}
        # 先量一次眼窝深度带：从眼心做正面射线，取表面 Y 与其后 12mm
        shot = []
        matrix = obj.matrix_world
        inverse = matrix.inverted()
        direction = (inverse.to_3x3() @ Vector((0, 1, 0))).normalized()
        cx, cz = spec[side]["center"]
        for dx in (-6, -3, 0, 3, 6):
            for dz in (-5, 0, 5):
                ok, location, _n, _i = obj.ray_cast(
                    inverse @ Vector((cx + dx / 1000.0, -0.30, cz + dz / 1000.0)),
                    direction, distance=0.6)
                if ok:
                    shot.append((matrix @ location).y)
        if not shot:
            entry["error"] = "眼区射线全部落空"
            report["eyes"].append(entry)
            continue
        front = min(shot)
        entry["surface_front_y"] = round(front, 6)
        y_window = (front - 0.004, front + 0.014)
        entry["y_window"] = [round(v, 6) for v in y_window]

        ring_before = eye_ring(obj, spec[side], 0.030)
        entry["ring_before"] = len(ring_before)

        if not dry:
            cut = cut_aperture(obj, spec[side], y_window, dry=False)
            entry["cut"] = cut
            ring = eye_ring(obj, spec[side], 0.030)
        else:
            ring = ring_before
        entry["ring_points"] = len(ring)
        if len(ring) < 8:
            entry["error"] = f"洞口边界点太少（{len(ring)}）"
            report["eyes"].append(entry)
            continue

        projections = [math.hypot(p.x - cx, p.z - cz) for p in ring]
        radius = max(projections) * ball_scale
        entry["ball_radius_mm"] = round(radius * 1000, 2)
        center_y = fit_sphere_fixed_axis(ring, cx, cz, radius)
        if center_y is None:
            entry["error"] = "所有边界点到中轴的距离都超过球半径"
            report["eyes"].append(entry)
            continue
        center = (cx, center_y + overlap, cz)
        entry["ball_center"] = [round(v, 6) for v in center]
        entry["fit"] = evaluate_fit(ring, center, radius, cx, cz)
        profile, spread = ring_profile(ring, cx, cz)
        entry["ring_y"] = spread
        entry["ring_profile"] = profile
        scan, best = scan_radius(ring)
        entry["radius_scan_best"] = best

        if not dry:
            ball = ensure_eyeball(source_blend, "eyeball_" + side)
            if ball is not None:
                entry["ball_object"] = ball.name
                entry["ball_place"] = place_ball(ball, center, radius)
            else:
                entry["ball_object"] = None
        report["eyes"].append(entry)

    print("=" * 96)
    print("眼区重做 v2 : " + bpy.data.filepath)
    for entry in report["eyes"]:
        print("")
        print(f"--- [{entry['side']}] 眼裂椭圆 中心{entry['spec']['center']} "
              f"半宽 {entry['spec']['half_w'] * 1000:.1f}mm 半高 {entry['spec']['half_h'] * 1000:.1f}mm "
              f"倾角 {entry['spec']['tilt_deg']}°")
        if "error" in entry:
            print("    " + entry["error"])
            continue
        print(f"    表面前沿 Y={entry['surface_front_y']}  开孔 Y 窗口 {entry['y_window']}")
        print(f"    开孔：候选面 {entry.get('cut', {}).get('candidates')} → 已删 "
              f"{entry.get('cut', {}).get('removed')}；洞口边界点 {entry['ring_points']} 个")
        print(f"    球：半径 {entry['ball_radius_mm']}mm  球心 {entry['ball_center']}")
        fit = entry["fit"]
        print(f"    验收：覆盖比 {fit['coverage_ratio']}（须 ≥1）  "
              f"未覆盖点 {fit['uncovered_points']}  ρ_max {fit['rho_max_mm']}mm")
        print(f"          台阶（球面相对睑缘，正=球在后）min {fit['step_min_mm']} / "
              f"mean {fit['step_mean_mm']} / max {fit['step_max_mm']} mm  "
              f"外凸={fit['protrudes']}")
        print(f"          睑缘环 Y 跨度 {entry['ring_y']['y_span_mm']}mm "
              f"（Y {entry['ring_y']['y_min']} ~ {entry['ring_y']['y_max']}）"
              f"  ← 球面在同一环上的 Y 只能差 "
              f"{round((radius - math.sqrt(max(0.0, radius ** 2 - (fit['rho_min_mm'] if 'rho_min_mm' in fit else 0) ** 2))) * 1000, 1)}mm 量级")
        print("          环剖面(deg/rho_mm/Y)：")
        line = "            "
        for item in entry["ring_profile"]:
            line += f"{item['deg']:g}:{item['rho_mm']:g}/{item['y']}  "
            if len(line) > 150:
                print(line)
                line = "            "
        if line.strip():
            print(line)
        best = entry.get("radius_scan_best")
        if best:
            print(f"    ★ 球形可行性扫描：最优 R={best['R_mm']}mm 时 σ={best['sigma_mm']}mm "
                  f"（球心距环的距离离散度，spread {best['step_spread_mm']}mm）"
                  f" 覆盖 {best['coverage']}  球心 {best['center']}")
            print(f"      判据：σ < 0.3mm 才算「睑缘环落在球面上」；"
                  f"σ 若达毫米级 → 该眼窝不是球面，插球必然一侧外凸/一侧深坑")
    if render_prefix and not dry:
        print("EYE_REBUILD2_RENDER " + render_prefix)
    if out and not dry:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("EYE_REBUILD2_OK 已保存 " + out)
    print("EYE_REBUILD2_JSON " + json.dumps(report, ensure_ascii=False))


main()
