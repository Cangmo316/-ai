"""生成软著材料，遇到文件被 Office 占用时自动另存为「（最新）」版。

## 为什么需要它

WPS / Word 打开 docx 时会独占文件句柄，覆盖写入直接 `PermissionError`。
一轮轮去关软件很烦，所以这里做三件事：

1. 先写到临时目录（一定成功）；
2. 尝试覆盖目标；成功就删临时文件；
3. 覆盖失败（被占用）就另存为 `原名（最新）.docx`，并打印明确的替换指引。

这样无论对方开没开文档，都能拿到一份可用的最新文件。

用法：
    python regen-copyright.py            # 四份全出
    python regen-copyright.py --only form
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import tempfile
from pathlib import Path

FINAL = Path(r"E:\ppt\比邻AI.ppt\软著材料-终版")
SM_SCRIPT = Path(r"E:\UI\.uni-shot\gen-copyright.py")
FM_SCRIPT = Path(r"E:\UI\.uni-shot\gen-copyright-form.py")


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def deliver(produced: Path) -> Path:
    """把临时产物送到最终目录；被占用则加「（最新）」后缀。"""
    FINAL.mkdir(parents=True, exist_ok=True)
    target = FINAL / produced.name
    try:
        shutil.copy2(produced, target)
        return target
    except PermissionError:
        fallback = FINAL / (produced.stem + "（最新）" + produced.suffix)
        shutil.copy2(produced, fallback)
        print("    ⚠️ %s 被占用，已另存为 %s" % (target.name, fallback.name))
        return fallback


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=["source", "manual", "form", "checklist", "all"], default="all")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        if args.only in ("source", "manual", "all"):
            sm = load("sm", SM_SCRIPT)
            sm.OUT = tmp_dir
            if args.only in ("source", "all"):
                # 源程序：60 页，逐页 50 行
                path = sm.make_source_doc(7, 13.0)[0]
                print("  源程序 → %s" % deliver(path).name)
            if args.only in ("manual", "all"):
                path = sm.make_manual_doc()
                print("  说明书 → %s" % deliver(path).name)

        if args.only in ("form", "checklist", "all"):
            fm = load("fm", FM_SCRIPT)
            fm.OUT = tmp_dir
            if args.only in ("form", "all"):
                path = fm.make_form()
                print("  申请表 → %s" % deliver(path).name)
            if args.only in ("checklist", "all"):
                path = fm.make_checklist()
                print("  清单   → %s" % deliver(path).name)


if __name__ == "__main__":
    main()
