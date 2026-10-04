#!/usr/bin/env python3
"""
比邻AI · .blend 结构速查（对象/变换/顶点组/形态键/边界边/贴图/眼球）

用法：
    blender --background <文件.blend> --python tools/blender-inspect-blend.py -- [--boundary]

用途：拿到一个陌生（或历史）资产时，先看清"里面到底有什么"，再决定动不动手。
"""

import json
import sys

import bpy
from mathutils import Vector


def has_flag(name):
    return name in sys.argv


def boundary_edges(mesh):
    counts = {}
    for poly in mesh.polygons:
        for key in poly.edge_keys:
            counts[key] = counts.get(key, 0) + 1
    return sum(1 for value in counts.values() if value == 1)


def object_info(obj):
    info = {
        "name": obj.name,
        "type": obj.type,
        "location": [round(v, 6) for v in obj.location],
        "rotation_quaternion": [round(v, 6) for v in obj.rotation_quaternion],
        "rotation_euler": [round(v, 6) for v in obj.rotation_euler],
        "scale": [round(v, 6) for v in obj.scale],
        "parent": obj.parent.name if obj.parent else None,
    }
    if obj.type == "MESH":
        mesh = obj.data
        info["mesh_name"] = mesh.name
        info["verts"] = len(mesh.vertices)
        info["polys"] = len(mesh.polygons)
        info["materials"] = [m.name if m else None for m in mesh.materials]
        info["uv_layers"] = [uv.name for uv in mesh.uv_layers]
        info["boundary_edges"] = boundary_edges(mesh)
        info["vertex_groups"] = [g.name for g in obj.vertex_groups]
        keys = mesh.shape_keys
        info["shape_keys"] = 0 if not keys else len(keys.key_blocks)
        info["modifiers"] = [m.type for m in obj.modifiers]
        # 世界包围盒
        matrix = obj.matrix_world
        lo = [1e9] * 3
        hi = [-1e9] * 3
        for corner in obj.bound_box:
            point = matrix @ Vector(corner)
            for k in range(3):
                lo[k] = min(lo[k], point[k])
                hi[k] = max(hi[k], point[k])
        info["world_bbox_min"] = [round(v, 5) for v in lo]
        info["world_bbox_max"] = [round(v, 5) for v in hi]
        info["world_size"] = [round(hi[k] - lo[k], 5) for k in range(3)]
    if obj.type == "ARMATURE":
        info["bones"] = [b.name for b in obj.data.bones]
        info["bone_count"] = len(obj.data.bones)
    return info


def main():
    report = {"file": bpy.data.filepath, "objects": [], "images": []}
    for obj in bpy.data.objects:
        report["objects"].append(object_info(obj))
    for image in bpy.data.images:
        report["images"].append({
            "name": image.name,
            "size": list(image.size),
            "packed": bool(image.packed_file),
            "filepath": image.filepath,
        })

    print("=" * 96)
    print("结构速查: " + report["file"])
    for obj in report["objects"]:
        print("")
        print(f"• [{obj['type']}] {obj['name']}")
        print(f"    loc {obj['location']}  rot_q {obj['rotation_quaternion']}  scale {obj['scale']}"
              f"  parent {obj['parent']}")
        if obj["type"] == "MESH":
            print(f"    mesh={obj['mesh_name']} verts={obj['verts']} polys={obj['polys']} "
                  f"boundary_edges={obj['boundary_edges']} shape_keys={obj['shape_keys']}")
            print(f"    materials={obj['materials']} uv={obj['uv_layers']} "
                  f"modifiers={obj['modifiers']}")
            print(f"    world_bbox {obj['world_bbox_min']} .. {obj['world_bbox_max']} "
                  f"size {obj['world_size']}")
            if obj["vertex_groups"]:
                shown = obj["vertex_groups"][:24]
                print(f"    vertex_groups({len(obj['vertex_groups'])})={shown}"
                      + (" ..." if len(obj["vertex_groups"]) > 24 else ""))
        if obj["type"] == "ARMATURE":
            print(f"    bones({obj['bone_count']})={obj['bones']}")
    print("")
    print("贴图：")
    for image in report["images"]:
        print(f"   {image['name']:<34} {image['size']} packed={image['packed']} "
              f"{image['filepath']}")
    print("INSPECT_JSON " + json.dumps(report, ensure_ascii=False))


main()
