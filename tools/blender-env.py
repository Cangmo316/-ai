#!/usr/bin/env python3
"""
比邻AI · Blender 运行环境前置（必须作为**第一个** --python 传入）

用法：
    blender --background <文件.blend> \
        --python tools/blender-env.py \
        --python tools/blender-xxx.py -- <参数...>

做三件事，把 Blender 的缓存从 C 盘赶到 E 盘项目目录：
  1. 关掉文件预览缩略图（`file_preview_type = NONE`）
     —— 否则每次保存 .blend 都会往 `C:\\Users\\<用户>\\.thumbnails\\large\\` 写预览图，
        在本机的写入沙箱（只允许写工作区）下必然报
        `image.write | ERROR OpenImageIO write failed: Could not open file "C:\\..."`
  2. 把 `temporary_directory` 指到工作区内的 `_tmp`
  3. 建好目录；若外部还传了 `BILIN_BLENDER_TMP` 则以它为准

⚠️ 这条错误不影响渲染/保存结果（图与 .blend 都正常落盘），但会污染日志、
   让"到底有没有失败"难以判断，因此从源头关掉。
"""

import os
import sys

PREFERRED = [
    os.environ.get("BILIN_BLENDER_TMP"),
    r"E:\比邻AI\3D建模\_rig_work\_tmp",
    r"E:\比邻AI\3D建模\_tmp",
]


def setup():
    import bpy

    temp_dir = None
    for candidate in PREFERRED:
        if not candidate:
            continue
        try:
            os.makedirs(candidate, exist_ok=True)
            probe = os.path.join(candidate, ".write-probe")
            with open(probe, "w", encoding="utf-8") as handle:
                handle.write("ok")
            os.remove(probe)
            temp_dir = candidate
            break
        except OSError:
            continue

    filepaths = bpy.context.preferences.filepaths
    try:
        filepaths.file_preview_type = "NONE"
    except (AttributeError, TypeError):
        pass
    if temp_dir:
        try:
            filepaths.temporary_directory = temp_dir
        except (AttributeError, TypeError):
            pass
        os.environ["TMP"] = temp_dir
        os.environ["TEMP"] = temp_dir
        os.environ["TMPDIR"] = temp_dir

    print(f"BLENDER_ENV temp={temp_dir or '(系统默认)'} "
          f"preview={getattr(filepaths, 'file_preview_type', 'n/a')}")


setup()
