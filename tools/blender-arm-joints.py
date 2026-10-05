#!/usr/bin/env python3
"""
比邻AI · 手臂关节精确定位（肩 / 肘 / 腕，用于"招手"骨骼链）

用法：
    blender --background <Z-up 资产.blend> --python tools/blender-env.py \
        --python tools/blender-arm-joints.py -- [--arm-min-x 0.16] [--json]

做法：只取 x 超过 `--arm-min-x` 的顶点（=从躯干伸出去的手臂段），按 x 分层：
  · 每一层报 x 截面中心 (y,z)、该层的 y/z 尺寸（粗细）
  · **肩** = 手臂段最内侧那一层；**腕** = 最外侧那一层；
  · **肘** = 粗细局部最细处（或 x 跨度的中点，按实测回退）
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


def main():
    want_json = "--json" in sys.argv
    arm_min_x = float(arg_value("--arm-min-x", "0.16"))
    obj = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
    count = len(obj.data.vertices)
    co = np.empty(count * 3, dtype=np.float64)
    obj.data.vertices.foreach_get("co", co)
    co = co.reshape(count, 3)
    print("=" * 92)
    print("手臂关节定位 : %s（%d 顶点）  手臂段判据 |x| > %.3f" % (obj.name, count, arm_min_x))

    report = {}
    for side, sign in (("L", 1.0), ("R", -1.0)):
        sel = co[sign * co[:, 0] > arm_min_x]
        if len(sel) < 50:
            print("  %s：手臂段顶点太少（%d），跳过" % (side, len(sel)))
            continue
        xs = sign * sel[:, 0]                    # 用"离躯干距离"表示
        x0, x1 = float(xs.min()), float(xs.max())
        print("\n  ── %s 侧：手臂段 %d 顶点，离躯干 %.3f → %.3f（长 %.3f）" % (
            side, len(sel), x0, x1, x1 - x0))
        print("  %-9s%-8s%-18s%-16s%-14s" % ("离躯干", "层顶点", "截面中心(y,z)", "y 尺寸", "z 尺寸"))
        layers = 16
        rows = []
        for index in range(layers + 1):
            lo = x0 + (x1 - x0) * index / layers
            hi = x0 + (x1 - x0) * (index + 1) / layers if index < layers else x1 + 1e-6
            cell = (xs >= lo) & (xs < hi)
            if cell.sum() < 8:
                continue
            part = sel[cell]
            center = part.mean(axis=0)
            ys = part[:, 1].max() - part[:, 1].min()
            zs = part[:, 2].max() - part[:, 2].min()
            rows.append({"t": round((lo + hi) / 2, 4), "n": int(cell.sum()),
                         "center": [round(float(v), 4) for v in center],
                         "y": round(float(ys), 4), "z": round(float(zs), 4),
                         "thick": round(float((ys + zs) / 2), 4)})
            print("  %-9.3f%-8d%-18s%-16.3f%-14.3f" % (
                (lo + hi) / 2, int(cell.sum()), np.round(center, 3).tolist(), ys, zs))
        if not rows:
            continue
        # 肩 = 最内侧一层；腕 = 最外侧一层；肘 = 粗细最小处（排除两端各 20%）
        shoulder = rows[0]["center"]
        wrist = rows[-1]["center"]
        inner = rows[int(len(rows) * 0.2): max(int(len(rows) * 0.8), 1)] or rows
        elbow = min(inner, key=lambda row: row["thick"])["center"]
        print("   → 肩 %s / 肘 %s / 腕 %s" % (
            np.round(shoulder, 4).tolist(), np.round(elbow, 4).tolist(), np.round(wrist, 4).tolist()))
        report[side] = {"shoulder": shoulder, "elbow": elbow, "wrist": wrist,
                        "hand_end": [wrist[0] + sign * (x1 - abs(wrist[0])) * 0.35,
                                     wrist[1], wrist[2]],
                        "rows": rows}
    if want_json:
        print("ARM_JOINTS_JSON " + json.dumps(report, ensure_ascii=False))
    print("ARM_JOINTS_OK")


main()
