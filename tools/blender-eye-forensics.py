#!/usr/bin/env python3
"""
比邻AI · 眼区取证（Blender 无头运行）

用法：
    blender --background <文件.blend> --python tools/blender-eye-forensics.py -- [--json]

回答的问题（用户反馈："女生眼球重做过，原眼球位置被掏空，新眼球不在原眼位，
把眼内部当成了眼眶"）：

  1. **原眼位在哪**：头部网格上权重大于 0.5 的 `eye.L` / `eye.R` 顶点组的形心
     —— 这是模型作者原本认作"眼睛"的那块皮肤，是解剖学上的眼位基准
  2. **新眼球在哪**：`eyeball_L/R` 的球心与半径
  3. **偏了多少**：球心 ↔ 原眼位形心的距离（这就是"不在原眼位"的量化）
  4. **眼眶有几圈边界**：把眼区附近的**边界边连成环**，逐个报告环的顶点数/形心/半径
     —— 正常应只有 1 圈（眼裂开口）；出现 2 圈以上说明存在"内部掏空腔"，
     我之前吸附的很可能是内腔那圈（所以怎么调都不像）
  5. **有没有朝内的面**：面法线指向眼球中心（内表面）的数量 —— 内腔的标志
"""

import json
import math
import sys

import bpy
from mathutils import Vector


def has_flag(name):
    return name in sys.argv


def world(obj, co):
    return obj.matrix_world @ co


def bbox_center_radius(obj):
    points = [world(obj, v.co) for v in obj.data.vertices]
    if not points:
        return None, None
    low = Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points)))
    high = Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points)))
    return (low + high) / 2, max((high - low).x, (high - low).y, (high - low).z) / 2


def group_centroid(obj, names):
    """指定顶点组（weight > 0.5）的形心 + 顶点数"""
    indices = []
    for name in names:
        group = obj.vertex_groups.get(name)
        if not group:
            continue
        gi = group.index
        for v in obj.data.vertices:
            for g in v.groups:
                if g.group == gi and g.weight > 0.5:
                    indices.append(v.index)
                    break
    if not indices:
        return None, 0
    total = Vector((0, 0, 0))
    for i in set(indices):
        total += world(obj, obj.data.vertices[i].co)
    return total / len(set(indices)), len(set(indices))


def boundary_loops(obj, center, radius):
    """把 center 附近的边界边连成环，返回 [{verts, centroid, meanRadius, maxRadius}]"""
    mesh = obj.data
    edge_faces = {}
    for poly in mesh.polygons:
        for key in poly.edge_keys:
            edge_faces[key] = edge_faces.get(key, 0) + 1
    adjacency = {}
    for key, count in edge_faces.items():
        if count != 1:
            continue
        a, b = key
        pa, pb = world(obj, mesh.vertices[a].co), world(obj, mesh.vertices[b].co)
        if (pa - center).length > radius and (pb - center).length > radius:
            continue
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)
    seen = set()
    loops = []
    for start in adjacency:
        if start in seen:
            continue
        stack = [start]
        comp = []
        seen.add(start)
        while stack:
            node = stack.pop()
            comp.append(node)
            for nxt in adjacency[node]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        total = Vector((0, 0, 0))
        for i in comp:
            total += world(obj, mesh.vertices[i].co)
        centroid = total / len(comp)
        distances = [(world(obj, mesh.vertices[i].co) - center).length for i in comp]
        loops.append(
            {
                "verts": len(comp),
                "centroid": [round(v, 5) for v in centroid],
                "meanRadius": round(sum(distances) / len(distances), 5),
                "maxRadius": round(max(distances), 5),
                "distanceToEye": round((centroid - center).length, 5),
            }
        )
    loops.sort(key=lambda item: -item["verts"])
    return loops


