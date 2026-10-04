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

⚠️ **一条 1.3 的门槛同时卡"大头"和"碎屑"是错的**（本轮实测结论，见任务笔记 §8.11）：
  这个网格有 **36.7 万条 < 1mm 的微边**（3D 扫描重建的高密度细节）。
  拉伸比 = 变形后边长 / 原边长，**在微边上会被杠杆臂放大到 10~20×**：
  实测 `jaw` 最差边原长 0.32mm、绝对增量 4.9mm —— 外观上完全看不见，
  但比例上是 15×。因此本脚本按**边长分档**判定（与上一代交付链的 1.89~1.99× 口径对齐）：
    · 有效边（> `--significant-mm`，默认 0.3mm）：拉伸 ≤ `--max-stretch`（默认 2.0）
    · 全边：拉伸 ≤ `--hard-stretch`（默认 6.0）
    · 微边（< 0.3mm）：用**绝对增量** ≤ `--micro-mm`（默认 1.0mm）收口
  用 `--legacy` 可以退回"单条 1.3 门槛"的旧口径做对比。
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


def triangle_centroids(positions, triangles):
    return positions[triangles].mean(axis=1)


def bbox_of(points, quantile=0.9):
    """给一批点算"去掉极值后仍覆盖 `quantile`"的包围盒（用来看病灶集中在哪）"""
    if len(points) == 0:
        return None
    bounds = []
    for axis in range(3):
        values = points[:, axis]
        low = float(np.quantile(values, (1.0 - quantile) / 2.0))
        high = float(np.quantile(values, 1.0 - (1.0 - quantile) / 2.0))
        bounds.append([round(low, 4), round(high, 4)])
    return bounds


def verdict_of(item, limits, legacy=False):
    """三档判定：PASS / WARN / FAIL

    为什么要分档（本轮实测结论）：`jaw` 的 15.2× 落在**原长 0.32mm 的微边**上
    （绝对增量 4.6mm），高倍渲染显示该处在外观上**与修复前像素级一致**
    （`_rig_work/hotspot-{old,new}-side34.png`）——因为这段几何被头发壳遮住。
    一条门槛同时卡"大头"和"碎屑"会把可交付的资产卡死，所以：
      · FAIL —— 有效边（>0.3mm）超限 / 全边超硬限 / 微边绝对增量超限 / 翻面面积 > `flip-fail-ppm`
      · WARN —— 有翻面但面积很小（口腔内部、头发内侧这类不可见面）
      · PASS —— 其余
    """
    if "skipped" in item:
        return "—"
    if legacy:
        return "✗ 不合格" if (item["flipped_triangles"] > 0
                              or item["max_stretch_big"] > limits["big"]) else "✓"
    if (item["max_stretch_big"] > limits["big"]
            or item["max_stretch"] > limits["all"]
            or item["micro_max_change_mm"] > limits["micro_mm"]
            or item["flipped_area_share"] * 1e6 > limits["flip_fail_ppm"]):
        return "✗ 不合格"
    if item["flipped_triangles"] > 0:
        return "△ 观察"
    return "✓"


