#!/usr/bin/env python3
"""
比邻AI · 形态键质量审计 v2（向量化，零第三方依赖）

用法：
    blender --background <文件.blend> \
        --python tools/blender-env.py \
        --python tools/blender-morph-audit2.py -- [--json] [--top 30] \
            [--max-stretch 2.0] [--hard-stretch 6.0] [--micro-mm 1.5]

与 `blender-bone-audit.py` 同一套三档判据（见交付规范 §4.6），但对象是**形态键**：
  · 有效边（原长 > 0.3mm）拉伸 ≤ 2.0（FAIL 线）
  · 全边拉伸 ≤ 6.0
  · 微边（< 0.3mm）绝对增量 ≤ 1.5mm
  · 翻转面面积占比 ≤ 500ppm（有翻面但面积小记「△ 观察」）

另外两项针对口型的专项（交付规范 §17.4 / §17.5）：
  · **中线开口量**：唇缝上下两行的中线垂距（静置基准自身就非零，报增量）
  · **位移外溢**：动顶点包围盒（判断形态键是不是"整张脸都在动"）
"""

import json
import sys

import bpy
import numpy as np

LIMITS = {}


def arg_value(name, default=None):
    args = sys.argv
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return default


def has_flag(name):
    return name in sys.argv


def target_mesh():
    best = None
    for obj in bpy.data.objects:
        if obj.type != "MESH" or not obj.data.shape_keys:
            continue
        if best is None or len(obj.data.vertices) > len(best.data.vertices):
            best = obj
    return best


