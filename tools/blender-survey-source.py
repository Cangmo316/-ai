#!/usr/bin/env python3
"""
比邻AI · 原始资产勘察（Blender 无头运行）

用法：
    blender --background --python tools/blender-survey-source.py -- \
        --in <原始.fbx|.obj> --out <工作.blend> [--render <前缀>] [--head-ratio 7.5]

为什么先做这个：骨骼位置不能靠目测。先把原始高模导入并量出**解剖锚点**
（整体包围盒、身高、头高、对称面、面部前缘、眼/口/下巴/耳根高度等），
后续"骨相骨骼"的位置与权重区域都以这些锚点为基准；同时落一个工作 .blend，
后续步骤不必反复导入 80MB 的源文件。
"""

import json
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


def has_flag(name):
    return name in sys.argv


def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_any(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path, automatic_bone_orientation=True)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif ext == ".blend":
        bpy.ops.wm.open_mainfile(filepath=path)
    else:
        raise SystemExit("不支持的格式: " + ext)


def mesh_stats(obj):
    mesh = obj.data
    tris = sum(len(p.vertices) - 2 for p in mesh.polygons)
    return {
        "name": obj.name,
        "verts": len(mesh.vertices),
        "polys": len(mesh.polygons),
        "tris": tris,
        "materials": [m.name if m else None for m in mesh.materials],
        "uv_layers": [uv.name for uv in mesh.uv_layers],
        "shape_keys": (len(mesh.shape_keys.key_blocks) - 1) if mesh.shape_keys else 0,
        "vertex_groups": len(obj.vertex_groups),
    }


def world_points(obj, step=1):
    matrix = obj.matrix_world
    verts = obj.data.vertices
    # 注意：bpy 的集合不支持步进切片（vertices[::step] 会 TypeError），必须用 range
    return [matrix @ verts[i].co for i in range(0, len(verts), step)]


def landmarks(points):
    xs = sorted(p.x for p in points)
    ys = sorted(p.y for p in points)
    zs = sorted(p.z for p in points)
    low = Vector((xs[0], ys[0], zs[0]))
    high = Vector((xs[-1], ys[-1], zs[-1]))
    height = high.z - low.z
    return {
        "bbox_low": [round(v, 4) for v in low],
        "bbox_high": [round(v, 4) for v in high],
        "size": [round(v, 4) for v in (high - low)],
        "height_m": round(height, 4),
        "front_y": round(ys[0], 4),
    }


def head_analysis(points, height, head_ratio):
    """按 head_ratio 估头高，并给出面部锚点高度（比例法，随后用渲染校准）"""
    top = max(p.z for p in points)
    head_h = height / head_ratio
    head_cut = top - head_h
    head_points = [p for p in points if p.z >= head_cut]
    if not head_points:
        return {"error": "按比例算出的头部区域为空"}
    # 面部前缘：头部区域里最靠前（-Y）的一批点，用来定位鼻尖/额面
    front = min(p.y for p in head_points)
    # 眼高：经验取头高 0.42~0.48 处；口高：0.72~0.78 处；下巴：头底
    def band(lo, hi):
        a, b = top - head_h * hi, top - head_h * lo
        band_points = [p for p in head_points if a <= p.z <= b]
        if not band_points:
            return None
        return {
            "z_range": [round(a, 4), round(b, 4)],
            "front_y": round(min(p.y for p in band_points), 4),
            "count": len(band_points),
        }
    return {
        "head_top_z": round(top, 4),
        "head_cut_z": round(head_cut, 4),
        "head_height_m": round(head_h, 4),
        "head_points": len(head_points),
        "face_front_y": round(front, 4),
        "bands": {
            "brow_0.30_0.36": band(0.30, 0.36),
            "eye_0.42_0.48": band(0.42, 0.48),
            "nose_0.52_0.60": band(0.52, 0.60),
            "mouth_0.72_0.78": band(0.72, 0.78),
            "chin_0.92_1.00": band(0.92, 1.00),
        },
    }


