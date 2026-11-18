"""把 UE 里实际抓到的窗口截图裁成纯游戏画面，供说明书使用。

编辑器边框（1600x960 窗口）：
  左 6px 细工具栏、上 152px 菜单+工具栏、右 1150px 起是大纲/细节面板、
  下 817px 起是内容浏览器。

抓到并采用的画面：
  s1-menu     主菜单（中文）
  c1-settings 设置面板
  s3a-timer   选择计时方式
  s3b-stain   制片阶段（步骤面板 + 原理说明 + 台面器材）
  s2-ai       染染对话（需检查是否已有回答）

另有工程内的显微镜视野纹理 40× / 100×，作为实验现象图。
"""

from pathlib import Path

from PIL import Image

SRC = Path(r"E:\UI\.uni-shot\ue-capture")
SHOTS = Path(r"E:\ppt\GramStain软著\图片")
PROJECT = Path(r"E:\ue5.8\3.0\GramStain")

VIEWPORT = (6, 152, 1150, 817)   # 1600x960 窗口里的 PIE 视口

MAPPING = [
    ("s1-menu.png", "shot-01-主菜单.png"),
    ("c1-settings.png", "shot-02-设置.png"),
    ("s3a-timer.png", "shot-03-计时方式.png"),
    ("s3b-stain.png", "shot-04-制片阶段.png"),
    ("s2-ai.png", "shot-05-AI对话.png"),
]


def crop_shots() -> None:
    for src_name, dst_name in MAPPING:
        src = SRC / src_name
        if not src.exists():
            print("  ⚠️ 缺图：%s" % src_name)
            continue
        with Image.open(src) as im:
            im = im.convert("RGB")
            box = (VIEWPORT[0], VIEWPORT[1], min(VIEWPORT[2], im.size[0]), min(VIEWPORT[3], im.size[1]))
            c = im.crop(box)
            # 宽度统一到 1400，文档里缩放后仍清晰
            if c.size[0] > 1400:
                c = c.resize((1400, int(c.size[1] * 1400 / c.size[0])), Image.LANCZOS)
            c.save(SHOTS / dst_name, quality=93)
            print("  %-18s → %-24s %dx%d" % (src_name, dst_name, c.size[0], c.size[1]))


def microscope_fields() -> None:
    for src, dst, w in (("T_Micro_40x.png", "shot-06-40倍视野.png", 1200),
                        ("T_Micro_100x.png", "shot-07-100倍视野.png", 1200)):
        p = PROJECT / "Tools" / "Micro" / "out" / src
        if not p.exists():
            print("  ⚠️ 缺图：%s" % src)
            continue
        with Image.open(p) as im:
            im = im.convert("RGB")
            ratio = w / im.size[0]
            im2 = im.resize((w, int(im.size[1] * ratio)), Image.LANCZOS)
            im2.save(SHOTS / dst, quality=90)
            print("  %-18s → %-24s %dx%d" % (src, dst, im2.size[0], im2.size[1]))


if __name__ == "__main__":
    crop_shots()
    microscope_fields()
