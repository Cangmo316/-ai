#!/usr/bin/env python3
"""
比邻AI · 眼区重做（在原始高模上）

用法：
    blender --background <工作.blend> --python tools/blender-eye-rebuild.py -- \
        --out <输出.blend> [--render <前缀>] [--iris <eye_iris.png>] [--dry-run]

为什么上一轮的眼睛是错的（两个错，缺一不可）：
  1) **位置错**：球心放到了 x=±0.0239（往鼻梁偏 1cm），而原眼位是 x=±0.0349
  2) **前后关系错**：球以"眼窝中心"为球心，球一大就凸出、球一小可见部分就太小
     正确构造（真实眼睛的几何）：**球心向后退**，使球面顶点（角膜）落在**眼睑缘平面**上
        center_y = rim_y + R     （rim_y = 眼睑缘最靠前的 Y）
     这样眼睑自然压住球的边缘，既不会凸出、也不会露出过多的眼白

本脚本流程：
  量眼窝（凹陷深度图 → 眼窝范围）→ 按眼窝开眼裂（椭圆开口，保留雕塑自带的眼睑缘）
  → 按眼裂宽度定球半径 R → 球心置于 rim_y + R → 清掉多余的内部面
"""

import json
import math
import os
import sys

import bmesh
import bpy
from mathutils import Vector


def has_flag(name):
    return name in sys.argv


def arg_value(name, default=None):
    args = sys.argv
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return default


EYE_L = (0.0349, -0.0584, 1.0701)   # 原眼位（掏空前 eye.L 顶点组形心）
EYE_R = (-0.0344, -0.0587, 1.0708)


def head_mesh():
    return max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices), default=None)


def measure_socket(obj, center, half_x=0.018, half_z=0.014):
    """量眼窝：在**收紧的方形搜索盒**内取数据。

    ⚠️ 不能用球形搜索（半径 3cm 会把鼻根、颧部一起圈进来，实测量出"眼窝深 4.1cm"这种
    荒谬值）。眼窝只占 x∈中心±1.8cm、z∈中心±1.4cm 的一小块，且只在面部正面（Y<0）。
    """
    matrix = obj.matrix_world
    cx, _, cz = center
    found = []
    for v in obj.data.vertices:
        p = matrix @ v.co
        if p.y > 0:
            continue
        if abs(p.x - cx) > half_x or abs(p.z - cz) > half_z:
            continue
        found.append(p)
    if not found:
        return None
    rim_y = min(p.y for p in found)          # 最靠前 = 眼睑缘脊
    floor_y = max(p.y for p in found)        # 最靠后 = 眼窝底
    # 眼窝深度上限 12mm：再深就不是眼窝，而是别的结构了
    depth = min(floor_y - rim_y, 0.012)
    deep = [p for p in found if p.y > rim_y + depth * 0.30]
    if not deep:
        deep = found
    xs = [p.x for p in deep]
    zs = [p.z for p in deep]
    return {
        "rim_y": round(rim_y, 5),
        "floor_y": round(rim_y + depth, 5),
        "depth": round(depth, 5),
        "socket_half_width": round((max(xs) - min(xs)) / 2, 5),
        "socket_half_height": round((max(zs) - min(zs)) / 2, 5),
        "points": len(found),
    }


def cut_ellipse(obj, center, half_w, half_h, tilt_deg, y_range):
    """在 (x,z) 平面上按椭圆开口删面 → 生成干净的眼裂轮廓

    只删"面心落在椭圆内 且 处在眼窝深度范围内"的面，避免误删后脑/内侧的面。
    返回 (删除面数, 椭圆内候选面数) —— 后者用于诊断"为什么一个都没删"。
    """
    matrix = obj.matrix_world
    tilt = math.radians(tilt_deg)
    cx, _, cz = center
    doomed = []
    candidates = 0
    for poly in obj.data.polygons:
        pts = [matrix @ obj.data.vertices[i].co for i in poly.vertices]
        centroid = sum(pts, Vector((0, 0, 0))) / len(pts)
        dx = centroid.x - cx
        dz = centroid.z - cz
        ex = dx * math.cos(tilt) + dz * math.sin(tilt)
        ez = -dx * math.sin(tilt) + dz * math.cos(tilt)
        if (ex / half_w) ** 2 + (ez / half_h) ** 2 > 1.0:
            continue
        candidates += 1
        if y_range[0] <= centroid.y <= y_range[1]:
            doomed.append(poly.index)
    if not doomed:
        return 0, candidates
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.faces[i] for i in doomed], context="FACES")
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return len(doomed), candidates


