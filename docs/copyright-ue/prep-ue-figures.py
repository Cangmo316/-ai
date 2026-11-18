"""为《革兰氏染色虚拟仿真实验系统》说明书准备插图。

参照的样例文档（中药经络养生三维互动学习软件）20 页里放了 23 张图，
几乎每页 1–2 张。我们手上只有 4 张整屏截图，所以做了两件事：

1. 从整屏截图里裁出局部（步骤面板、理论面板、倒计时弹窗、显微镜面板、
   AI 对话面板、实验室概览），这样同一个截图能支撑多个小节；
2. 用 PIL 画一张系统架构图，供"项目背景"一节引用（样例里也有图1-1）。

裁切坐标是按 1084×655 的截图目测定的，改图后需要重测。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

IMG = Path(r"E:\ppt\GramStain软著\图片")

# 局部裁切：(源文件, 输出文件, (左, 上, 右, 下))
CROPS = [
    ("fig-01-主菜单.png", "fig-02-模式入口.png", (18, 168, 245, 400)),
    ("fig-01-主菜单.png", "fig-03-染染对话.png", (525, 240, 745, 430)),
    ("fig-01-主菜单.png", "fig-04-实验室概览.png", (520, 480, 700, 570)),
    ("fig-02-制片阶段.png", "fig-05-步骤面板.png", (14, 14, 225, 230)),
    ("fig-02-制片阶段.png", "fig-06-理论面板.png", (872, 16, 1076, 122)),
    ("fig-02-制片阶段.png", "fig-07-台面器材.png", (250, 225, 1000, 560)),
    ("fig-03-染色阶段.png", "fig-08-倒计时弹窗.png", (376, 8, 712, 112)),
    ("fig-03-染色阶段.png", "fig-09-试剂与废液缸.png", (195, 245, 900, 600)),
    ("fig-03-染色阶段.png", "fig-10-理论面板染色.png", (855, 10, 1076, 180)),
    ("fig-04-油镜观察.png", "fig-11-显微镜面板.png", (578, 222, 782, 605)),
    ("fig-04-油镜观察.png", "fig-12-操作提示.png", (205, 130, 505, 190)),
]


def do_crops() -> None:
    for src_name, dst_name, box in CROPS:
        src = IMG / src_name
        if not src.exists():
            print("  ⚠️ 缺源图：%s" % src_name)
            continue
        with Image.open(src) as im:
            im = im.convert("RGB")
            w, h = im.size
            l, t, r, b = box
            r, b = min(r, w), min(b, h)
            if l >= r or t >= b:
                print("  ⚠️ 裁切范围无效：%s" % dst_name)
                continue
            crop = im.crop((l, t, r, b))
            # 宽度统一到 900，避免文档里尺寸差异过大
            if crop.size[0] > 900:
                ratio = 900 / crop.size[0]
                crop = crop.resize((900, int(crop.size[1] * ratio)), Image.LANCZOS)
            crop.save(IMG / dst_name, quality=92)
            print("  %-26s → %-24s %dx%d" % (src_name, dst_name, crop.size[0], crop.size[1]))


def font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("msyhbd.ttc", "msyh.ttc", "simhei.ttf", "simsun.ttc"):
        p = Path(r"C:\Windows\Fonts") / name
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except OSError:
                continue
    return ImageFont.load_default()


def draw_architecture() -> None:
    """画系统架构图：五层网格，列坐标统一，避免方框重叠。"""
    W, H = 1560, 800
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    f_title = font(31)
    f_box = font(21)
    f_small = font(20)
    f_note = font(18)

    dark = (32, 40, 52)
    blue = (232, 240, 250)
    green = (233, 246, 238)
    orange = (253, 242, 230)
    grey = (243, 244, 246)
    edge = (120, 132, 148)

    # 四列统一起点与宽度：140/470/800/1130，宽 300；最后一列宽 300
    COL = [(140, 300), (470, 300), (800, 300), (1130, 300)]

    def wrap(text: str, max_w: int, fs) -> list[str]:
        out = []
        for para in text.split("\n"):
            line = ""
            for ch in para:
                trial = line + ch
                if d.textlength(trial, font=fs) <= max_w or not line:
                    line = trial
                else:
                    out.append(line)
                    line = ch
            out.append(line)
        return out

    def box(col: int, y: int, h: int, text: str, fill, fs=f_box, w: int | None = None):
        x, base_w = COL[col]
        bw = w if w else base_w
        d.rounded_rectangle([x, y, x + bw, y + h], radius=10, fill=fill, outline=edge, width=2)
        lines = wrap(text, bw - 22, fs)
        lh = d.textbbox((0, 0), "字", font=fs)[3] + 5
        cy = y + (h - lh * len(lines)) // 2
        for ln in lines:
            bb = d.textbbox((0, 0), ln, font=fs)
            d.text((x + (bw - (bb[2] - bb[0])) // 2, cy), ln, font=fs, fill=dark)
            cy += lh

    def arrow(x1, y1, x2, y2):
        d.line([x1, y1, x2, y2], fill=edge, width=3)
        if y2 > y1:
            d.polygon([(x2 - 9, y2 - 12), (x2 + 9, y2 - 12), (x2, y2)], fill=edge)
        elif x2 > x1:
            d.polygon([(x2 - 12, y2 - 9), (x2 - 12, y2 + 9), (x2, y2)], fill=edge)

    d.text((W // 2 - 200, 24), "革兰氏染色虚拟仿真实验系统", font=f_title, fill=dark)
    d.text((W // 2 - 110, 70), "系统总体结构（V1.5）", font=f_note, fill=(90, 98, 110))

    # 入口层
    d.text((36, 122), "入口层", font=f_small, fill=(90, 98, 110))
    box(0, 110, 68, "主菜单 / 模式选择", blue)
    box(1, 110, 68, "中英文切换", blue)
    box(2, 110, 68, "设置\n画质 / 音量 / 色盲", blue)
    box(3, 110, 68, "存档 SimSettings", blue)

    # 模式层
    d.text((36, 232), "模式层", font=f_small, fill=(90, 98, 110))
    box(0, 220, 84, "引导学习\n步骤提示 + 理论 + 评分", green)
    box(1, 220, 84, "剧情模式\n林医生病例 + 随堂问答", green)
    box(2, 220, 84, "考核模式\n无提示 + 成绩单", green)
    box(3, 220, 84, "AI 助手「染染」\n答疑 / 分析 / 报告草稿", orange)

    # 实验流程层
    d.text((36, 366), "实验流程层", font=f_small, fill=(90, 98, 110))
    box(0, 354, 96, "制片阶段\n灭菌 · 取菌 · 涂片\n干燥 · 热固定", orange)
    box(1, 354, 96, "染色阶段\n初染 · 媒染\n脱色 · 复染 · 水洗", orange)
    box(2, 354, 96, "显微镜观察\n10×/40×/100× 油镜\n判定 G+/G−", orange, w=420)

    # 支撑层
    d.text((36, 494), "支撑层", font=f_small, fill=(90, 98, 110))
    box(0, 482, 92, "Unreal Engine 5.8\n蓝图 · 物理与动画系统", grey)
    box(1, 482, 92, "资源与媒体\n三维器材 · 立绘\n14 段演示视频", grey, w=300)
    box(2, 482, 92, "翻译表 Zh2En\n整句优先 · 片段兜底\n结果缓存", grey, w=420)

    # 数据层
    d.text((36, 618), "数据层", font=f_small, fill=(90, 98, 110))
    box(0, 606, 74, "本地存档\n语言 / 画质 / 音量", grey)
    box(1, 606, 74, "成绩单与错误记录\n（本地）", grey)
    box(2, 606, 74, "AI 接口配置\nDA_JJConfig", grey, w=420)

    # 纵向箭头
    arrow(290, 178, 290, 218)
    arrow(290, 304, 290, 352)
    arrow(620, 304, 620, 352)
    arrow(950, 304, 950, 352)
    arrow(290, 450, 290, 480)
    arrow(620, 450, 620, 480)
    arrow(950, 450, 950, 480)
    arrow(290, 574, 290, 604)
    arrow(620, 574, 620, 604)
    arrow(950, 574, 950, 604)

    d.text((140, 706),
           "注：核心交互逻辑以蓝图实现；可打印的自有代码为 73 个 Python 工具脚本"
           "（资源生成、文案替换、语言表导入、编辑器桥接）。",
           font=f_note, fill=(110, 118, 130))

    im.save(IMG / "fig-00-系统架构.png", quality=95)
    print("  %-26s → %-24s %dx%d" % ("（绘制）", "fig-00-系统架构.png", W, H))


if __name__ == "__main__":
    do_crops()
    draw_architecture()
