"""唇缝切开 + 上下唇权重重分配 + 开口实测（**只切唇缝**，用 sharp 标记而不是全局夹角）

步骤：
  1. 标 sharp：唇缝带内、且"上下都有邻居"的顶点，与它上方/下方邻居之间的边标为 sharp
  2. EdgeSplit(use_edge_sharp=True, use_edge_angle=False) → 只沿这些边分离
  3. 分离后：把"缝下侧"顶点组的权重改成 jaw 主导、"缝上侧"改成 head 主导
  4. 量中线开口（静置坐标分上下唇）
"""
import math
import sys

import bmesh
import numpy as np
import bpy

OPEN_ANGLE = float(([a for a in sys.argv if a.startswith("--open=")] or ["--open=8"])[0].split("=")[1])
DO_REWEIGHT = "--no-reweight" not in sys.argv

mesh_obj = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
mesh = mesh_obj.data

count = len(mesh.vertices)
rest = np.empty(count * 3, dtype=np.float64)
mesh.vertices.foreach_get("co", rest)
rest = rest.reshape(count, 3)

# ── 开口度量（用静置坐标分上下唇）──
BAND = (np.abs(rest[:, 0]) < 0.004) & (rest[:, 1] < -0.065) \
    & (rest[:, 2] > 1.022) & (rest[:, 2] < 1.042)
idx = np.nonzero(BAND)[0]
seam_z = float(np.median(rest[idx, 2]))
UPPER_SEL = BAND & (rest[:, 2] > seam_z + 0.0004)
LOWER_SEL = BAND & (rest[:, 2] < seam_z - 0.0004)
upper = np.nonzero(UPPER_SEL)[0]
lower = np.nonzero(LOWER_SEL)[0]


def opening(degrees):
    for bone in arm.pose.bones:
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0.0, 0.0, 0.0)
    if degrees:
        jaw = arm.pose.bones.get("jaw")
        if jaw is not None:
            jaw.rotation_euler = (math.radians(degrees), 0.0, 0.0)
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    evaluated = mesh_obj.evaluated_get(deps)
    evaluated_mesh = evaluated.to_mesh()
    co = np.empty(len(evaluated_mesh.vertices) * 3, dtype=np.float64)
    evaluated_mesh.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    evaluated.to_mesh_clear()
    # ⚠️ 切开后顶点数变了，必须用**位置口径**重新取上下唇行（用切开前的索引会读到错的顶点）
    mid = (np.abs(co[:, 0]) < 0.004) & (co[:, 1] < -0.065) & (co[:, 2] > 1.020) & (co[:, 2] < 1.044)
    local = np.nonzero(mid)[0]
    if len(local) < 4:
        return float("nan")
    up = local[co[local, 2] > seam_z + 0.0004]
    low = local[co[local, 2] < seam_z - 0.0004]
    if not len(up) or not len(low):
        return float("nan")
    return float((co[up, 2].min() - co[low, 2].max()) * 1000)


print("静置开口 %.3f mm（缝 z=%.4f，上唇 %d / 下唇 %d）" % (opening(0), seam_z, len(upper), len(lower)))
for degrees in (4, 8, 14):
    print("  [切开前] 下颌 %2d° → %6.2f mm" % (degrees, opening(degrees)))

# ── 1) 标 sharp：缝脊顶点与"上方邻居 / 下方邻居"之间的边 ──
bm = bmesh.new()
bm.from_mesh(mesh)
bm.verts.ensure_lookup_table()
sharp_marked = 0
seam_verts = []
for vert in bm.verts:
    co = vert.co
    if abs(co.x) > 0.004 or co.y > -0.065 or not (1.022 < co.z < 1.042):
        continue
    neighbors = [e.other_vert(vert) for e in vert.link_edges]
    has_up = any(n.co.z > co.z + 0.0004 for n in neighbors)
    has_down = any(n.co.z < co.z - 0.0004 for n in neighbors)
    if not (has_up and has_down):
        continue
    seam_verts.append(vert.index)
    for edge in vert.link_edges:
        other = edge.other_vert(vert)
        if abs(other.co.z - co.z) > 0.0004 or abs(other.co.x - co.x) > 0.006:
            edge.smooth = False          # smooth=False 即 sharp
            sharp_marked += 1
