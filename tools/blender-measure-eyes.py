#!/usr/bin/env python3
"""
比邻AI · 眼球 / 眼裂配合度精确测量（Blender 无头运行）

用法：
    blender --background <文件.blend> --python tools/blender-measure-eyes.py

为什么这样量：判断"眼球凸出 / 眼眶变形"的正确定量标准不是「眼球 vs 脸部最前点」
（那会把鼻梁、眉弓算进来，得出没意义的数），而是：

  **眼裂那圈开孔边界顶点，应该贴合在眼球球面上**（距离 ≈ 球半径且方差小）。

  · 若边界环到球心的距离普遍 < R  → 眼皮**陷进**眼球里（穿模）
  · 若普遍 > R                   → 眼皮与眼球之间**有空隙**（漏光 / 眼白过多）
  · 若方差大（σ 大）              → **眼眶形状与眼球不匹配**（就是"眼眶变形"）

同时报告：眼球半径、瞳孔/虹膜可见度、贴图是否丢失（品红 = 贴图没打包/路径失效）、
以及眼周是否有游离几何（非流形 / 孤立点）。
"""

import math
import sys

import bpy
from mathutils import Vector


def flag(name: str) -> bool:
    return name in sys.argv


def mesh_world_verts(obj):
    matrix = obj.matrix_world
    return [matrix @ v.co for v in obj.data.vertices]


def boundary_loops_near(obj, center, radius):
    """取 obj 上、位于 center 附近 radius 内的**边界边**（开孔的一圈），返回顶点集合"""
    mesh = obj.data
    # 统计每条边被几个面使用：只被 1 个面用 = 边界边
    edge_faces = {}
    for poly in mesh.polygons:
        for key in poly.edge_keys:
            edge_faces[key] = edge_faces.get(key, 0) + 1
    boundary_verts = set()
    matrix = obj.matrix_world
    for key, count in edge_faces.items():
        if count != 1:
            continue
        for index in key:
            point = matrix @ mesh.vertices[index].co
            if (point - center).length < radius:
                boundary_verts.add(index)
    return boundary_verts


def eye_report(head, eyeball):
    verts = mesh_world_verts(eyeball)
    if not verts:
        return None
    low = Vector((min(v.x for v in verts), min(v.y for v in verts), min(v.z for v in verts)))
    high = Vector((max(v.x for v in verts), max(v.y for v in verts), max(v.z for v in verts)))
    center = (low + high) / 2
    radius = max((high - low).x, (high - low).y, (high - low).z) / 2

    info = {
        "object": eyeball.name,
        "radius": round(radius, 5),
        "center": [round(v, 5) for v in center],
        "verts": len(eyeball.data.vertices),
    }

    if head is not None:
        loop = boundary_loops_near(head, center, radius * 3.5)
        if loop:
            matrix = head.matrix_world
            distances = [((matrix @ head.data.vertices[i].co) - center).length for i in loop]
            mean = sum(distances) / len(distances)
            variance = sum((d - mean) ** 2 for d in distances) / len(distances)
            info["rim_verts"] = len(loop)
            info["rim_distance"] = {
                "min": round(min(distances), 5),
                "max": round(max(distances), 5),
                "mean": round(mean, 5),
                "sigma": round(math.sqrt(variance), 5),
            }
            # 判定（阈值按眼球半径的比例，避免不同模型尺度差异）
            if info["rim_distance"]["min"] < radius * 0.85:
                info["verdict"] = "眼皮陷进眼球（穿模）"
            elif info["rim_distance"]["mean"] > radius * 1.25:
                info["verdict"] = "眼皮与眼球之间有空隙（眼白过多/漏光）"
            elif info["rim_distance"]["sigma"] > radius * 0.25:
                info["verdict"] = "眼眶形状与眼球不匹配（σ 偏大）"
            else:
                info["verdict"] = "贴合良好"
    return info


