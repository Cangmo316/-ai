#!/usr/bin/env python3
"""
比邻AI · 眼窝几何探测 v4（径向剖面：碗底 → 睑缘脊 → 周围脸）

用法：
    blender --background <工作.blend> --python tools/blender-eye-probe.py -- [--theta 24]

背景（前几版为什么都不行）：
  v1：「搜索盒内最靠前的点」当睑缘 → 取到**刘海发丝**（Y=-0.0886 vs 眼区皮肤 -0.059）
      → 球被推到脸前 5mm
  v2：按"皮肤壳"过滤 → 整个网格只有 1 个连通分量（头发与皮肤焊在一起），没用
  v3：二次曲面起伏图 → 把鼻根/颧骨的曲率带进参考面，误判成"眼区前凸 1.5mm"
      （cavity 宏观渲染证明真相是「睑缘环 + 内部凹碗」的完整眼窝）

v4 的做法：**从碗底沿 24 个方向向外扫射线**，记录 Y(r)：
      碗底(最靠后) → 睑缘脊(最靠前) → 周围脸(后退)
  每条方向的 argmin(Y) 就是**睑缘脊**，据此得到：
      · 睑缘环半径 r(θ)（= 眼裂的开口大小）
      · 睑缘比碗底靠前多少（= 睑缘脊高度）
      · 睑缘环相对眼位中心的 Y（= 球心该放多深）
"""

import json
import math
import sys

import bpy
from mathutils import Vector

EYE_L = (0.0349, -0.0584, 1.0701)
EYE_R = (-0.0344, -0.0587, 1.0708)

R_MAX = 0.022
R_STEP = 0.0005


def arg_value(name, default=None):
    args = sys.argv
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return default


def head_mesh():
    return max((o for o in bpy.data.objects if o.type == "MESH"),
               key=lambda o: len(o.data.vertices), default=None)


def make_raycaster(obj):
    matrix = obj.matrix_world
    inverse = matrix.inverted()
    direction = (inverse.to_3x3() @ Vector((0, 1, 0))).normalized()
    normal_matrix = matrix.to_3x3().inverted().transposed()

    def cast(x, z):
        origin = inverse @ Vector((x, -0.30, z))
        ok, location, normal, _index = obj.ray_cast(origin, direction, distance=0.6)
        if not ok:
            return None
        world = matrix @ location
        world_normal = (normal_matrix @ normal).normalized()
        return world.y, world_normal.y

    return cast


def probe(obj, center, side, theta_count):
    cast = make_raycaster(obj)
    cx, cy, cz = center
    directions = []
    for k in range(theta_count):
        theta = 2 * math.pi * k / theta_count
        cosine, sine = math.cos(theta), math.sin(theta)
        profile = []
        r = 0.0
        while r <= R_MAX + 1e-9:
            x = cx + cosine * r
            z = cz + sine * r
            hit = cast(x, z)
            profile.append((r, hit[0] if hit else None, hit[1] if hit else None))
            r += R_STEP
        # 睑缘脊 = 该方向上最靠前的点（Y 最小）
        valid = [p for p in profile if p[1] is not None]
        if not valid:
            continue
        crest = min(valid, key=lambda p: p[1])
        floor = max(valid, key=lambda p: p[1])
        outer = valid[-1]
        # 第一个"从碗底往外开始后退"的转折（脊的内侧起点）
        crest_index = profile.index(crest)
        directions.append({
            "deg": round(math.degrees(theta), 1),
            "crest_r_mm": round(crest[0] * 1000, 2),
            "crest_y_mm": round((crest[1] - cy) * 1000, 2),
            "floor_y_mm": round((floor[1] - cy) * 1000, 2),
            "floor_r_mm": round(floor[0] * 1000, 2),
            "outer_y_mm": round((outer[1] - cy) * 1000, 2),
            "ridge_height_mm": round((floor[1] - crest[1]) * 1000, 2),
            "inner_wall_r_mm": round(profile[max(0, crest_index - 4)][0] * 1000, 2),
            "normal_y_at_center": round(profile[0][2], 3) if profile[0][2] is not None else None,
            "normal_y_at_crest": round(crest[2], 3) if crest[2] is not None else None,
            "profile_mm": [None if p[1] is None else round((p[1] - cy) * 1000, 1)
                           for p in profile],
        })

    crest_radii = [d["crest_r_mm"] for d in directions]
    ridge_heights = [d["ridge_height_mm"] for d in directions]
    crest_ys = [d["crest_y_mm"] for d in directions]
    return {
        "side": side,
        "center": [round(v, 5) for v in center],
        "directions": directions,
        "crest_r_mm": {
            "min": round(min(crest_radii), 2), "max": round(max(crest_radii), 2),
            "mean": round(sum(crest_radii) / len(crest_radii), 2),
            "horizontal": round(max(d["crest_r_mm"] for d in directions
                                    if abs(math.cos(math.radians(d["deg"]))) > 0.9), 2),
            "vertical": round(max(d["crest_r_mm"] for d in directions
                                  if abs(math.sin(math.radians(d["deg"]))) > 0.9), 2),
        },
        "ridge_height_mm": {
            "min": round(min(ridge_heights), 2), "max": round(max(ridge_heights), 2),
            "mean": round(sum(ridge_heights) / len(ridge_heights), 2),
        },
        "crest_y_mm": {
            "min": round(min(crest_ys), 2), "max": round(max(crest_ys), 2),
            "mean": round(sum(crest_ys) / len(crest_ys), 2),
        },
    }


def main():
    obj = head_mesh()
    if obj is None:
        print("EYE_PROBE_FAIL 没有网格")
        return
    theta_count = int(arg_value("--theta", "24"))
    report = {"file": bpy.data.filepath, "mesh": obj.name, "eyes": []}
    for side, center in (("L", EYE_L), ("R", EYE_R)):
        report["eyes"].append(probe(obj, center, side, theta_count))

    print("=" * 100)
    print("眼窝径向剖面（值 = 相对眼位中心的 Y 偏移 mm；越负越靠前）")
    print(f"文件 {bpy.data.filepath}")
    for eye in report["eyes"]:
        print("")
        print(f"--- [{eye['side']}] 眼位 {eye['center']} ---")
        print(f"    睑缘环半径: {eye['crest_r_mm']}  （水平 {eye['crest_r_mm']['horizontal']}mm / "
              f"垂直 {eye['crest_r_mm']['vertical']}mm）")
        print(f"    睑缘脊高度(相对碗底): {eye['ridge_height_mm']}")
        print(f"    睑缘脊 Y: {eye['crest_y_mm']}")
        print("     角度   脊r    脊Y   碗底Y  外圈Y  脊高   剖面(0→22mm，每0.5mm)")
        for d in eye["directions"]:
            profile = " ".join("  ." if v is None else f"{v:>3.0f}" for v in d["profile_mm"])
            print(f"     {d['deg']:>5}  {d['crest_r_mm']:>5} {d['crest_y_mm']:>6} "
                  f"{d['floor_y_mm']:>6} {d['outer_y_mm']:>6} {d['ridge_height_mm']:>6}   {profile}")
    slim = {"file": report["file"], "eyes": [
        {k: v for k, v in eye.items() if k != "directions"} for eye in report["eyes"]]}
    print("EYE_PROBE_JSON " + json.dumps(slim, ensure_ascii=False))


main()
