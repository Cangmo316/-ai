#!/usr/bin/env python3
"""
比邻AI · 顶点组来源探针（判断"硬边是场写出来的、还是头发遮罩/解算造成的"）

用法：
    blender --background <工作.blend> \
        --python tools/blender-env.py \
        --python tools/blender-weight-source.py -- --at x,y,z [--radius 0.012] [--bone jaw]

输出：指定球邻域内每个顶点一行：坐标 / 是否头发 / 每根骨的原始场值 / 实际权重。
按"到球心距离"排序，方便直接看出**梯度出现在哪一拍**、以及头发标记是否与它吻合。
"""

import importlib.util
import os
import sys

import bpy
import numpy as np

TOOLS = os.path.dirname(os.path.abspath(__file__))


def arg_value(name, default=None):
    args = sys.argv
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return default


def load_module(path):
    with open(path, "r", encoding="utf-8") as handle:
        source = handle.read()
    source = source.replace("\nmain()\n", "\n")
    namespace = {"__name__": "bilin_weights", "__file__": path}
    exec(compile(source, path, "exec"), namespace)
    return namespace


def head_mesh():
    return max((o for o in bpy.data.objects if o.type == "MESH"),
               key=lambda o: len(o.data.vertices), default=None)


def main():
    at = arg_value("--at")
    radius = float(arg_value("--radius", "0.012"))
    bone = arg_value("--bone", "jaw")
    if not at:
        print("SOURCE_FAIL 需要 --at x,y,z")
        return
    center = np.array([float(part) for part in at.split(",")], dtype=np.float64)

    namespace = load_module(os.path.join(TOOLS, "blender-rig-weights.py"))
    mesh_obj = head_mesh()
    count = len(mesh_obj.data.vertices)
    buffer = np.empty(count * 3, dtype=np.float64)
    mesh_obj.data.vertices.foreach_get("co", buffer)
    coords = buffer.reshape(count, 3)

    vertex_hair, hair_note = namespace["hair_mask"](mesh_obj)
    if vertex_hair is None:
        vertex_hair = np.zeros(count, dtype=bool)
    fields = namespace["analytic_fields"](coords, vertex_hair)

    index_of = {group.index: group.name for group in mesh_obj.vertex_groups}
    bone_index = mesh_obj.vertex_groups[bone].index if mesh_obj.vertex_groups.get(bone) else None

    distance = np.linalg.norm(coords - center, axis=1)
    inside = np.nonzero(distance <= radius)[0]
    inside = inside[np.argsort(distance[inside])]

    print("=" * 110)
    print(f"顶点组来源探针 : {bpy.data.filepath}   骨 {bone}   半径 {radius * 1000:.1f}mm")
    print(f"  {hair_note}")
    print("")
    print(f"  {'dist_mm':>8}{'x':>9}{'y':>9}{'z':>9}{'头发':>6}"
          f"{'场值':>9}{'实际':>9}   实际影响骨")
    for vertex in inside[:80]:
        weight = 0.0
        tops = []
        for element in mesh_obj.data.vertices[int(vertex)].groups:
            name = index_of.get(element.group, "?")
            tops.append((name, element.weight))
            if element.group == bone_index:
                weight = element.weight
        tops.sort(key=lambda item: -item[1])
        top_text = " ".join(f"{name}={value:.3f}" for name, value in tops[:4] if value > 1e-4)
        print(f"  {distance[vertex] * 1000:>8.2f}{coords[vertex, 0]:>9.4f}"
              f"{coords[vertex, 1]:>9.4f}{coords[vertex, 2]:>9.4f}"
              f"{'是' if vertex_hair[vertex] else '否':>6}"
              f"{fields[bone][vertex]:>9.4f}{weight:>9.4f}   {top_text}")

    # 统计：球内"头发/非头发"各自的实际权重均值
    hair_inside = inside[vertex_hair[inside]]
    skin_inside = inside[~vertex_hair[inside]]
    actual = np.zeros(count, dtype=np.float64)
    if bone_index is not None:
        for vertex in mesh_obj.data.vertices:
            for element in vertex.groups:
                if element.group == bone_index:
                    actual[vertex.index] = element.weight
                    break
    print("")
    print(f"  球内头发顶点 {len(hair_inside)}（{bone} 实际均值 "
          f"{actual[hair_inside].mean() if len(hair_inside) else 0:.4f}）/ "
          f"非头发 {len(skin_inside)}（{actual[skin_inside].mean() if len(skin_inside) else 0:.4f}）")
    print(f"  {bone} 场值：头发均值 {fields[bone][hair_inside].mean() if len(hair_inside) else 0:.4f} / "
          f"非头发均值 {fields[bone][skin_inside].mean() if len(skin_inside) else 0:.4f}")
    print("SOURCE_OK")


main()