def inward_faces(obj, center, radius):
    """面法线指向眼球中心（= 朝向内腔的面）的数量"""
    mesh = obj.data
    count = 0
    for poly in mesh.polygons:
        centroid = Vector((0, 0, 0))
        for i in poly.vertices:
            centroid += world(obj, mesh.vertices[i].co)
        centroid /= len(poly.vertices)
        if (centroid - center).length > radius * 2.5:
            continue
        points = [world(obj, mesh.vertices[i].co) for i in poly.vertices]
        normal = (points[1] - points[0]).cross(points[2] - points[0])
        if normal.length < 1e-12:
            continue
        normal.normalize()
        to_center = (center - centroid)
        if to_center.length < 1e-9:
            continue
        if normal.dot(to_center.normalized()) > 0.5:
            count += 1
    return count


def main() -> None:
    head = None
    eyeballs = []
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        name = obj.name.lower()
        if "eyeball" in name:
            eyeballs.append(obj)
        elif not any(k in name for k in ("teeth", "tongue", "cavity")):
            if head is None or len(obj.data.vertices) > len(head.data.vertices):
                head = obj

    report = {"file": bpy.data.filepath, "head": head.name if head else None, "eyes": [], "boundary_loops_all": 0}

    if head is not None:
        edge_faces = {}
        for poly in head.data.polygons:
            for key in poly.edge_keys:
                edge_faces[key] = edge_faces.get(key, 0) + 1
        report["boundary_loops_all"] = sum(1 for c in edge_faces.values() if c == 1)

    sides = [("L", ["eye.L", "eye_L"]), ("R", ["eye.R", "eye_R"])]
    for side, group_names in sides:
        anatomical, skin_verts = group_centroid(head, group_names) if head else (None, 0)
        ball = None
        for obj in eyeballs:
            if obj.name.endswith(side) or obj.name.endswith("." + side) or ("_" + side) in obj.name:
                ball = obj
                break
        center, radius = bbox_center_radius(ball) if ball else (None, None)
        entry = {
            "side": side,
            "ball": ball.name if ball else None,
            "ball_center": [round(v, 5) for v in center] if center else None,
            "ball_radius": round(radius, 5) if radius else None,
            "anatomical_eye_center": [round(v, 5) for v in anatomical] if anatomical else None,
            "eye_group_verts": skin_verts,
        }
        if center and anatomical:
            entry["ball_to_anatomical_mm"] = round((center - anatomical).length * 1000, 2)
        if center and head is not None:
            entry["boundary_loops"] = boundary_loops(head, center, radius * 3.5)
            entry["inward_faces_near_eye"] = inward_faces(head, center, radius)
        report["eyes"].append(entry)

    if has_flag("--json"):
        print("EYE_FORENSICS_JSON " + json.dumps(report, ensure_ascii=False))
        return

    print("=" * 80)
    print("眼区取证: " + report["file"])
    print(f"头部网格: {report['head']}   全网格边界边: {report['boundary_loops_all']}")
    for eye in report["eyes"]:
        print("-" * 80)
        print(f"[{eye['side']}] 眼球对象 {eye['ball']}")
        print(f"    新球心 {eye['ball_center']}  半径 {eye['ball_radius']} m ({(eye['ball_radius'] or 0) * 1000:.2f} mm)")
        print(f"    原眼位（eye.{eye['side']} 顶点组 {eye['eye_group_verts']} 个顶点的形心） {eye['anatomical_eye_center']}")
        if "ball_to_anatomical_mm" in eye:
            print(f"    ★ 新球心 ↔ 原眼位距离 = {eye['ball_to_anatomical_mm']} mm")
        if "boundary_loops" in eye:
            print(f"    眼区边界环 {len(eye['boundary_loops'])} 圈，朝内面 {eye['inward_faces_near_eye']} 个")
            for i, loop in enumerate(eye["boundary_loops"][:6]):
                print(
                    f"      环{i}: {loop['verts']} 顶点  形心 {loop['centroid']}  "
                    f"到球心均值 {loop['meanRadius']}  环心离球心 {loop['distanceToEye']}"
                )
    print("=" * 80)


main()
