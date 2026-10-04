#!/usr/bin/env python3
"""
比邻AI · 独立眼球重建（给 v2 资产补回 v1 的"真眼球"）

用法：
    blender --background <v2资产.blend> --python tools/blender-env.py \
        --python tools/blender-eyeball-add.py -- --out <输出.blend> \
            [--radius-mm 8.5] [--iris <虹膜图.png>] [--report]

**为什么做**：参考图（`3D建模/04_preview/female_delivery_rest_face.png`，上一代 v1）
里眼睛是**鼓起的独立眼球**；v2 改走"雕穹顶 + 把虹膜画在 albedo 上"，
减面到 6 万后穹顶名存实亡——眼裂里只剩原始扫描的凹陷眼窝（44 个顶点、法线杂乱），
渲染起来"眼睛里一堆杂色"。这里按 v1 的实测参数把眼球补回来。

v1 实测参数（`tools/blender-eyeball-survey.py` 从 v1 .blend 量出来）：
  · 球心 = `eye.L` 骨枢轴（v2 已在 `blender-eye-dome.py` 里移到球心）
  · 半径 **8.5mm**（L）/ **8.63mm**（R），134 顶点 / 144 面
  · UV：整球 u/v 0~1；**虹膜占中央 u[0.125,0.875] v[0.125,0.875]**
  · 权重：**100% 绑到 `eye.L/eye.R`**（所以 gaze 转动眼球即可，不牵动皮肤）

做法：按球心生成 UV 球（半径/分段可调）→ 只保留**朝前的那半球**（后半藏在眼眶里，
省面数也避免 z-fighting）→ 权重全给 `eye.*` → 材质用虹膜图（整球 UV）。
"""

import json
import math
import os
import sys

import bmesh
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


UV_ZOOM = 1.62      # 虹膜图中央图案的放大系数（见 build_eyeball 里的说明）


def make_material(name, iris_image):
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name=name)
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    output.location = (420, 0)
    shader = tree.nodes.new("ShaderNodeBsdfPrincipled")
    shader.location = (120, 0)
    shader.inputs["Roughness"].default_value = 0.18      # 角膜湿润感
    shader.inputs["Metallic"].default_value = 0.0
    # 眼白偏灰的补救：给一点点自发光（实测 Workbench/EEVEE 下 sclera 会偏暗）
    if "Emission Color" in shader.inputs:
        shader.inputs["Emission Color"].default_value = (1.0, 0.99, 0.97, 1.0)
    if "Emission Strength" in shader.inputs:
        shader.inputs["Emission Strength"].default_value = float(arg_value("--emission", "0.10"))
    if "Specular IOR Level" in shader.inputs:
        shader.inputs["Specular IOR Level"].default_value = 0.6
    if "IOR" in shader.inputs:
        shader.inputs["IOR"].default_value = 1.45
    tree.links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    if iris_image is not None:
        texture = tree.nodes.new("ShaderNodeTexImage")
        texture.location = (-220, 0)
        texture.image = iris_image
        texture.interpolation = "Cubic"
        tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    return material


def build_eyeball(side, armature, radius, segments, rings, material):
    bone = armature.data.bones.get("eye.%s" % side)
    center = armature.matrix_world @ bone.matrix_local.translation
    mesh = bpy.data.meshes.new("eyeball_%s" % side)
    obj = bpy.data.objects.new("eyeball_%s" % side, mesh)
    bpy.context.scene.collection.objects.link(obj)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=rings, radius=radius)
    # 只留朝前的半球（脸朝 -Y）：删掉 y > 球心.y 的部分，再封口不需要——藏在眼眶里
    bmesh.ops.bisect_plane(
        bm,
        geom=list(bm.verts) + list(bm.edges) + list(bm.faces),
        plane_co=(0.0, 0.0, 0.0),
        plane_no=(0.0, 1.0, 0.0),
        clear_outer=True,      # 去掉 +Y 侧（后半）
        clear_inner=False,
    )
    bm.to_mesh(mesh)
    bm.free()
    obj.location = center
    # UV：Blender 的 UV 球是"整球铺满 0~1"。虹膜图的图案只占**中央一小块**，
    # 要让脸正前方那一块正好落在虹膜图案上，就得把 UV 往中心压：uv = (uv-0.5)*k+0.5。
    #
    # ⚠️ **k 不能太大、而且必须夹到 [0,1]**（本工具第二版的坑）：
    #    k=3.43 时 UV 变成 [-1.215, 2.215]，贴图默认 REPEAT → **平铺 3 次多**，
    #    渲染出来眼白是"灰格纹"（其实是贴图径向渐变被高频重复）。
    #    正解：夹到 [0,1]（球面近正视，投影失真很小），眼白自然取到贴图边上的纯白。
    uv_layer = mesh.uv_layers.active or mesh.uv_layers.new(name="UVMap")
    for loop in mesh.loops:
        u, v = uv_layer.data[loop.index].uv
        u = (u - 0.5) * UV_ZOOM + 0.5
        v = (v - 0.5) * UV_ZOOM + 0.5
        uv_layer.data[loop.index].uv = (min(max(u, 0.0), 1.0), min(max(v, 0.0), 1.0))
    # 权重：100% 给 eye.<side>
    group = obj.vertex_groups.new(name="eye.%s" % side)
    group.add([v.index for v in mesh.vertices], 1.0, "REPLACE")
    mesh.materials.append(material)
    # 骨架修改器（gaze 时随 eye 骨转）
    modifier = obj.modifiers.new("Armature", "ARMATURE")
    modifier.object = armature
    obj.parent = armature
    return obj, center


