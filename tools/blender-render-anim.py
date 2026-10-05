#!/usr/bin/env python3
"""按帧渲染动画（用于目视检查挥手动作）

用法：
    blender -b <带动画的.blend> --python tools/blender-env.py \
        --python tools/blender-render-anim.py -- --out <前缀> --frames 0,20,40,60,78 \
            [--center 0,-0.02,0.6] [--scale 1.2] [--view front]
"""
import os
import sys

import bpy
from mathutils import Vector


def arg_value(name, default=None):
    args = sys.argv
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return default


VIEWS = {
    "front": (Vector((0.0, -1.0, 0.0)), Vector((0.0, 0.0, 1.0))),
    "side": (Vector((-1.0, 0.0, 0.0)), Vector((0.0, 0.0, 1.0))),
    "q34": (Vector((-0.7, -0.7, 0.15)), Vector((0.0, 0.0, 1.0))),
}


def main():
    prefix = arg_value("--out", "anim")
    frames = [int(value) for value in arg_value("--frames", "0,20,40,60,78").split(",")]
    center = [float(value) for value in arg_value("--center", "0,-0.02,0.60").split(",")]
    scale = float(arg_value("--scale", "1.25"))
    view = arg_value("--view", "front")

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 900
    scene.render.resolution_y = 900
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.color_type = "MATERIAL"
    shading.show_cavity = True

    camera_data = bpy.data.cameras.new("anim_cam")
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = scale
    camera = bpy.data.objects.new("anim_cam", camera_data)
    bpy.context.collection.objects.link(camera)
    scene.camera = camera
    direction, up = VIEWS.get(view, VIEWS["front"])
    target = Vector(center)
    camera.location = target + direction.normalized() * (scale * 3)
    # 让相机看向 target
    look = (target - camera.location).normalized()
    camera.rotation_euler = look.to_track_quat("-Z", "Y").to_euler()

    for frame in frames:
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        path = os.path.abspath("%s-f%03d-%s.png" % (prefix, frame, view))
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        print("  ANIM_FRAME %d → %s" % (frame, path))
    print("ANIM_RENDER_OK")


main()
