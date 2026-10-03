#!/usr/bin/env python3
"""
比邻AI · 眼部资产诊断（Blender 无头运行）

用法：
    blender --background <文件.blend> --python tools/blender-diagnose-eyes.py

它回答三个问题（"眼球凸出 / 眼周拉伸"这类问题的根因通常在这三处之一）：
  1. 有没有**残留姿态**（pose bone 的 location/rotation/scale 不是单位值）
     —— glTF 会把当前姿态导出成骨骼变换，所以残留姿态会一路带进 GLB 和端侧
  2. 有没有**对象级缩放**（object scale != 1，例如眼球被放大过）
  3. **眼球与眼眶的相对关系**：眼球包围盒 vs 头部网格在眼区的顶点范围
     —— 眼球比眼眶大/靠前，就会"凸出来"

输出为可读文本（也可加 --json）。
"""

import json
import sys

import bpy
from mathutils import Vector


def flag(name: str) -> bool:
    return name in sys.argv


def world_bbox(obj):
    points = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    low = Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points)))
    high = Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points)))
    return low, high


def non_identity_pose(armature):
    """返回不是单位变换的姿态骨骼（这些会被导出成 GLB 的骨骼变换）

    ⚠️ 四元数必须跳过 w（identity 是 [1,0,0,0]，只看 w 会把所有骨骼都误报）
    """
    out = []
    for bone in armature.pose.bones:
        location = bone.location
        if bone.rotation_mode == "QUATERNION":
            rotation = bone.rotation_quaternion
            rotated = any(abs(rotation[i]) > 1e-6 for i in (1, 2, 3))
            rotation_values = [round(v, 5) for v in rotation]
        else:
            rotation = bone.rotation_euler
            rotated = any(abs(v) > 1e-6 for v in rotation)
            rotation_values = [round(v, 5) for v in rotation]
        scale = bone.scale
        moved = location.length > 1e-6
        scaled = any(abs(v - 1.0) > 1e-6 for v in scale)
        if moved or rotated or scaled:
            out.append(
                {
                    "bone": bone.name,
                    "location": [round(v, 5) for v in location],
                    "rotation": rotation_values,
                    "scale": [round(v, 5) for v in scale],
                    "constraints": [c.type for c in bone.constraints],
                }
            )
    return out


