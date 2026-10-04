#!/usr/bin/env python3
"""
比邻AI · 定点宏观渲染（看清局部起伏：眼角、睑缘、唇缝、鼻翼）

用法：
    blender --background <文件.blend> --python tools/blender-render-eye.py -- \
        --out <前缀> --center x,y,z [--scale 0.05] [--views front,front34,side,top] [--solid]
        [--shape <形态键名=值> ...] [--texture]

`--shape` 用于**验收形态键**（口型/表情）：`--shape vis_AA=1 --shape expr_blink_L=1`，
渲染前把对应 `key_block.value` 置上（其余保持 0），从而看到 morph 的实际效果。

为什么需要它：`blender-preview.py` 的 eye 模式靠"eyeball 对象"定位，
而原始高模**没有眼球对象**；而且判断"凸起还是凹陷"必须开 **cavity（空腔）着色**
——它按曲率给脊线/沟槽上色，比普通漫反射直观得多。
"""

import json
import math
import sys

import bpy
from mathutils import Vector


def all_args():
    argv = sys.argv
    if "--" not in argv:
        return []
    return argv[argv.index("--") + 1:]


def arg_value(name, default=None):
    args = sys.argv
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return default


def parse_center(raw):
    parts = [float(p) for p in raw.split(",")]
    return Vector(parts)


def apply_poses(specs):
    """`骨骼:轴:角度` 或 `骨骼:轴:平移mm` 形式的测试姿态，用于看形变穿帮

    例：`--pose jaw:X:20 --pose brow.L:X:-14`
    轴后加 `t` 表示平移（毫米）：`--pose face_width:X:4t`
    """
    applied = []
    for spec in specs:
        parts = spec.split(":")
        if len(parts) != 3:
            continue
        name, axis, raw = parts
        armature = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
        if armature is None:
            continue
        bone = armature.pose.bones.get(name)
        if bone is None:
            continue
        bone.rotation_mode = "XYZ"
        index = {"X": 0, "Y": 1, "Z": 2}.get(axis.upper(), 0)
        if raw.endswith("t"):
            vector = [0.0, 0.0, 0.0]
            vector[index] = float(raw[:-1]) / 1000.0
            bone.location = vector
            applied.append(f"{name}.loc{axis.upper()}={raw[:-1]}mm")
        else:
            euler = [0.0, 0.0, 0.0]
            euler[index] = math.radians(float(raw))
            bone.rotation_euler = euler
            applied.append(f"{name}.rot{axis.upper()}={raw}deg")
    bpy.context.view_layer.update()
    return applied


VIEWS = {
    "front": (Vector((0, -1, 0)), Vector((0, 0, 1))),
    "back": (Vector((0, 1, 0)), Vector((0, 0, 1))),
    "side": (Vector((1, -0.05, 0)), Vector((0, 0, 1))),
    "side34": (Vector((0.8, -0.6, 0.1)), Vector((0, 0, 1))),
    "top": (Vector((0, -0.15, 1)), Vector((0, -1, 0))),
    "up45": (Vector((0, -0.8, 0.6)), Vector((0, 0, 1))),
    "down45": (Vector((0, -0.8, -0.6)), Vector((0, 0, 1))),
}


def apply_shapes(specs):
    """把 `形态键=值` 应用到网格的 shape_keys（其余键保持 0）

    用于验收形态键：口型/表情必须能**单独看到**，不能和骨骼姿态混在一起
    （同一区域骨骼 + morph 双驱动是规格 §4.3 明令禁止的形态）。
    """
    applied = []
    for spec in specs:
        if "=" not in spec:
            continue
        name, raw = spec.split("=", 1)
        try:
            value = float(raw)
        except ValueError:
            continue
        for obj in bpy.data.objects:
            if obj.type != "MESH" or obj.data.shape_keys is None:
                continue
            block = obj.data.shape_keys.key_blocks.get(name)
            if block is None:
                continue
            block.value = value
            applied.append(f"{obj.name}.{name}={value}")
    bpy.context.view_layer.update()
    return applied


def main():
    out = arg_value("--out", "macro.png")
    center = parse_center(arg_value("--center", "0,0,0"))
    scale = float(arg_value("--scale", "0.05"))
    views = (arg_value("--views", "front,side34,top") or "front,side34,top").split(",")
    solid = "--solid" in sys.argv
    poses = []
    shapes = []
    for index, value in enumerate(sys.argv):
        if value == "--pose" and index + 1 < len(sys.argv):
            poses.append(sys.argv[index + 1])
        if value == "--shape" and index + 1 < len(sys.argv):
            shapes.append(sys.argv[index + 1])
    if poses:
        print("MACRO_POSE " + ", ".join(apply_poses(poses)))
    if shapes:
        applied = apply_shapes(shapes)
        print("MACRO_SHAPE " + (", ".join(applied) if applied else "（没有命中任何形态键）"))

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 900
    scene.render.resolution_y = 900
    scene.render.film_transparent = False
    shading = scene.display.shading
    shading.light = "STUDIO"
    # --texture 用材质里指派的贴图（能看到"画上去的眼睛/口红"，判断眼位最直接）
    if "--texture" in sys.argv:
        shading.color_type = "TEXTURE"
    else:
        shading.color_type = "SINGLE" if solid else "MATERIAL"
    shading.single_color = (0.75, 0.72, 0.70)
    # cavity（空腔）着色：按曲率给脊线/沟槽上色，判断凸起/凹陷靠它
    shading.show_cavity = True
    try:
        shading.cavity_type = "BOTH"
        shading.curvature_ridge_factor = 1.0
        shading.curvature_valley_factor = 1.0
        shading.cavity_ridge_factor = 1.5
        shading.cavity_valley_factor = 1.5
    except AttributeError:
        pass
    shading.show_object_outline = False

    camera_data = bpy.data.cameras.new("macro_cam")
    camera_data.type = "ORTHO"
    camera = bpy.data.objects.new("macro_cam", camera_data)
    bpy.context.collection.objects.link(camera)
    scene.camera = camera

    target = bpy.data.objects.new("macro_target", None)
    target.location = center
    bpy.context.collection.objects.link(target)

    rendered = []
    for label in views:
        label = label.strip()
        if label not in VIEWS:
            continue
        direction, up = VIEWS[label]
        camera_data.ortho_scale = scale
        camera.location = center + direction.normalized() * (scale * 3)
        for constraint in list(camera.constraints):
            camera.constraints.remove(constraint)
        track = camera.constraints.new("TRACK_TO")
        track.target = target
        track.track_axis = "TRACK_NEGATIVE_Z"
        track.up_axis = "UP_Y"
        scene.render.filepath = f"{out}-{label}.png"
        bpy.ops.render.render(write_still=True)
        rendered.append(scene.render.filepath)
        print("MACRO_RENDER " + scene.render.filepath)
    print("MACRO_JSON " + json.dumps({"out": out, "center": list(center),
                                      "scale": scale, "views": rendered},
                                     ensure_ascii=False))


main()
