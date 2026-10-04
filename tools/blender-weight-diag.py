#!/usr/bin/env python3
"""
比邻AI · 权重热点诊断（把"某根骨拉伸 24×"落到**具体顶点、具体权重、具体区域**）

用法：
    blender --background <工作.blend> \
        --python tools/blender-env.py \
        --python tools/blender-weight-diag.py -- --bone jaw [--angle 20] [--top 25]
            [--metric abs|ratio] [--json]

为什么需要它：`blender-bone-audit.py` 只给"最大拉伸 ×"这一个数字，
而修权重必须知道 **这些边在哪、两端权重差多少、周围一圈是不是也有同样的落差**。
本脚本按骨名摆出审计同款姿态，然后：

  1. 列出"绝对增量最大"与"拉伸比最大"的两组最差边（各自的顶点权重明细）
  2. 把最差边按**空间网格（5mm 体素）聚类**，给出"病灶区"清单：
     每簇的顶点数、坐标范围、骨权重区间、该簇里有多少条边超限
  3. 打印病灶区**邻域一圈**（1~2 环边）的骨权重分布 —— 直接看出是"硬边"还是"物理必需"
  4. 对比该骨在**全网格**的权重分位数，判断是"场本身写错了"还是"个别顶点被平滑拉爆"

输出中每个病灶区都带 `Δw`（该骨在边两端的权重差）：
  · Δw 大而边短 → 硬边（修权重）
  · Δw 大而边长且跨唇缝等真实解剖分界 → 物理必需（只能分级安全角度）
"""

import json
import math
import sys

import bpy
import numpy as np
from mathutils import Vector

AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}

