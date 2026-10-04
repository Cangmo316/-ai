#!/usr/bin/env python3
"""
比邻AI · 唇缝几何手术（切开折叠脊，让嘴能真正张开）

用法：
    blender --background <无形态键的资产.blend> \
        --python tools/blender-env.py \
        --python tools/blender-lip-surgery.py -- --out <输出.blend> \
            [--angle 50] [--gap-mm 0.3] [--report]

**为什么必须切开**（实测结论，见任务笔记 §8.27）：
  · 唇缝 **0 对重合顶点**——它不是"两片贴合"，而是**共享顶点的折叠脊**（58 个缝脊顶点）；
  · 于是下颌旋转时上下唇在缝处**被同一张面片连着一起走**，中线开口反而越来越小：
    下颌 0° → 1.01mm、8° → 0.38mm、14° → 0.09mm（实测，随角度单调缩小）；
  · 解析唇形场也救不了：缝是连续的，任何让下唇下移的场都会把缝处拉成 2× 以上的拉伸。

做法：
  1. **先删形态键**（Blender 的 EdgeSplit 不能应用到带形态键的网格上，会报错）
     —— 形态键随后由 `blender-morph-build.py` / `blender-morph-shape-build.py` 重建；
  2. 用 EdgeSplit 按夹角把**锐边**分离（唇缝是全网格最锐的脊）→ 上下唇成为两条独立边界；
  3. 把"下唇侧的新边界"沿 -Z 轻推 `--gap-mm`，避免静止时又贴回去；
  4. 顶点组与 UV 由 Blender 自动保留/复制，权重不变。

⚠️ 必须在**权重之前**的资产上跑（`rig_female_60k.blend`），因为切开改变了顶点集合；
   之后的顺序仍是 权重 → 形态键 → 口内几何 → 导出。
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


def main():
    out = arg_value("--out")
    angle = float(arg_value("--angle", "50"))
    gap_mm = float(arg_value("--gap-mm", "0.3"))
    want_report = has_flag("--report")

    mesh_obj = max((o for o in bpy.data.objects if o.type == "MESH"),
                   key=lambda o: len(o.data.vertices))
    mesh = mesh_obj.data
    before = {"verts": len(mesh.vertices), "polys": len(mesh.polygons),
              "shape_keys": (len(mesh.shape_keys.key_blocks) - 1) if mesh.shape_keys else 0}
    print("=" * 96)
    print("唇缝几何手术 : " + bpy.data.filepath)
    print(f"  输入 {before['verts']} 顶点 / {before['polys']} 面 / 形态键 {before['shape_keys']}")

    # ── 1) 删形态键（EdgeSplit 的前置条件）──
    if mesh.shape_keys is not None:
        bpy.context.view_layer.objects.active = mesh_obj
        mesh_obj.select_set(True)
        bpy.ops.object.shape_key_remove(all=True)
        print("  已删除形态键（稍后由形态键脚本重建）")
    mesh_obj.select_set(False)

    # ── 2) EdgeSplit 切开锐边 ──
    modifier = mesh_obj.modifiers.new("LipSplit", "EDGE_SPLIT")
    modifier.split_angle = np.radians(angle)
    modifier.use_edge_angle = True
    modifier.use_edge_sharp = False
    bpy.context.view_layer.objects.active = mesh_obj
    mesh_obj.select_set(True)
    result = bpy.ops.object.modifier_apply(modifier=modifier.name)
    mesh_obj.select_set(False)
    mesh = mesh_obj.data
    after = {"verts": len(mesh.vertices), "polys": len(mesh.polygons)}
    print(f"  EdgeSplit({angle:.0f}°) → {result}；顶点 {before['verts']} → {after['verts']}"
          f"（新增 {after['verts'] - before['verts']} 个复制顶点）")

    # ── 3) 下唇侧新边界轻推，避免静止时贴回 ──
    count = len(mesh.vertices)
    co = np.empty(count * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(count, 3)
    # 嘴区 + 位于缝下沿 + 是"边界顶点"（只有一侧有面）的，判为下唇新边界
    from collections import defaultdict
    face_count = defaultdict(int)
    for poly in mesh.polygons:
        for index in poly.vertices:
            face_count[int(index)] += 1
    # 边界顶点：面数明显偏少的（复制出来的新顶点面数会比内部少）
    zone = (np.abs(co[:, 0]) < 0.030) & (co[:, 1] < -0.065) \
        & (co[:, 2] > 1.020) & (co[:, 2] < 1.045)
    seam = float(np.median(co[zone, 2])) if zone.any() else 1.030
    lower_new = [v for v in range(count)
                 if zone[v] and co[v, 2] < seam and face_count[v] <= 3]
    pushed = 0
    if lower_new:
        delta = gap_mm / 1000.0
        new_co = co.copy()
        new_co[lower_new, 2] -= delta
        mesh.vertices.foreach_set("co", new_co.reshape(-1).astype(np.float64))
        mesh.update()
        pushed = len(lower_new)
    print(f"  下唇新边界顶点 {pushed} 个 → 沿 -Z 推开 {gap_mm}mm")

    report = {"file": bpy.data.filepath, "angle": angle, "gap_mm": gap_mm,
              "before": before, "after": after, "pushed": pushed,
              "split_added": after["verts"] - before["verts"]}
    print(f"  结果：{after['verts']} 顶点 / {after['polys']} 面；顶点组 {len(mesh_obj.vertex_groups)}")

    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("LIP_SURGERY_OK 已保存 " + out)
    if want_report:
        print("LIP_SURGERY_JSON " + json.dumps(report, ensure_ascii=False))


main()
