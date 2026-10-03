#!/usr/bin/env python3
"""
比邻AI · 头部模型验收渲染图（Blender 无头运行）

用法：
    blender --background <某个.blend> --python tools/blender-preview.py -- <输出.png> [角度]

    # 例：正视图 + 四分之三视图
    blender --background model.blend --python tools/blender-preview.py -- out/front.png front
    blender --background model.blend --python tools/blender-preview.py -- out/three.png three

为什么用它：rig 的自动校验只能查数字（骨数/morph 名/面数），
**形变质量与"像不像人"必须看图**。这个脚本用 Workbench 引擎（无需灯光、无 GPU 也能跑）
把头部框好渲染出来，方便版本间对比或贴给家属审校。

角度：front（正前）/ three（四分之三）/ side（右侧）。
"""

import math
import sys

import bpy


def all_args() -> list[str]:
    argv = sys.argv
    if "--" not in argv:
        return []
    return argv[argv.index("--") + 1 :]


def arg_after_separator(index: int, default: str = "") -> str:
    rest = all_args()
    return rest[index] if len(rest) > index else default


def head_bone_bounds():
    """用骨架里的 head 骨定位脸部（比按整体包围盒切顶部更准）"""
    for obj in bpy.data.objects:
        if obj.type != "ARMATURE":
            continue
        for name in ("head", "Head"):
            bone = obj.data.bones.get(name)
            if not bone:
                continue
            center = obj.matrix_world @ ((bone.head_local + bone.tail_local) / 2)
            length = (bone.tail_local - bone.head_local).length
            return center, max(length, 0.05)
    return None, None


def apply_morphs(pairs: list[str]) -> list[str]:
    """`name=value` → 设置形态键权重；返回实际生效的列表

    ⚠️ 必须**对所有带该键的对象**都设一遍：口腔/牙齿/舌头各自持有一份 vis_*，
    只改脸部网格会出现"嘴张开了但牙和口腔没动"的穿帮（实测踩过）。
    """
    applied = []
    for pair in pairs:
        if "=" not in pair:
            continue
        name, _, raw = pair.partition("=")
        try:
            value = float(raw)
        except ValueError:
            continue
        hit = 0
        for obj in bpy.data.objects:
            keys = getattr(obj.data, "shape_keys", None)
            if not keys:
                continue
            block = keys.key_blocks.get(name)
            if block:
                block.value = value
                hit += 1
        if hit:
            applied.append(f"{name}={value:g}(×{hit})")
    return applied


def target_meshes():
    """取用于框定的网格：优先名字像头部的，否则用最大的那个（排除眼球/牙/舌/口腔）"""
    meshes = [obj for obj in bpy.data.objects if obj.type == "MESH"]
    if not meshes:
        return []
    skip = ("eyeball", "teeth", "tongue", "cavity", "eye")
    main = [obj for obj in meshes if not any(token in obj.name.lower() for token in skip)]
    return main or meshes


def world_bounds(objects):
    low = None
    high = None
    for obj in objects:
        for corner in obj.bound_box:
            point = obj.matrix_world @ __import__("mathutils").Vector(corner)
            low = point if low is None else type(low)((min(low.x, point.x), min(low.y, point.y), min(low.z, point.z)))
            high = point if high is None else type(high)((max(high.x, point.x), max(high.y, point.y), max(high.z, point.z)))
    return low, high


def main() -> None:
    args = all_args()
    out = arg_after_separator(0, "preview.png")
    angle = (arg_after_separator(1, "front") or "front").lower()
    morphs = apply_morphs(args[2:])

    meshes = target_meshes()
    if not meshes:
        print("PREVIEW_FAIL 场景里没有网格")
        return

    low, high = world_bounds(meshes)
    center = ((low.x + high.x) / 2, (low.y + high.y) / 2, (low.z + high.z) / 2)
    size = max(high.x - low.x, high.z - low.z, 0.01)

    # face / face34：只框头部（用 head 骨定位），用于检查五官与口型表情
    if angle.startswith("face"):
        bone_center, bone_length = head_bone_bounds()
        if bone_center is not None:
            center = (bone_center.x, bone_center.y, bone_center.z)
            size = bone_length * 2.4
        else:
            center = (center[0], center[1], high.z - (high.z - low.z) * 0.11)
            size = (high.z - low.z) * 0.26

    # 相机：正交投影，距离给足避免裁切
    distance = max(high.y - low.y, size) * 3 + 0.5
    if angle in ("three", "face34"):
        offset = (size * 0.9, -distance, size * 0.35)
        rotation = (math.radians(84), 0, math.radians(28))
    elif angle == "side":
        offset = (distance, 0, 0)
        rotation = (math.radians(90), 0, math.radians(90))
    else:  # front / face
        offset = (0, -distance, 0)
        rotation = (math.radians(90), 0, 0)

    camera_data = bpy.data.cameras.new("PreviewCam")
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = size * 1.15
    camera = bpy.data.objects.new("PreviewCam", camera_data)
    camera.location = (center[0] + offset[0], center[1] + offset[1], center[2] + offset[2])
    camera.rotation_euler = rotation
    bpy.context.scene.collection.objects.link(camera)
    bpy.context.scene.camera = camera

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 560
    scene.render.resolution_y = 760
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = out
    # Workbench 着色：用材质/贴图颜色，开阴影让五官有立体感
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.color_type = "TEXTURE"
    shading.show_shadows = True
    shading.show_cavity = True

    bpy.ops.render.render(write_still=True)
    print(f"PREVIEW_OK {out} ({angle}) meshes={len(meshes)} size={size:.3f} morphs={morphs or '-'}")


main()