def main():
    max_stretch = float(arg_value("--max-stretch", "2.0"))
    hard_stretch = float(arg_value("--hard-stretch", "6.0"))
    micro_mm = float(arg_value("--micro-mm", "1.5"))
    flip_ppm = float(arg_value("--flip-ppm", "500"))
    top = int(arg_value("--top", "30"))
    want_json = has_flag("--json")

    obj = target_mesh()
    if obj is None:
        print("MORPH_AUDIT2_FAIL 没有带形态键的网格")
        return
    mesh = obj.data
    keys = mesh.shape_keys
    basis = keys.key_blocks[0]
    count = len(mesh.vertices)
    rest = np.empty(count * 3, dtype=np.float64)
    basis.data.foreach_get("co", rest)
    rest = rest.reshape(count, 3)

    edges = np.empty(len(mesh.edges) * 2, dtype=np.int32)
    mesh.edges.foreach_get("vertices", edges)
    edges = edges.reshape(-1, 2)
    rest_len = np.linalg.norm(rest[edges[:, 0]] - rest[edges[:, 1]], axis=1)
    valid = rest_len > 1e-7
    big = rest_len > 0.0003
    micro = valid & (rest_len <= 0.0003)

    mesh.calc_loop_triangles()
    tri = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", tri)
    tri = tri.reshape(-1, 3)
    def tri_normals(points):
        a, b, c = points[tri[:, 0]], points[tri[:, 1]], points[tri[:, 2]]
        return np.cross(b - a, c - a)
    rest_normals = tri_normals(rest)
    rest_area = np.linalg.norm(rest_normals, axis=1)
    total_area = float(rest_area.sum() / 2.0)

    # 唇缝中线（x≈0、唇红带）：用于量中线开口
    midline = (np.abs(rest[:, 0]) < 0.002) & (rest[:, 2] > 1.005) & (rest[:, 2] < 1.055) \
        & (rest[:, 1] < -0.060)

    rows = []
    for block in keys.key_blocks[1:]:
        posed_flat = np.empty(count * 3, dtype=np.float64)
        block.data.foreach_get("co", posed_flat)
        posed = posed_flat.reshape(count, 3)
        delta = posed - rest
        posed_len = np.linalg.norm(posed[edges[:, 0]] - posed[edges[:, 1]], axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            ratios = np.where(valid, posed_len / np.maximum(rest_len, 1e-12), 1.0)
        change = np.abs(posed_len - rest_len)
        posed_normals = tri_normals(posed)
        posed_area = np.linalg.norm(posed_normals, axis=1)
        significant = (rest_area > 1e-12) & (posed_area > 1e-14)
        dots = np.ones(len(tri))
        dots[significant] = (rest_normals[significant] * posed_normals[significant]).sum(axis=1) \
            / (rest_area[significant] * posed_area[significant])
        flipped = (dots < 0) & significant
        flip_area = float(rest_area[flipped].sum() / 2.0)
        disp = np.linalg.norm(delta, axis=1)
        moved = disp > 1e-7
        row = {
            "name": block.name,
            "max_big": round(float(ratios[big].max()), 3) if big.any() else 1.0,
            "max_all": round(float(ratios.max()), 3),
            "micro_mm": round(float(change[micro].max() * 1000), 4) if micro.any() else 0.0,
            "edges_big_over": int((ratios[big] > max_stretch).sum()) if big.any() else 0,
            "flipped": int(flipped.sum()),
            "flip_ppm": round(flip_area / total_area * 1e6, 2) if total_area else 0.0,
            "moved": int((disp > 0.0001).sum()),
            "max_mm": round(float(disp.max() * 1000), 3),
        }
        if moved.any():
            row["bbox"] = [[round(float(rest[moved, axis].min()), 3),
                            round(float(rest[moved, axis].max()), 3)] for axis in range(3)]
        # 最差有效边（帮助定位病灶）
        if big.any():
            order = np.argsort(-np.where(big, ratios, 0.0))[:3]
            row["worst_edges"] = []
            for edge in order:
                i, j = int(edges[edge, 0]), int(edges[edge, 1])
                row["worst_edges"].append({
                    "ratio": round(float(ratios[edge]), 2),
                    "rest_mm": round(float(rest_len[edge] * 1000), 5),
                    "change_mm": round(float(change[edge] * 1000), 4),
                    "mid": [round(float(v), 4) for v in (rest[i] + rest[j]) / 2],
                    "delta_mm": [round(float(np.linalg.norm(disp[i]) * 1000), 3),
                                 round(float(np.linalg.norm(disp[j]) * 1000), 3)],
                })
        # 中线开口量（静置 vs 该键）
        if midline.any():
            idx = np.nonzero(midline)[0]
            # 唇缝中线：取 x≈0 一列里 z 最大的"下唇行"与 z 最小的"上唇行"
            rest_z = rest[idx, 2]
            posed_z = posed[idx, 2]
            rest_open = (rest_z.max() - rest_z.min()) * 1000
            posed_open = (posed_z.max() - posed_z.min()) * 1000
            row["open_mm"] = round(posed_open, 2)
            row["open_delta_mm"] = round(posed_open - rest_open, 2)
        rows.append(row)

    # 判定（三档）
    def verdict(row):
        if row["max_big"] > max_stretch or row["max_all"] > hard_stretch \
                or row["micro_mm"] > micro_mm or row["flip_ppm"] > flip_ppm:
            return "✗ 不合格"
        if row["flipped"] > 0 or row["flip_ppm"] > 0:
            return "△ 观察"
        return "✓"

    for row in rows:
        row["verdict"] = verdict(row)
    failures = [r["name"] for r in rows if r["verdict"].startswith("✗")]
    warnings = [r["name"] for r in rows if r["verdict"].startswith("△")]
    report = {"object": obj.name, "vertices": count, "triangles": int(len(tri)),
              "limits": {"max_stretch_big": max_stretch, "max_stretch_all": hard_stretch,
                         "micro_mm": micro_mm, "flip_ppm": flip_ppm},
              "rows": rows, "failures": failures, "warnings": warnings}

    print("=" * 118)
    print("形态键质量审计 : %s  %d 顶点 / %d 三角面  形态键 %d"
          % (obj.name, count, len(tri), len(rows)))
    print(f"  判据（与骨骼审计同一套）：有效边拉伸 ≤ {max_stretch} / 全边 ≤ {hard_stretch} / "
          f"微边绝对增量 ≤ {micro_mm}mm / 翻面面积 ≤ {flip_ppm}ppm")
    print("")
    print(f"  {'形态键':<20}{'有效边拉伸':>11}{'全边拉伸':>10}{'微边mm':>9}"
          f"{'超限边':>8}{'翻面':>7}{'翻面ppm':>10}{'位移mm':>9}{'中线开口mm':>12}  判定")
    for row in rows[:top]:
        open_text = f"{row.get('open_mm', 0):.2f}" if "open_mm" in row else "—"
        print(f"  {row['name']:<20}{row['max_big']:>11}{row['max_all']:>10}"
              f"{row['micro_mm']:>9}{row['edges_big_over']:>8}{row['flipped']:>7}"
              f"{row['flip_ppm']:>10}{row['max_mm']:>9}{open_text:>12}  {row['verdict']}")
    print("")
    print("  位移范围（动顶点 >0.1mm 的包围盒，判断是否「整脸都在动」）：")
    for row in rows:
        if "bbox" in row:
            print(f"    {row['name']:<20} x{row['bbox'][0]} y{row['bbox'][1]} z{row['bbox'][2]}"
                  f"   动顶点 {row['moved']}")
    print("")
    print("  最差有效边（帮助定位病灶；rest=静置边长，Δ=两端各自位移）：")
    for row in rows:
        if not row.get("worst_edges"):
            continue
        if row["max_big"] < 1.5:
            continue
        for edge in row["worst_edges"]:
            print(f"    {row['name']:<20} 拉伸 {edge['ratio']:>8}×  原长 {edge['rest_mm']:>9}mm  "
                  f"边长变化 {edge['change_mm']:>8}mm  端部位移 {edge['delta_mm']}  中点 {edge['mid']}")
    print("")
    if failures:
        print(f"  ✗ 不合格 {len(failures)} 个：" + ", ".join(failures))
    else:
        print(f"  ✓ 硬指标全部通过（{len(rows)} 个形态键）")
    if warnings:
        print(f"  △ 观察 {len(warnings)} 个：" + ", ".join(warnings))
    if want_json:
        print("MORPH_AUDIT2_JSON " + json.dumps(report, ensure_ascii=False))


main()
