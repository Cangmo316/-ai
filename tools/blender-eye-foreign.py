#!/usr/bin/env python3
"""
比邻AI · 眼前"外来几何"探针（找出横在眼球前面的非眼区顶点）

用法：
    blender --background <资产.blend> --python tools/blender-env.py \
        --python tools/blender-eye-foreign.py -- [--axis z|y] [--json]

背景：v2 女生用"雕穹顶"方案（虹膜画在 albedo 上，无独立眼球网格）。
实测渲染里眼裂处有深色丝状物横穿——本脚本按**眼裂椭圆内的顶点**统计：
  · 有多少顶点属于"眼区"（眼骨权重高 / 眼皮环）
  · 有多少是"外来者"（在眼裂范围内、但在前表面之前，且不属于眼区）
并给出它们的主控骨与到眼穹顶的距离，用来判断该推回去还是该改权重。
"""

import json
import sys

import numpy as np
import bpy


def arg_value(name, default=None):
    args = sys.argv
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return default


EYE = {
    "L": {"center": (0.0176, -0.0532, 1.0680), "radius": 0.0155},
    "R": {"center": (-0.0177, -0.0539, 1.0679), "radius": 0.0149},
}


def main():
    want_json = "--json" in sys.argv
    mesh_obj = max((o for o in bpy.data.objects if o.type == "MESH"),
                   key=lambda o: len(o.data.vertices))
    mesh = mesh_obj.data
    count = len(mesh.vertices)
    co = np.empty(count * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(count, 3)

    def weights_of(name):
        out = np.zeros(count)
        group = mesh_obj.vertex_groups.get(name)
        if group is None:
            return out
        index = group.index
        for vertex in mesh.vertices:
            for element in vertex.groups:
                if element.group == index:
                    out[vertex.index] = element.weight
                    break
        return out

    eye_weight = {side: weights_of("eye.%s" % side) for side in ("L", "R")}
    socket_weight = {side: weights_of("eye_socket.%s" % side) for side in ("L", "R")}
    lid = {side: weights_of("eyelid_upper.%s" % side) + weights_of("eyelid_lower.%s" % side)
           for side in ("L", "R")}

    report = {"file": bpy.data.filepath, "eyes": {}}
    for side, spec in EYE.items():
        center = np.array(spec["center"])
        radius = spec["radius"]
        distance = np.linalg.norm(co - center, axis=1)
        in_front = co[:, 1] < center[1]
        inside = distance < radius * 1.35            # 眼裂及其一圈
        zone = inside & in_front
        eye_like = (eye_weight[side] > 0.12) | (lid[side] > 0.12) | (socket_weight[side] > 0.12)
        foreign = zone & ~eye_like
        print("=" * 92)
        print("EYE.%s 球心 %s 半径 %.2fmm" % (side, np.round(center, 4).tolist(), radius * 1000))
        print("  眼裂前方顶点 %d；其中眼区（eye/eyelid/eye_socket > 0.12）%d、外来者 %d"
              % (int(zone.sum()), int((zone & eye_like).sum()), int(foreign.sum())))
        entry = {"zone": int(zone.sum()), "eye_like": int((zone & eye_like).sum()),
                 "foreign": int(foreign.sum()), "foreign_detail": []}
        if foreign.any():
            # 这些外来者由谁驱动？看它们最强的那个骨
            for index in np.nonzero(foreign)[0][:12]:
                best = ("?", 0.0)
                for group in mesh.vertices[index].groups:
                    if group.weight > best[1]:
                        best = (mesh_obj.vertex_groups[group.group].name, group.weight)
                entry["foreign_detail"].append({
                    "v": int(index),
                    "pos": [round(float(v), 4) for v in co[index]],
                    "front_mm": round(float((center[1] - co[index, 1]) * 1000), 2),
                    "top_bone": best[0], "w": round(float(best[1]), 3),
                    "eye_w": round(float(eye_weight[side][index]), 3),
                })
            front = [d["front_mm"] for d in entry["foreign_detail"]]
            print("  外来者前伸量：%s …（最靠前 %.2fmm）" % (
                [round(v, 2) for v in front[:6]], max(front)))
            print("  前 3 个外来者的主控骨：%s" % (
                [(d["top_bone"], d["w"], d["eye_w"]) for d in entry["foreign_detail"][:3]]))
        report["eyes"][side] = entry
    if want_json:
        print("EYE_FOREIGN_JSON " + json.dumps(report, ensure_ascii=False))
    print("EYE_FOREIGN_OK")


main()