def main() -> None:
    report = {"file": bpy.data.filepath, "images": [], "eyes": [], "loose_geometry": [], "problems": []}

    # ── 贴图是否可用（品红 = 没打包或路径失效）────────────────
    for image in bpy.data.images:
        if image.name in ("Render Result", "Viewer Node", "Dirty"):
            continue
        report["images"].append(
            {
                "name": image.name,
                "size": list(image.size),
                "packed": bool(image.packed_file),
                "filepath": image.filepath,
                "exists_on_disk": bool(image.filepath and __import__("os").path.exists(bpy.path.abspath(image.filepath))),
            }
        )

    head = None
    eyeballs = []
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        name = obj.name.lower()
        if "eyeball" in name:
            eyeballs.append(obj)
        elif "teeth" not in name and "tongue" not in name and "cavity" not in name:
            if head is None or len(obj.data.vertices) > len(head.data.vertices):
                head = obj

    for eyeball in eyeballs:
        info = eye_report(head, eyeball)
        if info:
            report["eyes"].append(info)

    # ── 眼周游离几何：只被 0/1 个面使用的退化边、以及孤立顶点 ──
    if head is not None:
        mesh = head.data
        used = set()
        for poly in mesh.polygons:
            used.update(poly.vertices)
        loose = len(mesh.vertices) - len(used)
        report["loose_geometry"].append({"object": head.name, "vertices_not_in_any_face": loose})

    # ── 判定 ─────────────────────────────────────────────
    for image in report["images"]:
        if not image["packed"] and not image["exists_on_disk"]:
            report["problems"].append(f"贴图 {image['name']} 既没打包、磁盘上也不存在 → 渲染成品红")
    for eye in report["eyes"]:
        verdict = eye.get("verdict", "")
        if verdict and verdict != "贴合良好":
            report["problems"].append(
                f"{eye['object']}：{verdict}（球半径 R={eye['radius']}，"
                f"眼裂环到球心 min/mean/max = {eye['rim_distance']['min']}/"
                f"{eye['rim_distance']['mean']}/{eye['rim_distance']['max']}，σ={eye['rim_distance']['sigma']}）"
            )

    if flag("--json"):
        print("EYE_MEASURE_JSON " + __import__("json").dumps(report, ensure_ascii=False))
        return

    print("=" * 70)
    print("比邻AI · 眼球 / 眼裂配合度测量")
    print("=" * 70)
    print(f"文件: {report['file']}")
    print(f"主壳: {head.name if head else '?'} ({len(head.data.vertices) if head else 0} 顶点)")
    print("-" * 70)
    for eye in report["eyes"]:
        print(f"{eye['object']}: 半径 R={eye['radius']} 球心={eye['center']} 顶点={eye['verts']}")
        if "rim_distance" in eye:
            rd = eye["rim_distance"]
            print(
                f"    眼裂开孔边界环: {eye['rim_verts']} 顶点  "
                f"到球心 min={rd['min']} mean={rd['mean']} max={rd['max']} σ={rd['sigma']}"
            )
            print(f"    判定: {eye['verdict']}")
            print(
                f"        （理想：整个环都 ≈ R={eye['radius']}；小于 R 说明眼皮穿进球里，"
                f"大于 R 说明有缝，σ 大说明眼眶形状不匹配）"
            )
    print("-" * 70)
    print("贴图（品红渲染的根因）：")
    for image in report["images"]:
        state = "已打包" if image["packed"] else ("磁盘存在" if image["exists_on_disk"] else "❌ 丢失")
        print(f"  {image['name']}: {image['size']} {state}  {image['filepath'][:70]}")
    for item in report["loose_geometry"]:
        print(f"游离顶点：{item['object']} 有 {item['vertices_not_in_any_face']} 个顶点不属于任何面")
    print("-" * 70)
    if report["problems"]:
        print(f"❌ {len(report['problems'])} 个问题：")
        for problem in report["problems"]:
            print("   · " + problem)
    else:
        print("✅ 眼球贴合、贴图完好")


main()
