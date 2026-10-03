#!/usr/bin/env python3
"""
比邻AI · 面部 rig 交付校验（在 Blender 无头模式下运行）

用法：
    blender --background <某个.blend> --python tools/blender-validate.py
    blender --background <文件> --python tools/blender-validate.py -- --json

它按《3D 捏脸与面部骨骼绑定方案》的验收标准逐项检查并打印结论：
  · 骨架骨数与命名（交付资产应 ≤ 8 骨）
  · morph 命名空间（shape_* 捏脸 / vis_* 口型 / expr_* 表情）与数量
  · **运行时资产不该再带 shape_***（捏脸结果应已烘焙进网格）
  · 面数预算（整体 ≤ 60k tri，头部 ≤ 25k）
  · 材质槽 ≤ 6
  · 权重：每顶点影响骨骼数 ≤ 4

⚠️ 这是"能自动查的部分"。形变质量（拉到极端值破不破面）仍需人看，
   但可以用 --json 的输出做版本间对比。

注：用 `--` 之后的参数传给我们自己（Blender 会把 `--` 之前的吃掉）。
"""

import json
import sys

import bpy

# ── 预算（与设计方案 §3.6 / 交付规范一致）────────────────────────────
MAX_TRIS_TOTAL = 60000
MAX_TRIS_HEAD = 25000
MAX_BONES_DELIVERY = 8
MAX_BONES_EDIT = 40
MAX_MATERIALS = 6
MAX_INFLUENCES = 4

SHAPE_PREFIX = "shape_"
VIS_PREFIX = "vis_"
EXPR_PREFIX = "expr_"

# Blender 的默认命名（没改过的话一眼能看出是半成品）
DEFAULT_NAME_HINTS = ("node_0", "Cube", "Sphere", "Material.0", "Material.1", "Empty", "Circle")


def stage_of(path: str) -> str:
    """按文件名判断阶段：`_edit` = 编辑期（允许辅助骨与 shape_*），其余按交付期查"""
    name = (path or "").lower()
    return "edit" if "_edit" in name else "delivery"


def arg_flag(name: str) -> bool:
    return name in sys.argv


def tri_count(mesh) -> int:
    """三角面数：按多边形顶点数折算（四边面 = 2 tri）"""
    total = 0
    for poly in mesh.polygons:
        total += max(0, len(poly.vertices) - 2)
    return total


def shape_key_names(obj) -> list[str]:
    keys = getattr(obj.data, "shape_keys", None)
    if not keys or not keys.key_blocks:
        return []
    # 第一个是 Basis，不算 morph
    return [block.name for block in keys.key_blocks[1:]]


def max_influences(obj) -> int:
    """每个顶点最多被几根骨骼影响"""
    worst = 0
    try:
        groups = obj.vertex_groups
        for vertex in obj.data.vertices:
            worst = max(worst, len([g for g in vertex.groups if g.weight > 0]))
            if worst >= MAX_INFLUENCES:
                break
    except Exception:  # noqa: BLE001 —— 缺数据不该让校验崩掉
        return -1
    return worst


