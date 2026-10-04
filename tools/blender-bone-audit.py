#!/usr/bin/env python3
"""
比邻AI · 骨骼形变审计（第 2 步验收：每根骨加载测试姿态，量拉伸与翻面）

用法：
    blender --background <工作.blend> --python tools/blender-bone-audit.py -- \
        [--json] [--max-stretch 1.3] [--angle 20] [--push-mm 4] [--only <骨名,骨名>]

判据（与形态键审计同一口径）：
  · **翻面 = 0**：三角形法线相对静息态反转（dot < 0）即算翻面，出现就是硬伤
  · **最大边长拉伸 ≤ 1.3**（目标；超过 1.6 视为不可交付）
  · 位移量级合理（同时打印，便于判断"这根骨到底有没有起作用"）

为什么必须做这个：粗轮廓捏脸要交给**骨骼**，但如果某根骨的权重场有硬边，
一拉就会出现尖刺/翻面——这正是上一版"拖动就扭曲"的成因之一。
"""

import json
import math
import sys

import bpy
import numpy as np
from mathutils import Vector

# 每根骨的测试姿态：rotate = 绕局部轴转（度）；translate = 沿世界轴平移（毫米）
TESTS = {
    # 机能骨：按各自的语义轴
    "neck": {"mode": "rotate", "axis": "X", "value": -18, "group": "functional"},
    "head": {"mode": "rotate", "axis": "Z", "value": 20, "group": "functional"},
    "jaw": {"mode": "rotate", "axis": "X", "value": 20, "group": "functional"},
    "chin": {"mode": "rotate", "axis": "X", "value": -12, "group": "functional"},
    "nose": {"mode": "rotate", "axis": "X", "value": 10, "group": "functional"},
    "lip_upper": {"mode": "rotate", "axis": "X", "value": 18, "group": "functional"},
    "lip_lower": {"mode": "rotate", "axis": "X", "value": -18, "group": "functional"},
    "tongue": {"mode": "rotate", "axis": "X", "value": 15, "group": "functional"},
    "eye.L": {"mode": "rotate", "axis": "Z", "value": 15, "group": "functional"},
    "eye.R": {"mode": "rotate", "axis": "Z", "value": -15, "group": "functional"},
    "eyelid_upper.L": {"mode": "rotate", "axis": "X", "value": 18, "group": "functional"},
    "eyelid_upper.R": {"mode": "rotate", "axis": "X", "value": 18, "group": "functional"},
    "eyelid_lower.L": {"mode": "rotate", "axis": "X", "value": -14, "group": "functional"},
    "eyelid_lower.R": {"mode": "rotate", "axis": "X", "value": -14, "group": "functional"},
    "brow.L": {"mode": "rotate", "axis": "X", "value": -14, "group": "functional"},
    "brow.R": {"mode": "rotate", "axis": "X", "value": -14, "group": "functional"},
    "ear.L": {"mode": "rotate", "axis": "Y", "value": 12, "group": "functional"},
    "ear.R": {"mode": "rotate", "axis": "Y", "value": -12, "group": "functional"},
    # 骨相骨：粗轮廓捏脸，按"推挤方向"测试
    "face_width": {"mode": "translate", "axis": "X", "value": 4, "group": "structural"},
    "face_length": {"mode": "translate", "axis": "Z", "value": 4, "group": "structural"},
    "forehead_height": {"mode": "translate", "axis": "Z", "value": 4, "group": "structural"},
    "forehead_width": {"mode": "translate", "axis": "X", "value": 4, "group": "structural"},
    "cheekbone.L": {"mode": "translate", "axis": "X", "value": 4, "group": "structural"},
    "cheekbone.R": {"mode": "translate", "axis": "X", "value": -4, "group": "structural"},
    "temple.L": {"mode": "translate", "axis": "X", "value": 4, "group": "structural"},
    "temple.R": {"mode": "translate", "axis": "X", "value": -4, "group": "structural"},
    "jaw_width.L": {"mode": "translate", "axis": "X", "value": 4, "group": "structural"},
    "jaw_width.R": {"mode": "translate", "axis": "X", "value": -4, "group": "structural"},
    "cheek_fat.L": {"mode": "translate", "axis": "Y", "value": -3, "group": "structural"},
    "cheek_fat.R": {"mode": "translate", "axis": "Y", "value": -3, "group": "structural"},
    "eye_socket.L": {"mode": "translate", "axis": "Y", "value": 3, "group": "structural"},
    "eye_socket.R": {"mode": "translate", "axis": "Y", "value": 3, "group": "structural"},
}

AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}


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


def read_positions(mesh_obj):
    count = len(mesh_obj.data.vertices)
    buffer = np.empty(count * 3, dtype=np.float64)
    mesh_obj.data.vertices.foreach_get("co", buffer)
    return buffer.reshape(count, 3)


