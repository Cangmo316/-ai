#!/usr/bin/env python3
"""
比邻AI · 交付期减面（第 4 步：999k tri → ≤60k tri）

用法：
    blender --background <输入.blend> \
        --python tools/blender-env.py \
        --python tools/blender-decimate.py -- --out <输出.blend> \
            [--target-tris 60000] [--report]

**顺序很重要**：本脚本作用在**权重之前的资产**（`eye_dome.blend`），
减面之后必须**重跑** `blender-rig-weights.py` 与 `blender-morph-build.py`：
  · 权重是逐顶点的，减面会改变顶点集合 → 旧权重作废；
  · 形态键存的是**绝对坐标**且逐顶点对齐 → 旧形态键一起作废（§8.6 已记录过这个坑）。

⚠️ 减面必须保住：
  1. **顶点组**（`jaw`/`head`/`lip_*`/`eye*`/`brow*`…）——重跑权重脚本时会覆盖，
     但**眼区穹顶的几何细节**不能丢（雕出来的眼球是 v2 的核心成果）；
  2. **UV 与材质**（否则贴图错位）；
  3. 眼、唇、眼睑这些"小尺度特征"的区域密度。

因此判据除了三角面数，还要量：
  · 眼区（`eye.L/R` 顶点组权重 > 0.1 的顶点）剩余顶点数
  · 唇区（嘴部包围盒内）剩余顶点数
  · 穹顶是否还在（眼球区顶点到穹顶球心的距离分布）
"""

import json
import os
import sys

import bpy
import numpy as np


def arg_value(name, default=None):
    args = sys.argv
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return default


def has_flag(name):
    return name in sys.argv


def mesh_object():
    return max((o for o in bpy.data.objects if o.type == "MESH"),
               key=lambda o: len(o.data.vertices), default=None)


def triangle_count(obj):
    obj.data.calc_loop_triangles()
    return len(obj.data.loop_triangles)


