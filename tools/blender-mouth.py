#!/usr/bin/env python3
"""
比邻AI · 口内几何（mouth_cavity / teeth / tongue）

用法：
    blender --background <资产.blend> \
        --python tools/blender-env.py \
        --python tools/blender-mouth.py -- --out <输出.blend> [--report]

为什么需要它（两条实测结论，见任务笔记 §8.14 / §8.16）：
  1. v2 的 `node_0` 在口内**没有任何内腔**（嘴部 6141 面里朝口腔内的 **0** 个），
     jaw 一开就是"纸片口袋"，能看到唇内侧斜面；
  2. 端侧交付件里 `mouth_cavity` / `teeth` / `tongue` 是**独立网格**且带**同名 morph**，
     `tools/test-face-params.mjs` 有一条硬断言要求这三个网格存在并带 `shape_mouth_width_*`。

做法（解析式构造，不引入外部资产）：
  · 用唇缝（albedo 红度 + 唇区顶点）拟合**嘴裂椭圆**（中心、半宽、半高、法线方向）
  · 沿椭圆口环向内**放样**若干圈（每圈按椭圆缩放到喉咙深度 `--depth`），末端封盖
    → 得到一张"由口腔口到咽后壁"的连续内壁（上壁贴上腭、下壁贴舌下、两侧贴颊）
  · 牙齿：沿椭圆上部/下部各放一圈小方块（解析齿列，共 2×6 颗）
  · 舌头：口底一枚扁椭球
  · 权重：上半（z ≥ 缝）随 `head`、下半随 `jaw`，另给 `tongue` 网格绑 `tongue` 骨
  · 形态键：15 个 `vis_*` + `expr_surprise` + `shape_mouth_width_up/dn`
    （口型用"开口量缩放"实现：`vis_*` 让下壁随 jaw 一起下沉，上壁微升）

⚠️ 这是**解析造出来的**内腔，形状是"椭圆放样"而非解剖建模；
   它的目的是"张嘴不漏光、有合理的暗部与牙列"，不是医学正确。
"""

import json
import math
import os
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Vector

VIS_SILENCE = "vis_silence"
VIS_NAMES = ["vis_silence", "vis_AA", "vis_E", "vis_I", "vis_O", "vis_U", "vis_MBP",
             "vis_FV", "vis_L", "vis_TH", "vis_WQ", "vis_RR", "vis_SS", "vis_KK", "vis_NN"]
VIS_JAW_DEG = {"vis_silence": 0.0, "vis_AA": 14.0, "vis_E": 7.0, "vis_I": 4.0, "vis_O": 9.0,
               "vis_U": 5.0, "vis_MBP": 0.0, "vis_FV": 2.0, "vis_L": 8.0, "vis_TH": 5.0,
               "vis_WQ": 4.0, "vis_RR": 6.0, "vis_SS": 3.0, "vis_KK": 6.0, "vis_NN": 3.0}


def arg_value(name, default=None):
    args = sys.argv
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return default


def has_flag(name):
    return name in sys.argv


def head_mesh():
    return max((o for o in bpy.data.objects if o.type == "MESH"),
               key=lambda o: len(o.data.vertices), default=None)


