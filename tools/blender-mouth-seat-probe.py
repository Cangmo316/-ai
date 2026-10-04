#!/usr/bin/env python3
"""口内几何在**开合姿态下**的穿出量（静置不穿 ≠ 张嘴不穿）

用法： blender -b <资产> --python blender-env.py --python blender-mouth-seat-probe.py -- [--pose-mm]
对每个形态键（或只 vis_AA）单独置 1，量 mouth_cavity/teeth/tongue 有多少顶点
在"同 (x,z) 处主网格最前表面"之前（= 从脸上戳出来）。
"""
import json
import sys

import numpy as np
import bpy

SHAPE_ONLY = "--shape-only" in sys.argv
want_json = "--json" in sys.argv


def arg_value(name, default=None):
    args = sys.argv
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return default


head = bpy.data.objects.get("node_0") or max(
    (o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
count = len(head.data.vertices)
head_co = np.empty(count * 3, dtype=np.float64)
head.data.vertices.foreach_get("co", head_co)
head_co = head_co.reshape(count, 3)
zone = (np.abs(head_co[:, 0]) < 0.05) & (head_co[:, 1] < -0.03) \
    & (head_co[:, 2] > 0.98) & (head_co[:, 2] < 1.08)
face = head_co[zone]
print("参考面顶点 %d（嘴/下巴区）" % len(face))


def protrusion(tag):
    rows = {}
    for name in ("mouth_cavity", "teeth", "tongue"):
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        n = len(obj.data.vertices)
        co = np.empty(n * 3, dtype=np.float64)
        obj.data.vertices.foreach_get("co", co)
        co = co.reshape(n, 3)
        bad = 0
        worst = 0.0
        for index in range(n):
            x, y, z = co[index]
            near = face[(np.abs(face[:, 0] - x) < 0.0025) & (np.abs(face[:, 2] - z) < 0.0025)]
            if len(near) == 0:
                continue
            y_front = float(near[:, 1].min())
            if y < y_front - 5e-5:
                bad += 1
                worst = max(worst, (y_front - y) * 1000)
        rows[name] = {"protruding": bad, "worst_mm": round(worst, 3), "verts": n}
    print("  [%s] %s" % (tag, json.dumps(rows, ensure_ascii=False)))
    return rows


report = {"poses": {}}
keys = head.data.shape_keys
names = [k.name for k in keys.key_blocks if k.name != "Basis"] if keys else []
if not keys:
    print("MOUTH_SEAT_FAIL 没有形态键")
    sys.exit(1)
report["poses"]["rest"] = protrusion("rest")
targets = [n for n in names if n == "vis_AA"] if SHAPE_ONLY else \
    [n for n in ("vis_AA", "vis_O", "vis_E", "expr_surprise") if n in names]
for name in targets:
    for block in keys.key_blocks:
        block.value = 0.0
    keys.key_blocks[name].value = 1.0
    bpy.context.view_layer.update()
    # 重新取参考面（主网格在姿态下的位置）
    deps = bpy.context.evaluated_depsgraph_get()
    evaluated = head.evaluated_get(deps)
    mesh = evaluated.to_mesh()
    posed = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", posed)
    posed = posed.reshape(-1, 3)
    evaluated.to_mesh_clear()
    face = posed[zone] if len(posed) == count else face
    report["poses"][name] = protrusion(name)
for block in keys.key_blocks:
    block.value = 0.0
if want_json:
    print("MOUTH_SEAT_JSON " + json.dumps(report, ensure_ascii=False))
print("MOUTH_SEAT_OK")
