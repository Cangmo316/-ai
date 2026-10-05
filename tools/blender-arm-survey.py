#!/usr/bin/env python3
"""
比邻AI · 手臂/手部锚点勘察（为"招手"骨骼链找位置）

用法：
    blender --background <资产.blend> --python tools/blender-env.py \
        --python tools/blender-arm-survey.py -- [--json]

做法：把网格按 z 分层，逐层看 x 方向的横向跨度——
躯干是连续的宽体，手臂是**从躯干向两侧伸出的细长部分**。
在"肩线到腰线"这一段里，找每个 z 层最外侧的连通横段，估计：
  · 肩关节（手臂与躯干的分界）位置
  · 肘部（横向跨度收细处）
  · 手腕/手（最外端）
"""

import json
import sys

import bpy
import numpy as np


def main():
    want_json = "--json" in sys.argv
    obj = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
    count = len(obj.data.vertices)
    co = np.empty(count * 3, dtype=np.float64)
    obj.data.vertices.foreach_get("co", co)
    co = co.reshape(count, 3)
    zmin, zmax = float(co[:, 2].min()), float(co[:, 2].max())
    height = zmax - zmin
    print("=" * 92)
    print("手臂锚点勘察 : %s （%d 顶点，身高 %.4f）" % (obj.name, count, height))

    # 逐 z 层统计：总横向跨度、以及"最外 8% 顶点"的位置（手臂候选）
    layers = 40
    report = {"height": round(height, 4), "layers": []}
    print("  %-8s%-10s%-12s%-12s" % ("z", "层顶点", "x 跨度", "最外缘 |x|"))
    for index in range(layers):
        lo = zmin + height * index / layers
        hi = zmin + height * (index + 1) / layers
        cell = (co[:, 2] >= lo) & (co[:, 2] < hi)
        if cell.sum() < 20:
            continue
        xs = co[cell, 0]
        span = float(xs.max() - xs.min())
        outer = float(max(abs(xs.min()), abs(xs.max())))
        report["layers"].append({"z": round((lo + hi) / 2, 4), "n": int(cell.sum()),
                                 "span": round(span, 4), "outer": round(outer, 4)})
        if index % 2 == 0:
            print("  %-8.3f%-10d%-12.3f%-12.3f" % ((lo + hi) / 2, int(cell.sum()), span, outer))

    # 手臂判定：z 在"头底以下 ~ 身高 55%"区间内，取每层最外侧的一簇
    band = (co[:, 2] > zmin + height * 0.45) & (co[:, 2] < zmin + height * 0.78)
    if band.sum() > 100:
        band_co = co[band]
        print("\n  候选手臂带（z %.3f~%.3f，%d 顶点）：" % (
            zmin + height * 0.45, zmin + height * 0.78, int(band.sum())))
        for side, sign in (("L", 1.0), ("R", -1.0)):
            sel = band_co[sign * band_co[:, 0] > 0.10]
            if len(sel) < 20:
                print("    %s：外伸部分顶点太少（%d）" % (side, len(sel)))
                continue
            print("    %s：%d 顶点  x[%.3f,%.3f] y[%.3f,%.3f] z[%.3f,%.3f]" % (
                side, len(sel), sel[:, 0].min(), sel[:, 0].max(),
                sel[:, 1].min(), sel[:, 1].max(), sel[:, 2].min(), sel[:, 2].max()))
            # 取最外 25% 作为"手"的位置
            order = np.argsort(sign * sel[:, 0])[::-1]
            hand = sel[order[: max(1, len(order) // 4)]]
            print("         手部候选（最外 25%%）：中心 %s 尺寸 x%.3f y%.3f z%.3f" % (
                np.round(hand.mean(axis=0), 4).tolist(),
                hand[:, 0].max() - hand[:, 0].min(),
                hand[:, 1].max() - hand[:, 1].min(),
                hand[:, 2].max() - hand[:, 2].min()))
            report.setdefault("arms", {})[side] = {
                "outer_center": [round(float(v), 4) for v in hand.mean(axis=0)],
                "bbox": {"x": [round(float(sel[:, 0].min()), 4), round(float(sel[:, 0].max()), 4)],
                         "y": [round(float(sel[:, 1].min()), 4), round(float(sel[:, 1].max()), 4)],
                         "z": [round(float(sel[:, 2].min()), 4), round(float(sel[:, 2].max()), 4)]},
            }
    if want_json:
        print("ARM_JSON " + json.dumps(report, ensure_ascii=False))
    print("ARM_SURVEY_OK")


main()
