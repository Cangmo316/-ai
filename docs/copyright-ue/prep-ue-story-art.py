"""把工程里的林医生九种表情立绘拼成说明书用的图 3-8。

素材：`Tools/Doctor/out_r18/T_Doctor_*.png`（r18 版，口罩 + 圆帽 + 丁腈手套的实验室着装）。

两个处理要点：
  1. 原图头顶上方是透明区，直接 convert("RGB") 会变成黑块，
     必须先按 alpha 的 bbox 裁掉透明边，再贴到浅灰底上；
  2. 布局用 5 列 × 2 行，不是 3 × 3。3×3 是竖长图，按 8.5cm 宽排进文档要占 30 多行，
     把整页挤到只剩 20 来行；5×2 宽高比 1.62，按 12cm 宽排只占约 13 行。

输出：`E:\\ppt\\GramStain软著\\图片\\shot-08-林医生立绘.png`
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SRC = Path(r"E:\ue5.8\3.0\GramStain\Tools\Doctor\out_r18")
OUT = Path(r"E:\ppt\GramStain软著\图片")

ORDER = [
    ("Normal", "平常"), ("Happy", "高兴"), ("Wink", "眨眼"),
    ("Surprised", "惊讶"), ("Surprised2", "惊讶（二）"), ("Sad", "难过"),
    ("Scared", "惊恐"), ("Angry", "生气"), ("Embarrassed", "尴尬"),
]

CELL_W, CELL_H = 210, 300
CAPTION_H = 26
PAD = 8
COLS, ROWS = 5, 2


def font(size: int):
    for name in ("msyh.ttc", "simhei.ttf"):
        p = Path(r"C:\Windows\Fonts") / name
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except OSError:
                continue
    return ImageFont.load_default()


def build() -> Path:
    width = COLS * CELL_W + PAD * (COLS + 1)
    height = ROWS * (CELL_H + CAPTION_H) + PAD * (ROWS + 1)
    sheet = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(sheet)
    f = font(17)

    for idx, (key, label) in enumerate(ORDER):
        path = SRC / ("T_Doctor_%s.png" % key)
        if not path.exists():
            print("  ⚠️ 缺图：%s" % path.name)
            continue
        with Image.open(path) as im:
            im = im.convert("RGBA")
            bbox = im.split()[3].getbbox()
            if bbox:
                im = im.crop(bbox)
            bg = Image.new("RGB", im.size, (243, 244, 246))
            bg.paste(im, mask=im.split()[3])
            ratio = min((CELL_W - 6) / bg.size[0], (CELL_H - 6) / bg.size[1])
            cell_img = bg.resize((int(bg.size[0] * ratio), int(bg.size[1] * ratio)), Image.LANCZOS)

        row, col = divmod(idx, COLS)
        x = PAD + col * (CELL_W + PAD)
        y = PAD + row * (CELL_H + CAPTION_H + PAD)
        draw.rectangle([x, y, x + CELL_W, y + CELL_H], fill=(243, 244, 246))
        sheet.paste(cell_img, (x + (CELL_W - cell_img.size[0]) // 2,
                               y + (CELL_H - cell_img.size[1]) // 2))
        bb = draw.textbbox((0, 0), label, font=f)
        draw.text((x + (CELL_W - (bb[2] - bb[0])) // 2, y + CELL_H + 4), label,
                  font=f, fill=(30, 36, 46))

    out = OUT / "shot-08-林医生立绘.png"
    OUT.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=94)
    print("  已生成 %s  %dx%d" % (out.name, sheet.size[0], sheet.size[1]))
    return out


if __name__ == "__main__":
    build()
