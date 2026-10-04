#!/usr/bin/env python3
"""
比邻AI · 唇缝"窄带权重对调"（让下颌旋转真正把嘴掰开）

用法：
    blender --background <带权重的资产.blend> \
        --python tools/blender-env.py \
        --python tools/blender-lip-reweight.py -- --out <输出.blend> \
            [--band-mm 2.0] [--low 0.92] [--high 0.55] [--report]

**为什么要做这个**（实测依据，见任务笔记 §8.20.4）：
  · 中线唇缝一带的 `jaw` 权重是 **0.31~0.42 的近恒定场**（`head` 全为 0），
    `jaw + chin + lip_lower` 在缝上 = 0.49、缝下 = 0.50 —— **几乎完全相等**；
  · 于是下颌旋转时上下唇**一起走**，中线开口恒 1.08mm（4°/8°/14°/20° 都不变）；
  · 切开面片也没用（§8.20.3 已实测），因为两片仍被同一套权重驱动。

做法：只改**缝两侧各 `--band-mm` 内的薄带**（默认 2mm），
把缝下侧的下颌链权重抬到 `--low`（默认 0.92）、缝上侧压到 `--high`（默认 0.55），
差额按比例给 `jaw` / `chin` / `lip_lower`（下侧）与 `head`（上侧）——
这样旋转时下唇走 ~92%、上唇只走 ~55%（且是**向下的同向运动**，差值才是可见开口）。

⚠️ 只动薄带：带太宽会把唇形整体的权重拉平（嘴就不成形了），
   带太窄则开口不够。`--band-mm` 是要反复试的参数，判据见 `_probe_lip_open2.py`。
"""

import json
import math
import os
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


def has_flag(name):
    return name in sys.argv


def main():
    out = arg_value("--out")
    band_mm = float(arg_value("--band-mm", "1.5"))
    low = float(arg_value("--low", "0.92"))
    high = float(arg_value("--high", "0.55"))
    want_report = has_flag("--report")

    mesh_obj = max((o for o in bpy.data.objects if o.type == "MESH"),
                   key=lambda o: len(o.data.vertices))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
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

    jaw_w = weights_of("jaw")
    chin_w = weights_of("chin")
    lip_w = weights_of("lip_lower")
    head_w = weights_of("head")
    total_chain = jaw_w + chin_w + lip_w
    total_all = total_chain + head_w
    keep_ratio = np.divide(total_chain, np.maximum(total_all, 1e-9))

    # 缝 z（中线）
    mid = (np.abs(co[:, 0]) < 0.004) & (co[:, 1] < -0.065) \
        & (co[:, 2] > 1.022) & (co[:, 2] < 1.042)
    seam_z = float(np.median(co[mid, 2])) if mid.any() else 1.0307
    band = (np.abs(co[:, 0]) < 0.035) & (co[:, 1] < -0.060) \
        & (co[:, 2] > seam_z - band_mm / 1000.0) & (co[:, 2] < seam_z + band_mm / 1000.0)
    below = band & (co[:, 2] < seam_z)
    above = band & (co[:, 2] > seam_z)
    print("=" * 96)
    print("唇缝窄带权重对调 : " + bpy.data.filepath)
    print(f"  缝 z = {seam_z:.4f}；薄带 ±{band_mm}mm → 缝下 {int(below.sum())} 顶点 / "
          f"缝上 {int(above.sum())} 顶点")
    print(f"  目标：缝下下颌链 {low}、缝上 {high}")

    groups = {}
    for name in ("jaw", "chin", "lip_lower", "head"):
        groups[name] = mesh_obj.vertex_groups.get(name) or mesh_obj.vertex_groups.new(name=name)

    def set_chain(index, target_chain):
        """把某个顶点的"下颌链占比"设成 target_chain，链内按现有比例分配"""
        chain = total_chain[index]
        rest = total_all[index] - chain
        if chain <= 1e-9:
            # 没有下颌链权重：从 head 借
            groups["jaw"].add([int(index)], float(target_chain), "REPLACE")
            groups["head"].add([int(index)], float(max(0.0, 1.0 - target_chain)), "REPLACE")
            return
        scale = target_chain / chain if chain > 1e-9 else 0.0
        for name, weight in (("jaw", jaw_w[index]), ("chin", chin_w[index]),
                             ("lip_lower", lip_w[index])):
            if weight > 0:
                groups[name].add([int(index)], float(weight * scale), "REPLACE")
        remainder = max(0.0, 1.0 - target_chain)
        groups["head"].add([int(index)], float(remainder), "REPLACE")

    for index in np.nonzero(below)[0]:
        set_chain(int(index), low)
    for index in np.nonzero(above)[0]:
        set_chain(int(index), high)

    # 收尾：清理极小权重 + 归一化
    for vertex in mesh.vertices:
        elements = [(e.group, e.weight) for e in vertex.groups if e.weight > 0.002]
        if not elements:
            continue
        total = sum(w for _, w in elements)
        for group_index, _ in list(vertex.groups and [(e.group, e.weight) for e in vertex.groups]):
            group = mesh_obj.vertex_groups[group_index]
            current = next((e.weight for e in vertex.groups if e.group == group_index), 0.0)
            group.add([vertex.index], float(current / total) if total else 0.0, "REPLACE")

    sums = np.zeros(count)
    for vertex in mesh.vertices:
        sums[vertex.index] = sum(e.weight for e in vertex.groups)
    report = {"file": bpy.data.filepath, "seam_z": round(seam_z, 4), "band_mm": band_mm,
              "below": int(below.sum()), "above": int(above.sum()),
              "target": {"low": low, "high": high},
              "weight_sum": {"min": round(float(sums.min()), 5),
                             "max": round(float(sums.max()), 5),
                             "bad": int((np.abs(sums - 1.0) > 1e-3).sum())}}
    print(f"  权重和：min {report['weight_sum']['min']} / max {report['weight_sum']['max']}"
          f"  异常 {report['weight_sum']['bad']}")

    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("LIP_REWEIGHT_OK 已保存 " + out)
    if want_report:
        print("LIP_REWEIGHT_JSON " + json.dumps(report, ensure_ascii=False))


main()
