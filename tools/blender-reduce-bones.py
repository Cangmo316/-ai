#!/usr/bin/env python3
"""
比邻AI · 交付期减骨（33 骨 → 8 骨，第 6 步）

用法：
    blender --background <资产.blend> \
        --python tools/blender-env.py \
        --python tools/blender-reduce-bones.py -- --out <输出.blend> [--keep-set face|arms] [--report]

为什么要有这一步：交付规范与端侧判据都要求**运行期资产 ≤ 8 骨**
（`tools/blender-validate.py` 的 `MAX_BONES_DELIVERY = 8`，
`tools/test-avatar-v2-glb.mjs --role delivery` 同样卡 8；实测存量交付件正好 8 骨）。

做法（与上一代第 6 阶段同一套）：
  1. **先烘焙权重**：把每根辅助骨的顶点权重**按原比例并入它的父级**，
     并从自身删除——这样"每个顶点的权重和仍为 1"，只是权重换了宿主骨。
     ⚠️ 顺序必须是"先搬权重、后删骨"，直接删骨会让那些顶点的权重凭空消失（权重和 < 1）。
  2. 保留 `root / neck / head / jaw / tongue / eye.L / eye.R`（8 根），删掉其余 26 根。
  3. 把 `vis_*` / `expr_*` 形态键**保留**：它们存的是绝对坐标，与骨骼数量无关。
     （上一代把口型烘进顶点是因为它只剩 6 骨；v2 有完整的 `jaw`/`lip` 权重链，
       保留 morph 才能让端侧做 lip-sync。）
  4. 剔除权重极小的残留（< `--min-weight`），再把每顶点影响数截到 4 并归一化
     （交付规范 §4.5：≤4 骨、权重和 = 1）。
"""

import json
import os
import sys

import bpy
import numpy as np

# 交付期保留的骨骼（默认档：只有面部，用于"仅唇形同步"的旧场景）
KEEP = ("root", "neck", "head", "jaw", "tongue", "eye.L", "eye.R")

# ⚠️ 2026-10-05 新增：**"唇形同步 + 招手互动"档**必须保留左右手臂链**。
#    原来这份名单只有 7 根面部骨、没有手臂 —— 那样**招手动画会被整段烘没**
#    （骨骼被合并进父级后，动画曲线就找不到目标骨）。用 `--keep-set arms` 切到这一档。
KEEP_SETS = {
    "face": KEEP,
    "arms": (
        "root", "neck", "head", "jaw", "eye.L", "eye.R",
        "clavicle.L", "upperarm.L", "forearm.L", "hand.L",
        "clavicle.R", "upperarm.R", "forearm.R", "hand.R",
    ),
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


def mesh_object():
    return max((o for o in bpy.data.objects if o.type == "MESH"),
               key=lambda o: len(o.data.vertices), default=None)


def armature_object():
    return next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)


def remove_bones(armature, names):
    """删除骨骼必须走编辑模式的操作符（`armature.data.bones` 没有 remove()）

    ⚠️ 顺序：**先把权重搬到父级、再删骨**。直接删骨会让那些顶点的权重凭空消失
    （权重和 < 1），这是本轮写在文档里的硬要求。
    """
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    editable = armature.data.edit_bones
    for name in names:
        bone = editable.get(name)
        if bone is not None:
            editable.remove(bone)
    bpy.ops.object.mode_set(mode="OBJECT")
    armature.select_set(False)


def connect_chain(armature, links):
    """把"首尾相接"的骨设为 connected，让 glTF 的 joint 总数就是骨数本身

    背景：Blender 里 `bone.parent` 是一个**独立于关节层级**的关系，导出 glTF 时
    每个父子关系都可能额外产生一个内部 joint 节点（实测：8 根骨导出成 11 个 joints，
    因为 `eye.L`/`eye.R`/`tongue` 的首端不在父骨尾端、加了 extra joint）。
    把"骨 A 的尾部 = 骨 B 的首部"这种关系设成 connected，就不再需要额外节点。
    """
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    editable = armature.data.edit_bones
    for child, parent in links:
        c, p = editable.get(child), editable.get(parent)
        if c is None or p is None:
            continue
        if (c.head - p.tail).length < 1e-5:
            c.use_connect = True
    bpy.ops.object.mode_set(mode="OBJECT")
    armature.select_set(False)


