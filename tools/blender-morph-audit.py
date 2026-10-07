#!/usr/bin/env python3
"""
比邻AI · 形变键质量审计（Blender 无头运行）

用法：
    blender --background <文件.blend> --python tools/blender-morph-audit.py -- [--top 15] [--json]

为什么需要它：判断"拖滑杆就扭曲"不能靠肉眼一格格看。这里对每个形态键置权重 1.0，
量三个客观指标：

  1. **最大边长拉伸比**：相邻顶点间边长 / 静息边长。> 1.6 基本就是可见撕裂/尖刺
     （商业级 blendshape 一般控制在 1.2 以内）
  2. **法线翻转面数**：面法线相对静息态翻转 → 面片"翻过去"，就是最典型的扭曲
  3. **最大顶点位移**（mm）：判断幅度是否合理

另外报告**组合叠加**后的指标：把若干键同时置 1.0（模拟用户多滑杆同拖），
组合往往比单键更容易炸 —— 这是"拖一下就完全扭曲"最常见的原因。
"""

import json
import sys

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


def mesh_target():
    """取主壳：顶点最多的那个网格"""
    target = None
    for obj in bpy.data.objects:
        if obj.type != "MESH" or not obj.data.shape_keys:
            continue
        if target is None or len(obj.data.vertices) > len(target.data.vertices):
            target = obj
    return target


def edge_pairs(mesh):
    pairs = set()
    for poly in mesh.polygons:
        keys = list(poly.vertices)
        for i in range(len(keys)):
            a, b = keys[i], keys[(i + 1) % len(keys)]
            pairs.add((a, b) if a < b else (b, a))
    return sorted(pairs)


def face_normal(mesh, poly):
    points = [mesh.vertices[i].co for i in poly.vertices]
    if len(points) < 3:
        return Vector((0, 0, 0))
    normal = (points[1] - points[0]).cross(points[2] - points[0])
    return normal.normalized() if normal.length > 1e-12 else Vector((0, 0, 0))


def evaluate(obj, rest_coords, rest_normals, pairs, weights, label):
    mesh = obj.data
    keys = mesh.shape_keys
    basis = keys.key_blocks[0]

    # 计算目标位置：basis + Σ w_i * (key_i - basis)
    positions = [Vector(rest_coords[i]) for i in range(len(mesh.vertices))]
    deltas = [Vector((0, 0, 0)) for _ in range(len(mesh.vertices))]
    for name, weight in weights.items():
        block = keys.key_blocks.get(name)
        if block is None or weight == 0:
            continue
        for i in range(len(mesh.vertices)):
            d = block.data[i].co - basis.data[i].co
            deltas[i] += d * weight
    for i in range(len(positions)):
        positions[i] += deltas[i]

    max_ratio = 0.0
    worst_pair = None
    for a, b in pairs:
        rest = (Vector(rest_coords[a]) - Vector(rest_coords[b])).length
        if rest < 1e-9:
            continue
        now = (positions[a] - positions[b]).length
        ratio = now / rest
        if ratio > max_ratio:
            max_ratio = ratio
            worst_pair = (a, b)
    min_ratio = 999.0
    for a, b in pairs:
        rest = (Vector(rest_coords[a]) - Vector(rest_coords[b])).length
        if rest < 1e-9:
            continue
        min_ratio = min(min_ratio, (positions[a] - positions[b]).length / rest)

    flipped = 0
    for poly, rest_normal in zip(mesh.polygons, rest_normals):
        points = [positions[i] for i in poly.vertices]
        if len(points) < 3:
            continue
        normal = (points[1] - points[0]).cross(points[2] - points[0])
        if normal.length < 1e-12:
            continue
        if normal.normalized().dot(rest_normal) < 0:
            flipped += 1

    max_disp = max((d.length for d in deltas), default=0.0)
    return {
        "label": label,
        "max_edge_ratio": round(max_ratio, 3),
        "min_edge_ratio": round(min_ratio, 3),
        "flipped_faces": flipped,
        "max_disp_mm": round(max_disp * 1000, 2),
    }


def main() -> None:
    top = int(arg_value("--top", "15"))
    obj = mesh_target()
    if obj is None:
        print("MORPH_AUDIT_FAIL 没有找到带形态键的网格")
        return
    mesh = obj.data
    keys = mesh.shape_keys
    basis = keys.key_blocks[0]
    rest_coords = [v.co.copy() for v in basis.data]
    rest_normals = [face_normal(mesh, p) for p in mesh.polygons]
    pairs = edge_pairs(mesh)

    singles = []
    for block in keys.key_blocks[1:]:
        singles.append(evaluate(obj, rest_coords, rest_normals, pairs, {block.name: 1.0}, block.name))
    singles.sort(key=lambda r: (-r["max_edge_ratio"], -r["flipped_faces"]))

    # 组合：把所有 shape_* 里"骨架级"的大范围参数一起拉满（模拟用户乱拖）
    coarse = [b.name for b in keys.key_blocks[1:] if b.name.startswith("shape_")][:20]
    combo = evaluate(obj, rest_coords, rest_normals, pairs, {n: 1.0 for n in coarse}, "前20个 shape_* 全拉满")
    combo_same_axis = evaluate(
        obj, rest_coords, rest_normals, pairs,
        {b.name: 1.0 for b in keys.key_blocks[1:] if b.name.endswith("_up")},
        "所有 _up 键全拉满",
    )

    report = {
        "object": obj.name,
        "verts": len(mesh.vertices),
        "keys": len(keys.key_blocks) - 1,
        "worst_single": singles[:top],
        "combos": [combo, combo_same_axis],
    }

    if has_flag("--json"):
        print("MORPH_AUDIT_JSON " + json.dumps(report, ensure_ascii=False))
        return

    print("=" * 78)
    print(f"形变键质量审计: {obj.name}  顶点 {report['verts']}  形态键 {report['keys']}")
    print("判定参考：max_edge_ratio > 1.6 基本可见撕裂；flipped_faces > 0 就是面片翻面")
    print("-" * 78)
    print(f"{'形态键':<34}{'最大拉伸':>9}{'最小压缩':>9}{'翻面数':>7}{'位移mm':>9}")
    for row in singles[:top]:
        print(f"{row['label']:<34}{row['max_edge_ratio']:>9}{row['min_edge_ratio']:>9}{row['flipped_faces']:>7}{row['max_disp_mm']:>9}")
    print("-" * 78)
    print("组合叠加：")
    for row in report["combos"]:
        print(f"{row['label']:<34}{row['max_edge_ratio']:>9}{row['min_edge_ratio']:>9}{row['flipped_faces']:>7}{row['max_disp_mm']:>9}")
    print("-" * 78)
    bad = [r for r in singles if r["max_edge_ratio"] > 1.6 or r["flipped_faces"] > 0]
    print(f"结论：{len(bad)} / {len(singles)} 个单键超阈值；组合叠加最大拉伸 {report['combos'][1]['max_edge_ratio']}")


main()
