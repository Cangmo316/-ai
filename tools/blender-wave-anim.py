#!/usr/bin/env python3
"""
比邻AI · 挥手动画烘焙（工具 A：为"招手互动"生成 glTF animation）

用法：
    blender --background <带手臂链的资产.blend> --python tools/blender-env.py \
        --python tools/blender-wave-anim.py -- --out <输出.blend> \
            [--side R] [--raise-deg 55] [--swing-deg 22] [--cycles 3] [--fps 30] [--report]

设计要点（都是踩过的坑）：
  · **摆动轴必须实测**：手臂骨经过资产转轴（Y-up→Z-up）后，局部轴与直觉不一致，
    直接写 `rotation_euler[2]` 可能让手前后晃而不是左右晃。
    本工具逐个候选轴/方向转一次，量**手部顶点的世界 X 位移**，取最大的那组当"左右摆动轴"。
  · 动画是**骨骼关键帧**（glTF animation 导出后由端侧播放），不是形态键——
    形态键做手臂摆动体积大且难复用。
  · 同时写入 `wave` 动作与 NLA？不：只建一个 Action 命名为 `wave`，
    导出时用 `export_animations=True` 即可被端侧按名字取用。
"""
import json
import math
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


ARMS = {
    "R": ("upperarm.R", "forearm.R", "hand.R"),
    "L": ("upperarm.L", "forearm.L", "hand.L"),
}


def measurement_mesh():
    return max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))


def evaluate(obj):
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(deps)
    mesh = evaluated.to_mesh()
    co = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    evaluated.to_mesh_clear()
    return co


def reset_pose(armature):
    for bone in armature.pose.bones:
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0.0, 0.0, 0.0)
        bone.location = (0.0, 0.0, 0.0)
        bone.scale = (1.0, 1.0, 1.0)


