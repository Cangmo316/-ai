#!/usr/bin/env python3
"""
比邻AI · 贴图重链与打包（Blender 无头运行）

背景：`.blend` 里的贴图路径可能指向不存在的目录（渲染成品红），但同一套贴图
往往已经以规范名字落在别处（例如从 GLB 反抽出来的 `textures/` 目录）。
本脚本按**角色**（albedo / normal / metallic / roughness / eye_iris）把失效的
图片重新链接到目标目录里的对应文件，并 pack 进 .blend，最后保存。

用法：
    blender --background <文件.blend> --python tools/blender-fix-textures.py -- \
        --dir <贴图目录> --prefix <文件名前缀> [--save] [--report]

例：
    blender --background 02_male_60s_v1/BilinAI_MaleFaceRig_60k_edit.blend \
        --python tools/blender-fix-textures.py -- \
        --dir 02_male_60s_v1/textures --prefix BilinAI_MaleFaceRig_60k --save

不加 --save 时只报告不改（dry run）。角色识别按图片名里的关键词：
normal / metallic / roughness / iris / 其余视为 albedo。
"""

import os
import sys

import bpy

ROLE_KEYWORDS = [
    ("normal", ["normal", "nrm", "_n."]),
    ("roughness", ["roughness", "rough", "_r."]),
    ("metallic", ["metallic", "metal", "_m."]),
    ("eye_iris", ["iris", "eye"]),
]

ROLE_COLORSPACE = {
    "albedo": "sRGB",
    "eye_iris": "sRGB",
    "normal": "Non-Color",
    "metallic": "Non-Color",
    "roughness": "Non-Color",
}


def arg_value(name, default=None):
    args = sys.argv
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return default


def has_flag(name):
    return name in sys.argv


def role_of(image_name):
    lowered = image_name.lower()
    for role, keywords in ROLE_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return role
    return "albedo"


def candidate_files(directory):
    out = {}
    for entry in os.listdir(directory):
        path = os.path.join(directory, entry)
        if os.path.isfile(path) and entry.lower().endswith((".png", ".jpg", ".jpeg")):
            out[entry.lower()] = path
    return out


def pick_for_role(files, role, prefix):
    """在目录里按角色找目标文件：先找 <prefix>_<role>.*，再退回包含角色词的文件"""
    if prefix:
        for suffix in (f"_{role}.png", f"_{role}.jpg", f"_{role}.jpeg"):
            key = (prefix + suffix).lower()
            if key in files:
                return files[key]
    # 退而求其次：角色同义名
    synonyms = {
        "albedo": ["albedo", "basecolor", "base_color", "diffuse"],
        "normal": ["normal"],
        "metallic": ["metallic"],
        "roughness": ["roughness"],
        "eye_iris": ["eye_iris", "iris"],
    }[role]
    for key, path in files.items():
        if any(word in key for word in synonyms):
            return path
    return None


def main() -> None:
    directory = arg_value("--dir")
    prefix = arg_value("--prefix", "")
    do_save = has_flag("--save")
    if not directory:
        print("FIXTEX_FAIL 需要 --dir <贴图目录>")
        return
    if not os.path.isdir(directory):
        print(f"FIXTEX_FAIL 目录不存在: {directory}")
        return

    files = candidate_files(directory)
    print("=" * 70)
    print(f"贴图重链: {bpy.data.filepath}")
    print(f"目标目录: {directory}（{len(files)} 个候选文件）")
    print("-" * 70)

    changed = 0
    for image in bpy.data.images:
        if image.name in ("Render Result", "Viewer Node", "Dirty"):
            continue
        current = bpy.path.abspath(image.filepath) if image.filepath else ""
        ok = bool(current) and os.path.exists(current)
        role = role_of(image.name)
        if ok and image.packed_file:
            print(f"  ✅ {image.name}: 已打包，无需处理")
            continue
        target = pick_for_role(files, role, prefix)
        if not target:
            print(f"  ⚠️ {image.name}: 角色={role}，目标目录里找不到对应文件，跳过")
            continue
        print(f"  → {image.name}（角色={role}）")
        print(f"      原路径: {image.filepath or '(空)'}  存在={ok}  已打包={bool(image.packed_file)}")
        print(f"      新路径: {target}")
        if do_save:
            image.filepath = target
            image.reload()
            image.colorspace_settings.name = ROLE_COLORSPACE.get(role, "sRGB")
            try:
                image.pack()
                print("      已 pack ✓")
            except Exception as error:  # noqa: BLE001
                print(f"      pack 失败: {error}")
        changed += 1

    print("-" * 70)
    if not do_save:
        print(f"（dry run）需要处理 {changed} 张图；加 --save 才真正写入")
        return
    print(f"已处理 {changed} 张图，保存 .blend …")
    bpy.ops.wm.save_mainfile()
    print("FIXTEX_OK 已保存 " + bpy.data.filepath)


main()