# 与 blender-bone-audit.py 保持逐字一致的测试姿态（否则数据对不上）
TESTS = {
    "neck": ("rotate", "X", -18), "head": ("rotate", "Z", 20),
    "jaw": ("rotate", "X", 20), "chin": ("rotate", "X", -12),
    "nose": ("rotate", "X", 10), "lip_upper": ("rotate", "X", 18),
    "lip_lower": ("rotate", "X", -18), "tongue": ("rotate", "X", 15),
    "eye.L": ("rotate", "Z", 15), "eye.R": ("rotate", "Z", -15),
    "eyelid_upper.L": ("rotate", "X", 18), "eyelid_upper.R": ("rotate", "X", 18),
    "eyelid_lower.L": ("rotate", "X", -14), "eyelid_lower.R": ("rotate", "X", -14),
    "brow.L": ("rotate", "X", -14), "brow.R": ("rotate", "X", -14),
    "ear.L": ("rotate", "Y", 12), "ear.R": ("rotate", "Y", -12),
    "face_width": ("translate", "X", 4), "face_length": ("translate", "Z", 4),
    "forehead_height": ("translate", "Z", 4), "forehead_width": ("translate", "X", 4),
    "cheekbone.L": ("translate", "X", 4), "cheekbone.R": ("translate", "X", -4),
    "temple.L": ("translate", "X", 4), "temple.R": ("translate", "X", -4),
    "jaw_width.L": ("translate", "X", 4), "jaw_width.R": ("translate", "X", -4),
    "cheek_fat.L": ("translate", "Y", -3), "cheek_fat.R": ("translate", "Y", -3),
    "eye_socket.L": ("translate", "Y", 3), "eye_socket.R": ("translate", "Y", 3),
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


def read_positions(mesh_obj):
    count = len(mesh_obj.data.vertices)
    buffer = np.empty(count * 3, dtype=np.float64)
    mesh_obj.data.vertices.foreach_get("co", buffer)
    return buffer.reshape(count, 3)


def evaluate_positions(mesh_obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = mesh_obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    count = len(mesh.vertices)
    buffer = np.empty(count * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", buffer)
    positions = buffer.reshape(count, 3).copy()
    evaluated.to_mesh_clear()
    return positions


def clear_pose(armature):
    for bone in armature.pose.bones:
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0.0, 0.0, 0.0)
        bone.location = (0.0, 0.0, 0.0)
        bone.scale = (1.0, 1.0, 1.0)


def apply_test(armature, name, mode, axis, value, angle, push_mm):
    bone = armature.pose.bones.get(name)
    if bone is None:
        return False
    bone.rotation_mode = "XYZ"
    if mode == "rotate":
        euler = [0.0, 0.0, 0.0]
        euler[AXIS_INDEX[axis]] = math.radians(angle if value > 0 else -angle)
        bone.rotation_euler = euler
    else:
        vector = Vector((0.0, 0.0, 0.0))
        vector[AXIS_INDEX[axis]] = push_mm / 1000.0 * (1 if value > 0 else -1)
        bone.location = vector
    return True


def build_adjacency(mesh_obj):
    edges = np.empty(len(mesh_obj.data.edges) * 2, dtype=np.int32)
    mesh_obj.data.edges.foreach_get("vertices", edges)
    edges = edges.reshape(-1, 2)
    count = len(mesh_obj.data.vertices)
    sources = np.concatenate([edges[:, 0], edges[:, 1]])
    targets = np.concatenate([edges[:, 1], edges[:, 0]])
    order = np.argsort(sources, kind="stable")
    sources, targets = sources[order], targets[order]
    offsets = np.zeros(count + 1, dtype=np.int64)
    np.add.at(offsets, sources + 1, 1)
    offsets = np.cumsum(offsets)
    return targets, offsets


def bone_weights(mesh_obj, bone_name):
    """整表读取某个顶点组的权重

    ⚠️ 为什么不是一行 `foreach_get`：Blender 没有任何"整表读 deform 权重"的接口
    （`MeshVertex.groups` 是 `bpy_prop_collection`，不支持 `foreach_get`）。
    本资产是单网格 49.9 万顶点，逐顶点 Python 循环要 1~2 分钟——所以走
    **导出 → numpy 读 → 删文件**（几秒），仅在临时目录不可写时退回逐顶点循环。
    """
    group = mesh_obj.vertex_groups.get(bone_name)
    count = len(mesh_obj.data.vertices)
    weights = np.zeros(count, dtype=np.float64)
    if group is None:
        return weights
    import os
    import tempfile

    directory = tempfile.gettempdir()
    path = os.path.join(directory, f"bilin-weights-{group.index}.csv")
    try:
        result = bpy.ops.object.vertex_group_export(
            filepath=path, group_select_mode="ACTIVE", use_all_verts=True,
            apply_modifiers=False, export_normals=False, export_all_influences=False)
        if "FINISHED" not in result:
            raise RuntimeError(f"导出返回 {result}")
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            rows = [line.split(",") for line in handle if line.strip()]
        for row in rows[1:]:
            if len(row) < 2:
                continue
            try:
                weights[int(float(row[0]))] = float(row[1])
            except (ValueError, IndexError):
                continue
        return weights
    except Exception as error:  # noqa: BLE001 —— 任何失败都退回慢路径
        print(f"⚠️ 顶点组批量导出失败（{error}），改用逐顶点读取（较慢）")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

    index = group.index
    for vertex in mesh_obj.data.vertices:
        for element in vertex.groups:
            if element.group == index:
                weights[vertex.index] = element.weight
                break
    return weights


def top_bones(mesh_obj, index, limit=4):
    groups = {group.index: group.name for group in mesh_obj.vertex_groups}
    elements = sorted(mesh_obj.data.vertices[index].groups, key=lambda e: -e.weight)[:limit]
    return [(groups[e.group], round(float(e.weight), 4)) for e in elements if e.weight > 1e-4]


def cluster_edges(mids, voxel=0.005):
    """按体素把边聚簇（同一病灶区应落在相邻体素里）"""
    keys = np.floor(mids / voxel).astype(np.int64)
    unique, inverse = np.unique(keys, axis=0, return_inverse=True)
    clusters = []
    for cluster_id in range(len(unique)):
        members = np.nonzero(inverse == cluster_id)[0]
        clusters.append(members)
    return clusters, unique


def main():
    bone = arg_value("--bone", "jaw")
    angle = float(arg_value("--angle", "20"))
    push_mm = float(arg_value("--push-mm", "4"))
    top = int(arg_value("--top", "20"))
    metric = arg_value("--metric", "abs")
    want_json = has_flag("--json")
    neighborhood_rings = int(arg_value("--rings", "2"))
    significant_mm = float(arg_value("--significant-mm", "0.3"))

    mesh_obj = head_mesh()
    armature = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if mesh_obj is None or armature is None:
        print("WEIGHT_DIAG_FAIL 缺少网格或骨架")
        return
    if armature.pose.bones.get(bone) is None or mesh_obj.vertex_groups.get(bone) is None:
        print(f"WEIGHT_DIAG_FAIL 没有骨骼或顶点组：{bone}")
        return

    mode, axis, value = TESTS.get(bone, ("rotate", "X", 20))
    rest = read_positions(mesh_obj)
    edges = np.empty(len(mesh_obj.data.edges) * 2, dtype=np.int32)
    mesh_obj.data.edges.foreach_get("vertices", edges)
    edges = edges.reshape(-1, 2)
    rest_length = np.linalg.norm(rest[edges[:, 0]] - rest[edges[:, 1]], axis=1)

    weights = bone_weights(mesh_obj, bone)
    delta_w = np.abs(weights[edges[:, 0]] - weights[edges[:, 1]])

    clear_pose(armature)
    apply_test(armature, bone, mode, axis, value, angle, push_mm)
    bpy.context.view_layer.update()
    posed = evaluate_positions(mesh_obj)
    posed_length = np.linalg.norm(posed[edges[:, 0]] - posed[edges[:, 1]], axis=1)
    absolute = np.abs(posed_length - rest_length)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(rest_length > 1e-9, posed_length / np.maximum(rest_length, 1e-12), 1.0)
    displacement = np.linalg.norm(posed - rest, axis=1)
    big = rest_length > significant_mm / 1000.0

    report = {
        "file": bpy.data.filepath, "bone": bone, "vertices": int(len(rest)),
        "edges": int(len(edges)),
        "test": {"mode": mode, "axis": axis, "value": value, "angle": angle,
                 "push_mm": push_mm},
        "weight": {
            "verts_gt0": int((weights > 1e-5).sum()),
            "verts_gt_0_5": int((weights > 0.5).sum()),
            "max": round(float(weights.max()), 4),
            "p50": round(float(np.percentile(weights, 50)), 4),
            "p99": round(float(np.percentile(weights, 99)), 4),
            "moved_vertices": int((displacement > 1e-5).sum()),
            "max_displacement_mm": round(float(displacement.max()) * 1000, 3),
        },
        "stretch": {
            "max_all": round(float(ratio.max()), 4),
            "max_big": round(float(ratio[big].max()), 4) if big.any() else None,
            "over_1_3_all": int((ratio > 1.3).sum()),
            "over_1_3_big": int((ratio[big] > 1.3).sum()),
            "over_2_big": int((ratio[big] > 2.0).sum()),
            "p999_big": round(float(np.percentile(ratio[big], 99.9)), 4) if big.any() else None,
        },
    }

    def edge_record(index):
        v0, v1 = int(edges[index, 0]), int(edges[index, 1])
        return {
            "edge": int(index),
            "ratio": round(float(ratio[index]), 3),
            "rest_mm": round(float(rest_length[index]) * 1000, 4),
            "now_mm": round(float(posed_length[index]) * 1000, 4),
            "change_mm": round(float(absolute[index]) * 1000, 4),
            "delta_w": round(float(delta_w[index]), 4),
            "mid": [round(float(v), 4) for v in (rest[v0] + rest[v1]) / 2],
            "v0": {"i": v0, "co": [round(float(v), 4) for v in rest[v0]],
                   "w": round(float(weights[v0]), 4), "top": top_bones(mesh_obj, v0)},
            "v1": {"i": v1, "co": [round(float(v), 4) for v in rest[v1]],
                   "w": round(float(weights[v1]), 4), "top": top_bones(mesh_obj, v1)},
        }

    worst_abs = np.argsort(-absolute)[:top]
    worst_ratio = np.argsort(-ratio)[:top]
    over = np.nonzero((ratio > 1.3) & big)[0]
    report["worst_absolute"] = [edge_record(int(i)) for i in worst_abs]
    report["worst_ratio"] = [edge_record(int(i)) for i in worst_ratio]
    report["over_1_3_big_edges"] = int(len(over))

    # 位移最大的顶点落在哪：判断"拉伸大"是权重硬边造成的，还是枢轴/杠杆臂的必然
    moved = np.nonzero(displacement > 1e-5)[0]
    top_moved = np.argsort(-displacement)[:8]
    report["displacement"] = {
        "max_mm": round(float(displacement.max()) * 1000, 3),
        "moved_vertices": int(len(moved)),
        "bbox_moved": [[round(float(rest[moved, axis].min()), 4),
                        round(float(rest[moved, axis].max()), 4)] for axis in range(3)],
        "top": [{"i": int(v), "co": [round(float(c), 4) for c in rest[v]],
                 "mm": round(float(displacement[v]) * 1000, 3),
                 "w": round(float(weights[v]), 4)} for v in top_moved],
        # 边长 < 1mm 的微边统计：拉伸比在这种情况下会被放大，必须和绝对增量一起看
        "ratio_source": {
            "edges_below_1mm": int((rest_length < 0.001).sum()),
            "worst_ratio_rest_mm": round(float(rest_length[np.argmax(ratio)]) * 1000, 4),
            "worst_ratio_change_mm": round(float(absolute[np.argmax(ratio)]) * 1000, 4),
        },
    }

    # 病灶聚类：用"拉伸比 > 2 且边长 > 0.3mm"的边
    hot = np.nonzero((ratio > 2.0) & big)[0]
    clusters, keys = cluster_edges(((rest[edges[hot, 0]] + rest[edges[hot, 1]]) / 2)) \
        if len(hot) else ([], None)
    cluster_reports = []
    if len(hot):
        members_sorted = sorted(clusters, key=lambda m: -len(m))
        for members in members_sorted[:12]:
            edge_ids = hot[members]
            verts = np.unique(edges[edge_ids].ravel())
            cluster_reports.append({
                "edges": int(len(edge_ids)),
                "vertices": int(len(verts)),
                "ratio_max": round(float(ratio[edge_ids].max()), 3),
                "ratio_mean": round(float(ratio[edge_ids].mean()), 3),
                "rest_len_mm": [round(float(rest_length[edge_ids].min()) * 1000, 4),
                                round(float(rest_length[edge_ids].max()) * 1000, 4)],
                "delta_w_mean": round(float(delta_w[edge_ids].mean()), 4),
                "delta_w_max": round(float(delta_w[edge_ids].max()), 4),
                "w_range": [round(float(weights[verts].min()), 4),
                            round(float(weights[verts].max()), 4)],
                "bbox": [[round(float(rest[verts, axis].min()), 4),
                          round(float(rest[verts, axis].max()), 4)] for axis in range(3)],
                "sample_edge": edge_record(int(edge_ids[np.argmax(ratio[edge_ids])])),
            })
    report["hot_clusters"] = cluster_reports

    # 邻域环：取最差边端点，向外扩 N 环，列出该骨的权重分布（判断是"孤立坏点"还是"整条硬边"）
    if len(worst_abs):
        targets, offsets = build_adjacency(mesh_obj)
        seeds = list(np.unique(edges[worst_abs].ravel()))
        visited = set(seeds)
        frontier = list(seeds)
        for _ in range(max(0, neighborhood_rings)):
            nxt = []
            for vertex in frontier:
                for pointer in range(offsets[vertex], offsets[vertex + 1]):
                    neighbor = int(targets[pointer])
                    if neighbor not in visited:
                        visited.add(neighbor)
                        nxt.append(neighbor)
            frontier = nxt
        ring = np.array(sorted(visited), dtype=np.int64)
        ring_weights = weights[ring]
        report["neighborhood"] = {
            "rings": neighborhood_rings, "vertices": int(len(ring)),
            "w_min": round(float(ring_weights.min()), 4),
            "w_max": round(float(ring_weights.max()), 4),
            "w_mean": round(float(ring_weights.mean()), 4),
            "bbox": [[round(float(rest[ring, axis].min()), 4),
                      round(float(rest[ring, axis].max()), 4)] for axis in range(3)],
            "top_bone_mix": {},
        }
        mix = {}
        for vertex in ring:
            for name, weight in top_bones(mesh_obj, int(vertex), limit=3):
                mix[name] = round(mix.get(name, 0.0) + weight, 3)
        report["neighborhood"]["top_bone_mix"] = dict(
            sorted(mix.items(), key=lambda kv: -kv[1])[:10])

    print("=" * 100)
    print(f"权重热点诊断 : {bpy.data.filepath}")
    print(f"  骨 {bone}  测试姿态 {mode} {axis} "
          f"{angle if mode == 'rotate' else push_mm}{'°' if mode == 'rotate' else 'mm'}")
    weight = report["weight"]
    print(f"  权重：顶点 >0 {weight['verts_gt0']} / >0.5 {weight['verts_gt_0_5']} / "
          f"max {weight['max']} / p50 {weight['p50']} / p99 {weight['p99']}")
    print(f"  位移：动顶点 {weight['moved_vertices']} / 最大 {weight['max_displacement_mm']}mm")
    stretch = report["stretch"]
    print(f"  拉伸：全边 max {stretch['max_all']} / 有效边 max {stretch['max_big']} / "
          f"有效边 p99.9 {stretch['p999_big']} / 有效边 >1.3 {stretch['over_1_3_big']} 条 / "
          f">2.0 {stretch['over_2_big']} 条")
    print("")
    print(f"  ▸ 绝对增量最大的 {top} 条边（{metric} 视角）：")
    for record in report["worst_absolute"]:
        print(f"      增量 {record['change_mm']}mm  拉伸 {record['ratio']}×  "
              f"原长 {record['rest_mm']}mm  Δw({bone}) {record['delta_w']}  中点 {record['mid']}")
        print(f"         v0 w={record['v0']['w']} {record['v0']['top']}")
        print(f"         v1 w={record['v1']['w']} {record['v1']['top']}")
    print("")
    print(f"  ▸ 病灶区（拉伸 > 2.0 且原长 > {significant_mm}mm，按 5mm 体素聚类，取前 12）：")
    if not cluster_reports:
        print("      无")
    for order, cluster in enumerate(cluster_reports, 1):
        print(f"      [{order}] {cluster['edges']} 条边 / {cluster['vertices']} 顶点  "
              f"拉伸 max {cluster['ratio_max']} mean {cluster['ratio_mean']}  "
              f"原长 {cluster['rest_len_mm'][0]}~{cluster['rest_len_mm'][1]}mm")
        print(f"          Δw {bone} mean {cluster['delta_w_mean']} / max {cluster['delta_w_max']}  "
              f"该骨权重区间 {cluster['w_range']}")
        print(f"          包围盒 x{cluster['bbox'][0]} y{cluster['bbox'][1]} z{cluster['bbox'][2]}")
        sample = cluster["sample_edge"]
        print(f"          最差边：{sample['ratio']}×  原长 {sample['rest_mm']}mm  "
              f"Δw {sample['delta_w']}  中点 {sample['mid']}")
        print(f"            v0 w={sample['v0']['w']} {sample['v0']['top']}")
        print(f"            v1 w={sample['v1']['w']} {sample['v1']['top']}")
    print("")
    print(f"  ▸ 位移最大的 8 个顶点（判断拉伸是否只是「杠杆臂」必然）：")
    for item in report["displacement"]["top"]:
        print(f"      位移 {item['mm']}mm  {bone} 权重 {item['w']}  坐标 {item['co']}")
    source = report["displacement"]["ratio_source"]
    print(f"      最大拉伸边：原长 {source['worst_ratio_rest_mm']}mm → "
          f"绝对增量 {source['worst_ratio_change_mm']}mm"
          f"（全网格 <1mm 的微边 {source['edges_below_1mm']} 条）")
    print(f"      动顶点包围盒 x{report['displacement']['bbox_moved'][0]} "
          f"y{report['displacement']['bbox_moved'][1]} "
          f"z{report['displacement']['bbox_moved'][2]}")
    print("")
    if "neighborhood" in report:
        ring = report["neighborhood"]
        print(f"  ▸ 最差边端点外扩 {ring['rings']} 环邻域（{ring['vertices']} 顶点）："
              f"{bone} 权重 min {ring['w_min']} / mean {ring['w_mean']} / max {ring['w_max']}")
        print(f"      包围盒 x{ring['bbox'][0]} y{ring['bbox'][1]} z{ring['bbox'][2]}")
        print(f"      邻域影响骨 Top10：{ring['top_bone_mix']}")
    if want_json:
        print("WEIGHT_DIAG_JSON " + json.dumps(report, ensure_ascii=False))


main()