def main():
    out = arg_value("--out")
    want_report = has_flag("--report")
    global KEEP
    keep_set = arg_value("--keep-set", "face")
    if keep_set in KEEP_SETS:
        KEEP = KEEP_SETS[keep_set]
    elif keep_set != "face":
        # 也允许直接传逗号分隔的骨名
        KEEP = tuple(name.strip() for name in keep_set.split(",") if name.strip())
    print(f"  保留档位：{keep_set}（{len(KEEP)} 骨）")
    min_weight = float(arg_value("--min-weight", "0.002"))
    max_influences = int(arg_value("--max-influences", "4"))

    mesh_obj = mesh_object()
    armature = armature_object()
    if mesh_obj is None or armature is None:
        print("REDUCE_FAIL 缺少网格或骨架")
        return

    count = len(mesh_obj.data.vertices)
    bones_before = [b.name for b in armature.data.bones]
    helpers = [b for b in armature.data.bones if b.name not in KEEP]
    print("=" * 96)
    print("交付期减骨 : " + bpy.data.filepath)
    print(f"  网格 {mesh_obj.name}  {count} 顶点")
    print(f"  骨架 {armature.name}  {len(bones_before)} 骨 → 保留 {len(KEEP)} 骨，"
          f"待合并 {len(helpers)} 根辅助骨")

    # ── 1) 读全部顶点权重到内存（顶点组索引 → 骨名）──
    index_of = {group.index: group.name for group in mesh_obj.vertex_groups}
    weight_map = [dict() for _ in range(count)]
    for vertex in mesh_obj.data.vertices:
        for element in vertex.groups:
            name = index_of.get(element.group)
            if name and element.weight > 0:
                weight_map[vertex.index][name] = element.weight

    def parent_of(name):
        bone = armature.data.bones.get(name)
        return bone.parent.name if (bone is not None and bone.parent is not None) else "root"

    # ── 2) 辅助骨权重并入父级（可级联：父级也可能被合并，故循环到收敛）──
    moved_rounds = 0
    for _ in range(8):
        pending = [b.name for b in armature.data.bones if b.name not in KEEP]
        if not pending:
            break
        moved_rounds += 1
        for name in pending:
            target = parent_of(name)
            while target not in KEEP:              # 父级也要被合并 → 一路往上传
                target = parent_of(target)
            for weights in weight_map:
                if name in weights:
                    weights[target] = weights.get(target, 0.0) + weights.pop(name)
        # 这一轮之后，把"待合并骨"从骨架里删掉（权重要先搬完）
        remove_bones(armature, pending)

    # 骨架里若还有"保留骨"却不在 KEEP 里的（例如 root 之外多出来的），也清掉
    leftovers = [b.name for b in armature.data.bones if b.name not in KEEP]
    if leftovers:
        remove_bones(armature, leftovers)

    # 首尾相接的骨设为 connected，避免导出时多出内部 joint 节点
    connect_chain(armature, [("neck", "root"), ("head", "neck"), ("jaw", "head")])

    print(f"  权重烘焙：{moved_rounds} 轮完成（辅助骨权重按原比例并入父级）")

    # ── 3) 清理 + 截断到 ≤4 骨 + 归一化 ──
    stats = {"dropped_vertices": 0, "clipped": 0, "renormalized": 0}
    for index, weights in enumerate(weight_map):
        cleaned = {k: v for k, v in weights.items() if k in KEEP and v > min_weight}
        if not cleaned:
            cleaned = {"head": 1.0}
        if len(cleaned) > max_influences:
            top = sorted(cleaned.items(), key=lambda kv: -kv[1])[:max_influences]
            cleaned = dict(top)
            stats["clipped"] += 1
        total = sum(cleaned.values())
        if abs(total - 1.0) > 1e-6:
            cleaned = {k: v / total for k, v in cleaned.items()}
            stats["renormalized"] += 1
        weight_map[index] = cleaned

    # ── 4) 写回顶点组（先清空旧的，再按骨名建新的）──
    for group in list(mesh_obj.vertex_groups):
        mesh_obj.vertex_groups.remove(group)
    groups = {name: mesh_obj.vertex_groups.new(name=name) for name in KEEP}
    buckets = {name: {} for name in KEEP}
    for index, weights in enumerate(weight_map):
        for name, value in weights.items():
            level = round(value, 4)
            buckets[name].setdefault(level, []).append(index)
    for name, levels in buckets.items():
        for level, indices in levels.items():
            if level > 0:
                groups[name].add(indices, float(level), "REPLACE")

    # ── 5) 收尾校验 ──
    sums = np.zeros(count)
    influences = np.zeros(count, dtype=np.int32)
    for weights in weight_map:
        for value in weights.values():
            pass
    for index, weights in enumerate(weight_map):
        sums[index] = sum(weights.values())
        influences[index] = len(weights)
    bones_after = [b.name for b in armature.data.bones]
    shape_keys = (len(mesh_obj.data.shape_keys.key_blocks) - 1) if mesh_obj.data.shape_keys else 0
    report = {
        "file": bpy.data.filepath,
        "bones_before": len(bones_before), "bones_after": len(bones_after),
        "bone_names": bones_after,
        "helpers_merged": len(helpers),
        "vertices": count, "shape_keys": shape_keys,
        "weight_sum": {"min": round(float(sums.min()), 6), "max": round(float(sums.max()), 6),
                       "bad": int((np.abs(sums - 1.0) > 1e-3).sum())},
        "influences": {"max": int(influences.max()), "mean": round(float(influences.mean()), 2),
                       "over_limit": int((influences > max_influences).sum())},
        "cleanup": stats,
    }
    print(f"  减骨后：{len(bones_after)} 骨（{', '.join(bones_after)}）")
    print(f"  权重和：min {report['weight_sum']['min']} / max {report['weight_sum']['max']}"
          f"  异常顶点 {report['weight_sum']['bad']}")
    print(f"  影响数：max {report['influences']['max']} / 平均 {report['influences']['mean']}"
          f"  超限 {report['influences']['over_limit']}")
    print(f"  形态键保留 {shape_keys} 个")

    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("REDUCE_OK 已保存 " + out)
    if want_report:
        print("REDUCE_JSON " + json.dumps(report, ensure_ascii=False))


main()