def render_views(prefix, head_top_z, head_h):
    """正交渲染正/侧/45° 三视图（Workbench，仅看形状），用于与参考图对照"""
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 1200
    scene.render.resolution_y = 1200
    scene.render.film_transparent = False
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "TEXTURE" if has_flag("--texture") else "MATERIAL"

    center = Vector((0.0, 0.0, head_top_z - head_h * 0.5))
    size = head_h * 1.25
    camera_data = bpy.data.cameras.new("survey_cam")
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = size
    camera = bpy.data.objects.new("survey_cam", camera_data)
    bpy.context.collection.objects.link(camera)
    scene.camera = camera

    for label, direction in (("front", Vector((0, -1, 0))), ("side", Vector((1, 0, 0))), ("q34", Vector((0.8, -0.8, 0.1)))):
        camera.location = center + direction.normalized() * (size * 3)
        track = camera.constraints.new("TRACK_TO")
        target = bpy.data.objects.new("survey_target", None)
        target.location = center
        bpy.context.collection.objects.link(target)
        track.target = target
        track.track_axis = "TRACK_NEGATIVE_Z"
        track.up_axis = "UP_Y"
        scene.render.filepath = f"{prefix}-{label}.png"
        bpy.ops.render.render(write_still=True)
        camera.constraints.remove(track)
        bpy.data.objects.remove(target, do_unlink=True)
        print("SURVEY_RENDER " + scene.render.filepath)


def main() -> None:
    source = arg_value("--in")
    out = arg_value("--out")
    render_prefix = arg_value("--render")
    head_ratio = float(arg_value("--head-ratio", "7.5"))
    if not source or not os.path.exists(source):
        print("SURVEY_FAIL 找不到输入文件: " + str(source))
        return

    clear_scene()
    import_any(source)

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    armatures = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if not meshes:
        print("SURVEY_FAIL 导入后没有网格")
        return

    stats = [mesh_stats(o) for o in meshes]
    total_verts = sum(s["verts"] for s in stats)
    total_tris = sum(s["tris"] for s in stats)

    # 取最大的网格做解剖分析
    main_obj = max(meshes, key=lambda o: len(o.data.vertices))
    points = world_points(main_obj, step=max(1, len(main_obj.data.vertices) // 60000))
    marks = landmarks(points)
    head = head_analysis(points, marks["height_m"], head_ratio)

    report = {
        "source": source,
        "objects": stats,
        "armatures": [{"name": a.name, "bones": len(a.data.bones)} for a in armatures],
        "total_verts": total_verts,
        "total_tris": total_tris,
        "landmarks": marks,
        "head": head,
        "materials": [m.name for m in bpy.data.materials],
        "images": [
            {"name": i.name, "size": list(i.size), "packed": bool(i.packed_file), "filepath": i.filepath}
            for i in bpy.data.images
            if i.name not in ("Render Result", "Viewer Node")
        ],
    }

    print("=" * 78)
    print("原始资产勘察: " + source)
    print(f"网格 {len(meshes)} 个，合计 {total_verts} 顶点 / {total_tris} 三角面")
    for s in stats[:6]:
        print(
            f"  {s['name']}: {s['verts']}v / {s['tris']}tri  材质={s['materials']}  "
            f"UV={s['uv_layers']} 形态键={s['shape_keys']} 顶点组={s['vertex_groups']}"
        )
    print(f"骨架: {report['armatures'] or '无（原始资产是静态网格）'}")
    print(f"包围盒: {marks['size']}  身高 {marks['height_m']}m  最前缘 Y={marks['front_y']}")
    if "head_height_m" in head:
        print(
            f"头部(按 1:{head_ratio} 估): 顶 Z={head['head_top_z']}  底 Z={head['head_cut_z']}  "
            f"头高 {head['head_height_m']}m  头部采点数 {head['head_points']}  面部前缘 Y={head['face_front_y']}"
        )
        for name, band in head["bands"].items():
            if band:
                print(f"    {name}: Z {band['z_range']}  前缘 Y={band['front_y']}  采点 {band['count']}")
    print("材质: " + ", ".join(report["materials"]))
    for image in report["images"]:
        print(f"贴图 {image['name']} {image['size']} {image['filepath']}")

    if render_prefix and "head_height_m" in head:
        render_views(render_prefix, head["head_top_z"], head["head_height_m"])

    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("SURVEY_OK 工作文件已保存: " + out)
    print("SURVEY_JSON " + json.dumps(report, ensure_ascii=False))


main()
