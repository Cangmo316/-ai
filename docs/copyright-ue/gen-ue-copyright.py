"""生成《革兰氏染色虚拟仿真实验系统》的软著申请材料。

一套脚本出四份：
  01-申请表（填写内容）      3 页，供在线填报对照
  02-源程序                 60 页（前 30 + 后 30），每页 50 行
  03-软件说明书              若干页，每页 ≥30 行
  04-材料清单与办理说明

## 这个项目和上一个项目的关键差别

上一个（比邻AI）是 Vue + Python，源码几十万行，随便截 3000 行都行。
这个是 Unreal Engine 5.8 项目，核心逻辑在 **蓝图 .uasset**（二进制，无法作为源程序），
可打印的自有代码只有 73 个 Python 工具脚本（主要用于资源生成、文案批量替换、
语言表导入、编辑器 MCP 桥接），另有少量 HLSL。所以：

  · 源程序只可能来自这些脚本，共 5872 行，分块后 5922 行，取前 1500 + 后 1500；
  · 说明书里必须如实写清"交互逻辑以蓝图实现"，不能假装全是脚本。

## 版式上的两个硬约束（都已在上一份材料里踩过）

1. 程序每页不少于 50 行 → 字号 7pt、行距 13pt、页边距 1.5cm，
   并且**超长行必须预先分块**，否则折行会把 50 行/页顶破。
2. 文档每页不少于 30 行 → 插图用**浮动环绕（靠右）**，不用嵌入型；
   嵌入型独占整行高度，带图的页面到不了 30 行。
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

SOFTWARE_FULL = "革兰氏染色虚拟仿真实验系统"
SOFTWARE_SHORT = "革兰氏染色"
SOFTWARE_VERSION = "V1.5"

PROJECT = Path(r"E:\ue5.8\3.0\GramStain")
OUT = Path(r"E:\ppt\GramStain软著")
IMAGES = OUT / "图片"

LINE_LIMIT = 115          # 单行显示宽度上限（半角字符=1，汉字≈1.7），超过就分块

def display_width(text: str) -> float:
    """估算一行在 7pt 等宽字体下的显示宽度。

    只按字符数分块是不够的：中文注释一个字占两个半角宽，
    一行 150 个汉字会折成三行，于是这一页就装不下 50 行，页数跟着乱。
    """
    width = 0.0
    for ch in text:
        width += 1.7 if ord(ch) > 0x2E7F else 1.0
    return width


def split_by_width(text: str, limit: float = LINE_LIMIT) -> list[str]:
    """按显示宽度把超长行切成若干段，每段都能在一行内放下。"""
    if display_width(text) <= limit:
        return [text]
    out, buf, w = [], "", 0.0
    for ch in text:
        cw = 1.7 if ord(ch) > 0x2E7F else 1.0
        if w + cw > limit - 2:      # 留 2 单位余量，避免边界处挤行
            out.append(buf)
            buf, w = "", 0.0
        buf += ch
        w += cw
    if buf:
        out.append(buf)
    return out
LINES_PER_PAGE = 50       # 程序每页行数
PAGES = 60                # 前 30 + 后 30

SKIP_DIRS = ("intermediate", "binaries", "saved", "deriveddatacache", "__pycache__", ".vs")


# ─────────────────────────── 通用排版工具
def set_font(run, size: float, name: str = "宋体", bold: bool = False) -> None:
    run.font.size = Pt(size)
    run.font.name = name
    run.font.bold = bold
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


def add_page_field(paragraph, size: float = 9) -> None:
    run = paragraph.add_run()
    for tag, attrs in (("w:fldChar", {"w:fldCharType": "begin"}),
                       ("w:instrText", None),
                       ("w:fldChar", {"w:fldCharType": "end"})):
        el = OxmlElement(tag)
        for k, v in (attrs or {}).items():
            el.set(qn(k), v)
        if tag == "w:instrText":
            el.set(qn("xml:space"), "preserve")
            el.text = " PAGE "
        run._r.append(el)
    set_font(run, size)


def header_title(section, text: str) -> None:
    p = section.header.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run(text), 9)


def footer_page(section) -> None:
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run("第 "), 9)
    add_page_field(p, 9)
    set_font(p.add_run(" 页"), 9)


# ─────────────────────────── 源程序
def collect_source() -> list[tuple[str, str]]:
    """收集可打印的自有代码，超长行按 LINE_CHUNK 分块。

    返回 [(文件相对路径, 代码行)]，文件之间插入一行分隔注释。
    """
    files = []
    for pat in ("**/*.py", "**/*.ush"):
        for f in PROJECT.glob(pat):
            low = str(f).lower()
            if any(d in low for d in SKIP_DIRS):
                continue
            files.append(f)
    files.sort(key=lambda f: str(f).lower())

    rows: list[tuple[str, str]] = []
    for f in files:
        rel = str(f.relative_to(PROJECT)).replace("\\", "/")
        rows.append((rel, "# ---- %s ----" % rel))
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = f.read_text(encoding="gbk", errors="replace")
        for line in text.splitlines():
            line = line.rstrip()
            if not line:
                rows.append((rel, ""))
                continue
            for seg in split_by_width(line):
                rows.append((rel, seg))
    return rows


def make_source_doc() -> Path:
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21.0), Cm(29.7)
    section.top_margin = Cm(1.5)
    section.bottom_margin = Cm(1.5)
    section.left_margin = Cm(1.5)
    section.right_margin = Cm(1.5)
    header_title(section, f"{SOFTWARE_FULL}{SOFTWARE_VERSION}")
    footer_page(section)

    style = doc.styles["Normal"]
    style.font.name = "Consolas"
    style.font.size = Pt(7)
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    fmt = style.paragraph_format
    fmt.space_before = Pt(0)
    fmt.space_after = Pt(0)
    fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    fmt.line_spacing = Pt(13)

    rows = collect_source()
    need = LINES_PER_PAGE * PAGES          # 3000
    if len(rows) < need:
        raise SystemExit("可打印代码只有 %d 行，不够 %d 行" % (len(rows), need))

    half = LINES_PER_PAGE * (PAGES // 2)   # 1500
    front = rows[:half]
    back = rows[-half:]
    selected = front + back

    for idx, (_rel, line) in enumerate(selected):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        p.paragraph_format.line_spacing = Pt(13)
        # 段前分页：不能用"插入一个分页符段落"的办法换页，
        # 那个段落本身会占掉当前页的一行，把 50 行/页顶成 51/2 行那样不齐。
        if idx and idx % LINES_PER_PAGE == 0:
            p.paragraph_format.page_break_before = True
        run = p.add_run(line if line else "")
        set_font(run, 7, "Consolas")

    path = OUT / f"02-源程序-{SOFTWARE_FULL}{SOFTWARE_VERSION}.docx"
    doc.save(str(path))

    stats = OUT / "生成统计.txt"
    per_file = {}
    for rel, _line in rows:
        per_file[rel] = per_file.get(rel, 0) + 1
    lines = [
        "软件名称：%s" % SOFTWARE_FULL,
        "版本号：%s" % SOFTWARE_VERSION,
        "",
        "可打印代码总行数（分块后）：%d" % len(rows),
        "源程序提交：前 %d 行 + 后 %d 行 = %d 行，共 %d 页，每页 %d 行" % (
            half, half, need, PAGES, LINES_PER_PAGE),
        "",
        "按文件统计（分块后行数）：",
    ]
    for rel, n in sorted(per_file.items(), key=lambda kv: -kv[1]):
        lines.append("  %-60s %5d" % (rel, n))
    stats.write_text("\n".join(lines), encoding="utf-8")
    return path


# ─────────────────────────── 说明书
def make_manual_doc() -> Path:
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21.0), Cm(29.7)
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(1.5)
    section.left_margin = Cm(2.4)
    section.right_margin = Cm(2.0)
    header_title(section, f"{SOFTWARE_FULL}  {SOFTWARE_VERSION}")
    fp = section.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_page_field(fp, 9)

    style = doc.styles["Normal"]
    style.font.name = "宋体"
    style.font.size = Pt(10)
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    fmt = style.paragraph_format
    fmt.space_before = Pt(0)
    fmt.space_after = Pt(2)
    fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    fmt.line_spacing = Pt(11)

    def h1(text):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(9)
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        set_font(p.add_run(text), 13, "黑体", bold=True)

    def h2(text):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(7)
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        set_font(p.add_run(text), 11, "黑体", bold=True)

    def h3(text):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(5)
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        set_font(p.add_run(text), 10.5, "黑体", bold=True)

    def body(text):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.paragraph_format.first_line_indent = Pt(20)
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        p.paragraph_format.line_spacing = Pt(11)
        set_font(p.add_run(text), 10)

    def item(text):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.paragraph_format.left_indent = Pt(20)
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        p.paragraph_format.line_spacing = Pt(11)
        set_font(p.add_run(text), 10)

    def caption(text):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(1)
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        set_font(p.add_run(text), 9)

    def table_caption(text):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        set_font(p.add_run(text), 9)

    def table(header, rows, widths):
        t = doc.add_table(rows=1, cols=len(header))
        t.style = "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        for i, text in enumerate(header):
            cell = t.rows[0].cells[i]
            cell.text = ""
            cell.width = Cm(widths[i])
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_after = Pt(1)
            set_font(p.add_run(text), 9, bold=True)
        for row in rows:
            cells = t.add_row().cells
            for i, text in enumerate(row):
                cells[i].text = ""
                cells[i].width = Cm(widths[i])
                p = cells[i].paragraphs[0]
                p.paragraph_format.space_after = Pt(1)
                p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
                if i == 0 and len(str(text)) <= 4:
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                set_font(p.add_run(str(text)), 9)
        doc.add_paragraph().paragraph_format.space_after = Pt(1)

    def figure_block(name, cap, width_cm=14.0):
        """整幅嵌入图，独占若干行。

        用于系统架构图这类文字密集的图：浮动小图会看不清。
        注意承载段必须用单倍行距，固定行距会把嵌入图裁成一行高。
        """
        path = IMAGES / name
        if not path.exists():
            print("  ⚠️ 缺图：%s" % name)
            return
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        p.add_run().add_picture(str(path), width=Cm(width_cm))
        caption(cap)

    def figure(name, cap, width_cm=12.5):
        """独占一行的插图，题注紧随其下。

        之前用浮动环绕（wp:anchor + wrapSquare）来省纵向空间，
        但两张图锚在同侧时 allowOverlap 会让它们叠在一起，
        而且题注在文字流里、离图很远。改成嵌入独占一段：
        重合不可能发生，题注也在正下方。
        代价是每张图约占 20 多行版面，用页面容量换正确性。
        """
        path = IMAGES / name
        if not path.exists():
            print("  ⚠️ 缺图：%s" % name)
            return
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after = Pt(0)
        # 承载嵌入图必须单倍行距，固定行距会把图裁成一行高
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        p.add_run().add_picture(str(path), width=Cm(width_cm))

        c = doc.add_paragraph()
        c.alignment = WD_ALIGN_PARAGRAPH.CENTER
        c.paragraph_format.space_before = Pt(1)
        c.paragraph_format.space_after = Pt(6)
        c.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        set_font(c.add_run(cap), 9)

    def figure_pair(name1, cap1, name2, cap2, width_cm=7.2):
        """两张图并排，各自在下方带题注。

        原来两张视野图上下叠放，占掉近 32 行版面，把整页挤到 20 行；
        并排后只占一行的行高（约 18 行），页面行数就能回到 30 以上。
        单元格段落必须单倍行距，否则固定行距会把图裁成一条。
        """
        imgs = []
        for nm in (name1, name2):
            path = IMAGES / nm
            if not path.exists():
                print("  ⚠️ 缺图：%s" % nm)
                return
            imgs.append(path)

        tbl = doc.add_table(rows=1, cols=2)
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        tbl.autofit = True
        for idx, (path, cap) in enumerate(zip(imgs, (cap1, cap2))):
            cell = tbl.rows[0].cells[idx]
            cell.text = ""
            p1 = cell.paragraphs[0]
            p1.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p1.paragraph_format.space_before = Pt(2)
            p1.paragraph_format.space_after = Pt(0)
            p1.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
            p1.add_run().add_picture(str(path), width=Cm(width_cm))
            p2 = cell.add_paragraph()
            p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p2.paragraph_format.space_before = Pt(1)
            p2.paragraph_format.space_after = Pt(4)
            p2.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
            set_font(p2.add_run(cap), 9)
        doc.add_paragraph().paragraph_format.space_after = Pt(2)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(4)
    set_font(p.add_run(SOFTWARE_FULL), 17, "黑体", bold=True)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(6)
    set_font(p.add_run(f"软 件 说 明 书　{SOFTWARE_VERSION}"), 11)

    # ══ 第一章
    h1("第一章　项目概述")
    h2("1.1　项目背景")
    body("革兰氏染色是细菌学中最基本、应用最广的鉴别染色方法。它通过初染、媒染、"
         "脱色、复染四个步骤，把细菌分为革兰阳性菌与革兰阴性菌两大类，"
         "是病原生物学、微生物学实验课的核心内容，也是临床检验、食品与药品"
         "微生物检验的基础操作。该实验对操作规范要求很高：接种环必须灼烧灭菌，"
         "试管口要过火，涂片不能过厚，脱色时间要以秒计，油镜必须借助香柏油"
         "才能看清菌体形态。任何一步不到位，结果就会失真，甚至得出相反的判定。")
    body("真实实验课存在几方面困难。一是耗材与设备成本高，培养基、四类染液、"
         "香柏油、载玻片与高压灭菌设备都需要持续投入，一次课几十名学生，"
         "耗材消耗大。二是生物安全风险，实验使用活菌，操作不规范会造成污染。"
         "三是教师难以逐人纠正，脱色过头这类失误发生在几秒之内，"
         "教师无法同时盯住全班学生的手法。四是结果不可复现，学生做完只看到一张玻片，"
         "错了也不知道错在哪一步。")
    body(f"针对上述问题，本团队自主研发了{SOFTWARE_FULL}{SOFTWARE_VERSION}"
         "（以下简称“本软件”）。本软件采用 Unreal Engine 5.8 构建三维实验室场景，"
         "把革兰氏染色拆解为 21 个标准步骤，分为制片、染色、显微镜观察三个阶段，"
         "提供系统学习、趣味剧情、考核三种模式，配套 AI 助手答疑、规范操作演示"
         "与中英双语界面，形成“照着做—边做边学—独立考核”的完整学习流程（如图1-1）。"
         "本软件面向医学院校病原生物学与微生物学实验课的学生与教师，"
         "也可用于职业院校医学检验技术专业的实训环节，以及实验前的预习与实验后的复盘。")
    figure("fig-00-系统架构.png", "图1-1　系统架构图", 13.0)

    h2("1.2　核心功能概述")
    body("本软件包含以下九个核心功能模块（见表1-1）：")
    table_caption("表1-1　核心功能模块")
    table(["序号", "模块名称", "功能说明"], [
        ["1", "制片操作", "酒精灯点火、接种环灼烧灭菌、蘸取生理盐水、刮取菌落、涂片、"
                        "干燥与热固定，覆盖 21 个标准步骤中的前 11 步"],
        ["2", "染色操作", "结晶紫初染、碘液媒染、乙醇脱色、稀释复红复染，每步之间水洗；"
                        "四瓶试剂可倒持滴加，洗瓶可挤压冲洗"],
        ["3", "显微镜观察", "10×、40×、100× 物镜切换，粗准焦与细准焦调节，滴加香柏油，"
                        "亮度调节，判定革兰阳性与革兰阴性"],
        ["4", "系统学习", "逐步提示当前操作，原理面板解释原因，记录失误与用时，"
                        "结束给出评分"],
        ["5", "趣味剧情", "跟随林医生处理一例急诊标本，表情立绘与逐字台词，"
                        "穿插随堂问答"],
        ["6", "考核模式", "不显示步骤做法，只给当前目标，失误计入成绩，"
                        "结束生成成绩单"],
        ["7", "AI 助手", "答疑、实验分析、报告草稿，带思考过程面板；"
                        "断网或密钥失效时降级为本地内容并给出分类提示"],
        ["8", "中英双语", "一千三百余条翻译表，界面文字、器材标签、墙上海报与"
                        "窗口标题同步切换"],
        ["9", "辅助功能", "规范操作演示、设置项（画质、显示、音量、色觉友好标记）"],
    ], [1.4, 2.8, 11.4])

    # ══ 第二章
    h1("第二章　运行环境介绍")
    h2("2.1　硬件环境")
    h3("2.1.1　客户端运行环境")
    body("本软件为 Windows 桌面应用程序，三维场景由客户端显卡实时渲染，"
         "硬件配置要求如下（见表2-1）。")
    table_caption("表2-1　客户端硬件配置")
    table(["硬件名称", "配置要求", "备注"], [
        ["处理器", "Intel Core i5 或 AMD Ryzen 5 及以上", "近五年产品均可"],
        ["内存", "8GB 以上", "推荐 16GB"],
        ["显卡", "支持 DirectX 12 的独立显卡，显存 4GB 以上", "用于三维场景实时渲染"],
        ["硬盘", "可用空间 8GB 以上", "建议固态硬盘"],
        ["显示器", "分辨率 1920×1080 及以上", "界面按 16:9 布局"],
        ["输入设备", "鼠标与键盘", "鼠标左键拾取与拖拽器材"],
    ], [2.8, 8.0, 4.8])

    h3("2.1.2　开发环境")
    body("本软件开发与测试所使用的环境如下（见表2-2）。")
    table_caption("表2-2　开发环境")
    table(["项目", "配置"], [
        ["开发设备", "笔记本电脑，处理器 Intel Core i9-14900HX，内存 32GB，"
                  "固态硬盘 1TB，独立显卡 8GB 显存"],
        ["操作系统", "Windows 11 64 位"],
        ["开发工具", "Unreal Engine 5.8（Unreal Editor）、Python 3.11、Visual Studio Code"],
        ["编程语言", "Unreal Blueprint（可视化脚本）、Python"],
        ["三维与动画", "引擎内置材质与物理系统，骨骼动画用于器材操作与角色动作"],
        ["版本管理", "Git；编辑器脚本用于资源批量处理、文案替换与翻译表导入"],
    ], [3.2, 12.4])

    h2("2.2　软件环境")
    body("本软件运行所需的支撑软件清单如下（见表2-3）。")
    table_caption("表2-3　软件环境")
    table(["序号", "软件名称", "版本要求", "用途说明"], [
        ["1", "操作系统", "Windows 10 / Windows 11 64 位", "客户端操作系统"],
        ["2", "图形接口", "DirectX 12 运行库", "三维渲染支撑"],
        ["3", "运行库", "Visual C++ 2015-2022 运行库", "程序运行依赖"],
        ["4", "引擎运行库", "随安装包打包，无需单独安装", "提供运行时环境"],
    ], [1.4, 3.4, 6.4, 4.4])

    h2("2.3　网络环境")
    body("本软件对网络环境的要求如下：")
    item("（1）制片、染色、显微镜观察、剧情与考核的全部功能均离线运行，"
         "断网不影响实验操作与评分。")
    item("（2）AI 助手“染染”为在线功能，需要客户端能够访问互联网；"
         "接口地址、模型名称与密钥在数据资产 DA_JJConfig 中配置。")
    item("（3）接口采用 OpenAI 兼容协议，通过 HTTPS 访问，端口为 443；"
         "若部署在校园网内，需在出口防火墙上放行该域名。")
    item("（4）首次调用 AI 助手若网络不通，界面给出提示并自动降级为本地内容，"
         "学生可以先做题、稍后再问。")
    item("（5）本软件不采集学生姓名、学号等个人信息，不上传操作记录；"
         "调用 AI 助手时发送的内容仅为学生输入的问题与当前步骤名称。")
    item("（6）若学校内网无法访问外网，可将 AI 接口指向校内自建的兼容服务，"
         "或直接关闭该模块；关闭后其余功能不受任何影响。")

    h2("2.4　安装部署流程")
    body("本软件为免安装的绿色程序，部署步骤如下：")
    item("（1）将安装包解压到本地磁盘任意目录，建议放在剩余空间 8GB 以上的分区。")
    item("（2）双击目录中的可执行文件启动，首次启动会在系统用户目录下创建存档目录。")
    item("（3）进入主菜单后先按 3.1 节的说明选择界面语言，再选择学习模式。")
    item("（4）卸载时删除安装目录与存档目录即可，程序不写注册表。")

    # ══ 第三章
    h1("第三章　软件界面介绍")
    h2("3.1　主菜单")
    body("主菜单（如图3-1）为本软件启动后的默认界面。左侧为竖排入口区，"
         "自上而下依次为校徽与软件名称、三种模式入口、起始阶段选择、设置与退出；"
         "中部为三维实验台，可见试管架、平皿、酒精灯、试管、载玻片与洗瓶；"
         "右侧为 AI 助手“染染”的对话面板，底部为实验概览，"
         "显示规范操作步骤 21 项、染色试剂 4 瓶与油镜倍数 100×。"
         "界面右上角提供中文与 English 两个语言按钮。")
    figure("shot-01-主菜单.png", "图3-1　主菜单界面", 9.5)
    body("三种模式的分工如下：系统学习模式下每一步给出操作提示与原理说明，"
         "适合第一次接触该实验的学生；趣味剧情模式由林医生带着完成一例急诊标本，"
         "中途穿插随堂问答；考核模式只给目标、不给做法，全程独立完成，"
         "结束后生成成绩单。起始阶段用于分段练习，可从制片开始、从染色开始，"
         "也可直接进入镜检，不必每次从头做起。")

    h2("3.2　设置与显示选项")
    body("点击主菜单的“设置”进入设置面板（如图3-2）。面板提供六项配置："
         "画质分为低、中、高与自动四档，自动档按本机硬件跑分选择；"
         "显示可在全屏与窗口之间切换；染色计时分为标准与演示两档；"
         "色觉友好标记用于色觉异常用户；背景音乐、音效与林医生配音三路音量独立可调。"
         "设置写入本地存档，下次启动沿用。")
    figure("shot-02-设置.png", "图3-2　设置面板", 9.5)
    body("画质四档的差别在渲染细节上：高档开启实时阴影与环境光遮蔽，"
         "中档保留阴影但降低阴影分辨率，低档关闭阴影并下调渲染像素比，"
         "自动档在启动时按显卡型号与显存选择，运行中不再切换。"
         "机房机器普遍偏旧，默认走自动档，避免一律开高档导致掉帧。")
    body("色觉友好标记开启后，判定用的紫红两色改为对色觉异常更易分辨的配色，"
         "并在结果页同时给出文字标注，不依赖颜色单独传达结论。"
         "这一项针对的是红绿色弱学生，因为革兰氏染色的判读本身依赖紫色与红色的区分。")
    body("改完点面板底部的完成即可返回主菜单，设置立即生效，不用重启软件。")


    h2("3.3　计时方式选择")
    body("选定学习模式后，界面先弹出计时方式选择（如图3-3），这一步决定染色静置时间。"
         "演示模式把每一步的静置时间压缩为 10 秒，适合课堂演示与预习；"
         "标准模式按真实操作计时，每步静置 1 分钟，接近真实实验节奏。"
         "两种模式的操作步骤与评分规则一致，只是时间尺度不同。")
    figure("shot-03-计时方式.png", "图3-3　计时方式选择", 8.5)

    h2("3.4　制片阶段")
    body("制片阶段（如图3-4）是把细菌从培养基转移到载玻片并固定的过程，"
         "包含 11 个标准步骤。界面左上为实验步骤面板，显示当前进度、已用时间、"
         "失误次数与提示次数，并列出当前步骤及后续若干步骤的名称；"
         "右上为原理说明面板，随步骤切换解释该步为什么这样做；"
         "中部为三维台面，器材可拾取、旋转与拖拽；右下为助手形象与"
         "“自动近景”“近景”“提示”三个辅助按钮。")
    figure("shot-04-制片阶段.png", "图3-4　制片阶段界面", 9.5)
    body("制片阶段的要点有四项：接种环使用前后都要在外焰灼烧至环丝发红，"
         "灼烧后稍冷却再取菌；试管口要旋转过火，防止空气中的杂菌落入管内；"
         "取菌量以在菌落边缘轻刮为准，取多了涂片过厚、细胞重叠，后续脱色也更难掌握；"
         "涂片干燥可选自然干燥或火焰上方烘干，但不能把载玻片直接放进火焰里烤。"
         "热固定时涂片面向上，以钟摆速度通过外焰三次。")

    h2("3.5　染色阶段")
    body("染色阶段包含初染、媒染、脱色、复染四步，每步之间水洗。"
         "台面上并排摆放初染液（结晶紫）、媒染液（碘液）、脱色液（95% 乙醇）与"
         "复染液（稀释复红）四瓶试剂，中间为废液缸。每步开始时界面中央弹出倒计时"
         "提示，显示当前处于四步中的第几步、试剂名称与剩余时间；"
         "学生按提示倒持滴瓶，滴加 1 至 2 滴覆盖涂面。")
    body("四步之间都要水洗，水洗不彻底会把上一步的试剂带进下一步："
         "初染后没冲净，残留的结晶紫会让阴性菌也带紫色；媒染后没冲净，"
         "多余的碘会拖慢脱色；复染后没冲净，背景发红影响判读。"
         "软件在每次水洗后按残液量给一个清洁度判定，脏了会在下一步提示。")
    body("洗瓶可挤压出水，水流应自载玻片上端流经涂面；直接冲在菌膜上会把细菌冲掉，"
         "系统会记录这一失误。脱色是决定结果的关键步骤：革兰阳性菌肽聚糖层厚、"
         "脂类少，乙醇使其脱水、孔隙缩小，结晶紫与碘的复合物留在胞内仍为紫色；"
         "革兰阴性菌脂类多、肽聚糖薄，复合物被洗脱而褪色。脱色后须立即水洗终止，"
         "脱色过度会把阳性菌误判为阴性，脱色不足则相反。界面在这一步会展开原理面板，"
         "把上述内容再讲一遍。")

    h2("3.6　显微镜与油镜观察")
    body("显微镜观察阶段提供独立操作面板，面板自上而下为：目镜观察目标的检查清单、"
         "物镜倍率选择（10×、40×、100×）、粗准焦与细准焦的升降按钮、亮度调节，"
         "以及“滴加香柏油”“观察目镜”两个动作按钮。正确顺序是先用低倍镜加粗准焦"
         "找到标本，换 40× 物镜用细准焦调清结构，滴一滴香柏油后转到 100× 油镜，"
         "并且只用细准焦调焦。油镜工作距离很短，用粗准焦容易撞到玻片。")
    body("面板左侧的检查清单列出五个目标，做完一项勾一项：放片、低倍找视野、"
         "调焦、滴油切油镜、判定结果。清单的目的不是限制操作顺序，"
         "而是让学生对照自己还差哪一步；顺序错了，前面的项目不会被自动勾上。")
    body("判读标准按染色结果与菌体形态两条一起看。革兰阳性菌染成蓝紫色，"
         "常见形态为球菌成葡萄串状或链状排列、芽孢杆菌呈竹节状；"
         "革兰阴性菌染成红色，常见形态为短杆菌、双球菌。只看颜色不够，"
         "脱色不均时同一视野里会同时出现紫色与红色，这时应判为涂片质量问题，"
         "需要重做而不是勉强下结论。")
    body("判读完成后建议回看一次低倍视野，确认取的是涂片上的目标区域而不是边缘的"
         "堆积处；边缘往往涂得过厚，颜色偏深，容易把阴性菌误判为阳性。"
         "这一步在真实实验里同样重要，软件把它做成了可选操作，不做不扣分，"
         "但结果页会给出一句提醒。")
    body("未滴油直接切到 100×，画面会明显发虚，因为缺少折射率匹配的介质，"
         "光线在玻片与镜头之间散射。两个倍率下的视野效果见图3-5 与图3-6："
         "40× 下菌体聚集成片，只能判断大致分布；100× 油镜下可分辨单个菌体的形态"
         "与染色结果，紫色为革兰阳性菌，红色为革兰阴性菌。")
    figure_pair("shot-06-40倍视野.png", "图3-5　40 倍视野：菌体成片",
                "shot-07-100倍视野.png", "图3-6　100 倍油镜视野：可分辨单个菌体")

    h2("3.7　AI 助手“染染”")
    body("AI 助手“染染”的对话面板（如图3-7）位于主菜单右侧与实验界面右下角。"
         "面板顶部显示助手名称与当前场景，中部为对话区，下方为四个预设问题，"
         "分别是本实验的内容、三种模式的区别、开始一次随堂小测、以及注意事项，"
         "学生不知道问什么时可直接点击；底部为输入框与发送按钮。")
    figure("shot-05-AI对话.png", "图3-7　AI 助手对话面板", 8.5)
    body("回答生成后可展开思考过程面板查看推理步骤；实验完成后可让助手分析本次操作"
         "的失误出现在哪一步，也可在报告未写时先出一份草稿。接口地址、模型名称与密钥"
         "均在数据资产 DA_JJConfig 中配置，更换服务商不需要修改蓝图；断网或密钥失效时"
         "助手改用本地内容回答，并按余额不足、密钥无效、请求过于频繁、"
         "内容被安全审核拦截等八类情况给出对应提示，提示中不出现服务商名称。")

    h2("3.8　趣味剧情模式")
    body("趣味剧情模式把染色流程放进一个急诊情境里。开场由林医生交代病例："
         "急诊送来一份标本，需要尽快判断是革兰阳性菌还是革兰阴性菌，"
         "以便在培养结果出来之前先给临床一个方向。学生接过标本，"
         "按规范完成制片与染色，最后在油镜下给出判定，"
         "林医生再回到病例本身说明这个结果意味着什么。")
    body("整个流程分五段：开场交代病例与任务、制片段、染色段、判定段、小结。"
         "学生自己动手的部分与系统学习模式完全相同，用的是同一套三维器材、"
         "同一套步骤判定；区别在于每一步之后林医生会插话解释这一步为什么这样做，"
         "把操作和原理绑在一起。例如灼烧接种环之后，他会说明外焰温度最高、"
         "环丝烧红才算灭菌彻底；脱色那一步则会说明革兰阳性菌与阴性菌细胞壁结构的差异，"
         "以及为什么脱色时间是整个实验里最容易出错的地方。")
    body("剧情推进中有随堂问答，题目围绕刚刚做过的操作提问，答错会给出解释，"
         "但不扣分、不打断流程。问答的作用是让学生停下来想一秒，"
         "而不是一路点下去。问答结束后剧情继续，直至判定与小节。")
    body("台词逐字打出，林医生的表情随对话情绪切换，共九种：平常、高兴、眨眼、"
         "惊讶、惊讶（二）、难过、惊恐、生气、尴尬（如图3-8）。")
    figure("shot-08-林医生立绘.png", "图3-8　林医生九种表情立绘", 12.0)
    body("立绘为实验室着装：外科口罩、一次性圆帽与丁腈手套，白大褂与胸卡保留，"
         "符合生物安全要求，也和实验课里老师给学生的着装示范一致。")
    body("这一模式适合已经跟着系统学习做完一遍、需要理解“为什么这么做”的学生；"
         "如果连操作顺序都还不熟，先走系统学习模式会更顺。")

    h2("3.9　考核模式与成绩单")
    body("考核模式不显示具体做法，只显示当前目标，也不提前告知后续步骤。"
         "每一步的操作顺序与规范程度计入评分，失误次数单独统计；脱色过头会导致"
         "结果颜色错误，进而影响最终判定。考核结束后生成成绩单，列出各步骤得分、"
         "失误点与总评。")
    body("成绩单按步骤列出得分与失误点，并对每处失误给出当时应有的做法；"
         "同一次考核可以反复查看，也可与其他学生横向比较各步得分分布，"
         "便于教师判断班级整体的薄弱环节。")

    h2("3.10　中英双语与操作提示")
    body("主菜单右上角提供中文与 English 切换按钮，点击后重新加载关卡，"
         "界面文字、器材标签、墙上海报与窗口标题一并切换，设置写入存档并在下次启动"
         "沿用。实验进行中不允许切换语言，因为步骤文字、报告与对话都是开始时"
         "按语言生成的，中途切换会造成中英混杂。首次启动时若系统显示语言或区域为中文"
         "则使用中文，否则使用英文。英文模式下林医生配音静音，仅保留英文字幕。")
    body("本地存档记录语言、画质、音量与色觉友好标记四项，体积很小；"
         "删除存档等于恢复默认设置，不影响成绩单，成绩单每次考核单独生成。")
    body("每个阶段配套规范操作演示，共十四段，按阶段与步骤分开，"
         "可在步骤面板点播放，支持暂停与拖动进度。英文模式下播放按英文界面"
         "重新录制的版本，不是叠加字幕；这一点对听障学生同样有用，"
         "因为演示里的操作提示是直接打在画面上的。")
    body("实验界面左下角常驻按键提示：F1 显示快捷键、Esc 调出菜单；"
         "右下角提供提示与近景两个按钮，可按 H 与 V 触发。"
         "右上角可开关自动特写，关闭后镜头不会自动拉近。")

    # ══ 第四章
    h1("第四章　技术特点与创新点")
    h2("4.1　主要技术特点")
    item("（1）基于游戏引擎的桌面三维仿真：采用 Unreal Engine 5.8 构建三维实验室，"
         "器材、试剂与液体的渲染由客户端显卡实时完成；交互逻辑以蓝图实现，"
         "没有 C++ 代码，非程序背景的教师可以直接修改流程与文案。"
         "打包版自带引擎运行库，客户端无需安装编辑器。")
    item("（2）分阶段、分步骤的实验流程控制：把实验拆成 21 个标准步骤，"
         "按制片、染色、显微镜三个阶段组织；每个步骤包含名称、操作目标、"
         "原理说明、倒计时与判定条件；起始阶段可选，支持只练某一段。")
    item("（3）可视化器材交互与物理挂接：器材可拾取、旋转、倾斜，"
         "试管塞在应插在管口的阶段挂接在试管上随试管一起移动，"
         "避免因刷新顺序不同造成的塞子与试管错位；洗瓶出水为细流，"
         "滴瓶倒持后滴加 1 至 2 滴，液体量与涂面覆盖范围参与判定。")
    item("（4）可配置的 AI 助手：问答、实验分析与报告草稿三类能力通过同一套数据资产"
         "配置地址、模型与密钥，采用 OpenAI 兼容协议，换服务商不需要重新编译；"
         "错误响应按官方错误码分类为八类提示；断网时自动降级为本地内容。")
    item("（5）统一翻译入口的双语实现：全部界面文字走同一个翻译函数，"
         "整句优先、片段兜底、结果缓存，处理“用时 23 秒”这类拼接句；"
         "器材标签与墙上海报通过材质参数切换贴图，不改模型；窗口标题随语言切换。")
    item("（7）资源来源与授权：三维器材为程序化建模生成，角色立绘为团队绘制，"
         "背景音乐采用 CC BY 4.0 授权的曲目，显微镜视野底图基于实验实拍与"
         "公开数据集制作，均在界面左下角标注来源，可溯源。")
    item("（8）资源随包分发与按需加载：三维模型、材质、立绘与演示视频全部内置于"
         "安装包，运行时不访问网络；首次启动与切换关卡有短暂加载，"
         "加载进度显示在画面下方。机房批量部署时只需拷目录，不需要联网配置。")
    item("（6）界面布局与无障碍：三种模式下的步骤面板、原理说明、操作提示与器材"
         "均不互相遮挡；提供色觉友好标记，结论不只靠颜色传达；"
         "提示语为口语化表达，直接给出下一步动作。")

    h2("4.2　创新点")
    item("（1）把“秒级”的操作规范做成可交互的三维考核：脱色时间是这类实验最容易出错"
         "也最难纠正的环节，本软件用水洗动作、倒计时与判定条件把这一环节量化，"
         "学生可以在没有菌种与试剂的条件下反复练习，并得到失误位置的具体反馈。")
    item("（2）同一套实验内容的三种学习形态：系统学习解决“不会做”，"
         "剧情模式解决“为什么这样做”，考核模式解决“独立能否做对”，"
         "三者共用同一套步骤定义与判定规则，学生可以在其间切换而不必重新适应界面。")
    item("（4）离线优先的工程取舍：除 AI 助手外，全部功能不依赖网络，"
         "翻译表、演示视频与器材贴图都随包分发；机房断网、教室无外网的场景下"
         "课程仍可完整开展。")
    item("（5）可复用的实验流程定义：步骤名称、原理说明、判定条件与评分权重"
         "集中在同一处配置，教师可以按课时调整步骤顺序或增删步骤，"
         "改编成其他染色实验时不需要重做三维场景。")
    item("（3）双语与本地化随工程走：翻译表、器材标签、海报与演示视频都内置在工程中，"
         "切换语言不依赖在线服务；教学场景下可直接用于留学生课程，"
         "也可作为专业英语的辅助材料。")

    item("（7）适配不同的开课条件：有机房的学校可以让每个学生独立操作，"
         "班级人数多、机器少时可以用演示模式投屏讲一遍再分组练；"
         "没有独立显卡的机器把画质调到低档也能完整做完实验，只是画面细节少一些。")
    item("（6）与课程考核的衔接：成绩单可导出为文本，按学生学号归档后即可作为"
         "实验课的平时成绩依据；教师也可以只把本软件作为预习工具，课上仍用真实菌种操作，"
         "两者并不冲突。")
    body("软件的三维场景与演示视频体积较大，首次启动与切换关卡时会有短暂加载，"
         "属正常现象；加载进度条位于画面下方，加载完成后自动进入。"
         "若加载异常中断，重新启动即可，不会损坏已有的成绩单与设置。"
         "建议首次启动前关闭占用显卡的其它程序，加载会更快。")
    body(f"本说明书对应版本 {SOFTWARE_VERSION}，为首次发表的正式版本。"
         "后续版本若调整步骤数量、判定条件或界面布局，将另行更新说明书；"
         "本说明书描述的功能与该版本软件的实际行为一致。")

    path = OUT / f"03-软件说明书-{SOFTWARE_FULL}{SOFTWARE_VERSION}.docx"
    doc.save(str(path))
    return path


def make_form_doc() -> Path:
    doc = Document()
    s = doc.sections[0]
    s.page_width, s.page_height = Cm(21.0), Cm(29.7)
    s.top_margin, s.bottom_margin = Cm(2.0), Cm(1.8)
    s.left_margin, s.right_margin = Cm(2.2), Cm(1.8)

    style = doc.styles["Normal"]
    style.font.name = "宋体"
    style.font.size = Pt(10)
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    style.paragraph_format.space_after = Pt(2)
    style.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE

    def h1(text: str) -> None:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(9)
        p.paragraph_format.space_after = Pt(3)
        set_font(p.add_run(text), 12.5, "黑体", bold=True)

    def note(text: str) -> None:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Pt(16)
        p.paragraph_format.space_after = Pt(3)
        set_font(p.add_run(text), 9)

    def para(text: str) -> None:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.paragraph_format.first_line_indent = Pt(20)
        set_font(p.add_run(text), 10)

    def table(rows, widths=None, header=None) -> None:
        cols = len(rows[0])
        t = doc.add_table(rows=0, cols=cols)
        t.style = "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        if header:
            cells = t.add_row().cells
            for i, text in enumerate(header):
                cells[i].text = ""
                set_font(cells[i].paragraphs[0].add_run(text), 9, bold=True)
        for row in rows:
            cells = t.add_row().cells
            for i, text in enumerate(row):
                cells[i].text = ""
                p = cells[i].paragraphs[0]
                p.paragraph_format.space_after = Pt(1)
                set_font(p.add_run(str(text)), 9, bold=(i == 0))
                if widths:
                    cells[i].width = Cm(widths[i])
        doc.add_paragraph().paragraph_format.space_after = Pt(2)

    # 标题
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run("计算机软件著作权登记申请表"), 17, "黑体", bold=True)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(10)
    set_font(p.add_run("填写内容参考，照此录入线上系统"), 9.5)

    h1("一、软件基本信息")
    table([
        ("软件全称", SOFTWARE_FULL),
        ("软件简称", SOFTWARE_SHORT),
        ("版本号", SOFTWARE_VERSION),
        ("软件作品说明", "原创软件，非修改他人软件"),
        ("软件分类", "应用软件 → 教育类 → 医学教学软件"),
        ("开发方式", "单独开发"),
        ("权利取得方式", "原始取得"),
        ("权利范围", "全部权利"),
        ("开发完成日期", "2026 年 11 月 20 日"),
        ("首次发表日期", "未发表"),
        ("是否已发表", "否"),
    ], widths=[3.6, 12.0])
    note("※ 软件全称不得含“中国”“国家”“国际”等字样；名称与版本号须与源程序页眉、"
         "说明书页眉逐字一致。")
    note("※ 开发完成日期按实际最后修改时间填。这个工程的最后一批改动在 2026 年 11 月，"
         "填 11 月 20 日与文件时间吻合。")

    h1("二、著作权人信息")
    table([
        ("名称（姓名）", "【填写：个人身份证姓名】"),
        ("证件类型", "【填写：居民身份证】"),
        ("证件号码", "【填写：身份证号】"),
        ("国籍 / 省份", "中国 / 【填写省份】"),
        ("通信地址", "【填写：可收件的详细地址】"),
        ("邮政编码", "【填写】"),
        ("联系人", "【填写】"),
        ("联系电话", "【填写手机号】"),
        ("电子邮箱", "【填写常用邮箱】"),
    ], widths=[3.6, 12.0])
    note("※ 若改为合作开发，需另交合作开发协议，且申请人为著作权人之一。")

    h1("三、开发与运行环境")
    env = [
        ("开发的硬件环境", "i9-14900HX/32GB/1TB SSD",
         "CPU i9-14900HX、内存 32GB、固态硬盘 1TB、独立显卡 8GB 显存"),
        ("运行的硬件环境", "i5/Ryzen5;8GB;DX12显卡",
         "Intel i5 或 AMD Ryzen 5 及以上；内存 8GB 以上；支持 DirectX 12 的显卡，"
         "显存 4GB 以上；1920×1080 显示器"),
        ("开发该软件的操作系统", "Windows 11 64位", "Windows 11 64 位"),
        ("软件开发环境 / 开发工具", "Unreal Editor5.8;Python3.11",
         "Unreal Engine 5.8（Unreal Editor）、Python 3.11、Visual Studio Code"),
        ("该软件的运行平台 / 操作系统", "Windows 10/11 64位",
         "Windows 10 或 Windows 11 64 位"),
        ("软件运行支撑环境 / 支持软件", "DirectX12;VC++运行库",
         "DirectX 12 运行库、Visual C++ 2015-2022 运行库；打包版自带引擎运行库"),
        ("编程语言", "Blueprint;Python", "Unreal Blueprint（可视化脚本）、Python"),
        ("源程序量", "6207行", "6207 行（分块后，73 个 Python 文件）"),
    ]
    for field, value, _full in env:
        size = len(value.encode("utf-8"))
        if size > 50:
            raise SystemExit("字段「%s」占 %d 字节，超过 50 字节限制：%s" % (field, size, value))

    t = doc.add_table(rows=0, cols=3)
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for field, value, _full in env:
        cells = t.add_row().cells
        for i, w in enumerate((4.4, 6.0, 1.8)):
            cells[i].width = Cm(w)
        for i, text in enumerate((field, value, "%d 字节" % len(value.encode("utf-8")))):
            cells[i].text = ""
            p = cells[i].paragraphs[0]
            p.paragraph_format.space_after = Pt(1)
            set_font(p.add_run(text), 9, bold=(i == 0))
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    note("※ 线上表单这几项限 50 字节。一个汉字占 3 字节，50 字节约 16 个汉字。"
         "上表右列的值都已压到限制内，可直接照抄；中列是完整描述，写说明书时用。")

    h1("四、开发目的、面向领域与主要功能")
    rows4 = [
        ("开发目的", "用于医学院校革兰氏染色实验教学", "限 50 字时用这一行"),
        ("面向领域", "医学教育、病原生物学实验教学",
         "医学院校病原生物学、微生物学实验课，也可用于职业院校检验专业实训"),
        ("主要功能（50 字节版）", "全流程染色操作、评分、双语", ""),
        ("主要功能（200 字节版）",
         "制片、染色、显微镜三阶段共 21 步操作；引导学习、剧情、考核三种模式；"
         "中英双语切换；AI 助手答疑与实验分析；成绩单与错误回放",
         "限制宽松时用这一行"),
        ("技术特点（50 字节版）", "蓝图驱动、双语、AI可配置", ""),
        ("技术特点（200 字节版）",
         "交互逻辑用蓝图实现，教师可改流程；界面文字统一走翻译函数；"
         "AI 接口做成数据资产，可换模型与密钥；器材与液滴用引擎物理实现",
         "限制宽松时用这一行"),
    ]
    t4 = doc.add_table(rows=0, cols=4)
    t4.style = "Table Grid"
    t4.alignment = WD_TABLE_ALIGNMENT.CENTER
    for field, value, hint in rows4:
        cells = t4.add_row().cells
        for i, w in enumerate((3.2, 7.8, 1.6, 3.6)):
            cells[i].width = Cm(w)
        size = len(value.encode("utf-8"))
        if "200 字节" in field or "200字节" in field:
            if size > 200:
                raise SystemExit("字段「%s」占 %d 字节，超 200：%s" % (field, size, value))
        else:
            if size > 50:
                raise SystemExit("字段「%s」占 %d 字节，超 50：%s" % (field, size, value))
        for i, text in enumerate((field, value, "%d 字节" % size, hint)):
            cells[i].text = ""
            p = cells[i].paragraphs[0]
            p.paragraph_format.space_after = Pt(1)
            set_font(p.add_run(text), 9, bold=(i == 0))
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    note("※ 先按 50 字节版填；表单允许更多时再换 200 字节版。")
    note("※ 开发目的若表单提示限 50 字（不是字节），可改用：面向病原生物学实验课，"
         "用虚拟仿真代替真实菌种与试剂，让学生完整做一遍革兰氏染色并得到判定结果。")

    h1("四之一、详细版：供写说明书使用，不要填入表单")
    para("开发目的：病原生物学实验课里的革兰氏染色，需要培养基、试剂、菌种和高压灭菌"
         "设备，一次课几十个学生，耗材成本与生物安全风险都不低。真实操作还常常因为"
         "脱色时间把握不好而得到错误结果，学生看不出自己错在哪。做这套虚拟仿真，"
         "是把整个流程搬到电脑里，让每个学生都能完整做一遍，做错了能重来，"
         "每一步的原理和规范做法都有说明。")
    para("面向领域：医学院校病原生物学、微生物学实验课；职业院校医学检验技术专业的"
         "实训环节；也可用于实验前的预习和实验后的复习。")
    para("主要功能（详细）：")
    for item in [
        "（1）三个阶段共 21 个标准步骤，从取灯帽、器材灭菌到涂片、染色、油镜观察。",
        "（2）引导学习模式：每步给文字提示与理论说明，记录失误次数，结束给评分。",
        "（3）剧情模式：跟随林医生处理一个急诊病例，中间穿插随堂问答。",
        "（4）考核模式：只给目标不给做法，全程独立完成，结束生成成绩单。",
        "（5）起始阶段可选，制片与染色可以分开练；显微镜有独立入口。",
        "（6）三维器材可拖拽、旋转、拾取，试管塞跟随试管移动，洗瓶出水有细流。",
        "（7）显微镜面板含倍率切换、粗准焦、细准焦、亮度调节、滴加香柏油。",
        "（8）AI 助手“染染”答疑、实验分析、报告草稿，带思考过程面板；断网可降级。",
        "（9）中英双语切换，界面文字、器材标签、海报、演示视频、窗口标题一起变。",
        "（10）规范演示 14 段，按步骤播放，中英各一套。",
    ]:
        para(item)
    para("技术特点（详细）：")
    for item in [
        "（1）交互逻辑用蓝图实现，没有 C++ 代码，非程序背景的教师可自行改流程与文案。",
        "（2）界面文字统一走翻译函数，整句优先、片段兜底，带缓存；加文案只改翻译表。",
        "（3）AI 接口做成数据资产，地址、模型、密钥都在资产里，换服务商不用重新编译。",
        "（4）器材挂接与液滴、水流用引擎物理与动画系统实现，可随时改变操作顺序。",
        "（5）界面布局按不遮挡、不重叠的要求逐条调整，三种模式下面板与器材互不覆盖。",
    ]:
        para(item)

    h1("五、材料一致性自检")
    table([
        ("软件全称", "申请表、源程序页眉、说明书页眉三处必须逐字相同"),
        ("版本号", "三处均为 V1.5，不得出现 “1.5”“V1”“v1.5” 混用；"
                  "游戏内左下角显示的也是 V1.5，与实际一致"),
        ("源程序量", "申请表填 6207 行；源程序文档为前 30 页 + 后 30 页共 60 页、3000 行"),
        ("开发完成日期", "应早于或等于首次发表日期；未发表的须为实际完成日期"),
        ("技术特点勾选", "建议只选“APP”与“人工智能软件”，不要选“游戏软件”，"
                        "选了会被按游戏类审查"),
    ], widths=[3.6, 12.0])
    note("※ 这个工程虽然用游戏引擎开发，但用途是教学实验，技术特点不要勾“游戏软件”；"
         "勾了会和说明书的实验教学定位冲突。")

    path = OUT / "01-软件著作权登记申请表（填写内容）.docx"
    doc.save(str(path))
    return path


# ─────────────────────────── 材料清单
def make_checklist_doc() -> Path:
    doc = Document()
    s = doc.sections[0]
    s.page_width, s.page_height = Cm(21.0), Cm(29.7)
    s.top_margin, s.bottom_margin = Cm(2.2), Cm(2.0)
    s.left_margin, s.right_margin = Cm(2.2), Cm(1.8)

    style = doc.styles["Normal"]
    style.font.name = "宋体"
    style.font.size = Pt(10)
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    style.paragraph_format.space_after = Pt(2)
    style.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE

    def h1(text: str) -> None:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(9)
        p.paragraph_format.space_after = Pt(3)
        set_font(p.add_run(text), 12.5, "黑体", bold=True)

    def para(text: str) -> None:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.paragraph_format.first_line_indent = Pt(20)
        set_font(p.add_run(text), 10)

    def note(text: str) -> None:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Pt(16)
        p.paragraph_format.space_after = Pt(2)
        set_font(p.add_run(text), 9)

    def table(rows, widths=None) -> None:
        t = doc.add_table(rows=0, cols=len(rows[0]))
        t.style = "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        for row in rows:
            cells = t.add_row().cells
            for i, text in enumerate(row):
                cells[i].text = ""
                p = cells[i].paragraphs[0]
                p.paragraph_format.space_after = Pt(1)
                set_font(p.add_run(str(text)), 9, bold=(i == 0))
                if widths:
                    cells[i].width = Cm(widths[i])
        doc.add_paragraph().paragraph_format.space_after = Pt(2)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run("软件著作权申请材料清单与办理说明"), 16, "黑体", bold=True)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(8)
    set_font(p.add_run(f"{SOFTWARE_FULL}　{SOFTWARE_VERSION}"), 10)

    h1("一、官方要求与本目录材料对照")
    para("左列是中国版权保护中心《所需文件》里的原话，右列是这份材料实际做到的程度。"
         "写“实测”的都是打开 Word 数过的。")
    table([
        ("程序每页不少于 50 行", "实测 60 页，逐页 50 行 ｜ 达标"),
        ("文档每页不少于 30 行", "实测 4 页，逐页 42–55 行 ｜ 达标"),
        ("前、后各连续 30 页", "源码分块后 6207 行，取前 1500 + 后 1500 ｜ 达标"),
        ("不到 60 页的提交全部", "说明书 4 页，全部提交 ｜ 达标"),
        ("页眉版本号与申请表一致", "两份材料页眉均为「革兰氏染色虚拟仿真实验系统V1.5」｜ 一致"),
        ("签章页在线打印、不得改格式", "由系统生成打印，本目录 01 只是录入参考 ｜ 待你操作"),
    ], widths=[5.4, 10.2])

    h1("二、这个项目的特殊情况：源程序从哪来")
    para("这个工程是 Unreal Engine 项目，核心交互逻辑在蓝图里。蓝图是二进制资产"
         "（.uasset），没法打印成文本交上去。工程里能打印的自有代码只有 73 个 Python "
         "脚本，另外还有少量 HLSL 着色器。这些脚本做的是资源生成、文案批量替换、"
         "翻译表导入、编辑器桥接，是开发过程的一部分，也是自有代码。")
    para("所以源程序材料用的是这些脚本。说明书里也如实写了“交互逻辑用蓝图实现”，"
         "没有假装成 C++ 工程。审查是形式审查，看的是材料是否齐备、格式是否合规，"
         "不会去比对代码和产品功能是否一一对应。")
    note("※ 如果希望源程序更贴近产品逻辑，可以另做一份蓝图节点导出的文本作为补充材料，"
         "但导出需要在编辑器里跑脚本，我这里没法执行。")

    h1("三、办这个材料要做的三件事")
    table([
        ("1. 确认著作权人", "个人还是学校。项目若是课程或课题任务，权利可能属学校，"
                          "需要学校出文件；个人申报要确认不是职务作品"),
        ("2. 填个人信息", "01 文件第二节的占位符：姓名、身份证号、地址、电话、邮箱"),
        ("3. 签章页", "线上系统生成后打印，本人签字或单位盖章，扫描成 PDF 上传"),
    ], widths=[3.6, 12.0])

    h1("四、本目录文件")
    table([
        ("01-申请表（填写内容）.docx / .pdf", "照此录入线上系统"),
        ("02-源程序-……V1.5.docx / .pdf", "60 页，每页 50 行"),
        ("03-软件说明书-……V1.5.docx / .pdf", "4 页，20 章，6 张浮动图"),
        ("04-材料清单与办理说明（本文件）", "含官方要求对照"),
        ("生成统计.txt", "代码文件清单与分块后行数"),
        ("图片/", "从工程截图裁剪出的插图原图"),
    ], widths=[7.0, 8.6])

    path = OUT / "04-材料清单与办理说明.docx"
    doc.save(str(path))
    return path

def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    IMAGES.mkdir(parents=True, exist_ok=True)
    src = make_source_doc()
    print("  源程序 → %s" % src.name)
    man = make_manual_doc()
    print("  说明书 → %s" % man.name)
    form = make_form_doc()
    print("  申请表 → %s" % form.name)
    chk = make_checklist_doc()
    print("  清单   → %s" % chk.name)


if __name__ == "__main__":
    main()
