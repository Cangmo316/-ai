#!/usr/bin/env python3
"""
比邻AI · glTF(GLB) 导出（Blender 无头运行）

按交付规范导出：glTF 2.0 / 内嵌贴图 / 保留蒙皮与形变键 / 不导出动画 / +Y up。

用法：
    blender --background <文件.blend> --python tools/blender-export-glb.py -- \
        --out <输出.glb> [--stats]

注意：
  · **不能** apply 修改器里的 Armature（那会把蒙皮烘死）——导出器本身会跳过 Armature 修改器，
    这里显式用 export_apply=False 保证安全
  · 导出后建议用 `node tools/glb-inspect.mjs` 复核：joints 数、形变键数量与命名、
    内嵌贴图是否齐全（与本轮修复前的基线对照）
"""

import json
import os
import sys

import bpy


def arg_value(name, default=None):
    args = sys.argv
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return default


def has_flag(name):
    return name in sys.argv


def scene_stats():
    meshes = {}
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        keys = obj.data.shape_keys
        meshes[obj.name] = {
            "verts": len(obj.data.vertices),
            "tris": sum(len(p.vertices) - 2 for p in obj.data.polygons),
            "morphs": max(0, len(keys.key_blocks) - 1) if keys else 0,
            "materials": len(obj.data.materials),
            "max_influences": max((len(v.groups) for v in obj.data.vertices), default=0),
        }
    joints = {}
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE":
            joints[obj.name] = len(obj.data.bones)
    images = [
        {"name": image.name, "size": list(image.size), "packed": bool(image.packed_file)}
        for image in bpy.data.images
        if image.name not in ("Render Result", "Viewer Node", "Dirty")
    ]
    return {"meshes": meshes, "armatures": joints, "images": images}


def main() -> None:
    out = arg_value("--out")
    if not out:
        print("EXPORT_FAIL 需要 --out <输出.glb>")
        return

    before = scene_stats()
    print("=" * 70)
    print("导出前场景: " + json.dumps(before, ensure_ascii=False))

    # ── 贴图上限：出厂 GLB 内嵌贴图是 1024×1024；.blend 里可能留着 2048（甚至 4096），
    #    直接导出会让 GLB 体积翻倍。这里在**内存中**缩到上限后再导出；
    #    不保存 .blend，所以源文件与其 packed 数据不受影响。
    max_size = int(arg_value("--texture-max", "0"))
    if max_size > 0:
        for image in bpy.data.images:
            if image.name in ("Render Result", "Viewer Node", "Dirty"):
                continue
            width, height = image.size
            if width and height and max(width, height) > max_size:
                try:
                    image.scale(max_size, max_size)
                    print(f"  贴图缩放 {image.name}: {width}x{height} → {max_size}x{max_size}")
                except Exception as error:  # noqa: BLE001
                    print(f"  ⚠️ 贴图缩放失败 {image.name}: {error}")

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=out,
        export_format="GLB",
        export_apply=False,          # 绝不要把 Armature 烘进网格
        export_skins=True,
        export_morph=True,
        # ⚠️ 必须关：开启会给**每个形变键**都写一组法线，137 个键 → 体积从 9.6MB 涨到 32MB
        #    （对照原版资产：137 个 morph 目标里带法线的 = 0）
        export_morph_normal=False,
        export_animations=False,
        export_yup=True,
        export_materials="EXPORT",
        export_image_format="AUTO",
        export_texture_dir="",
        export_cameras=False,
        export_lights=False,
        use_selection=False,
        use_visible=False,
        use_renderable=False,
        export_extras=False,
    )
    size = os.path.getsize(out)
    print(f"EXPORT_OK {out}  {size} B  ({size / 1024 / 1024:.1f} MB)")
    if has_flag("--stats"):
        print("EXPORT_STATS " + json.dumps(before, ensure_ascii=False))


main()