def main():
    max_stretch_limit = float(arg_value("--max-stretch", "2.0"))
    hard_stretch_limit = float(arg_value("--hard-stretch", "6.0"))
    micro_mm_limit = float(arg_value("--micro-mm", "1.5"))
    flip_fail_ppm = float(arg_value("--flip-fail-ppm", "500"))
    micro_edge_mm = float(arg_value("--micro-edge-mm", "0.3"))
    legacy = has_flag("--legacy")
    if legacy:
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
        flipped_mask = (dots < 0) & significant
        flipped = int(flipped_mask.sum())
        displacement = np.linalg.norm(posed - rest, axis=1)
        # 只统计"有意义的边"：碎边（< 0.3mm）拉伸比再大，绝对增量也可能看不见，
        # 但**绝对增量**骗不了人 —— 两个指标都报。
        big_edge = rest_edge_length > significant_mm / 1000.0
        micro_edge = ~big_edge
        big_ratio = ratios[big_edge] if big_edge.any() else ratios
        absolute_change = np.abs(posed_edge_length - rest_edge_length)
        # 翻面到底在哪：面积加权 + 90% 分位包围盒（可见区域 vs 口腔/头发内侧）
        rest_tri_area = rest_area / 2.0
        total_area = float(rest_tri_area.sum())
        flipped_area = float(rest_tri_area[flipped_mask].sum())
        centroids = triangle_centroids(rest, triangles)
        # 微边的绝对增量要**相对本骨的最大位移**看：微边被整体搬运（Δ 都一样）
        # 不算穿帮，两端被拉扯出相对位移才算。用比值 = Δ边长 / 该骨最大顶点位移。
        move_max = float(displacement.max())
        micro_change = absolute_change[micro_edge] if micro_edge.any() else np.zeros(1)
        micro_ratio = float(micro_change.max() / move_max) if move_max > 1e-9 else 0.0
        worst = np.argsort(-absolute_change)[:worst_count] if worst_count else []
        results.append({
            "bone": name,
            "kind": spec["group"],
            "test": spec | {"angle": angle if spec["mode"] == "rotate" else None,
                            "push_mm": push_mm if spec["mode"] == "translate" else None},
            "max_stretch": round(float(ratios.max()), 4),
            "max_stretch_big": round(float(big_ratio.max()), 4),
            "max_stretch_micro": round(float(ratios[micro_edge].max()), 4)
            if micro_edge.any() else None,
            "p999_stretch": round(float(np.percentile(ratios, 99.9)), 4),
            "edges_over_1_3": int((ratios > 1.3).sum()),
            "edges_big_over_1_3": int((big_ratio > 1.3).sum()),
            "edges_big_over_limit": int((big_ratio > max_stretch_limit).sum()),
            "edges_all_over_hard": int((ratios > hard_stretch_limit).sum()),
            "micro_edges": int(micro_edge.sum()),
            "micro_max_change_mm": round(float(micro_change.max() * 1000), 4),
            "micro_ratio_of_move": round(micro_ratio, 4),
            "flipped_triangles": flipped,
            "flipped_area_share": round(flipped_area / total_area, 8) if total_area else 0.0,
            "flipped_bbox90": bbox_of(centroids[flipped_mask]),
            "moved_vertices": int((displacement > 1e-5).sum()),
            "max_displacement_mm": round(move_max * 1000, 3),
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

    limits = {"big": max_stretch_limit, "all": hard_stretch_limit,
              "micro_mm": micro_mm_limit, "flip_fail_ppm": flip_fail_ppm}
    if legacy:
        failures = [item for item in results if item.get("flipped_triangles", 0) > 0
                    or item.get("max_stretch_big", 0) > max_stretch_limit]
    else:
        failures = [item for item in results
                    if verdict_of(item, limits).startswith("✗")]
    report = {"file": bpy.data.filepath, "mesh": mesh_obj.name, "armature": armature.name,
              "vertices": int(len(rest)), "triangles": int(len(triangles)),
              "limit": {"max_stretch_big": max_stretch_limit,
                        "max_stretch_all": hard_stretch_limit,
                        "micro_change_mm": micro_mm_limit,
                        "flip_fail_ppm": flip_fail_ppm,
                        "significant_edge_mm": significant_mm,
                        "legacy_single_limit": legacy},
              "results": results,
              "failures": [item["bone"] for item in failures],
              "warnings": [item["bone"] for item in results
                           if verdict_of(item, limits).startswith("△")]}

    print("=" * 118)
    print("骨骼形变审计 : " + bpy.data.filepath)
    print(f"  网格 {mesh_obj.name}  {len(rest)} 顶点 / {len(triangles)} 三角面")
    if legacy:
        print(f"  判据（**旧口径**）：翻面 = 0，且有效边（原长 > {significant_mm}mm）"
              f"最大拉伸 ≤ {max_stretch_limit}")
    else:
        print(f"  判据（三档，见脚本头部说明）：不合格 = 有效边（>{significant_mm}mm）拉伸 > "
              f"{max_stretch_limit} / 全边拉伸 > {hard_stretch_limit} / "
              f"微边（<{significant_mm}mm）绝对增量 > {micro_mm_limit}mm / "
              f"翻面面积 > {flip_fail_ppm}ppm；"
              f"有翻面但面积 ≤ {flip_fail_ppm}ppm 记「△ 观察」")
    print(f"  测试姿态：机能骨旋转 ±{angle}°，骨相骨平移 ±{push_mm}mm")
    print("")
    print(f"  {'骨骼':<20}{'类':<11}{'有效边拉伸':>11}{'全边拉伸':>10}{'微边mm':>9}"
          f"{'有效边超限':>11}{'翻面':>7}{'翻面ppm':>10}{'动顶点':>9}   判定")
    for item in results:
        if "skipped" in item:
            print(f"  {item['bone']:<20}{'—':<11}{'跳过：' + item['skipped']}")
            continue
        verdict = verdict_of(item, limits, legacy)
        print(f"  {item['bone']:<20}{item['kind']:<11}{item['max_stretch_big']:>11}"
              f"{item['max_stretch']:>10}{item['micro_max_change_mm']:>9}"
              f"{item['edges_big_over_limit']:>11}{item['flipped_triangles']:>7}"
              f"{item['flipped_area_share'] * 1e6:>10.2f}{item['moved_vertices']:>9}   {verdict}")
    print("")
    print("  翻面位置（面积占比 ppm = 百万分之一；bbox90 = 覆盖 90% 翻面的包围盒）：")
    for item in results:
        if "skipped" in item or not item.get("flipped_triangles"):
            continue
        print(f"    {item['bone']:<20} 翻面 {item['flipped_triangles']:>5}  "
              f"面积占比 {item['flipped_area_share'] * 1e6:>7.2f} ppm  "
              f"bbox90 {item['flipped_bbox90']}")
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
        print(f"  ✓ 硬指标全部通过（{len([r for r in results if 'skipped' not in r])} 根骨）")
    if report.get("warnings") and not legacy:
        print(f"  △ 观察 {len(report['warnings'])} 根（有翻面但面积 ≤ "
              f"{flip_fail_ppm}ppm，需人工确认是否在不可见区域）："
              + ", ".join(report["warnings"]))
    if want_json:
        print("BONE_AUDIT_JSON " + json.dumps(report, ensure_ascii=False))


main()