def smoothstep(value):
    value = np.clip(value, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


def fit_mouth_ellipse(mesh_obj):
    """用"唇红（albedo 红度）+ 唇区顶点"拟合嘴裂椭圆"""
    mesh = mesh_obj.data
    count = len(mesh.vertices)
    co = np.empty(count * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(count, 3)
    material = mesh.materials[0]
    image = next((n.image for n in material.node_tree.nodes
                  if n.type == "TEX_IMAGE" and n.image is not None), None)
    redness = np.zeros(count)
    if image is not None:
        sample = 1024
        working = image.copy()
        working.scale(sample, sample)
        pixels = np.empty(sample * sample * 4, dtype=np.float32)
        working.pixels.foreach_get(pixels)
        rgb = pixels.reshape(sample, sample, 4)[:, :, :3]
        uv_layer = mesh.uv_layers.active
        loop_uvs = np.empty(len(mesh.loops) * 2, dtype=np.float32)
        uv_layer.data.foreach_get("uv", loop_uvs)
        loop_uvs = loop_uvs.reshape(-1, 2)
        loops_vertex = np.empty(len(mesh.loops), dtype=np.int32)
        mesh.loops.foreach_get("vertex_index", loops_vertex)
        uniq, first = np.unique(loops_vertex, return_index=True)
        vertex_uv = np.zeros((count, 2), dtype=np.float32)
        vertex_uv[uniq] = loop_uvs[first]
        px = np.clip((vertex_uv[:, 0] % 1.0) * (sample - 1), 0, sample - 1).astype(np.int32)
        py = np.clip((vertex_uv[:, 1] % 1.0) * (sample - 1), 0, sample - 1).astype(np.int32)
        redness = rgb[py, px, 0] - rgb[py, px, 2]
        bpy.data.images.remove(working)
    zone = (np.abs(co[:, 0]) < 0.035) & (co[:, 1] < -0.062) \
        & (co[:, 2] > 1.012) & (co[:, 2] < 1.048)
    lip = zone & (redness > 0.25)
    if lip.sum() < 10:
        lip = zone
    pts = co[lip]
    center = np.array([float(np.median(pts[:, 0])), float(pts[:, 1].min() + 0.004),
                       float(np.median(pts[:, 2]))])
    half_width = float(np.percentile(np.abs(pts[:, 0]), 97))
    half_height = float((np.percentile(pts[:, 2], 97) - np.percentile(pts[:, 2], 3)) / 2.0)
    # ⚠️ 口环必须**退到唇面之后**，否则内壁的前缘会从人中/下巴戳出来
    #    （第一版按唇最前点放，渲染里在人中处看到一圈发亮的环 —— 见 §8.21）。
    #    唇面本身是双层的（外层唇红 + 内层贴合壳），这里退 3mm 进头内。
    seat_y = float(pts[:, 1].min() + 0.0035)
    # 唇线（每个 x 处的唇最前 y）：口环要沿它起伏，否则正中会从唇面戳出来
    line = {}
    for x0 in np.arange(-0.030, 0.0305, 0.002):
        cell = zone & (np.abs(co[:, 0] - x0) < 0.002)
        if cell.sum() >= 3:
            line[round(float(x0), 4)] = float(co[cell, 1].min())
    xs = np.array(sorted(line))
    ys = np.array([line[x] for x in xs])
    return center, half_width, half_height, co, redness, seat_y, (xs, ys)


def build_cavity_mesh(center, half_width, half_height, head_co=None, rings=6, depth=0.045,
                      segments=24, opening_half_height=0.0012, seat_offset=0.0015):
    """沿嘴裂椭圆向内放样成口腔内壁（含末端封盖）

    ⚠️ 两个实测踩过的坑（见任务笔记 §8.21）：
      1. **口环要按"嘴裂开缝"尺寸**，不能按唇高：v2 唇缝只有 ~1mm 高、唇红带 10mm 高，
         按唇高做口环会让内壁上弧从上唇之上戳出来。
      2. **口环必须沿唇线起伏**：唇线 y 在嘴角是 −0.0770、在正中只有 −0.0736（差 3.4mm），
         用一个平面 y 放口环，正中那圈就会从唇面**戳出 3.4mm**（实测 13 个顶点戳出、最多 4.47mm）。
         现在按每个顶点的 x 查唇线 y（`lip_line` 是 (x, y) 折线），再往头内退 `seat_offset`。
    """
    bm = bmesh.new()

    def front_y(x, z):
        if head_co is None:
            return None
        near = head_co[(np.abs(head_co[:, 0] - x) < 0.0015)
                       & (np.abs(head_co[:, 2] - z) < 0.0015)]
        if len(near) == 0:
            return None
        return float(near[:, 1].min())

    layers = []
    for ring in range(rings + 1):
        t = ring / rings
        if t <= 0.25:
            blend = t / 0.25
            height = opening_half_height + (half_height - opening_half_height) * blend
            width = half_width * (0.75 + 0.25 * blend)
        else:
            scale = 1.0 - 0.45 * ((t - 0.25) / 0.75)
            width = half_width * scale
            height = half_height * scale
        verts = []
        for index in range(segments):
            angle = 2.0 * math.pi * index / segments
            x = center[0] + width * math.cos(angle)
            z = center[2] + height * math.sin(angle)
            if ring == 0:
                # 口环逐顶点贴着嘴面：查"(x,z) 附近 1.5mm 的最前表面 y"再退进头内
                surface = front_y(x, z)
                y = (surface if surface is not None else center[1]) + seat_offset
            else:
                y = center[1] + seat_offset + depth * t
            verts.append(bm.verts.new((x, y, z)))
        layers.append(verts)
    bm.verts.ensure_lookup_table()
    for ring in range(rings):
        a, b = layers[ring], layers[ring + 1]
        for index in range(segments):
            nxt = (index + 1) % segments
            bm.faces.new((a[index], a[nxt], b[nxt], b[index]))
    # 末端封盖
    bm.faces.new(list(reversed(layers[-1])))
    mesh = bpy.data.meshes.new("mouth_cavity_mesh")
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new("mouth_cavity", mesh)
    bpy.context.collection.objects.link(obj)
    return obj, layers


def build_teeth(center, half_width, half_height, upper=True, count=6, depth=0.016):
    """解析齿列：沿椭圆上（或下）缘放一排小方块"""
    bm = bmesh.new()
    teeth = []
    for index in range(count):
        t = (index + 0.5) / count
        angle = math.pi * (0.15 + 0.7 * t) if upper else math.pi * (1.15 + 0.7 * t)
        x = center[0] + half_width * 0.85 * math.cos(angle)
        z = center[2] + half_height * 0.80 * math.sin(angle)
        y = center[1] + depth
        size_x, size_z = half_width * 0.075, half_height * 0.22
        verts = []
        for dx, dy, dz in ((-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
                           (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)):
            verts.append(bm.verts.new((x + dx * size_x, y + dy * 0.004, z + dz * size_z)))
        faces = ((0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2),
                 (2, 6, 7, 3), (3, 7, 4, 0))
        for face in faces:
            bm.faces.new([verts[i] for i in face])
        teeth.append((x, y, z, upper))
    mesh = bpy.data.meshes.new("teeth_mesh")
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new("teeth", mesh)
    bpy.context.collection.objects.link(obj)
    return obj, teeth


def build_tongue(center, half_width, half_height, depth=0.020):
    """舌头：口底一枚扁椭球"""
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=12, v_segments=8, radius=1.0)
    for vert in bm.verts:
        vert.co.x = center[0] + vert.co.x * half_width * 0.55
        vert.co.y = center[1] + depth + vert.co.y * 0.014
        vert.co.z = center[2] - half_height * 0.35 + vert.co.z * half_height * 0.35
    mesh = bpy.data.meshes.new("tongue_mesh")
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new("tongue", mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def assign_weights(obj, head_z, jaw_bone_z=None):
    """口腔内壁分带权重：上半随 head、下半随 jaw（让下壁随下颌一起沉）"""
    mesh = obj.data
    head_group = obj.vertex_groups.new(name="head")
    jaw_group = obj.vertex_groups.new(name="jaw")
    for vert in mesh.vertices:
        above = smoothstep((vert.co.z - head_z) / 0.006)
        if above > 1e-4:
            head_group.add([vert.index], float(above), "REPLACE")
        if above < 1.0 - 1e-4:
            jaw_group.add([vert.index], float(1.0 - above), "REPLACE")


def main():
    out = arg_value("--out")
    depth = float(arg_value("--depth", "0.045"))
    want_report = has_flag("--report")

    mesh_obj = head_mesh()
    if mesh_obj is None:
        print("MOUTH_FAIL 找不到主网格")
        return
    center, half_width, half_height, co, redness, seat_y, lip_line = fit_mouth_ellipse(mesh_obj)
    center = np.array([center[0], seat_y, center[2]])
    print("=" * 96)
    print("口内几何构建 : " + bpy.data.filepath)
    print(f"  嘴裂椭圆：中心 [{center[0]:.4f}, {center[1]:.4f}, {center[2]:.4f}]  "
          f"半宽 {half_width * 1000:.2f}mm  半高 {half_height * 1000:.2f}mm  深度 {depth * 1000:.0f}mm")

    # 清掉同名旧对象（幂等）
    for name in ("mouth_cavity", "teeth", "tongue"):
        old = bpy.data.objects.get(name)
        if old is not None:
            bpy.data.objects.remove(old, do_unlink=True)

    cavity, layers = build_cavity_mesh(center, half_width, half_height, head_co=co, depth=depth)
    assign_weights(cavity, center[2])
    teeth_up, _ = build_teeth(center, half_width, half_height, upper=True)
    teeth_dn, _ = build_teeth(center, half_width, half_height, upper=False)
    # 上下齿合并成一个 teeth 网格
    bm = bmesh.new()
    bm.from_mesh(teeth_up.data)
    bm.from_mesh(teeth_dn.data)
    merged = bpy.data.meshes.new("teeth_mesh")
    bm.to_mesh(merged)
    bm.free()
    bpy.data.objects.remove(teeth_up, do_unlink=True)
    bpy.data.objects.remove(teeth_dn, do_unlink=True)
    teeth = bpy.data.objects.new("teeth", merged)
    bpy.context.collection.objects.link(teeth)
    assign_weights(teeth, center[2])
    tongue = build_tongue(center, half_width, half_height)
    tongue_group = tongue.vertex_groups.new(name="tongue")
    tongue_group.add([v.index for v in tongue.data.vertices], 1.0, "REPLACE")

    report = {"file": bpy.data.filepath, "center": [round(float(v), 4) for v in center],
              "half_width_mm": round(half_width * 1000, 2),
              "half_height_mm": round(half_height * 1000, 2),
              "depth_mm": round(depth * 1000, 1), "meshes": {}}
    for obj in (cavity, teeth, tongue):
        obj.data.calc_loop_triangles()
        report["meshes"][obj.name] = {"verts": len(obj.data.vertices),
                                      "tris": len(obj.data.loop_triangles),
                                      "vgroups": [g.name for g in obj.vertex_groups]}

    # ── 形态键：15 个 vis_* + expr_surprise + shape_mouth_width_up/dn ──
    def add_keys(obj, name_of_jaw_offset):
        """给口内网格加同名形态键：下壁随 jaw 下沉 = 开口量；宽度键做水平展缩"""
        obj.shape_key_add(name="Basis", from_mix=False)
        base = np.empty(len(obj.data.vertices) * 3, dtype=np.float64)
        obj.data.vertices.foreach_get("co", base)
        base = base.reshape(-1, 3)
        jaw_w = np.zeros(len(obj.data.vertices))
        group = obj.vertex_groups.get("jaw")
        if group is not None:
            for vert in obj.data.vertices:
                for element in vert.groups:
                    if element.group == group.index:
                        jaw_w[vert.index] = element.weight
                        break
        for name in VIS_NAMES + ["expr_surprise"]:
            degrees = VIS_JAW_DEG.get(name, 8.0)
            drop = name_of_jaw_offset(degrees)
            delta = np.zeros_like(base)
            delta[:, 2] = -drop * jaw_w
            block = obj.shape_key_add(name=name, from_mix=False)
            positions = base + delta
            block.data.foreach_set("co", positions.reshape(-1).astype(np.float32))
            block.value = 0.0
        for suffix, sign in (("up", 1.0), ("dn", -1.0)):
            delta = np.zeros_like(base)
            delta[:, 0] = sign * 0.0012 * np.sign(base[:, 0])
            block = obj.shape_key_add(name="shape_mouth_width_%s" % suffix, from_mix=False)
            positions = base + delta
            block.data.foreach_set("co", positions.reshape(-1).astype(np.float32))
            block.value = 0.0

    for obj in (cavity, teeth, tongue):
        add_keys(obj, lambda degrees: math.radians(degrees) * 0.030)
        for block in obj.data.shape_keys.key_blocks:
            block.value = 0.0
        names = [b.name for b in obj.data.shape_keys.key_blocks]
        report["meshes"][obj.name]["morphs"] = len(names) - 1
        report["meshes"][obj.name]["vis_expr"] = len([n for n in names if n.startswith(("vis_", "expr_"))])

    print("")
    print(f"  {'网格':<16}{'顶点':>7}{'三角面':>8}{'顶点组':>22}{'形态键':>8}")
    for name, item in report["meshes"].items():
        print(f"  {name:<16}{item['verts']:>7}{item['tris']:>8}"
              f"{','.join(item['vgroups']):>22}{item['morphs']:>8}")

    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("MOUTH_OK 已保存 " + out)
    if want_report:
        print("MOUTH_JSON " + json.dumps(report, ensure_ascii=False))


main()
