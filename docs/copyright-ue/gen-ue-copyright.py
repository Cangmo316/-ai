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
    section.bottom_margin = Cm(1.6)
    section.left_margin = Cm(2.4)
    section.right_margin = Cm(2.0)
    header_title(section, f"{SOFTWARE_FULL}{SOFTWARE_VERSION}")
    footer_page(section)

    style = doc.styles["Normal"]
    style.font.name = "宋体"
    style.font.size = Pt(10)
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    fmt = style.paragraph_format
    fmt.space_before = Pt(0)
    fmt.space_after = Pt(2)
    fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    fmt.line_spacing = Pt(11)

    def h1(text: str) -> None:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        set_font(p.add_run(text), 12.5, "黑体", bold=True)

    def h2(text: str) -> None:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        set_font(p.add_run(text), 10.5, "黑体", bold=True)

    def body(text: str) -> None:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.paragraph_format.first_line_indent = Pt(20)
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        p.paragraph_format.line_spacing = Pt(11)
        set_font(p.add_run(text), 10)

    def step(text: str) -> None:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Pt(20)
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        p.paragraph_format.line_spacing = Pt(11)
        set_font(p.add_run(text), 10)

    def figure(name: str, caption: str, width_cm: float = 4.6) -> None:
        """浮动图：靠右锚在上一段正文上，文字绕左。

        嵌入型会独占整行高度，一页 50 行的容量被图吃掉 20 行，
        带图的页面就到不了"每页 30 行"。
        """
        path = IMAGES / name
        if not path.exists():
            print("  ⚠️ 缺图：%s" % name)
            return
        target = None
        for para in reversed(doc.paragraphs):
            if para.text.strip():
                target = para
                break
        if target is None:
            target = doc.add_paragraph()
        run = target.add_run()
        run.add_picture(str(path), width=Cm(width_cm))

        inline = run._r.find(".//" + qn("wp:inline"))
        if inline is None:
            return
        anchor = OxmlElement("wp:anchor")
        for k, v in (("distT", "0"), ("distB", "0"), ("distL", "114300"), ("distR", "0"),
                     ("simplePos", "0"), ("relativeHeight", "251658240"),
                     ("behindDoc", "0"), ("locked", "0"), ("layoutInCell", "1"),
                     ("allowOverlap", "1")):
            anchor.set(k, v)
        sp = OxmlElement("wp:simplePos")
        sp.set("x", "0")
        sp.set("y", "0")
        anchor.append(sp)
        ph = OxmlElement("wp:positionH")
        ph.set("relativeFrom", "margin")
        al = OxmlElement("wp:align")
        al.text = "right"
        ph.append(al)
        anchor.append(ph)
        pv = OxmlElement("wp:positionV")
        pv.set("relativeFrom", "paragraph")
        off = OxmlElement("wp:posOffset")
        off.text = "0"
        pv.append(off)
        anchor.append(pv)
        import copy as _copy
        for tag in ("wp:extent", "wp:effectExtent"):
            el = inline.find(qn(tag))
            if el is not None:
                anchor.append(_copy.deepcopy(el))
        wrap = OxmlElement("wp:wrapSquare")
        wrap.set("wrapText", "left")
        anchor.append(wrap)
        doc_pr = inline.find(qn("wp:docPr"))
        if doc_pr is not None:
            anchor.append(_copy.deepcopy(doc_pr))
        graphic = inline.find(qn("a:graphic"))
        if graphic is not None:
            anchor.append(_copy.deepcopy(graphic))
        inline.getparent().replace(inline, anchor)

        cap = doc.add_paragraph()
        cap.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        cap.paragraph_format.space_before = Pt(0)
        cap.paragraph_format.space_after = Pt(2)
        cap.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        set_font(cap.add_run(caption), 8.5)

    # 封面
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(10)
    set_font(p.add_run(SOFTWARE_FULL), 18, "黑体", bold=True)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run("软 件 说 明 书"), 13)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(8)
    set_font(p.add_run(f"版本号：{SOFTWARE_VERSION}"), 10)

    # ── 一
    h1("一、软件概述")
    body("这是一套病原生物学实验课用的虚拟仿真软件，内容是把革兰氏染色的完整操作"
         "搬到电脑里做一遍。学生从取下酒精灯灯帽开始，经过器材灭菌、涂片、干燥、"
         "热固定、初染、媒染、脱色、复染，最后在显微镜下用油镜判断细菌是革兰阳性"
         "还是革兰阴性。整个过程 21 个标准步骤，一步做错会影响后面的结果。")
    body("软件用 Unreal Engine 5.8 开发，打包成 Windows 桌面程序运行。场景是三维的，"
         "器材可以拿起来、转动、倾斜，液体的滴加和冲洗都有对应的动画和水流效果。"
         "实验分三个阶段：制片、染色、显微镜观察，每个阶段有独立的面板和步骤清单。")
    body("主要的教学对象是医学院校的病原生物学、微生物学实验课。传统实验要培养基、"
         "试剂、菌种和高压灭菌设备，一次课几十个学生，耗材成本和生物安全风险都不低。"
         "用虚拟仿真代替，每个学生都能完整做一遍，做错了可以重来，也不存在污染问题。")

    # ── 二
    h1("二、运行环境")
    h2("硬件")
    step("（1）处理器：近五年的 Intel i5 或 AMD Ryzen 5 及以上。")
    step("（2）内存：8GB 起，16GB 更稳。三维场景和贴图占内存比较多。")
    step("（3）显卡：支持 DirectX 12 的独立显卡，显存 4GB 以上。集显能跑，帧率低。")
    step("（4）存储：安装包与运行数据共需 8GB 左右，建议固态硬盘。")
    step("（5）显示：分辨率 1920×1080 及以上，界面按 16:9 布局。")
    h2("软件")
    step("（1）操作系统：Windows 10 或 Windows 11 64 位。")
    step("（2）运行库：DirectX 12 运行库、Visual C++ 2015-2022 运行库。")
    step("（3）运行时不依赖 Unreal 编辑器，打包版自带引擎运行库。")
    step("（4）联网只在用 AI 助手时需要，其余功能全部离线可用。")

    # ── 三
    h1("三、安装与启动")
    step("（1）解压安装包到任意目录，路径不要带中文以外的特殊符号。")
    step("（2）双击可执行文件启动，第一次启动会建存档目录，约需几秒。")
    step("（3）进入主菜单后先看右上角的语言按钮，中文或 English 点一下即切换。")
    step("（4）语言设置会写进存档，下次启动沿用，不需要每次选。")
    step("（5）退出点主菜单的 Exit，或按 Esc 调出菜单再退出。")
    body("实验进行中不能切换语言。步骤文字、报告和对话都是开始时按语言生成的，"
         "中途切换会出现中英混杂，所以设置里那一行在中途是隐藏的。")

    # ── 四
    h1("四、主菜单与模式选择")
    body("主菜单左侧竖排四种入口，右侧下方是实验室概览，写着标准步骤数、试剂瓶数"
         "和油镜倍数。右下角是 AI 助手染染的对话框，进来就能提问。")
    step("（1）Guided Learning 引导学习：按步骤做，每一步有文字提示和理论说明，"
         "最后给评分。适合第一次接触这门实验的学生。")
    step("（2）Story Mode 剧情模式：跟着林医生处理一个急诊病例，中间穿插随堂问答。"
         "适合已经做过一遍、需要理解为什么这么做的人。")
    step("（3）Exam mode 考核模式：只给操作目标，不给步骤提示，全程独立完成，"
         "结束给成绩单。适合作为实验课的过程性考核。")
    step("（4）Settings 设置：画质、显示、音量、色盲模式。")
    body("选模式时会先问从哪个阶段开始。制片阶段和染色阶段可以分开练，"
         "只练染色就不用每次从取灯帽开始。显微镜单独入口，随时可以进去看视野。")
    figure("fig-01-主菜单.png", "图 4-1 主菜单：四种入口与 AI 助手对话面板")

    # ── 五
    h1("五、制片阶段")
    body("制片是把细菌从培养基转移到载玻片上并固定的过程。这个阶段最容易出问题的"
         "是无菌操作，软件把每一步的规范做法都写在提示里，做错会记录失误次数。")
    step("（1）取下酒精灯灯帽，平稳放置，不要滚落。")
    step("（2）用打火机或火柴点燃酒精灯。不能用燃着的酒精灯去点另一盏。")
    step("（3）接种环在外焰中灼烧至环丝发红，杀灭残留微生物，然后稍冷却。")
    step("（4）拔棉塞时用小指与手掌夹住，不要放在台面上，防止污染。")
    step("（5）试管口在外焰中旋转过火，杀灭管口附近的杂菌。")
    step("（6）接种环顺管轴伸进倾斜的试管，蘸取无菌生理盐水。")
    step("（7）在载玻片中央放一小滴生理盐水，作为涂片的分散液。")
    step("（8）接种环再次灼烧灭菌并冷却，在菌落边缘刮取少量细菌。")
    step("（9）与生理盐水混匀，涂成直径约 1 厘米的均匀薄膜。")
    step("（10）涂片干燥：可以选自然干燥，也可以在火焰上方高处微微烘干。"
         "不能把载玻片放进火焰里直接烤，细菌会变形。")
    step("（11）热固定：涂片面向上，以钟摆速度通过外焰三次。")
    body("取菌量过多会让涂片过厚、细胞重叠，后面脱色也更难掌握，这是新手最常见的"
         "失误。软件在取菌这一步会按刮取面积和次数给量，涂得太厚时下一步的提示会变。")
    figure("fig-02-制片阶段.png", "图 5-1 制片阶段：步骤面板、理论说明与台面器材")

    # ── 六
    h1("六、染色阶段")
    body("染色是这套实验的核心，四步染色加三次水洗，顺序不能错。软件把每一步的"
         "试剂、作用时间、滴加量和冲洗方式都做成了可操作的动作。")
    h2("初染")
    step("（1）滴加结晶紫染液，覆盖涂面，作用约 1 分钟。结晶紫是碱性染料，"
         "所有细菌都会被染成紫色。")
    step("（2）用洗瓶细水流从载玻片上端冲洗，让水流过涂面。水流不要直接冲在菌膜上，"
         "以免把细菌冲掉。")
    h2("媒染")
    step("（3）滴加碘液，作用约 1 分钟。碘与结晶紫形成大分子复合物，"
         "增强染料与细胞的结合。")
    step("（4）冲去多余碘液。")
    h2("脱色")
    step("（5）滴加 95% 乙醇脱色，这是关键步骤，时间要掐准。")
    step("（6）脱色后立即水洗终止。脱色过度会把阳性菌误判成阴性，脱色不足则相反。")
    body("脱色的原理写在理论面板里：革兰阳性菌的肽聚糖层厚、脂类少，乙醇使其脱水、"
         "孔隙缩小，结晶紫与碘的复合物留在胞内，仍是紫色；革兰阴性菌脂类多、"
         "肽聚糖薄，复合物被乙醇洗脱而褪色。软件在脱色时会弹出提示，"
         "把这一段再讲一遍，因为多数学不好这门课的人都是卡在这一步。")
    h2("复染")
    step("（7）滴加稀释复红复染，作用约 1 分钟。已脱色的阴性菌染成红色，阳性菌仍为紫色。")
    step("（8）冲去多余复染液，用吸水纸吸干或自然干燥。")
    figure("fig-03-染色阶段.png", "图 6-1 染色阶段：四瓶试剂、滴加与冲洗操作")

    # ── 七
    h1("七、显微镜与油镜观察")
    body("显微镜是单独的一块面板，倍率、粗准焦、细准焦、亮度、滴油都在面板上操作。"
         "顺序是先低倍找标本，再换高倍，最后滴油上油镜。")
    step("（1）把载玻片放到载物台上，用低倍镜（10×）加粗准焦找到标本。")
    step("（2）换 40× 物镜，用细准焦调清楚结构。")
    step("（3）滴一滴香柏油在涂面上，转到 100× 油镜。")
    step("（4）只用细准焦螺旋调焦。油镜的工作距离很短，粗准焦容易撞到玻片。")
    step("（5）调亮度到合适，观察菌体颜色并判定：紫色为革兰阳性菌，红色为革兰阴性菌。")
    step("（6）判定完成后点判定按钮，进入结果页。")
    body("香柏油的折射率与玻璃接近，可以减少光线在玻片与镜头之间的散射，"
         "油镜才看得清细菌形态。软件把这一条做成理论面板的固定内容，"
         "学生不滴油直接切到 100×，画面会明显发虚。")
    figure("fig-04-油镜观察.png", "图 7-1 油镜观察：显微镜操作面板与操作提示")
    body("下面是两个倍率下的视野效果。40× 下能看到菌体聚集成片，"
         "100× 油镜下能分清单个菌体的形态和染色结果。")
    figure("fig-05-40倍视野.png", "图 7-2 40 倍视野：菌体成片，形态不清", 3.6)
    figure("fig-06-100倍视野.png", "图 7-3 100 倍油镜视野：可分辨单个菌体与染色", 3.6)

    # ── 八
    h1("八、AI 助手染染")
    body("主菜单和实验过程中都能叫出染染，位置在画面右下角。它回答三类问题："
         "这一步为什么这么做、这个器材有什么用、某个现象说明了什么。")
    step("（1）点输入框打字提问，回车或点发送。")
    step("（2）下面有四个预设问题，不知道问什么的时候直接点，"
         "分别是这个实验讲什么、三种模式有什么区别、开始小测、还有什么要注意。")
    step("（3）回答里有思考过程面板，可以展开看推理，也可以收起。")
    step("（4）实验做完可以让它分析这次操作，会指出失误出现在哪一步。")
    step("（5）报告还没写，可以让它先出草稿，再自己改。")
    body("接口地址、模型名和密钥在数据资产 DA_JJConfig 里配置，换服务商不用改蓝图。"
         "密钥在工程包里，交付给学校时要换成学校自己的账号，否则费用记在开发者头上。")
    body("断网或密钥失效时，染染会改用本地内容回答，常见的八类错误都有对应提示，"
         "比如余额不足、密钥无效、请求太频繁、内容被安全审核拦截。提示里不写服务商"
         "名字，学生看到的是人话。")

    # ── 九
    h1("九、剧情模式与角色")
    body("剧情模式把染色流程放进一个急诊病例里。林医生会先讲病人的情况，"
         "然后请你按规范做一遍染色，过程中提问为什么要这么做。")
    step("（1）林医生出场，说明标本来源和要回答的问题。")
    step("（2）按提示完成制片与染色，林医生在关键步骤上插话解释原理。")
    step("（3）中途有随堂问答，答错会解释，不扣分。")
    step("（4）做完给出判定结论，回到病例本身说明诊断意义。")
    body("林医生有九种表情立绘，按对话情绪切换，文字逐字打出。"
         "立绘是戴口罩、帽子、手套的实验室着装，符合生物安全要求。")

    # ── 十
    h1("十、考核模式与成绩单")
    body("考核模式不给步骤提示，只给目标，全程自己判断。评分按步骤完成度、"
         "操作顺序和失误次数算。")
    step("（1）选 Exam mode，选起始阶段，开始。")
    step("（2）每一步只显示当前目标，不显示具体做法，也不显示下一步是什么。")
    step("（3）做错会记失误，脱色过头会把结果染成错误颜色，后面判定就错了。")
    step("（4）结束后生成成绩单，列出各步得分、失误点和总评。")
    step("（5）可以回放错误步骤，看当时错在哪。")

    # ── 十一
    h1("十一、规范演示")
    body("每个阶段配了规范操作演示，共十四段，是录屏视频，按阶段和步骤分开。"
         "不会做的时候先看演示，再自己动手。")
    step("（1）在步骤面板点演示按钮，播放当前步骤的规范操作。")
    step("（2）演示可以暂停、拖动进度。")
    step("（3）英文模式播放按英文界面重录的视频，不是加字幕。")

    # ── 十二
    h1("十二、中英双语")
    body("主菜单右上角切换中英文，切换后重新加载关卡，界面文字、器材标签、"
         "墙上海报、演示视频、窗口标题一起变。")
    step("（1）中文 / English 按钮点一下即切换，设置存档，下次沿用。")
    step("（2）第一次启动时看系统显示语言和区域，有一个是中文就用中文，否则用英文。")
    step("（3）翻译表一千三百多条，整句查不到时按片段替换，处理"
         "「用时 23 秒」这类拼接句。")
    step("（4）器材标签和海报用材质参数切贴图，不换模型。")
    step("（5）英文模式下林医生配音静音，只留英文字幕。")
    body("英文模式有一条规则：染染的回复里如果还残留中文，这条回复不显示，"
         "改用本地英文内容。学生自己打的字原样显示，不翻译。")

    # ── 十三
    h1("十三、器材与交互细节")
    body("台面上的器材都能拖拽、旋转、拾取。放回位置时会有吸附，避免对不准。"
         "试管塞在应该插在管口的阶段挂接在试管上，跟着试管一起动，不会出现"
         "「塞子停在原地、试管跑了」的情况。")
    step("（1）洗瓶可以挤压，出水是一束细流，对着涂面冲。")
    step("（2）滴瓶倒持，滴一到两滴覆盖涂面。")
    step("（3）接种环用后要立即灼烧灭菌，软件会提示。")
    step("（4）界面右上角可以开关自动特写，关掉之后不会自动拉近镜头。")
    step("（5）按 H 显示提示，按 Esc 调出菜单。")

    # ── 十四
    h1("十四、设置与无障碍")
    step("（1）画质：低、中、高、极高四档，按显卡选。")
    step("（2）显示：分辨率、全屏 / 窗口、垂直同步。")
    step("（3）音量：总音量、音乐、音效三路分开调。")
    step("（4）色盲模式：开启后把判定用的紫红两色改成对色觉异常更易分辨的配色，"
         "同时在结果页加文字标注，不靠颜色单独传达结论。")

    # ── 十五
    h1("十五、数据与存档")
    body("存档只有一个文件，记语言、画质、音量和色盲模式，存在系统用户目录下的"
         "游戏存档目录里。删除存档等于恢复出厂设置，不影响成绩单数据，"
         "成绩单每做一次单独生成。")
    body("软件不收集个人信息，不上传操作记录。联网只发生在调用 AI 助手时，"
         "发送的是学生输入的问题和当前步骤，不发送姓名、学号等信息。")

    # ── 十六
    h1("十六、技术特点")
    body("交互逻辑用蓝图实现，没有 C++ 代码，方便非程序背景的老师自己改流程和文案。")
    body("所有界面文字统一走一个翻译函数，整句优先、片段兜底，结果带缓存。"
         "加新文案只要往翻译表加一行，不用改蓝图。")
    body("器材的挂接、滴加、水流、特写都用引擎的物理和动画系统做，不是预渲染视频，"
         "所以可以随时改变操作顺序。")
    body("AI 接口做成可配置的数据资产，换模型、换地址、换密钥都不用重新编译。"
         "断网时自动降级到本地内容。")
    body("界面布局按「不遮挡、不重叠」反复调过。三种模式下每一步的文字、面板、"
         "器材都不互相盖住，这是按使用方的反馈一条条改的。")

    # ── 十七
    h1("十七、常见问题")
    step("问：染染一直提示网络错误。")
    step("答：先看是不是断网。再看密钥是否有效，余额是否够。提示里会写明是哪一类。")
    step("问：换了语言，中途的口令还是中文。")
    step("答：实验中途不允许切换语言，退出到主菜单再切。")
    step("问：画面卡。")
    step("答：画质降到中或低，关掉垂直同步，分辨率降到 1920×1080。")
    step("问：油镜看不清。")
    step("答：确认滴了香柏油，并且只用细准焦调。粗准焦在油镜下容易撞到玻片。")
    step("问：脱色后全变红了。")
    step("答：脱色时间过长。这是最常见的失误，重做时把乙醇停留时间缩短。")

    # ── 十八
    h1("十八、界面约定")
    body("一屏只做一件事。步骤面板、理论面板、操作提示分开摆，不叠在一起。")
    body("正文不小于 14pt，标题不小于 20pt，按钮点击区放大。色盲模式下不只靠颜色"
         "传达结论，结果页同时给出文字。")
    body("提示语用口语，不用「操作失败」「参数错误」这类词。提示里直接写下一步做什么，"
         "而不是让学生自己找。")

    # ── 十九
    h1("十九、附录：术语")
    body("革兰氏染色：丹麦医生革兰发明的一种细菌鉴别染色法，按染色结果把细菌分成"
         "革兰阳性菌和革兰阴性菌两类。")
    body("初染：第一步，用结晶紫把所有细菌染成紫色。")
    body("媒染：用碘液与结晶紫形成复合物，增强染色结合力。")
    body("脱色：用乙醇洗脱，是区分两类细菌的关键步骤。")
    body("复染：用稀释复红把已脱色的阴性菌染成红色。")
    body("油镜：放大倍数 100 倍的物镜，需要香柏油做介质。")
    body("热固定：通过火焰加热使细菌牢固附着在载玻片上，染色时不易被冲掉。")

    # ── 二十
    h1("二十、版本说明")
    body(f"本说明书对应版本 {SOFTWARE_VERSION}，为首次发表的正式版本。"
         "后续版本的增补与修复不在本说明书范围内。")

    path = OUT / f"03-软件说明书-{SOFTWARE_FULL}{SOFTWARE_VERSION}.docx"
    doc.save(str(path))
    return path


# ─────────────────────────── 申请表（填写内容参考）
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