def add_eyeball(center, radius, iris_path, name):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=20, radius=radius, location=center)
    ball = bpy.context.active_object
    ball.name = name
    material = bpy.data.materials.new("M_Eyeball_" + name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    # ⚠️ 不能用 nodes.get("Principled BSDF")：中文界面下节点名被本地化，会取到 None。
    # 一律按**节点类型**查找。
    bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        bsdf = next((n for n in nodes if n.type == "OUTPUT_MATERIAL"), None)
    if iris_path and os.path.exists(iris_path) and bsdf is not None:
        image = bpy.data.images.load(iris_path)
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = image
        material.node_tree.links.new(bsdf.inputs["Base Color"], tex.outputs["Color"])
    if bsdf is not None and "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = 0.25
    ball.data.materials.append(material)
    return ball


def render_views(prefix, eye_center):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 900
    scene.render.resolution_y = 900
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "TEXTURE"
    camera_data = bpy.data.cameras.new("eye_cam")
    camera_data.type = "ORTHO"
    camera = bpy.data.objects.new("eye_cam", camera_data)
    bpy.context.collection.objects.link(camera)
    scene.camera = camera
    views = [
        ("face", Vector((0, 0, eye_center[2] + 0.01)), Vector((0, -1, 0)), 0.14),
        ("eyemacro", Vector(eye_center), Vector((0, -1, 0)), 0.05),
        ("eyeside", Vector(eye_center), Vector((0.85, -0.5, 0.05)), 0.05),
    ]
    for label, center, direction, size in views:
        camera_data.ortho_scale = size
        camera.location = center + direction.normalized() * (size * 3)
        target = bpy.data.objects.new("eye_target", None)
        target.location = center
        bpy.context.collection.objects.link(target)
        track = camera.constraints.new("TRACK_TO")
        track.target = target
        track.track_axis = "TRACK_NEGATIVE_Z"
        track.up_axis = "UP_Y"
        scene.render.filepath = f"{prefix}-{label}.png"
        bpy.ops.render.render(write_still=True)
        camera.constraints.remove(track)
        bpy.data.objects.remove(target, do_unlink=True)
        print("EYE_RENDER " + scene.render.filepath)


def main() -> None:
    out = arg_value("--out")
    render_prefix = arg_value("--render")
    iris = arg_value("--iris")
    dry = has_flag("--dry-run")
    obj = head_mesh()
    if obj is None:
        print("EYE_REBUILD_FAIL 没有网格")
        return

    report = {"file": bpy.data.filepath, "mesh": obj.name, "verts_before": len(obj.data.vertices), "eyes": []}
    for side, center in (("L", EYE_L), ("R", EYE_R)):
        m = measure_socket(obj, center)
        if m is None:
            report["eyes"].append({"side": side, "error": "眼窝附近没有面部顶点"})
            continue
        # 眼裂尺寸：取眼窝横向范围的 0.75（略收，保留雕塑自带的眼睑缘脊）
        half_w = max(0.011, min(0.014, m["socket_half_width"] * 0.75))
        half_h = half_w * 0.76
        R = half_w * 1.08                      # 球半径略大于眼裂半宽，眼睑才能压住球
        rim_y = m["rim_y"]
        # 球心后退：让球面顶点（角膜）落在睑缘平面稍后一点，避免凸出
        ball_center = (center[0], rim_y + R * 0.95, center[2])
        entry = {
            "side": side,
            "socket": m,
            "fissure_half_w": round(half_w, 5),
            "fissure_half_h": round(half_h, 5),
            "ball_radius": round(R, 5),
            "ball_center": [round(v, 5) for v in ball_center],
        }
        if not dry:
            # 注意 Y 是负值：靠前更小 → 睑缘是下界、窝底是上界（写反会导致一个面都删不掉）
            y_range = (m["rim_y"] - 0.014, m["floor_y"] + 0.014)
            removed, candidates = cut_ellipse(obj, center, half_w, half_h, 7.0, y_range)
            entry["faces_removed"] = removed
            entry["ellipse_candidates"] = candidates
            add_eyeball(ball_center, R, iris, "eyeball_" + side)
            # 眼球基色贴图需要 UV：球体自带 UVMap
        report["eyes"].append(entry)

    print("=" * 78)
    print("眼区重做: " + report["file"])
    for eye in report["eyes"]:
        if "error" in eye:
            print(f"  [{eye['side']}] {eye['error']}")
            continue
        m = eye["socket"]
        print(f"  [{eye['side']}] 眼窝: 睑缘Y={m['rim_y']} 窝底Y={m['floor_y']} 深 {m['depth']}m "
              f"横向半宽 {m['socket_half_width']} 纵向半高 {m['socket_half_height']}")
        print(f"        眼裂: 半宽 {eye['fissure_half_w']} 半高 {eye['fissure_half_h']}；"
              f"球半径 {eye['ball_radius']} 球心 {eye['ball_center']}")
        if "faces_removed" in eye:
            print(f"        已删面 {eye['faces_removed']} 个 → 眼裂轮廓已生成")
    if not dry and render_prefix:
        render_views(render_prefix, EYE_L)
    if out and not dry:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("EYE_REBUILD_OK 已保存: " + out)
    print("EYE_REBUILD_JSON " + json.dumps(report, ensure_ascii=False))


main()