def read_triangles(mesh_obj):
    mesh_obj.data.calc_loop_triangles()
    tri_count = len(mesh_obj.data.loop_triangles)
    buffer = np.empty(tri_count * 3, dtype=np.int32)
    mesh_obj.data.loop_triangles.foreach_get("vertices", buffer)
    return buffer.reshape(tri_count, 3)


def read_edges(mesh_obj):
    buffer = np.empty(len(mesh_obj.data.edges) * 2, dtype=np.int32)
    mesh_obj.data.edges.foreach_get("vertices", buffer)
    return buffer.reshape(-1, 2)


def evaluate_positions(mesh_obj):
    """取形变后的顶点坐标（走 depsgraph，含 Armature 修改器）"""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = mesh_obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    count = len(mesh.vertices)
    buffer = np.empty(count * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", buffer)
    positions = buffer.reshape(count, 3).copy()
    evaluated.to_mesh_clear()
    return positions


def triangle_normals(positions, triangles):
    a = positions[triangles[:, 0]]
    b = positions[triangles[:, 1]]
    c = positions[triangles[:, 2]]
    return np.cross(b - a, c - a)


def apply_test(armature, name, spec, angle, push_mm):
    bone = armature.pose.bones.get(name)
    if bone is None:
        return False
    bone.rotation_mode = "XYZ"
    if spec["mode"] == "rotate":
        axis = AXIS_INDEX[spec["axis"]]
        euler = [0.0, 0.0, 0.0]
        euler[axis] = math.radians(angle if spec["value"] > 0 else -angle)
        bone.rotation_euler = euler
    else:
        vector = Vector((0.0, 0.0, 0.0))
        vector[AXIS_INDEX[spec["axis"]]] = push_mm / 1000.0 * (1 if spec["value"] > 0 else -1)
        bone.location = vector
    return True


def clear_pose(armature):
    for bone in armature.pose.bones:
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0.0, 0.0, 0.0)
        bone.location = (0.0, 0.0, 0.0)
        bone.scale = (1.0, 1.0, 1.0)


def vertex_top_bones(mesh_obj, index, count=3):
    groups = {group.index: group.name for group in mesh_obj.vertex_groups}
    elements = sorted(mesh_obj.data.vertices[index].groups, key=lambda e: -e.weight)[:count]
    return [(groups[e.group], round(e.weight, 3)) for e in elements]