bm.to_mesh(mesh)
bm.free()
print("缝脊顶点 %d 个；标记为 sharp 的边 %d 条" % (len(seam_verts), sharp_marked))

# ── 2) EdgeSplit 只按 sharp 分离 ──
modifier = mesh_obj.modifiers.new("LipSplitSharp", "EDGE_SPLIT")
modifier.use_edge_angle = False
modifier.use_edge_sharp = True
bpy.context.view_layer.objects.active = mesh_obj
mesh_obj.select_set(True)
result = bpy.ops.object.modifier_apply(modifier=modifier.name)
mesh_obj.select_set(False)
print("EdgeSplit(sharp) → %s；顶点 %d → %d" % (result, count, len(mesh.vertices)))

# ── 3) 重分配上下唇权重（切开后每侧有独立顶点）──
mesh = mesh_obj.data
count2 = len(mesh.vertices)
co2 = np.empty(count2 * 3, dtype=np.float64)
mesh.vertices.foreach_get("co", co2)
co2 = co2.reshape(count2, 3)


def group_weights(name):
    weights = np.zeros(count2)
    group = mesh_obj.vertex_groups.get(name)
    if group is None:
        return weights
    for vertex in mesh.vertices:
        for element in vertex.groups:
            if element.group == group.index:
                weights[vertex.index] = element.weight
                break
    return weights


if DO_REWEIGHT:
    head_w = group_weights("head")
    jaw_w = group_weights("jaw")
    # 唇区：缝上下各 3mm
    lip_zone = (np.abs(co2[:, 0]) < 0.030) & (co2[:, 1] < -0.065) \
        & (co2[:, 2] > seam_z - 0.004) & (co2[:, 2] < seam_z + 0.004)
    above = lip_zone & (co2[:, 2] > seam_z)
    below = lip_zone & (co2[:, 2] < seam_z)
    head_group = mesh_obj.vertex_groups.get("head") or mesh_obj.vertex_groups.new(name="head")
    jaw_group = mesh_obj.vertex_groups.get("jaw") or mesh_obj.vertex_groups.new(name="jaw")
    # 下唇侧：jaw 主导（0.9），其余给 lip_lower；上唇侧：head 主导（0.9）
    lip_lower_group = mesh_obj.vertex_groups.get("lip_lower")
    changed = 0
    for index in np.nonzero(below)[0]:
        total = head_w[index] + jaw_w[index]
        if total <= 1e-6:
            continue
        target_jaw = min(0.9, jaw_w[index] / total * 1.6)
        jaw_group.add([int(index)], float(target_jaw), "REPLACE")
        head_group.add([int(index)], float(1.0 - target_jaw), "REPLACE")
        changed += 1
    for index in np.nonzero(above)[0]:
        total = head_w[index] + jaw_w[index]
        if total <= 1e-6:
            continue
        target_head = min(0.95, head_w[index] / total * 1.5)
        head_group.add([int(index)], float(target_head), "REPLACE")
        jaw_group.add([int(index)], float(1.0 - target_head), "REPLACE")
        changed += 1
    print("上下唇权重重分配：下唇 %d 个 + 上唇 %d 个 = %d 个顶点" % (
        int(below.sum()), int(above.sum()), changed))

# ── 4) 复测开口 ──
jaw2 = group_weights("jaw"); head2 = group_weights("head")
print("  下唇行 jaw 均值 %.3f（改前 %.3f）/ 上唇行 head 均值 %.3f（改前 %.3f）" % (
    jaw2[below].mean() if below.any() else 0, jaw_w[below].mean() if below.any() else 0,
    head2[above].mean() if above.any() else 0, head_w[above].mean() if above.any() else 0))
print("切开并重分配后：")
for degrees in (4, 8, 14):
    print("  下颌 %2d° → %6.2f mm" % (degrees, opening(degrees)))
print("LIP_SURGERY2_OK")