def main() -> None:
    report = {
        "file": bpy.data.filepath,
        "frame": bpy.context.scene.frame_current,
        "actions": [a.name for a in bpy.data.actions],
        "object_scales": [],
        "pose_problems": [],
        "eye_geometry": {},
        "modifiers": [],
        "problems": [],
    }

    # ── 1) 对象级缩放 / 修改器 ───────────────────────────────
    for obj in bpy.data.objects:
        scale = obj.scale
        if any(abs(v - 1.0) > 1e-6 for v in scale):
            report["object_scales"].append(
                {"object": obj.name, "scale": [round(v, 4) for v in scale]}
            )
        if obj.type == "MESH" and obj.modifiers:
            report["modifiers"].append(
                {"object": obj.name, "modifiers": [(m.type, m.name) for m in obj.modifiers]}
            )

    # ── 2) 残留姿态 ────────────────────────────────────────
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE":
            bad = non_identity_pose(obj)
            if bad:
                report["pose_problems"].append({"armature": obj.name, "bones": bad})

    # ── 3) 眼球 vs 眼眶 ────────────────────────────────────
    eyes = {}
    head = None
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        name = obj.name.lower()
        if "eyeball" in name or name.startswith("eye"):
            low, high = world_bbox(obj)
            eyes[obj.name] = {
                "bbox_size": [round(v, 4) for v in (high - low)],
                "center": [round(v, 4) for v in ((low + high) / 2)],
                "verts": len(obj.data.vertices),
                "shape_keys": len(obj.data.shape_keys.key_blocks) - 1 if obj.data.shape_keys else 0,
            }
        elif "eyeball" not in name and "teeth" not in name and "tongue" not in name and "cavity" not in name:
            head = obj if head is None or len(obj.data.vertices) > len(head.data.vertices) else head

    report["eye_geometry"]["eyeballs"] = eyes

    if head is not None and eyes:
        low, high = world_bbox(head)
        report["eye_geometry"]["head"] = {
            "name": head.name,
            "bbox_size": [round(v, 4) for v in (high - low)],
            "verts": len(head.data.vertices),
        }
        for eye_name, info in eyes.items():
            cx, cy, cz = info["center"]
            eye_size = max(info["bbox_size"])
            # 眼区：以**眼球中心**为中心的一个球内取头部顶点（之前按全身高度切 Z 波段是错的，
            # 会取到胸腹的顶点，导致"凸出量"算成负数）
            radius = eye_size * 1.5
            near = []
            for v in head.data.vertices:
                point = head.matrix_world @ v.co
                if (
                    abs(point.x - cx) < radius
                    and abs(point.y - cy) < radius * 1.2
                    and abs(point.z - cz) < radius * 1.2
                ):
                    near.append(point)
            if near:
                info["socket_verts_near"] = len(near)
                info["head_front_y"] = round(min(p.y for p in near), 4)
                info["eye_front_y"] = round(cy - info["bbox_size"][1] / 2, 4)
                # -Y 是正面（Blender 前视图朝 +Y 看）。眼球中心比"眼区皮肤最前点"还靠前 → 凸出
                info["bulge"] = round(cy - min(p.y for p in near), 4)
                info["skin_around_eye_z"] = [
                    round(min(p.z for p in near), 4),
                    round(max(p.z for p in near), 4),
                ]

    # ── 判定 ──────────────────────────────────────────────
    problems = report["problems"]
    if report["pose_problems"]:
        for item in report["pose_problems"]:
            names = ", ".join(b["bone"] for b in item["bones"][:8])
            problems.append(
                f"骨架 {item['armature']} 有 {len(item['bones'])} 根骨骼带着**非单位姿态**"
                f"（会一起导出到 GLB）：{names}"
            )
    if report["object_scales"]:
        for item in report["object_scales"]:
            problems.append(f"对象 {item['object']} 有对象级缩放 {item['scale']}（导出后会被烘焙进网格）")
    for eye_name, info in report["eye_geometry"].get("eyeballs", {}).items():
        if info.get("bulge") is not None and info["bulge"] > 0:
            problems.append(
                f"{eye_name} 比脸部表面还靠前 {info['bulge']}（正值 = 凸出眼眶）"
            )

    if flag("--json"):
        print("EYE_DIAG_JSON " + json.dumps(report, ensure_ascii=False))
        return

    print("=" * 66)
    print("比邻AI · 眼部资产诊断")
    print("=" * 66)
    print(f"文件: {report['file']}")
    print(f"当前帧: {report['frame']}   动作(actions): {report['actions'] or '无'}")
    print(f"对象级缩放: {report['object_scales'] or '无'}")
    print(f"修改器: {report['modifiers'] or '无'}")
    print("-" * 66)
    print("眼球与头部的几何关系：")
    for eye_name, info in report["eye_geometry"].get("eyeballs", {}).items():
        print(
            f"  {eye_name}: 尺寸={info['bbox_size']} 中心={info['center']} "
            f"顶点={info['verts']} 形变键={info['shape_keys']}"
        )
        if "bulge" in info:
            print(
                f"      眼区附近头部顶点={info['socket_verts_near']}  "
                f"眼球最前=-Y{abs(info['eye_front_y'])} vs 头部最前=-Y{abs(info['head_front_y'])}  "
                f"凸出量={info['bulge']}"
            )
    head_info = report["eye_geometry"].get("head")
    if head_info:
        print(f"  头部网格: {head_info['name']} 尺寸={head_info['bbox_size']} 顶点={head_info['verts']}")
    print("-" * 66)
    if report["pose_problems"]:
        print("⚠️ 残留姿态（会被导出进 GLB）：")
        for item in report["pose_problems"]:
            print(f"  骨架 {item['armature']}:")
            for bone in item["bones"][:14]:
                print(
                    f"    {bone['bone']}: loc={bone['location']} rot={bone['rotation']} "
                    f"scale={bone['scale']}{' 约束=' + str(bone['constraints']) if bone['constraints'] else ''}"
                )
    else:
        print("✅ 没有残留姿态（骨骼都是单位变换）")
    print("-" * 66)
    if problems:
        print(f"❌ 发现 {len(problems)} 个问题：")
        for problem in problems:
            print("   · " + problem)
    else:
        print("✅ 以上三项检查均无异常（问题可能在 morph 目标自身或贴图 UV）")


main()