def region_stats(obj, label, mask):
    mesh = obj.data
    count = len(mesh.vertices)
    co = np.empty(count * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(count, 3)
    inside = mask(co)
    stats = {"label": label, "verts": int(inside.sum())}
    if inside.any():
        stats["bbox"] = [[round(float(co[inside, axis].min()), 4),
                          round(float(co[inside, axis].max()), 4)] for axis in range(3)]
    return stats


def feature_mask(co, pad=0.0):
    """"特征区"：嘴（含唇缝与口角）与眼（含穹顶与睑缘）

    为什么必须保护：均匀 collapse 会把嘴区从 3073 顶点砍到 221（实测），
    而口型 morph 全靠这一带的顶点——上一代交付件在同样 6 万面下，
    嘴唇光顶点组就有 777 个。所以减面必须**按区域分配**密度。
    """
    mouth = ((np.abs(co[:, 0]) < 0.045 + pad) & (co[:, 1] > -0.100 - pad)
             & (co[:, 1] < -0.040) & (co[:, 2] > 0.998 - pad) & (co[:, 2] < 1.055 + pad))
    eyes = ((np.abs(co[:, 0]) > 0.005) & (np.abs(co[:, 0]) < 0.052 + pad)
            & (co[:, 1] < -0.030) & (co[:, 2] > 1.045 - pad) & (co[:, 2] < 1.100 + pad))
    return mouth | eyes


def main():
    out = arg_value("--out")
    target = int(arg_value("--target-tris", "60000"))
    want_report = has_flag("--report")
    protect = not has_flag("--no-protect")
    factor = float(arg_value("--protect-factor", "1.0"))

    obj = mesh_object()
    if obj is None:
        print("DECIMATE_FAIL 找不到网格")
        return
    before_tris = triangle_count(obj)
    before_verts = len(obj.data.vertices)
    ratio = min(1.0, float(target) / max(1, before_tris))
    print("=" * 96)
    print("交付期减面 : " + bpy.data.filepath)
    print(f"  输入 {before_verts} 顶点 / {before_tris} 三角面 → 目标 {target} 三角面"
          f"（collapse ratio {ratio:.5f}）")
    print(f"  特征区保护：{'开' if protect else '关'}"
          f"{'' if not protect else f'（权重组 feature 系数 {factor}）'}")

    def mouth_mask(co):
        return ((np.abs(co[:, 0]) < 0.035) & (co[:, 1] > -0.095) & (co[:, 1] < -0.045)
                & (co[:, 2] > 1.000) & (co[:, 2] < 1.050))

    def eye_mask(co):
        return ((np.abs(co[:, 0]) > 0.010) & (np.abs(co[:, 0]) < 0.048)
                & (co[:, 1] < -0.035) & (co[:, 2] > 1.050) & (co[:, 2] < 1.095))

    before = {"tris": before_tris, "verts": before_verts,
              "mouth": region_stats(obj, "嘴区", mouth_mask),
              "eyes": region_stats(obj, "眼区", eye_mask),
              "uv_layers": len(obj.data.uv_layers),
              "vgroups": len(obj.vertex_groups),
              "materials": len(obj.data.materials)}

    weight_group = None
    if protect:
        co = np.empty(before_verts * 3, dtype=np.float64)
        obj.data.vertices.foreach_get("co", co)
        co = co.reshape(before_verts, 3)
        mask = feature_mask(co)
        group = obj.vertex_groups.new(name="feature")
        group.add(np.nonzero(mask)[0].tolist(), 1.0, "REPLACE")
        weight_group = group.name
        print(f"  特征区顶点 {int(mask.sum())} / {before_verts}"
              f"（{100.0 * mask.sum() / before_verts:.1f}%）")

    modifier = obj.modifiers.new("Decimate", "DECIMATE")
    modifier.decimate_type = "COLLAPSE"
    modifier.ratio = ratio
    modifier.use_collapse_triangulate = True
    try:
        modifier.use_symmetry = True
        modifier.symmetry_axis = "X"
    except AttributeError:
        pass
    try:
        modifier.delimit = {"UV", "MATERIAL", "SEAM", "SHARP"}
    except (AttributeError, TypeError):
        pass
    if weight_group:
        try:
            modifier.vertex_group = weight_group
            modifier.vertex_group_factor = factor
            modifier.invert_vertex_group = False
        except AttributeError:
            print("  ⚠️ 这个 Blender 版本的 Decimate 不支持顶点组权重，退回均匀减面")

    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    result = bpy.ops.object.modifier_apply(modifier=modifier.name)
    if "FINISHED" not in result:
        print(f"DECIMATE_FAIL modifier_apply 返回 {result}")
        return

    # 清掉临时权重组（避免它被当成骨骼顶点组导出）
    if weight_group and obj.vertex_groups.get(weight_group):
        obj.vertex_groups.remove(obj.vertex_groups[weight_group])

    after_tris = triangle_count(obj)
    after_verts = len(obj.data.vertices)
    after = {"tris": after_tris, "verts": after_verts,
             "mouth": region_stats(obj, "嘴区", mouth_mask),
             "eyes": region_stats(obj, "眼区", eye_mask),
             "uv_layers": len(obj.data.uv_layers),
             "vgroups": len(obj.vertex_groups),
             "materials": len(obj.data.materials)}

    print(f"  减面后 {after_verts} 顶点 / {after_tris} 三角面"
          f"（{100.0 * (1 - after_tris / max(1, before_tris)):.1f}% 折叠）")
    print(f"  UV 层 {before['uv_layers']} → {after['uv_layers']} / "
          f"顶点组 {before['vgroups']} → {after['vgroups']} / "
          f"材质 {before['materials']} → {after['materials']}")
    print(f"  嘴区顶点 {before['mouth']['verts']} → {after['mouth']['verts']}")
    print(f"  眼区顶点 {before['eyes']['verts']} → {after['eyes']['verts']}")
    verdict = []
    if after_tris > target * 1.15:
        verdict.append(f"⚠️ 三角面 {after_tris} 超过目标 {target} 的 15%")
    if after["uv_layers"] != before["uv_layers"]:
        verdict.append("⚠️ UV 层数变了")
    if after["vgroups"] != before["vgroups"]:
        verdict.append("⚠️ 顶点组数量变了")
    if after["mouth"]["verts"] < before["mouth"]["verts"] * 0.3:
        verdict.append("⚠️ 嘴区顶点掉了 >70%（口型会变粗）")
    if after["eyes"]["verts"] < before["eyes"]["verts"] * 0.3:
        verdict.append("⚠️ 眼区顶点掉了 >70%（穹顶会变粗）")
    for line in verdict:
        print("  " + line)
    if not verdict:
        print("  ✓ 减面质量检查通过")

    report = {"file": bpy.data.filepath, "before": before, "after": after,
              "target_tris": target, "ratio": round(ratio, 6),
              "warnings": verdict}
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("DECIMATE_OK 已保存 " + out)
    if want_report:
        print("DECIMATE_JSON " + json.dumps(report, ensure_ascii=False))


main()