def hand_zone(mesh_obj, hand_bone_name, armature):
    bone = armature.data.bones.get(hand_bone_name)
    if bone is None:
        return None
    head = (armature.matrix_world @ bone.matrix_local).translation
    count = len(mesh_obj.data.vertices)
    co = np.empty(count * 3, dtype=np.float64)
    mesh_obj.data.vertices.foreach_get("co", co)
    co = co.reshape(count, 3)
    distance = np.linalg.norm(co - np.array([head.x, head.y, head.z]), axis=1)
    order = np.argsort(distance)
    return order[: max(20, count // 150)]


def find_swing_axis(armature, mesh_obj, zone, bone_name, degrees=35.0):
    """找出让"手部世界 X 位移最大"的（轴, 方向）——即左右摆动方向。"""
    reset_pose(armature)
    base = evaluate(mesh_obj)
    best = None
    for axis in range(3):
        for sign in (1.0, -1.0):
            reset_pose(armature)
            bone = armature.pose.bones.get(bone_name)
            rotation = [0.0, 0.0, 0.0]
            rotation[axis] = sign * math.radians(degrees)
            bone.rotation_euler = tuple(rotation)
            co = evaluate(mesh_obj)
            delta = (co[zone] - base[zone]).mean(axis=0)
            score = abs(float(delta[0]))          # 只关心世界 X（左右）
            if best is None or score > best[0]:
                best = (score, axis, sign)
    reset_pose(armature)
    return best


def main():
    out = arg_value("--out")
    side = arg_value("--side", "R").upper()
    raise_deg = float(arg_value("--raise-deg", "55"))
    swing_deg = float(arg_value("--swing-deg", "22"))
    cycles = int(arg_value("--swing-cycles", "3"))   # 注意：不能叫 --cycles（与 Blender 自带选项冲突）
    fps = int(arg_value("--fps", "30"))
    duration = float(arg_value("--duration", "2.6"))
    want_report = has_flag("--report")

    armature = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    mesh_obj = measurement_mesh()
    if armature is None:
        print("WAVE_FAIL 没有骨架")
        return
    upper_name, fore_name, hand_name = ARMS.get(side, ARMS["R"])
    zone = hand_zone(mesh_obj, hand_name, armature)
    if zone is None:
        print("WAVE_FAIL 找不到 %s" % hand_name)
        return
    print("=" * 92)
    print("挥手动画烘焙 : %s（用 %s 侧手臂，%d 帧 @%dfps）"
          % (bpy.data.filepath, side, int(duration * fps), fps))

    # ── 轴探测：分别找"抬臂轴"（世界 Z 最大）与"摆动轴"（世界 X 最大）──
    # ⚠️ 实测结论（Q 版男医）：抬臂是 `upperarm` 的 **X 轴**（+40° → 手部世界 Δz +99mm），
    #    而**横向摆动是 `upperarm` 的 Z 轴**（±45° → 手部 |Δx| 33~38mm）；
    #    `forearm` / `hand` 的任一轴横向都只有 1~4mm（圆团手 + 短前臂），**指望不上**。
    #    第一版只转 forearm 摆动 → 手部左右只有 ~1.5mm，动画看起来"只是抬了下手"。
    reset_pose(armature)
    base = evaluate(mesh_obj)

    def probe(bone_name, prefer_axis, degrees=45.0):
        best = None
        for axis in range(3):
            for sign in (1.0, -1.0):
                reset_pose(armature)
                rotation = [0.0, 0.0, 0.0]
                rotation[axis] = sign * math.radians(degrees)
                armature.pose.bones.get(bone_name).rotation_euler = tuple(rotation)
                co = evaluate(mesh_obj)
                delta = (co[zone] - base[zone]).mean(axis=0)
                score = float(delta[prefer_axis])
                if best is None or score > best[0]:
                    best = (score, axis, sign, delta)
        reset_pose(armature)
        return best

    # 抬臂：世界 Z 越大越好；摆动：世界 X 幅度越大越好 —— 但**两者必须用不同的轴**。
    # ⚠️ 实测踩坑：`upperarm` 的 X 轴同时产生很大的 Δz(+48.9) 与 Δx(-38.0)，
    #    于是"按 Δx 选摆动轴"又选回了 X 轴 → 抬臂与摆动在同一通道上**相互抵消**
    #    （验收显示"手部抬起 1.3mm"，动画几乎不动）。
    #    正确做法：摆动只在**除抬臂轴之外**的轴里挑。
    lift = probe(upper_name, 2, degrees=40.0)
    lift_axis = lift[1]
    swing_best = None
    for axis in range(3):
        if axis == lift_axis:
            continue
        for sign in (1.0, -1.0):
            reset_pose(armature)
            rotation = [0.0, 0.0, 0.0]
            rotation[axis] = sign * math.radians(45.0)
            armature.pose.bones.get(upper_name).rotation_euler = tuple(rotation)
            co = evaluate(mesh_obj)
            delta = (co[zone] - base[zone]).mean(axis=0)
            score = abs(float(delta[0]))
            if swing_best is None or score > swing_best[0]:
                swing_best = (score, axis, sign, delta)
    reset_pose(armature)
    swing = swing_best if swing_best is not None else lift
    # 摆动的另一个方向（往内侧）也要能摆，取符号相反的那侧作为回摆
    print("  抬臂：%s axis=%d sign=%+d（世界 Δz %+.1fmm）"
          % (upper_name, lift[1], int(lift[2]), lift[0] * 1000))
    print("  摆动：%s axis=%d sign=%+d（世界 Δx %+.1fmm，幅度 %.1fmm）"
          % (upper_name, swing[1], int(swing[2]), swing[0] * 1000, abs(swing[0]) * 1000))
    if abs(swing[0]) * 1000 < 12.0:
        print("  ⚠️ 摆动幅度偏小（%.1fmm），招手会不明显——考虑加大 --swing-deg" % (abs(swing[0]) * 1000))

    lift_axis, lift_sign = lift[1], lift[2]
    swing_axis, swing_sign = swing[1], swing[2]

    # ── 建 Action：抬臂（lift）常驻 + 摆动（swing）叠加 ──
    armature.animation_data_create()
    action = bpy.data.actions.new("wave")
    armature.animation_data.action = action
    reset_pose(armature)

    def key_multi(bone_name, frame, rotations):
        """rotations: {axis: degrees}，一次性写成一个 euler 并打帧"""
        bone = armature.pose.bones.get(bone_name)
        euler = [0.0, 0.0, 0.0]
        for axis, degrees in rotations.items():
            euler[axis] += math.radians(degrees)
        bone.rotation_euler = tuple(euler)
        bone.keyframe_insert(data_path="rotation_euler", frame=frame)

    total = int(duration * fps)
    lift_end = int(total * 0.16)
    wave_end = int(total * 0.80)
    for frame in range(0, total + 1):
        if frame <= lift_end:
            t = frame / max(lift_end, 1)
            ease = t * t * (3 - 2 * t)
            key_multi(upper_name, frame, {
                lift_axis: lift_sign * raise_deg * ease,
                swing_axis: swing_sign * swing_deg * 0.5 * ease,
            })
            key_multi(fore_name, frame, {lift_axis: lift_sign * raise_deg * 0.35 * ease})
            key_multi(hand_name, frame, {})
        elif frame <= wave_end:
            t = (frame - lift_end) / max(wave_end - lift_end, 1)
            phase = math.sin(2 * math.pi * cycles * t)
            key_multi(upper_name, frame, {
                lift_axis: lift_sign * raise_deg,
                swing_axis: swing_sign * swing_deg * 0.5
                + swing_sign * swing_deg * 0.5 * phase,
            })
            key_multi(fore_name, frame, {
                lift_axis: lift_sign * raise_deg * 0.35,
                swing_axis: swing_sign * swing_deg * 0.25 * phase,
            })
            # 手：跟着摆动轴微摆（幅度小，只为"自然感"）
            key_multi(hand_name, frame, {swing_axis: swing_sign * swing_deg * 0.18 * phase})
        else:
            t = (frame - wave_end) / max(total - wave_end, 1)
            ease = 1.0 - (t * t * (3 - 2 * t))
            key_multi(upper_name, frame, {
                lift_axis: lift_sign * raise_deg * ease,
                swing_axis: swing_sign * swing_deg * 0.5 * ease,
            })
            key_multi(fore_name, frame, {lift_axis: lift_sign * raise_deg * 0.35 * ease})
            key_multi(hand_name, frame, {})

    bpy.context.scene.frame_start = 0
    bpy.context.scene.frame_end = total
    bpy.context.scene.render.fps = fps
    print("  已写入动作 `wave`：%d 帧（%.2fs）" % (total, duration))

    # ── 自动验收：量手部在各帧的位移范围（"招手"必须真的左右动 + 抬起来）──
    reset_pose(armature)
    armature.animation_data.action = None          # 先关动画取静止基
    rest_co = evaluate(mesh_obj)
    rest_hand = rest_co[zone]
    armature.animation_data.action = action
    stats = []
    for frame in range(0, total + 1, max(1, total // 12)):
        bpy.context.scene.frame_set(frame)
        co = evaluate(mesh_obj)
        hand = co[zone]
        stats.append({
            "frame": frame,
            "z": float(hand[:, 2].max()),
            "x": float(hand[:, 0].mean()),
            "disp": float(np.linalg.norm(hand - rest_hand, axis=1).mean() * 1000),
        })
    z_lift = max(row["z"] for row in stats) - float(rest_hand[:, 2].max())
    x_span = max(row["x"] for row in stats) - min(row["x"] for row in stats)
    disp_max = max(row["disp"] for row in stats)
    print("  验收：手部抬起 %.1fmm，左右摆动 %.1fmm，最大位移 %.1fmm"
          % (z_lift * 1000, x_span * 1000, disp_max))
    if z_lift * 1000 < 40:
        print("  ⚠️ 抬手幅度 <40mm，招手不明显（可加大 --raise-deg）")
    if x_span * 1000 < 15:
        print("  ⚠️ 左右摆动 <15mm，招手不明显（可加大 --swing-deg）")
    bpy.context.scene.frame_set(0)

    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("WAVE_OK 已保存 " + out)
    if want_report:
        print("WAVE_JSON " + json.dumps(report, ensure_ascii=False))


main()