def main():
    max_stretch_limit = float(arg_value("--max-stretch", "1.3"))
    angle = float(arg_value("--angle", "20"))
    push_mm = float(arg_value("--push-mm", "4"))
    only = arg_value("--only")
    only_names = set(only.split(",")) if only else None
    want_json = has_flag("--json")
    worst_count = int(arg_value("--worst", "3"))
    significant_mm = float(arg_value("--significant-mm", "0.3"))

    mesh_obj = head_mesh()
    armature = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if mesh_obj is None or armature is None:
        print("BONE_AUDIT_FAIL 缺少网格或骨架")
        return
    groups = {group.name for group in mesh_obj.vertex_groups}

    rest = read_positions(mesh_obj)
    triangles = read_triangles(mesh_obj)
    edges = read_edges(mesh_obj)
    rest_edge_length = np.linalg.norm(rest[edges[:, 0]] - rest[edges[:, 1]], axis=1)
    valid_edge = rest_edge_length > 1e-7
    rest_normals = triangle_normals(rest, triangles)

    results = []
    for name, spec in TESTS.items():
        if only_names and name not in only_names:
            continue
        if name not in groups or armature.pose.bones.get(name) is None:
            results.append({"bone": name, "skipped": "无顶点组或骨骼"})
            continue
        clear_pose(armature)
        apply_test(armature, name, spec, angle, push_mm)
        bpy.context.view_layer.update()
        posed = evaluate_positions(mesh_obj)
        posed_edge_length = np.linalg.norm(posed[edges[:, 0]] - posed[edges[:, 1]], axis=1)
        ratios = np.ones_like(rest_edge_length)
        ratios[valid_edge] = posed_edge_length[valid_edge] / rest_edge_length[valid_edge]
        posed_normals = triangle_normals(posed, triangles)
        rest_area = np.linalg.norm(rest_normals, axis=1)
        posed_area = np.linalg.norm(posed_normals, axis=1)
        significant = (rest_area > 1e-12) & (posed_area > 1e-14)
        dots = np.ones(len(triangles))
        dots[significant] = (rest_normals[significant] * posed_normals[significant]).sum(axis=1) \
            / (rest_area[significant] * posed_area[significant])
        flipped = int(((dots < 0) & significant).sum())
        displacement = np.linalg.norm(posed - rest, axis=1)
        # 只统计"有意义的边"：碎边（< 0.3mm）拉伸比再大，绝对增量也可能看不见，
        # 但**绝对增量**骗不了人 —— 两个指标都报。
        big_edge = rest_edge_length > significant_mm / 1000.0
        big_ratio = ratios[big_edge] if big_edge.any() else ratios
        absolute_change = np.abs(posed_edge_length - rest_edge_length)
        worst = np.argsort(-absolute_change)[:worst_count] if worst_count else []
        results.append({
            "bone": name,
            "kind": spec["group"],
            "test": spec | {"angle": angle if spec["mode"] == "rotate" else None,
                            "push_mm": push_mm if spec["mode"] == "translate" else None},
            "max_stretch": round(float(ratios.max()), 4),
            "max_stretch_big": round(float(big_ratio.max()), 4),
            "p999_stretch": round(float(np.percentile(ratios, 99.9)), 4),
            "edges_over_1_3": int((ratios > 1.3).sum()),
            "edges_big_over_1_3": int((big_ratio > 1.3).sum()),
            "edges_over_1_6": int((ratios > 1.6).sum()),
            "flipped_triangles": flipped,
            "moved_vertices": int((displacement > 1e-5).sum()),
            "max_displacement_mm": round(float(displacement.max()) * 1000, 3),
            "max_abs_edge_change_mm": round(float(absolute_change.max()) * 1000, 4),
            "worst_edges": [
                {
                    "ratio": round(float(ratios[i]), 3),
                    "rest_len_mm": round(float(rest_edge_length[i]) * 1000, 5),
                    "change_mm": round(float(absolute_change[i]) * 1000, 4),
                    "mid": [round(float(v), 4) for v in (rest[edges[i, 0]] + rest[edges[i, 1]]) / 2],
                    "v0": vertex_top_bones(mesh_obj, int(edges[i, 0])),
                    "v1": vertex_top_bones(mesh_obj, int(edges[i, 1])),
                } for i in worst
            ],
        })
    clear_pose(armature)
    bpy.context.view_layer.update()

    failures = [item for item in results if item.get("flipped_triangles", 0) > 0
                or item.get("max_stretch_big", 0) > max_stretch_limit]
    report = {"file": bpy.data.filepath, "mesh": mesh_obj.name, "armature": armature.name,
              "vertices": int(len(rest)), "triangles": int(len(triangles)),
              "limit": {"max_stretch": max_stretch_limit,
                        "significant_edge_mm": significant_mm},
              "results": results,
              "failures": [item["bone"] for item in failures]}

    print("=" * 100)
    print("骨骼形变审计 : " + bpy.data.filepath)
    print(f"  网格 {mesh_obj.name}  {len(rest)} 顶点 / {len(triangles)} 三角面")
    print(f"  判据：翻面 = 0，且**有效边**（原长 > {significant_mm}mm）最大拉伸 ≤ {max_stretch_limit}")
    print(f"  测试姿态：机能骨旋转 ±{angle}°，骨相骨平移 ±{push_mm}mm")
    print("")
    print(f"  {'骨骼':<20}{'类':<11}{'有效边拉伸':>11}{'全边拉伸':>10}{'绝对增量mm':>11}"
          f"{'有效边>1.3':>11}{'翻面':>7}{'动顶点':>9}   判定")
    for item in results:
        if "skipped" in item:
            print(f"  {item['bone']:<20}{'—':<11}{'跳过：' + item['skipped']}")
            continue
        bad = item["flipped_triangles"] > 0 or item["max_stretch_big"] > max_stretch_limit
        verdict = "✗ 不合格" if bad else "✓"
        print(f"  {item['bone']:<20}{item['kind']:<11}{item['max_stretch_big']:>11}"
              f"{item['max_stretch']:>10}{item['max_abs_edge_change_mm']:>11}"
              f"{item['edges_big_over_1_3']:>11}{item['flipped_triangles']:>7}"
              f"{item['moved_vertices']:>9}   {verdict}")
    for item in results:
        if "skipped" in item or not item.get("worst_edges"):
            continue
        print("")
        print(f"  ▸ {item['bone']} 绝对增量最大的边：")
        for edge in item["worst_edges"]:
            print(f"      拉伸 {edge['ratio']}×  原长 {edge['rest_len_mm']}mm → "
                  f"增量 {edge['change_mm']}mm  中点 {edge['mid']}")
            print(f"         v0 {edge['v0']}")
            print(f"         v1 {edge['v1']}")
    print("")
    if failures:
        print(f"  ✗ 不合格 {len(failures)} 根：" + ", ".join(item["bone"] for item in failures))
    else:
        print(f"  ✓ 全部 {len([r for r in results if 'skipped' not in r])} 根骨通过")
    if want_json:
        print("BONE_AUDIT_JSON " + json.dumps(report, ensure_ascii=False))


main()
