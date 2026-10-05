#!/usr/bin/env python3
"""
比邻AI · 通用面部 landmark 实测（按网格自身特征，不套用别的角色）

用法：
    blender --background <Z-up 资产.blend> --python tools/blender-env.py \
        --python tools/blender-face-landmarks.py -- [--json]

判据（都对"正面朝 −Y、+Z 向上"的网格成立，与美术风格无关）：
  · **头顶/下巴**：|x|<3mm 中线上的 z 极值
  · **鼻尖**：中线上（|x|<3mm）**y 最小**（最靠前）的那个点
  · **眼位**：鼻尖上方一段内、左右两侧 y 的**局部极小**（眼窝比周围眉/颧都靠后）
  · **嘴**：鼻尖下方一段内、中线附近"红度最高"的一圈（用 albedo 的红度定位，卡通脸也有效）
  · **耳根**：|x| 最大且 z 在眼位附近的一层
"""
import json
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


def sample_albedo(obj, co, size=1024):
    """把每个顶点的 albedo 采样出来（红度 = R - B），用于找嘴唇。"""
    node_tree = obj.data.materials[0].node_tree if obj.data.materials else None
    image = None
    if node_tree:
        image = next((n.image for n in node_tree.nodes if n.type == "TEX_IMAGE" and n.image), None)
    if image is None or not obj.data.uv_layers.active:
        return None
    working = image.copy()
    working.scale(size, size)
    pixels = np.empty(size * size * 4, dtype=np.float32)
    working.pixels.foreach_get(pixels)
    rgb = pixels.reshape(size, size, 4)[:, :, :3]
    uvs = np.empty(len(obj.data.loops) * 2, dtype=np.float32)
    obj.data.uv_layers.active.data.foreach_get("uv", uvs)
    uvs = uvs.reshape(-1, 2)
    vindex = np.empty(len(obj.data.loops), dtype=np.int32)
    obj.data.loops.foreach_get("vertex_index", vindex)
    uniq, first = np.unique(vindex, return_index=True)
    vertex_uv = np.zeros((len(obj.data.vertices), 2), dtype=np.float32)
    vertex_uv[uniq] = uvs[first]
    xs = np.clip((vertex_uv[:, 0] % 1.0) * (size - 1), 0, size - 1).astype(np.int32)
    ys = np.clip((vertex_uv[:, 1] % 1.0) * (size - 1), 0, size - 1).astype(np.int32)
    sampled = rgb[ys, xs]
    bpy.data.images.remove(working)
    return sampled


def main():
    want_json = "--json" in sys.argv
    obj = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
    count = len(obj.data.vertices)
    co = np.empty(count * 3, dtype=np.float64)
    obj.data.vertices.foreach_get("co", co)
    co = co.reshape(count, 3)
    print("=" * 92)
    print("面部 landmark 实测 : %s（%d 顶点）" % (obj.name, count))

    midline = np.abs(co[:, 0]) < 0.004
    zs = co[midline, 2]
    top, bottom = float(zs.max()), float(zs.min())
    height = top - bottom

    # 鼻尖：中线上最靠前（y 最小）
    front_vertex = np.argmin(co[midline, 1])
    nose_tip = co[midline][front_vertex]
    print("  中线 z 范围 %.4f~%.4f（高 %.4f）；鼻尖（中线上最靠前）%s" % (
        bottom, top, height, np.round(nose_tip, 4).tolist()))

    # 眼窝：鼻尖上方 0.8~1.6 倍"眼距半"内，找左右两侧 y 的局部极小
    # 先用"|x| 在鼻尖附近、z 在鼻尖上方"的带，统计每侧 y 最小处
    for label, lo_frac, hi_frac in (("眼位", 0.010, 0.040), ("眉位", 0.040, 0.062)):
        band = (co[:, 2] > nose_tip[2] + lo_frac) & (co[:, 2] < nose_tip[2] + hi_frac) \
            & (np.abs(co[:, 0]) > 0.008) & (np.abs(co[:, 0]) < 0.075)
        if band.sum() < 30:
            print("  %s：带内顶点太少（%d）" % (label, int(band.sum())))
            continue
        for side, sign in (("L", 1.0), ("R", -1.0)):
            cell = band & (sign * co[:, 0] > 0)
            if cell.sum() < 10:
                continue
            # 取该侧最靠前的一簇的形心（眼窝底/眉峰都在最前缘附近）
            ys = co[cell, 1]
            front_mask = ys < np.percentile(ys, 12)
            sel = co[cell][front_mask]
            center = sel.mean(axis=0)
            print("  %s %s：%d 顶点 → 形心 %s（z 范围 %.4f~%.4f）" % (
                label, side, int(cell.sum()), np.round(center, 4).tolist(),
                sel[:, 2].min(), sel[:, 2].max()))

    # 嘴：鼻尖下方，用 albedo 红度最高的顶点定位
    sampled = sample_albedo(obj, co)
    mouth = None
    if sampled is not None:
        redness = sampled[:, 0] - sampled[:, 2]
        below = (co[:, 2] < nose_tip[2] - 0.005) & (co[:, 2] > nose_tip[2] - 0.075) \
            & (np.abs(co[:, 0]) < 0.06) & (co[:, 1] < -0.05)
        if below.sum() > 50:
            values = redness[below]
            threshold = np.percentile(values, 92)
            lip = below & (redness >= threshold)
            if lip.sum() > 20:
                selected = co[lip]
                mouth = selected.mean(axis=0)
                print("  嘴（红度 >p92=%.3f）：%d 顶点 → 中心 %s  x[%.4f,%.4f] z[%.4f,%.4f] y 最前 %.4f" % (
                    threshold, int(lip.sum()), np.round(mouth, 4).tolist(),
                    selected[:, 0].min(), selected[:, 0].max(),
                    selected[:, 2].min(), selected[:, 2].max(), selected[:, 1].min()))
    if mouth is None:
        print("  ⚠️ 嘴未定位（贴图红度不可用）")

    # 耳根：|x| 最大、z 在眼位附近
    ear_band = (co[:, 2] > nose_tip[2]) & (co[:, 2] < nose_tip[2] + 0.05) & (co[:, 1] > -0.02)
    if ear_band.sum() > 20:
        outer = co[ear_band]
        ear_x = float(max(abs(outer[:, 0].max()), abs(outer[:, 0].min())))
        print("  耳根 |x| 最大 %.4f（z 在鼻尖上方 0~0.05 带内）" % ear_x)

    if want_json:
        print("LANDMARK_JSON " + json.dumps({
            "top": round(top, 4), "bottom": round(bottom, 4), "height": round(height, 4),
            "nose_tip": [round(float(v), 4) for v in nose_tip],
            "mouth": [round(float(v), 4) for v in mouth] if mouth is not None else None,
        }, ensure_ascii=False))
    print("LANDMARK_OK")


main()