def main():
    out = arg_value("--out")
    radius_mm = float(arg_value("--radius-mm", "8.5"))
    iris_path = arg_value("--iris")
    global UV_ZOOM
    UV_ZOOM = float(arg_value("--uv-zoom", str(UV_ZOOM)))
    segments = int(arg_value("--segments", "16"))
    rings = int(arg_value("--rings", "10"))
    want_report = has_flag("--report")

    armature = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if armature is None:
        print("EYEBALL_FAIL 没有骨架")
        return
    head = bpy.data.objects.get("node_0") or max(
        (o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
    # 虹膜贴图：优先从 v1 资产里**搬运现成的 image datablock**（自带像素，最稳），
    # 其次按 --iris 路径加载；两条路都必须 **pack 进 .blend**，否则保存后像素丢失，
    # 渲染时显示为"缺失纹理"棋盘（本工具第一版就是这么错的）。
    iris_image = None
    source_blend = arg_value("--iris-from-blend")
    if source_blend and os.path.exists(source_blend):
        with bpy.data.libraries.load(source_blend, link=False) as (src, dst):
            candidates = [n for n in src.images if "iris" in n.lower()] or [
                n for n in src.images if "albedo" in n.lower() or "pbr" in n.lower()]
            dst.images = candidates[:1]
        iris_image = next((i for i in dst.images if i is not None), None)
        if iris_image is not None:
            print("  虹膜贴图（从 v1 资产搬运）：%s %s" % (iris_image.name, tuple(iris_image.size)))
    if iris_image is None and iris_path and os.path.exists(iris_path):
        iris_image = bpy.data.images.load(iris_path)
        print("  虹膜贴图（按路径加载）：" + iris_path)
    if iris_image is None:
        node_tree = head.data.materials[0].node_tree if head.data.materials else None
        if node_tree:
            iris_image = next((n.image for n in node_tree.nodes
                               if n.type == "TEX_IMAGE" and n.image), None)
            if iris_image is not None:
                print("  虹膜贴图（复用主材质 albedo）：" + iris_image.name)
    if iris_image is not None:
        try:
            if not iris_image.packed_file and iris_image.has_data:
                iris_image.pack()
        except Exception as error:
            print("  ⚠️ pack 失败：" + str(error))

    material = make_material("M_Eyeball_v2", iris_image)
    print("=" * 92)
    print("独立眼球重建 : " + bpy.data.filepath)
    print("  半径 %.2fmm / 分段 %d×%d / 只留朝前半球" % (radius_mm, segments, rings))
    report = {"file": bpy.data.filepath, "radius_mm": radius_mm, "eyeballs": []}
    for side in ("L", "R"):
        # 右眼在 v1 里略大（8.63 vs 8.51），这里按侧微调
        side_radius = radius_mm * (1.015 if side == "R" else 1.0)
        obj, center = build_eyeball(side, armature, side_radius / 1000.0,
                                    segments, rings, material)
        entry = {"side": side, "name": obj.name,
                 "center": [round(float(v), 5) for v in center],
                 "radius_mm": round(side_radius, 2),
                 "verts": len(obj.data.vertices), "polys": len(obj.data.polygons)}
        report["eyeballs"].append(entry)
        print("  eyeball_%s：球心 %s 半径 %.2fmm → %d 顶点 / %d 面（权重 100%% eye.%s）"
              % (side, entry["center"], side_radius, entry["verts"], entry["polys"], side))

    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("EYEBALL_OK 已保存 " + out)
    if want_report:
        print("EYEBALL_JSON " + json.dumps(report, ensure_ascii=False))


main()
