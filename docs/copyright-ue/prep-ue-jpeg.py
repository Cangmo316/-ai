"""把说明书用到的图片转成 JPEG，把 docx 从 12.5MB 压到 3MB 以内。

思路：
  · 图片在文档里的显示宽度是 13.9cm，按 300dpi 只需约 1650px；
    取 1500px 宽足够清晰，再大只是让文件变胖。
  · 界面截图和照片用 q=86；架构图里有大量细字，用 q=92；
    九宫格立绘是浅灰底的人像，用 q=90。
  · 输出到 图片\\jpg\\，文件名与原图一致（扩展名改 .jpg），
    生成器只需把 IMAGES 指到该目录。

注意：源程序、申请表、清单三份文档不含图片，不受影响。
"""

from pathlib import Path

from PIL import Image

SRC = Path(r"E:\ppt\GramStain软著\图片")
OUT = SRC / "jpg"

# (源文件名, 输出名, 质量)
JOBS = [
    ("fig-00-系统架构.png", "fig-00-系统架构.jpg", 92),
    ("shot-01-主菜单.png", "shot-01-主菜单.jpg", 86),
    ("shot-02-设置.png", "shot-02-设置.jpg", 86),
    ("shot-03-计时方式.png", "shot-03-计时方式.jpg", 86),
    ("shot-04-制片阶段.png", "shot-04-制片阶段.jpg", 86),
    ("shot-06-40倍视野-宽幅.png", "shot-06-40倍视野-宽幅.jpg", 86),
    ("shot-07-100倍视野-宽幅.png", "shot-07-100倍视野-宽幅.jpg", 86),
    ("shot-05-AI对话.png", "shot-05-AI对话.jpg", 86),
    ("shot-08-林医生立绘.png", "shot-08-林医生立绘.jpg", 90),
    ("shot-09-剧情对话.png", "shot-09-剧情对话.jpg", 86),
    ("shot-10-随堂问答.png", "shot-10-随堂问答.jpg", 86),
]

MAX_W = 1500


def convert() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    for src_name, dst_name, quality in JOBS:
        src = SRC / src_name
        if not src.exists():
            print("  ⚠️ 缺图：%s" % src_name)
            continue
        with Image.open(src) as im:
            im = im.convert("RGB")
            if im.size[0] > MAX_W:
                h = round(im.size[1] * MAX_W / im.size[0])
                im = im.resize((MAX_W, h), Image.LANCZOS)
            dst = OUT / dst_name
            im.save(dst, "JPEG", quality=quality, optimize=True, progressive=True)
            size = dst.stat().st_size
            total += size
            print("  %-30s %4dx%-4d → %5.0f KB" % (dst_name, im.size[0], im.size[1], size / 1024))
    print("  合计 %.2f MB" % (total / 1024 / 1024))


if __name__ == "__main__":
    convert()
