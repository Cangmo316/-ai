#!/usr/bin/env python3
"""
比邻AI · 字典分数探针（在**不跑全流程**的前提下，直接读解析场）

用法：
    blender --background <工作.blend> \
        --python tools/blender-env.py \
        --python tools/blender-weight-probe.py -- --at x,y,z [--radius 0.008] [--top 12]

为什么需要它：审计报出"`jaw` 20.6×"时，必须先把两种可能分开——
  · **字典本身**在那一小片上有硬边（场的公式/门限写错）
  · **解算**（归一化 + 只留 Top-4 + 3 轮平滑）把本来平滑的场拉出了硬边
本脚本导入 `tools/blender-rig-weights.py` 里的同一套解析场函数，直接在指定坐标
邻域里打印每根骨的**原始场值**，并与当前 .blend 里的**实际权重**并排对比。
这样"该修场还是该修解算"一眼可判。
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


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # 不执行 main()：这些工具脚本末尾是裸调用，因此先读源码、砍掉最后一行
    with open(path, "r", encoding="utf-8") as handle:
        source = handle.read()
    source = source.replace("\nmain()\n", "\n")
    exec(compile(source, path, "exec"), module.__dict__)
    return module


def head_mesh():
    return max((o for o in bpy.data.objects if o.type == "MESH"),
               key=lambda o: len(o.data.vertices), default=None)


def vertex_weights_all(mesh_obj, names):
    """当前 .blend 里的实际权重（逐顶点循环；本脚本只在邻域内用，慢无所谓）"""
    index_of = {group.index: group.name for group in mesh_obj.vertex_groups}
    wanted = {name: i for i, name in enumerate(names)}
    matrix = np.zeros((len(mesh_obj.data.vertices), len(names)), dtype=np.float64)
    for vertex in mesh_obj.data.vertices:
        for element in vertex.groups:
            name = index_of.get(element.group)
            if name in wanted:
                matrix[vertex.index, wanted[name]] = element.weight
    return matrix


def main():
    at = arg_value("--at")
    radius = float(arg_value("--radius", "0.008"))
    top = int(arg_value("--top", "12"))
    if not at:
        print("PROBE_FAIL 需要 --at x,y,z")
        return
    center = np.array([float(part) for part in at.split(",")], dtype=np.float64)

    weights_mod = load_module(os.path.join(TOOLS, "blender-rig-weights.py"), "bilin_weights")
    mesh_obj = head_mesh()
    count = len(mesh_obj.data.vertices)
    buffer = np.empty(count * 3, dtype=np.float64)
    mesh_obj.data.vertices.foreach_get("co", buffer)
    coords = buffer.reshape(count, 3)

    distance = np.linalg.norm(coords - center, axis=1)
    inside = distance <= radius
    print("=" * 100)
    print(f"解析场探针 : {bpy.data.filepath}")
    print(f"  球心 {list(np.round(center, 4))}  半径 {radius * 1000:.1f}mm  "
          f"命中顶点 {int(inside.sum())}")
    if not inside.any():
        print("PROBE_FAIL 邻域内没有顶点")
        return

    vertex_hair, hair_note = weights_mod.hair_mask(mesh_obj)
    print(f"  头发遮罩：{hair_note}")
    if vertex_hair is None:
        vertex_hair = np.zeros(count, dtype=bool)
    hair_inside = int(vertex_hair[inside].sum())
    print(f"  邻域内头发顶点：{hair_inside} / {int(inside.sum())}")
    fields = weights_mod.analytic_fields(coords, vertex_hair)

    bones = [bone.name for bone in
             next(o for o in bpy.data.objects if o.type == "ARMATURE").data.bones]
    actual = vertex_weights_all(mesh_obj, bones)

    rows = []
    for name, field in fields.items():
        values = field[inside]
        rows.append((name, float(values.max()), float(values.mean()),
                     int((values > 0.02).sum())))
    rows.sort(key=lambda row: -row[1])

    print("")
    print(f"  ▸ 解析场原始值（邻域内，取前 {top}）：")
    print(f"      {'骨':<20}{'max':>9}{'mean':>9}{'>0.02 顶点':>12}")
    for name, maximum, mean, strong in rows[:top]:
        print(f"      {name:<20}{maximum:>9.4f}{mean:>9.4f}{strong:>12}")

    print("")
    print("  ▸ 当前 .blend 实际权重（同一邻域，取前 %d）：" % top)
    actual_rows = []
    for index, name in enumerate(bones):
        values = actual[inside, index]
        actual_rows.append((name, float(values.max()), float(values.mean()),
                            int((values > 0.02).sum())))
    actual_rows.sort(key=lambda row: -row[1])
    print(f"      {'骨':<20}{'max':>9}{'mean':>9}{'>0.02 顶点':>12}")
    for name, maximum, mean, strong in actual_rows[:top]:
        print(f"      {name:<20}{maximum:>9.4f}{mean:>9.4f}{strong:>12}")

    # 并排对比指定骨（默认列全部"有场值或有权重"的骨）
    watch = (arg_value("--bones") or "").split(",") if arg_value("--bones") else None
    if watch:
        print("")
        print("  ▸ 指定骨对照（场 max / 权重 max）：")
        for name in watch:
            field = fields.get(name)
            actual_index = bones.index(name) if name in bones else None
            field_max = float(field[inside].max()) if field is not None else None
            weight_max = float(actual[inside, actual_index].max()) if actual_index is not None else None
            print(f"      {name:<20} 场 {field_max}   权重 {weight_max}")
    print("PROBE_OK")


main()