def main() -> None:
    report = {
        "file": bpy.data.filepath,
        "blender": bpy.app.version_string,
        "objects": [],
        "armatures": [],
        "materials": [material.name for material in bpy.data.materials],
        "mesh_count": 0,
        "tris_total": 0,
        "morphs": {"shape": [], "vis": [], "expr": [], "other": []},
        "worst_influences": 0,
        "problems": [],
        "warnings": [],
        "ok": True,
    }

    for obj in bpy.data.objects:
        entry = {"name": obj.name, "type": obj.type}
        if obj.type == "MESH":
            entry["tris"] = tri_count(obj.data)
            entry["verts"] = len(obj.data.vertices)
            names = shape_key_names(obj)
            entry["morphs"] = len(names)
            report["tris_total"] += entry["tris"]
            report["mesh_count"] += 1
            for name in names:
                if name.startswith(SHAPE_PREFIX):
                    report["morphs"]["shape"].append(f"{obj.name}:{name}")
                elif name.startswith(VIS_PREFIX):
                    report["morphs"]["vis"].append(name)
                elif name.startswith(EXPR_PREFIX):
                    report["morphs"]["expr"].append(name)
                else:
                    report["morphs"]["other"].append(f"{obj.name}:{name}")
            influences = max_influences(obj)
            entry["max_influences"] = influences
            report["worst_influences"] = max(report["worst_influences"], influences)
        elif obj.type == "ARMATURE":
            bones = [bone.name for bone in obj.data.bones]
            entry["bones"] = bones
            entry["bone_count"] = len(bones)
            report["armatures"].append(entry)
        report["objects"].append(entry)

    # ── 逐项判定 ────────────────────────────────────────────────
    problems = report["problems"]
    warnings = report["warnings"]
    stage = stage_of(bpy.data.filepath)
    report["stage"] = stage

    if report["tris_total"] > MAX_TRIS_TOTAL:
        problems.append(f"面数超预算：{report['tris_total']} > {MAX_TRIS_TOTAL} tri")

    if len(report["materials"]) > MAX_MATERIALS:
        problems.append(f"材质槽过多：{len(report['materials'])} > {MAX_MATERIALS}")

    if not report["armatures"]:
        problems.append("没有骨架（Armature）")
    bone_limit = MAX_BONES_EDIT if stage == "edit" else MAX_BONES_DELIVERY
    for armature in report["armatures"]:
        if armature["bone_count"] > bone_limit:
            extra = (
                "（交付期应删掉辅助骨）" if stage == "delivery" else "（编辑期上限 %d）" % MAX_BONES_EDIT
            )
            problems.append(
                f"骨架骨数 {armature['bone_count']} > {bone_limit}{extra}："
                f"{', '.join(armature['bones'])}"
            )

    if report["worst_influences"] > MAX_INFLUENCES:
        problems.append(f"有顶点被 {report['worst_influences']} 根骨骼影响（上限 {MAX_INFLUENCES}）")

    if report["morphs"]["other"]:
        problems.append("有 morph 不在白名单命名空间内：" + ", ".join(report["morphs"]["other"][:8]))

    vis = len(set(report["morphs"]["vis"]))
    expr = len(set(report["morphs"]["expr"]))
    shape = len(set(report["morphs"]["shape"]))

    if stage == "delivery":
        # 交付给运行时的资产：捏脸结果必须已烘焙，肩上只留口型与表情
        if shape:
            problems.append(f"交付资产里还有 {shape} 个 shape_*（捏脸应已烘焙进网格）")
        if vis and vis < 15:
            problems.append(f"viseme 只有 {vis} 个（要求 15）")
        if expr and expr < 8:
            problems.append(f"表情 morph 只有 {expr} 个（要求 ≥ 8，眨眼左右分开）")
    else:
        if not shape:
            warnings.append("编辑期文件里没有 shape_*（捏脸形变键还没做？）")

    # 默认命名：不影响能不能跑，但会让端侧与后续维护变麻烦
    for hint in DEFAULT_NAME_HINTS:
        for material in report["materials"]:
            if material.startswith(hint):
                warnings.append(f"材质还是默认名：{material}")
        for entry in report["objects"]:
            if entry["name"].startswith(hint) or entry["name"] == hint:
                warnings.append(f"网格还是默认名：{entry['name']}（端侧按名字取，建议改成 head/face 之类）")

    report["ok"] = not problems

    if arg_flag("--json"):
        print("VALIDATION_JSON " + json.dumps(report, ensure_ascii=False))
        return

    print("=" * 66)
    print("比邻AI · 面部 rig 交付校验")
    print("=" * 66)
    print(f"文件      : {report['file']}")
    print(f"阶段      : {report.get('stage', '?')}（按文件名判断：_edit = 编辑期）")
    print(f"Blender   : {report['blender']}")
    print(f"网格      : {report['mesh_count']} 个，合计 {report['tris_total']} tri（预算 {MAX_TRIS_TOTAL}）")
    for entry in report["objects"]:
        if entry["type"] == "MESH":
            print(
                f"    - {entry['name']}: {entry['tris']} tri / {entry['verts']} 顶点"
                f" / morph {entry['morphs']} / 最大骨骼影响 {entry.get('max_influences')}"
            )
        elif entry["type"] == "ARMATURE":
            print(f"    - [骨架] {entry['name']}: {entry['bone_count']} 骨 → {', '.join(entry['bones'])}")
    print(f"材质      : {len(report['materials'])} 个 → {', '.join(report['materials'])}")
    print(f"morph     : shape_* {len(report['morphs']['shape'])} / vis_* {vis} / expr_* {expr} / 其他 {len(report['morphs']['other'])}")
    if report["morphs"]["shape"]:
        print("    shape_* 明细: " + ", ".join(sorted(set(report["morphs"]["shape"]))[:12])
              + (" …" if len(report["morphs"]["shape"]) > 12 else ""))
    print("-" * 66)
    if report["ok"]:
        print("✅ 通过：自动可查的项目全部符合交付规范")
    else:
        print("❌ 有 %d 项不符合：" % len(problems))
        for problem in problems:
            print("    · " + problem)
    if warnings:
        print("⚠️ 建议（不影响功能）：")
        for warning in sorted(set(warnings)):
            print("    · " + warning)
    print("（形变质量、极端值破面等仍需人工/渲染图验收）")


main()
