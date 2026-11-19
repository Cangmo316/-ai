"""比邻AI说明书最终版：参考件格式 + 竖屏图环绕 + 题注在图下 + 18-20 页。

## 图的两套插入方式（按要求）

  · 横屏（架构图，宽/高 ≥ 1）→ 居中嵌入，题注居中在下方
  · 竖屏（手机截图）→ 右侧环绕，文字绕左；题注用 VML 文本框锚在图片下方 7pt

VML 题注的定位写法是试错出来的，只有一种生效：
  style 里用 margin-top + mso-position-vertical-relative:paragraph。
  用 top: 不生效（题注会停在锚点段落顶部），DrawingML 文本框会被 Word 丢弃。

## 页数

目标 18-20 页。正文 9.9pt、行距 13pt，每页约 1200-1400 字。
七章：项目概述 / 运行环境 / 界面介绍（12 节，每节带操作步骤）/
技术特点与创新点 / 数据存储与维护 / 典型使用流程 / 常见问题与术语。
"""

from __future__ import annotations

import struct
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

SOFTWARE_FULL = "比邻AI智慧康养陪伴软件"
SOFTWARE_VERSION = "V1.0"
OUT = Path(r"E:\ppt\比邻AI.ppt\软著材料-终版")
IMAGES = Path(r"E:\ppt\比邻AI.ppt\图片")

BODY_PT = 9.9
LINE_PT = 13.0

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
V_NS = "urn:schemas-microsoft-com:vml"
O_NS = "urn:schemas-microsoft-com:office:office"


def font(run, size, name="宋体", bold=False):
    run.font.size = Pt(size)
    run.font.name = name
    run.font.bold = bold
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


def setup(doc: Document) -> None:
    s = doc.sections[0]
    s.page_width, s.page_height = Cm(21.0), Cm(29.7)
    s.top_margin, s.bottom_margin = Cm(2.0), Cm(2.0)
    s.left_margin, s.right_margin = Cm(2.2), Cm(2.0)

    normal = doc.styles["Normal"]
    normal.font.name = "宋体"
    normal.font.size = Pt(BODY_PT)
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    pf = normal.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(LINE_PT)

    hp = s.header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    font(hp.add_run(f"{SOFTWARE_FULL}  {SOFTWARE_VERSION}"), 9)

    fp = s.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = fp.add_run()
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
    font(run, 9)


def chapter(doc, num: str, title: str) -> None:
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(14)
    pf.space_after = Pt(6)
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(20)
    pf.keep_with_next = True
    font(p.add_run(f"{num}  {title}"), 12.9, "黑体", bold=True)


def section(doc, num: str, title: str) -> None:
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(9)
    pf.space_after = Pt(3)
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(17)
    pf.keep_with_next = True
    font(p.add_run(f"{num}  {title}"), 11.1, "黑体", bold=True)


def subsection(doc, num: str, title: str) -> None:
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(6)
    pf.space_after = Pt(2)
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(15)
    pf.keep_with_next = True
    font(p.add_run(f"{num}  {title}"), 10.4, "黑体", bold=True)


def para(doc, text: str, indent: bool = True):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    pf = p.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(LINE_PT)
    if indent:
        pf.first_line_indent = Pt(BODY_PT * 2)
    font(p.add_run(text), BODY_PT)
    return p


def caption(doc, text: str, align=WD_ALIGN_PARAGRAPH.CENTER, before=2, after=6):
    p = doc.add_paragraph()
    p.alignment = align
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
    try:
        p.style = doc.styles["Caption"]
    except KeyError:
        pass
    run = p.add_run(text)
    font(run, 9)
    run.font.color.rgb = RGBColor(0, 0, 0)
    run.font.italic = False
    return p


def _png_size(path: Path):
    try:
        with path.open("rb") as f:
            head = f.read(26)
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        return struct.unpack(">II", head[16:24])
    except OSError:
        return None


def _vml_caption(doc, text: str, width_cm: float, offset_pt: float, shape_id: str) -> None:
    from lxml import etree

    width_pt = width_cm / 2.54 * 72
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    p.paragraph_format.line_spacing = Pt(2)
    run = p.add_run()
    run.font.size = Pt(2)

    pict = etree.SubElement(run._r, f"{{{W_NS}}}pict")
    shape = etree.SubElement(pict, f"{{{V_NS}}}shape", nsmap={"v": V_NS, "o": O_NS})
    shape.set("id", shape_id)
    shape.set("type", "#_x0000_t202")
    shape.set("style",
              "position:absolute;margin-left:0;margin-top:%.1fpt;"
              "width:%.1fpt;height:12pt;z-index:251659264;"
              "mso-position-horizontal:right;"
              "mso-position-horizontal-relative:margin;"
              "mso-position-vertical-relative:paragraph;"
              "mso-fit-shape-to-text:t" % (offset_pt, width_pt))
    shape.set("filled", "f")
    shape.set("stroked", "f")

    textbox = etree.SubElement(shape, f"{{{V_NS}}}textbox")
    textbox.set("inset", "0,0,0,0")
    content = etree.SubElement(textbox, f"{{{W_NS}}}txbxContent")
    cp = etree.SubElement(content, f"{{{W_NS}}}p")
    ppr = etree.SubElement(cp, f"{{{W_NS}}}pPr")
    jc = etree.SubElement(ppr, f"{{{W_NS}}}jc")
    jc.set(f"{{{W_NS}}}val", "center")
    spacing = etree.SubElement(ppr, f"{{{W_NS}}}spacing")
    spacing.set(f"{{{W_NS}}}before", "0")
    spacing.set(f"{{{W_NS}}}after", "0")
    spacing.set(f"{{{W_NS}}}line", "240")
    spacing.set(f"{{{W_NS}}}lineRule", "auto")

    r = etree.SubElement(cp, f"{{{W_NS}}}r")
    rpr = etree.SubElement(r, f"{{{W_NS}}}rPr")
    rfonts = etree.SubElement(rpr, f"{{{W_NS}}}rFonts")
    rfonts.set(f"{{{W_NS}}}ascii", "宋体")
    rfonts.set(f"{{{W_NS}}}eastAsia", "宋体")
    rfonts.set(f"{{{W_NS}}}hAnsi", "宋体")
    for tag in ("sz", "szCs"):
        el = etree.SubElement(rpr, f"{{{W_NS}}}{tag}")
        el.set(f"{{{W_NS}}}val", "18")
    color = etree.SubElement(rpr, f"{{{W_NS}}}color")
    color.set(f"{{{W_NS}}}val", "000000")
    t_el = etree.SubElement(r, f"{{{W_NS}}}t")
    t_el.text = text


def figure(doc, name: str, label: str, caption_text: str, width_cm: float = None) -> None:
    """图居中嵌入，题注紧随其下居中。

    不用浮动原因：浮动图的题注要靠 VML 文本框绝对偏移，实测会飘——
    同一页有两张图时，第一张的题注会落进第二张图的范围（y 坐标重叠），
    图靠近页底时还会偏移 4-5 行。嵌入型由排版流决定位置，图多高、题注就在其下，
    不会错位。
    """
    path = IMAGES / name
    if not path.exists():
        print("  ⚠️ 缺图：%s" % name)
        return

    size = _png_size(path)
    landscape = bool(size) and size[0] / size[1] >= 1.0
    if width_cm is None:
        # 竖屏取 3.4cm：高约 7.4cm ≈ 16 行，页面仍能留 30 行以上给文字
        width_cm = 12.5 if landscape else 3.4

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(5)
    p.paragraph_format.space_after = Pt(0)
    # 嵌入图所在段落必须用单倍行距，固定行距会把图裁成一行高
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    p.paragraph_format.keep_with_next = True   # 图与题注不分页
    p.add_run().add_picture(str(path), width=Cm(width_cm))

    cap = doc.add_paragraph()
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap.paragraph_format.space_before = Pt(1)
    cap.paragraph_format.space_after = Pt(6)
    cap.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    try:
        cap.style = doc.styles["Caption"]
    except KeyError:
        pass
    run = cap.add_run(f"{label}  {caption_text}")
    font(run, 9)
    run.font.color.rgb = RGBColor(0, 0, 0)
    run.font.italic = False


def figure_row(doc, items, width_cm: float = 3.4) -> None:
    """一行并排多图，每张图下方各自跟题注（居中）。

    用无边框表格实现：图片与题注都放在同一个单元格里，
    题注紧贴图片下方，位置由单元格排版保证，不会偏移。
    """
    cols = len(items)
    t = doc.add_table(rows=1, cols=cols)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False

    tbl_pr = t._tbl.tblPr
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tbl_pr.append(layout)
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement("w:%s" % edge)
        el.set(qn("w:val"), "none")
        el.set(qn("w:sz"), "0")
        borders.append(el)
    tbl_pr.append(borders)

    cell_w = width_cm + 1.2
    for idx, (name, label, cap_text) in enumerate(items):
        t.columns[idx].width = Cm(cell_w)
        cell = t.rows[0].cells[idx]
        cell.width = Cm(cell_w)

        p1 = cell.paragraphs[0]
        p1.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p1.paragraph_format.space_before = Pt(2)
        p1.paragraph_format.space_after = Pt(1)
        p1.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        path = IMAGES / name
        if path.exists():
            p1.add_run().add_picture(str(path), width=Cm(width_cm))
        else:
            print("  ⚠️ 缺图：%s" % name)

        p2 = cell.add_paragraph()
        p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p2.paragraph_format.space_before = Pt(0)
        p2.paragraph_format.space_after = Pt(4)
        p2.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        try:
            p2.style = doc.styles["Caption"]
        except KeyError:
            pass
        run = p2.add_run(f"{label}  {cap_text}")
        font(run, 9)
        run.font.color.rgb = RGBColor(0, 0, 0)
        run.font.italic = False

    for row in t.rows:
        row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))

    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(0)
    spacer.paragraph_format.space_after = Pt(2)
    spacer.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    spacer.paragraph_format.line_spacing = Pt(6)


def table(doc, label: str, cap_text: str, header, rows, widths) -> None:
    caption(doc, f"{label}  {cap_text}", before=6, after=2)

    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False

    tbl_pr = t._tbl.tblPr
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tbl_pr.append(layout)
    for i, w in enumerate(widths):
        t.columns[i].width = Cm(w)

    for i, text in enumerate(header):
        cell = t.rows[0].cells[i]
        cell.width = Cm(widths[i])
        cell.text = ""
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(1)
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        p.paragraph_format.line_spacing = Pt(12)
        font(p.add_run(text), 9, bold=True)

    for row in rows:
        cells = t.add_row().cells
        for i, text in enumerate(row):
            cells[i].width = Cm(widths[i])
            cells[i].text = ""
            p = cells[i].paragraphs[0]
            p.alignment = (WD_ALIGN_PARAGRAPH.CENTER if i in (0, 1) and len(header) >= 3
                           else WD_ALIGN_PARAGRAPH.LEFT)
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.space_after = Pt(1)
            p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
            p.paragraph_format.line_spacing = Pt(12)
            font(p.add_run(str(text)), 9)

    for idx, row in enumerate(t.rows):
        tr_pr = row._tr.get_or_add_trPr()
        tr_pr.append(OxmlElement("w:cantSplit"))
        if idx == 0:
            tr_pr.append(OxmlElement("w:tblHeader"))

    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_after = Pt(4)
    spacer.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    spacer.paragraph_format.line_spacing = Pt(6)


def steps(doc, items) -> None:
    for line in items:
        para(doc, line)

def build() -> Path:
    doc = Document()
    setup(doc)

    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    t.paragraph_format.space_before = Pt(6)
    t.paragraph_format.space_after = Pt(2)
    t.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    font(t.add_run(SOFTWARE_FULL), 17, "黑体", bold=True)

    st = doc.add_paragraph()
    st.alignment = WD_ALIGN_PARAGRAPH.CENTER
    st.paragraph_format.space_after = Pt(10)
    st.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    font(st.add_run(f"软件说明书  {SOFTWARE_VERSION}"), 11)

    # ══════ 第一章
    chapter(doc, "第一章", "项目概述")
    section(doc, "1.1", "项目背景")
    para(doc, "独居老人和需要长期吃药的慢病人群，日常有两件事最难：说话没人接，身体的变化没人记。"
              "前者是陪伴问题，后者是照护问题。市面上的产品大多只解决一边。健康类的应用功能齐，"
              "但把力气花在填表和看图上看，字小、层级深、步骤多，老人自己用不起来；"
              "聊天类的应用老人愿意用，但聊完就过去了，记不下血压，不会提醒吃药，家属也看不到情况。")
    para(doc, "本软件把入口放在说话上。老人对着手机说一句，软件先判断这是闲聊还是身体不舒服："
              "闲聊就陪着说，遇到医疗话题就换成另一种说法，并在回答末尾加一句以医嘱为准、及时就医。"
              "说的内容里提到的事会被记下来，包括怎么称呼、作息、吃什么、家里有谁、有哪些重要的日子。"
              "身体数据和病历另有一处存放，家属用另一个账号登录能看到老人这几天的情况。")
    para(doc, "界面按老人的眼神和手指做过几轮调整：字号大、对比度高、能点就不让打字，"
              "删除类操作都要二次确认。软件分手机端和服务端两部分，服务端跑在部署方自己的机器上，"
              "数据不出本机（如图1-1）。")
    figure(doc, "架构-01-系统分层.png", "图1-1", "系统架构图", 12.5)
    para(doc, "服务端分五层：接入层负责鉴权与路由，应用层是对话、计划、健康、病例等业务模块，"
              "能力层封装对话模型、语音识别与语音合成，数据层用 SQLite 存业务数据、用文件存语音，"
              "运行层是 Python 进程与 systemd 守护。手机端只有界面与本地缓存，不做业务判断，"
              "这样换手机不用迁移数据。")
    para(doc, "整套软件由团队四人共同开发，分工见登记材料中的合作开发协议：一人负责智能体搭建、"
              "核心代码与部署，三人分别负责界面开发、功能与交互设计、适老化需求调研。")

    section(doc, "1.2", "核心功能概述")
    para(doc, "本软件包含以下十一个核心功能模块（见表1-1）。")
    table(doc, "表1-1", "核心功能模块",
          ["序号", "模块名称", "功能说明"],
          [
              [1, "账号与登录", "注册即登录，系统按序分配 8 位数字编号作为账号唯一标识；"
                             "账号名称最长 20 个字符，支持头像设置"],
              [2, "家属绑定", "老人端生成邀请码，家属凭码绑定；绑定后家属可看今日日程确认情况、"
                             "老人主动说过的话与连续活跃天数，双方可互相留言"],
              [3, "智能对话", "文字与语音两种输入；默认陪伴助手，命中医疗话题自动切换健康顾问"
                             "并追加合规提示；可锁定纯聊天或纯医疗模式；回复按行分开呈现"],
              [4, "三维数字人", "端侧渲染三维形象，按语音字级时间戳驱动口型；"
                               "低端设备可关闭三维改静态头像，不影响对话与语音"],
              [5, "长期记忆", "分老人画像与说话风格两类，每 5 轮对话沉淀一次；"
                             "用户可查看、编辑、删除任一条目"],
              [6, "健康档案", "记录血压、血糖、体重三类指标；血压要求高压大于低压并做范围校验；"
                             "按时间展示记录与趋势，可切日、周、月"],
              [7, "病例管理", "上传病历、检查单的图片或 PDF，自动识别文字并回填标题、"
                             "就诊日期、医院、诊断、摘要五个字段，按时间轴归档"],
              [8, "用药与日程", "日常、每周、一次性特别安排三类计划；日历汇总当月安排；"
                               "到期以系统通知与应用内消息提醒；可打卡与取消打卡"],
              [9, "主动关心", "在清醒时段（默认 8:00–21:00）发起关心提问，每日最多 2 次、"
                             "间隔不少于 4 小时、刚聊过 30 分钟内不问；未来事项转为待回访"],
              [10, "智能体角色", "可建多个角色并设定姓名、关系、性格、口头禅、称呼方式；"
                                "关系标签显示在对话列表；可设默认与删除"],
              [11, "设置与适老化", "大字体模式、服务器地址配置与连接测试、数字人形象配置；"
                                  "界面按大字号、高对比度、宽点击区设计"],
          ],
          [1.4, 2.6, 12.6])

    section(doc, "1.3", "读者与阅读约定")
    para(doc, "本说明书面向三类读者：一是部署方，负责把服务端跑起来；二是使用者，"
              "即老人与家属，关心界面上怎么操作；三是验收或审查人员，需要核对功能是否属实。"
              "三类读者的关注点不同，建议按下面的顺序读。")
    steps(doc, [
        "（1）部署方：第二章（运行环境与安装）、第五章（数据与安全）。",
        "（2）使用者：第三章（界面介绍）、第六章（典型使用流程）。",
        "（3）验收与审查：第一章（功能清单）、第三章各节的操作步骤、第四章（技术特点）。",
    ])
    para(doc, "全书约定：界面上的按钮、菜单、提示语一律用中文引号标出，如“服务器地址”，"
              "以便与应用内文字对照；参数名用等宽写法，如 API_TOKENS；"
              "凡带具体数字的说明（次数、间隔、条数、超时）都取自程序默认配置，"
              "部署方可以在配置文件里改，改后以实际配置为准。")
    para(doc, "文中插图取自实机运行界面，未做美化或拼接；图里的人名、编号与数值均为测试数据。"
              "表格用于罗列配置项、字段与模块，正文用于解释为什么这样设计，两者可以分开看。")

    # ══════ 第二章
    chapter(doc, "第二章", "运行环境介绍")
    section(doc, "2.1", "硬件环境")
    subsection(doc, "2.1.1", "手机端运行环境")
    para(doc, "本软件手机端为 Android 应用，界面与三维形象由手机端渲染，配置要求如下（见表2-1）。"
              "安装包按 Android 5.0（API 21）及以上构建，目标版本为 Android 14（API 34）。")
    table(doc, "表2-1", "手机端硬件配置",
          ["项目", "配置要求", "备注"],
          [
              ["操作系统", "Android 5.0（API 21）及以上", "目标版本 Android 14（API 34）"],
              ["处理器", "四核 1.8GHz 及以上", "近五年机型均可"],
              ["内存", "2GB 以上", "开启三维形象建议 4GB"],
              ["存储", "可用空间 200MB 以上", "三维形象资源随安装包提供"],
              ["屏幕", "分辨率 720×1280 及以上", "界面按竖屏布局"],
              ["网络", "Wi-Fi 或 4G/5G", "与服务端在同一网络时最稳定"],
              ["输入", "触摸屏、麦克风、摄像头", "麦克风用于语音，摄像头用于拍病历"],
          ], [2.2, 7.0, 7.2])

    subsection(doc, "2.1.2", "服务端运行环境")
    para(doc, "服务端承担对话编排、数据存储与接口服务，可部署在普通电脑或云主机上（见表2-2）。"
              "服务端本身不依赖显卡，三维渲染全部在手机端完成。")
    table(doc, "表2-2", "服务端硬件配置",
          ["项目", "配置要求", "备注"],
          [
              ["处理器", "1 核及以上", "建议 2 核，主要开销在模型请求转发"],
              ["内存", "1GB 以上", "建议 2GB"],
              ["磁盘", "40GB 可用空间", "病例图片占用随使用增长"],
              ["其他", "可长期通电、可联网", "家用小主机或云主机均可"],
          ], [2.2, 7.0, 7.2])

    subsection(doc, "2.1.3", "开发环境")
    para(doc, "本软件开发与测试所使用的环境如下（见表2-3）。")
    table(doc, "表2-3", "开发环境",
          ["项目", "配置"],
          [
              ["开发设备", "笔记本电脑，处理器 i9-14900HX，内存 16GB，固态硬盘 512GB"],
              ["操作系统", "Windows 11 64 位"],
              ["开发工具", "HBuilderX 5.26、Visual Studio Code、Node.js 18、Vite 5、Git"],
              ["编程语言", "Python、JavaScript、Vue（HTML/CSS）"],
              ["版本管理", "Git；模型训练与数据脚本位于 ml/scripts 目录"],
          ], [3.0, 13.6])

    section(doc, "2.2", "软件环境")
    para(doc, "本软件运行所需的支撑软件清单如下（见表2-4）。服务端依赖只有 5 个包，"
              "没有数据库服务、没有缓存服务，装完即可跑。")
    table(doc, "表2-4", "软件环境",
          ["序号", "软件名称", "版本要求", "用途说明"],
          [
              [1, "手机端操作系统", "Android 5.0（API 21）及以上", "客户端运行环境"],
              [2, "服务端操作系统", "Ubuntu 22.04 / Debian 12 / Windows 10 及以上", "服务端运行环境"],
              [3, "Python", "3.11 及以上", "服务端运行语言"],
              [4, "FastAPI / Uvicorn", "0.141.1 / 0.54.0", "接口服务与进程托管"],
              [5, "httpx / PyYAML / python-multipart", "0.28.1 / 6.0.3 / 0.0.32", "模型请求、配置解析、文件上传"],
              [6, "SQLite", "3", "数据存储，单文件，无需单独安装"],
              [7, "浏览器", "支持 HTML5 的现代浏览器", "网页端访问"],
          ], [1.4, 6.0, 4.6, 4.6])

    section(doc, "2.3", "网络环境")
    para(doc, "本软件对网络环境的要求如下：")
    steps(doc, [
        "（1）手机端与服务端需在同一网络内，或服务端具备可访问的公网地址；"
        "局域网部署时手机连同一路由器的 Wi-Fi 即可。",
        "（2）服务端默认监听 127.0.0.1:8000；要让手机访问，需把 HOST 改为 0.0.0.0 或内网地址，"
        "并在云主机安全组放行 8000 端口。",
        "（3）对话内容由大语言模型生成，需服务端能够访问模型接口。默认指向 "
        "https://api.deepseek.com/v1，模型名 deepseek-chat，单次超时 30 秒。",
        "（4）接口采用 HTTP/HTTPS，鉴权用令牌加账号会话凭据，两个凭据放在两个请求头，"
        "一个管能不能进来，一个管你是谁。",
        "（5）对话采用流式返回，服务端每 10 秒发一次心跳，避免中间代理掐断长连接。",
        "（6）服务端不可达时，手机端保留已缓存的历史消息供查看，并提示正在使用的地址，不显示白屏。",
        "（7）若不便访问外部模型，可把模型地址指向内网自建服务，或改用本地模型；"
        "切换只改配置，不改代码。",
        "（8）本软件不上传数据到第三方；账号、聊天、健康数据与病例均存放在部署方自己的数据库中。",
    ])

    section(doc, "2.4", "安装部署流程")
    subsection(doc, "2.4.1", "服务端部署")
    para(doc, "服务端按以下步骤部署：")
    steps(doc, [
        "（1）将代码拷到目标机器，进入 server 目录。",
        "（2）创建虚拟环境：python -m venv .venv，然后激活。",
        "（3）安装依赖：pip install -r requirements.txt，共 5 个包。",
        "（4）复制 .env.example 为 .env，按下表逐项填写。",
        "（5）执行 python run.py 启动，默认监听 8000 端口。",
        "（6）访问 http://<地址>:8000/healthz，返回 ok 表示服务已就绪。",
        "（7）需要开机自启时，Linux 注册为 systemd 服务，Windows 注册为计划任务；"
        "服务文件里要写清工作目录与 .env 路径，否则读不到配置。",
        "（8）日志默认输出到标准输出，用 journalctl 或重定向到文件都可以；建议按大小轮转。",
    ])
    para(doc, "常用配置项如下（见表2-5），全部通过 .env 读取，改完重启生效。")
    table(doc, "表2-5", "服务端主要配置项",
          ["配置项", "默认值", "说明"],
          [
              ["HOST / PORT", "127.0.0.1 / 8000", "监听地址与端口；供手机访问要改 HOST"],
              ["DATABASE_URL", "memory://", "数据库位置；正式部署指向 data/*.db 文件"],
              ["AUTH_MODE", "auto", "接口鉴权：auto / required / off"],
              ["API_TOKENS", "空", "令牌列表；对外提供服务时必须设置"],
              ["LLM_MODEL", "deepseek-chat", "对话模型名"],
              ["LLM_BASE_URL", "api.deepseek.com/v1", "模型接口地址，兼容 OpenAI 协议"],
              ["LLM_TIMEOUT", "30 秒", "单次请求超时"],
              ["LLM_TEMPERATURE", "0.8", "生成温度"],
              ["LLM_MAX_TOKENS", "800", "单次回复最大长度"],
              ["HISTORY_TURNS", "8", "进入提示词的历史轮数"],
              ["HISTORY_COMPRESS_THRESHOLD", "48", "历史超过多少条触发压缩"],
              ["HISTORY_KEEP_RECENT", "16", "压缩时保留最近多少条原文"],
              ["WIKI_ENABLED / LEARN_EVERY", "true / 5", "长期记忆开关与学习间隔（轮）"],
              ["CARE_ENABLED / TICK_SECONDS", "true / 600", "主动关心开关与调度检查间隔"],
              ["SSE_HEARTBEAT_SECONDS", "10", "流式返回心跳间隔"],
          ], [5.4, 3.6, 7.6])

    subsection(doc, "2.4.2", "手机端安装")
    para(doc, "手机端安装与首次配置步骤如下：")
    steps(doc, [
        "（1）安装提供的 Android 安装包。清单里声明了 11 项权限，运行时只申请麦克风、"
        "摄像头、相册三类，用于语音、拍病历与选择图片。",
        "（2）进入底部“我的”，点“服务器地址”，填写服务端地址（含端口）。",
        "（3）点“测试连接”，页面显示耗时与返回内容，正常后保存。",
        "（4）连接失败时页面给出四条排查方向：地址是否带端口、手机与服务端是否同网、"
        "服务端进程是否在跑、防火墙是否放行。",
        "（5）返回登录页注册或登录，注册成功后系统按序分配 8 位数字编号。",
        "（6）装好之后不联网也能看已缓存的历史消息，只是发不出新消息。",
    ])

    section(doc, "2.5", "三种部署形态")
    para(doc, "同一套服务端代码支持三种部署形态，按使用场景选择（见表2-6）。"
              "三者功能一致，区别只在手机怎么找到服务端，以及数据经过哪条网络。")
    table(doc, "表2-6", "部署形态对比",
          ["形态", "适用场景", "手机如何连接", "注意事项"],
          [
              ["局域网", "单个家庭，服务端放在家里的电脑或小主机", "手机连同一路由器的 Wi-Fi，"
                       "直接填服务端内网地址", "服务端地址随网络变化，路由器里可绑定固定地址"],
              ["虚拟专网", "服务端在另一个地点，但不想暴露到公网", "先加入同一虚拟专网，"
                        "再填专网地址", "手机与服务端都要装专网客户端"],
              ["公网反向代理", "社区或机构统一部署，多户远程访问", "填域名，由反向代理转发", "需要 HTTPS 证书；务必把鉴权改为强制并更换令牌"],
          ], [2.6, 5.4, 5.0, 4.6])
    para(doc, "三种形态的切换只涉及网络配置，不涉及业务代码。从局域网改成公网时，"
              "服务端要打开的开关只有两个：把 AUTH_MODE 设为 required，把 API_TOKENS 换成随机串；"
              "手机端只需把服务器地址改成域名。")

    section(doc, "2.6", "目录结构说明")
    para(doc, "部署时经常要在目录里找文件，这里说明主要目录的职责，便于定位问题：")
    steps(doc, [
        "（1）server/app/api：各业务接口，按模块分文件，路由在这里注册。",
        "（2）server/app/persona：双人设判断与提示词拼装，医疗合规的第一道关卡在这里。",
        "（3）server/app/llm、asr、voice、vision：四类外部能力，各自封装成可替换的提供者。",
        "（4）server/app/wiki、history、care：长期记忆、历史压缩、主动关心三条链路。",
        "（5）server/app/health、schedule、messaging：健康档案、日程提醒、家属消息。",
        "（6）server/data：数据库文件；server/case_files：病例图片与原件。",
        "（7）server/deploy：部署脚本、服务单元、反向代理配置与备份脚本。",
    ])

    section(doc, "2.7", "部署自检")
    para(doc, "部署完成后按下列顺序自检，前四条不通过不必继续：")
    steps(doc, [
        "（1）访问 http://127.0.0.1:8000/healthz，应返回 ok。",
        "（2）查看启动日志，应没有鉴权失败、数据库打不开、模型地址为空这几类报错。",
        "（3）在服务端本机访问 /docs，能打开接口文档说明服务跑通了。",
        "（4）用 curl 带上令牌请求任一接口，应返回业务数据而不是 auth_required。",
        "（5）手机端填服务端地址后“测试连接”通过，说明网络与端口都通。",
        "（6）注册一个测试账号、发一句消息，能收到回复说明模型侧也通了。",
        "（7）执行一次备份脚本，确认生成的压缩包里有数据库与清单。",
    ])
    para(doc, "自检用过的测试账号建议保留一个，后续演练与验收可复用；"
              "正式使用前把测试账号的数据清掉，避免混进真实记录。")

    section(doc, "2.8", "数据迁移与换机")
    para(doc, "换服务端或换手机时按下列顺序操作，可以做到不丢数据：")
    steps(doc, [
        "（1）在旧服务端执行一次备份，确认压缩包生成且清单校验值正常。",
        "（2）停掉旧服务端，避免迁移过程中还在写数据。",
        "（3）把 data 目录与 case_files 目录整体复制到新机器同一路径。",
        "（4）在新机器装依赖、复制 .env，按需改 DATABASE_URL 指向新路径。",
        "（5）启动新服务端，访问 /healthz 确认就绪。",
        "（6）手机端把服务器地址改成新地址，重新登录后检查历史消息与病例是否都在。",
    ])
    para(doc, "只换手机不换服务端时更简单：新手机装包、填同一个服务端地址、用原账号登录即可，"
              "本地缓存会重新拉取，历史记录不受影响。")

    # ══════ 第三章
    chapter(doc, "第三章", "软件界面介绍")
    para(doc, "本章按界面顺序说明各页的用途与操作。每节先讲这个页面解决什么问题，"
              "再按编号列出操作步骤；步骤里的名称与应用内显示一致，可对照操作。")

    section(doc, "3.1", "登录与注册")
    figure_row(doc, [
        ("18-登录.png", "图3-1", "登录与注册入口"),
        ("02-聊天详情.png", "图3-2", "对话详情"),
    ])
    para(doc, "启动后进入登录页。页面提供账号名与密码输入框，下方有“忘记密码”“没有账号请点击注册”"
              "两个入口（如图3-1）。注册时填账号名与密码，账号名最长 20 个字符且不能与已有账号重名；"
              "注册成功即进入登录状态，系统按序分配一个 8 位数字编号作为账号唯一标识，"
              "这个编号可以给家属，用于绑定。")
    steps(doc, [
        "（1）输入账号名称。新用户先点“没有账号请点击注册”。",
        "（2）输入密码。密码框右侧有显示与隐藏的切换图标，老人打字慢时可以打开核对。",
        "（3）点“登录”。登录成功后直接进入对话列表，没有额外的引导页。",
        "（4）忘记密码时点“忘记密码?”。该入口目前只给提示，需由部署方在服务端重置；"
        "这是有意为之，老人账号通常由家属代为维护，开放自助重置反而容易被冒用。",
        "（5）账号名称重复、过长或为空时，页面会在输入框下方给出中文提示，不会静默失败。",
    ])
    para(doc, "同一台手机可以登录不同账号，退出登录后本地缓存的消息会清除，"
              "换人使用不会看到上一位的内容。账号编号是 8 位定长数字，由服务端按序发放，"
              "不会出现跳号或重复。")

    para(doc, "登录页从上到下分四块：顶部是返回与标题，中部是品牌标识与账号密码两个输入框，"
              "输入框下方是“忘记密码?”“没有账号请点击注册”两个文字入口，最下面是整行宽的登录按钮。"
              "页面不设第三方登录，避免老人被引导到别的应用。")

    section(doc, "3.2", "对话列表")
    para(doc, "登录后进入对话列表。默认有一个与助手的会话，固定在最上面不参与排序；"
              "与家属的会话在绑定之后才出现。每条显示对方名字、关系、最后一句话与时间，"
              "有新消息时右侧显示红点，进入会话即清除，不按条数累计。")
    para(doc, "列表按最近消息时间排序，助手会话固定在顶部。会话多了以后，常联系的人自然排在前面，"
              "不需要手动置顶或分组。列表下拉可手动刷新，用于另一台设备刚发过消息的情况。")
    para(doc, "会话里没有“正在输入”这类提示，也没有已读回执。老人不需要判断对方看没看，"
              "家属也不必因为“已读未回”焦虑。消息状态只有三种：发送中、已发送、发送失败，"
              "在气泡右侧分别用转圈、对勾、红色感叹号区分。")
    para(doc, "会话列表支持长按删除，删除只清列表入口与本地缓存，服务端记录按账号分别保留，"
              "误删后可用同一账号重新进入恢复。")

    section(doc, "3.3", "对话详情与双人设")
    para(doc, "点会话进入详情页。底部输入框打字，点发送；发送失败的消息右侧显示红色感叹号，"
              "点一下重发；长按消息可复制。回复按行分开，一行一句，不写成一大段，"
              "老人看起来轻松，语音播报时也好与口型对上（如图3-2）。")
    para(doc, "对话里有两套说法。一套是陪伴助手，用在日常聊天，句子短、用词口语，"
              "不说“您好，请问有什么可以帮您”；另一套是健康顾问，用在医疗健康话题，"
              "回答末尾补一句固定提示：仅供参考，实际情况请以医嘱为准，及时线下就医。")
    para(doc, "切换分自动与手动。自动按关键词分层判断：先看这句话里有没有明显的医疗词，"
              "比如血压、血糖、吃药、头晕、摔了；再看是不是常规吃药询问，比如“药吃了没”，"
              "这种不算医疗问题，不加提醒；最后结合情绪词与认知相关的说法判断。"
              "命中就换成健康顾问。手动是在“人设模式”里选，选完不再自动切。")
    para(doc, "举三个例子。“血压有点高”命中医疗词，换健康顾问，回答末尾加提醒；"
              "“药吃了没”属常规吃药询问，不算医疗问题，不加提醒；"
              "“心里堵得慌”没有医疗词，但情绪词命中，语气会自动放缓。")
    para(doc, "提醒做了三道：第一道判断问题类型，第二道检查回答里有没有停药、剂量、诊断这类说法，"
              "第三道在回答生成完再扫一遍。三道都在代码里。把模式锁成“只聊家常”后，"
              "只要回答涉及医疗内容，提醒照样加，这一项不开放关闭。")
    steps(doc, [
        "（1）在底部输入框打字，点“发送”。",
        "（2）回复逐字出现；若走语音播报，语句与文字同步高亮。",
        "（3）发送失败时点红色感叹号重发；连续失败三次给出网络提示。",
        "（4）长按任意消息可复制；长按回复可重新朗读。",
        "（5）进“我的 → 人设模式”可锁定纯聊天或纯医疗，锁定状态在页面顶部有标识。",
    ])

    para(doc, "对话页分三块：顶部显示对方名字与关系，中部是消息流，底部是输入区。"
              "输入区左侧是麦克风按钮，中间是输入框，右侧是发送按钮；"
              "按住麦克风时按钮变色并显示“正在听”，松手即发送，不需要再点发送。")

    section(doc, "3.4", "语音与三维数字人")
    figure_row(doc, [
        ("10-数字人通话.png", "图3-3", "三维数字人通话"),
        ("15-健康档案.png", "图3-4", "健康档案"),
    ])
    para(doc, "语音做三件事：把说的话转成文字，把回复念出来，让数字人的嘴跟着动（如图3-3）。")
    steps(doc, [
        "（1）在对话页按住麦克风说话，松开即发送。",
        "（2）页面显示“正在听”，识别完文字自动填入输入框；识别有误可直接改文字。",
        "（3）点发送后回复逐字出现，同时开始念；念的时候嘴型跟着变，可暂停与重播。",
        "（4）麦克风权限未授予时，页面提示前往系统设置打开，文字输入不受影响。",
        "（5）环境嘈杂或方言较重时识别率会下降，建议说完整句子再松手。",
        "（6）语音合成不可用时自动退回纯文字，界面给一次提示，功能不中断。",
    ])
    para(doc, "数字人形象在“我的”里配置，资源随安装包提供，不需要联网下载。"
              "形象可换装、换场景，换完回对话页生效。手机带不动时可在设置里关闭三维、"
              "改为静态头像，聊天与语音照常。")

    section(doc, "3.5", "AI 了解我的（长期记忆）")
    para(doc, "软件记两类东西：一类是老人提到的事实，包括怎么称呼、几点起几点睡、爱吃什么、"
              "家里有谁、关心哪些健康问题、有没有重要的日子；另一类是说话习惯，"
              "包括口头禅、怎么称呼人、句子长短。两类分开存，每 5 轮对话整理一次，"
              "不是每轮都调模型——每轮都学会让模型调用次数翻倍，也没有必要。")
    para(doc, "说话习惯只从真人发的消息里学，助手自己的回复不拿来当素材，否则越学越僵。"
              "口头禅与称呼习惯单独存放，清理时不会一起删。记忆条数不设硬上限，"
              "但参与对话的只取最近更新的若干条，太老的留着可查、不进上下文。")
    steps(doc, [
        "（1）进“我的”，点“AI 了解我的”。",
        "（2）页面按分节列出全部条目，每条显示内容、来源与更新时间。",
        "（3）点某条能改能删；删掉之后后面聊天不再引用该条，历史记录不受影响。",
        "（4）分节可以整段编辑，保存后下一次对话即生效。",
        "（5）右上角显示上次整理时间，方便判断记忆是否够新。",
    ])

    section(doc, "3.6", "健康档案")
    para(doc, "健康档案能记三类指标：血压、血糖、体重（如图3-4）。录入时填数值与时间，可加备注，"
              "比如“饭后两小时”；列表按时间倒序，趋势图能切日、周、月。"
              "血压要求同时填高压与低压，高压范围 50 到 300、低压 30 到 200，"
              "且高压必须大于低压，填反了会提示。")
    steps(doc, [
        "（1）进“我的”，点“健康档案”。",
        "（2）点右上角“记录”，选择血压、血糖或体重。",
        "（3）填数值与时间，可加备注说明测量条件。",
        "（4）保存后列表刷新，趋势图按所选周期重画。",
        "（5）超出常见范围的数值标红，但只提示不给结论。",
    ])
    para(doc, "标红只是提示。单次测量受测量方式、时间、情绪影响，凭一个数字下判断既不准确，"
              "也容易让人紧张；连续多天的趋势比单次数值更有参考价值，所以页面把趋势图放在列表上方。")

    para(doc, "健康档案页顶部是三项指标的切换标签，中间是趋势图，下面是记录列表，"
              "右上角是“记录”按钮。趋势图与列表联动，点图上某一点会高亮对应记录。")

    section(doc, "3.7", "病例与病史")
    para(doc, "病历、检查单都能传，图片与 PDF 都行。上传后系统先做文字识别，再把结果回填到表单："
              "标题、就诊日期、医院、诊断、摘要共五个字段。回填只填空着的字段，"
              "不覆盖用户已经写好的内容；识别不准的地方可以手动改。")
    para(doc, "确认保存后按时间轴归档，时间轴按就诊日期倒序，同一天的按上传先后排。"
              "老人后来说身体不舒服时，助手能调出这些记录参考，回答比通用建议贴合。"
              "若部署环境没有接入视觉识别，这一步自动改为手动填写，填完一样能归档，"
              "一样能在对话里用。")
    steps(doc, [
        "（1）进“健康档案”，点“病例”。",
        "（2）点“上传”，拍照或从相册选，可多选。",
        "（3）上传后显示识别结果，并自动填进空字段。",
        "（4）核对并补齐字段后保存，记录进入时间轴。",
        "（5）点某条记录可查看原件大图与字段内容。",
    ])

    section(doc, "3.8", "用药与日程提醒")
    figure_row(doc, [
        ("05-康养计划.png", "图3-5", "康养计划"),
        ("12-智能体角色.png", "图3-6", "智能体角色列表"),
    ])
    para(doc, "提醒分三类：日常计划是每天都要做的事，比如早饭后吃药；每周计划是每周固定某天做的事；"
              "特别计划是一次性的，比如下周三复查，过了那天不再提醒。分三类是为了不让老人"
              "把每天吃的药和下周三复查混在一起（如图3-5）。")
    steps(doc, [
        "（1）进入底部“日程”，点“日常计划”添加，填事项、时刻与重复规则。",
        "（2）点“每周计划”，选星期与时刻。",
        "（3）点“特别计划”，选具体日期，到期自动失效。",
        "（4）点日历上某天可查看当天全部安排，也能直接添加。",
        "（5）到点提醒走系统通知与应用内消息两条路，未完成项在当天列表保留标记。",
        "（6）做完的点一下打卡，状态变为已完成，点错了能取消；打卡数据回流为完成率，"
        "家属端按完成率看当天情况。",
    ])

    para(doc, "日程页顶部是三个计划入口：日常计划、每周计划、特别计划；"
              "中间是当天安排列表，每条右侧有打卡按钮；底部是日历视图，"
              "点某一天可跳到那天的列表。三个入口分开，是为了避免老人在一堆设置里找。")

    section(doc, "3.9", "主动关心与回访")
    para(doc, "软件会在合适的时候主动问一句，内容包括吃了什么、今天有没有遇到特别的事、"
              "今天过得怎么样、有没有想做还没做的事。这四类是照着独居老人平常打电话会聊的内容定的，"
              "问法按时段换，不天天用同一句。")
    para(doc, "问的次数与时机有四重限制：每日最多 2 次；两次之间至少隔 4 小时；"
              "只在 8:00 到 21:00 之间问，深夜不打扰；刚聊过 30 分钟内不问。"
              "四个值都在配置里，部署方可以调整，不用改代码。")
    para(doc, "老人连着回几个字，就不再追问。提到以后要做的事会被记下来，到那天在聊天里再提一次；"
              "同一天只提一次，老人说还没做就隔天再问，说做完了就不再问。"
              "过期条目按实际过了几天调措辞，不会出现“今天正是这日子”但日期对不上的情况。")

    section(doc, "3.10", "家属绑定与关怀查看")
    para(doc, "老人账号里能生成邀请码，家属在自己账号里填这个码完成绑定。"
              "绑定后家属端主要看三样：今日日程的确认情况（完成了哪些、哪些没完成）、"
              "老人主动说过的话、连续活跃天数。双方可以互相留言，留言支持文字与语音，"
              "都能看到历史。")
    steps(doc, [
        "（1）老人端进“我的”，点“家人管理”，生成邀请码。",
        "（2）家属在“家人管理”里点“绑定老人”，填码。",
        "（3）绑定成功后两边列表里互相出现对方会话。",
        "（4）家属端首页看今日日程确认情况与老人主动说过的话。",
        "（5）可以解绑，解绑后两边列表里的会话一起消失。",
    ])
    para(doc, "家属会话与助手会话是两回事，消息不混在一起，免得家里私下说的话跑到助手那边去。"
              "家属端看到的是日程确认与老人主动发言的摘录，不是聊天全文；"
              "需要了解细节时建议直接通话。")

    para(doc, "家属端首页分三块：顶部是老人称呼与连续活跃天数，中间是今日日程确认情况，"
              "下面是“他主动说的话”摘录与留言入口。看不到聊天全文，是有意的隐私边界。")

    section(doc, "3.11", "智能体角色")
    para(doc, "可以建多个角色，每个填名字、关系、性格、口头禅与怎么称呼（如图3-6）。"
              "关系显示在对话列表里，老人按平时的叫法就能找；设好称呼方式后，"
              "这个称呼会进入长期记忆。")
    steps(doc, [
        "（1）进“我的”，点“智能体角色”。",
        "（2）点“新建角色”，填名字、关系、性格、口头禅。",
        "（3）设称呼方式，填“您”还是“妈”，这一项会进长期记忆。",
        "（4）保存后出现在对话列表，长按可设默认或删除。",
        "（5）删掉角色之后对话还在，只是不再走这个角色的设定。",
    ])
    para(doc, "智能体设置里换对话模型。云端模型聪明些，要联网；本地模型不用出网，"
              "适合对数据外传有要求的地方。换完立刻生效，历史消息不受影响。")

    section(doc, "3.12", "设置与适老化")
    para(doc, "“我的”页分两组。上面一组是陪伴设置：智能体角色、人设模式、AI 了解我的、"
              "数字人形象、家人管理、智能体设置；下面一组是健康与设置：健康档案、大字体、"
              "服务器地址。分组按常改与少改来，减少误点。")
    para(doc, "界面字号大、对比度高、按钮点击区大，大字体模式能把正文再放大一档。"
              "键盘输入只有两处：聊天输入框与健康数值，其余用下拉、点选、加减按钮。"
              "数值超出合理范围时提示复核，但不阻止保存，免得把真实异常藏起来。")
    para(doc, "服务器地址页的提示里带着正在用的地址。这里吃过亏，早先只提示“连不上服务器”，"
              "老人只能找家人，家人也不知道软件在连哪个地址，只能来回猜。")
    steps(doc, [
        "（1）点“大字体模式”右侧开关，正文放大约一档，立即生效。",
        "（2）点“服务器地址”，可查看当前地址、来源与凭据状态。",
        "（3）填新地址后点“测试连接”，显示耗时与返回内容。",
        "（4）保存后软件重新进入，不用重装。",
    ])

    section(doc, "3.13", "页面清单")
    para(doc, "手机端共 25 个页面，按功能分组如下（见表3-1）。表中“页面”是程序内的目录名，"
              "排查问题或看代码时可按此定位。")
    table(doc, "表3-1", "手机端页面清单",
          ["分组", "页面", "用途"],
          [
              ["启动与账号", "splash / auth / register", "启动页、登录、注册"],
              ["会话", "chats / chat-detail / empty", "会话列表、对话详情、空状态页"],
              ["人文陪伴", "face / vision / persona-mode", "数字人对话、数字人形象、人设模式"],
              ["记忆", "wiki / remark", "AI 了解我的、备注编辑"],
              ["角色", "roles / role-new / agent-settings", "角色列表、新建角色、智能体设置"],
              ["健康", "health / plans", "健康档案、计划总览"],
              ["日程", "daily / weekly / special / calendar", "日常计划、每周计划、特别计划、日历"],
              ["家属", "family / family-manage", "家属会话、家人管理与绑定"],
              ["设置", "me / server / tokens", "我的、服务器地址、令牌设置"],
          ], [2.6, 6.4, 7.6])
    para(doc, "页面之间不设过渡动画，点一下直接进入。老人对动画不敏感，"
              "反而会觉得卡；直接进页面能减少等待感。")

    section(doc, "3.14", "空状态与异常页")
    para(doc, "数据为空时不显示白屏，而是给一句话说明加一个动作入口。"
              "比如还没有任何会话时，页面居中显示“还没有消息”，下面一个“去说两句”的按钮；"
              "家属没有绑定时显示“还看不到家人的情况”，下面给“去绑定”的入口。")
    para(doc, "空状态页存在的理由是避免老人以为软件坏了。老人看到空白页第一反应是"
              "“是不是手机坏了”，有人在旁边还好，独居时就会放下不用。"
              "一句说明加一个按钮，成本很低，但能把这个误解掐掉。")
    para(doc, "异常提示统一放在页面顶部，不用弹窗。弹窗要手动关，老人有时会关不掉；"
              "顶部提示三秒后自动收起，也可以点一下关掉。")

    # ══════ 第四章
    chapter(doc, "第四章", "技术特点与创新点")
    section(doc, "4.1", "主要技术特点")
    para(doc, "本软件的主要技术特点如下：")
    steps(doc, [
        "（1）双人设自动路由。说话方式按关键词分层判断，命中医疗话题就换；"
        "合规提示由代码写入，模型不写也得写。",
        "（2）医疗合规三重兜底。先分类，再查话术，回答出来再扫一遍；"
        "停药、剂量、诊断这几类说法会被拦下或改写。",
        "（3）分层长期记忆。记忆分两层存，说话习惯只学真人发的消息，不拿助手自己的回复当素材；"
        "口头禅单独放，清理时不会一起丢；学习间隔为 5 轮，避免每轮都调模型。",
        "（4）对话历史压缩。超过 48 条触发压缩，保留最近 16 条原文，其余压成摘要；"
        "用短语出现的次数判断哪些是冗余，摘要本身也可再压缩。",
        "（5）主动关心调度。每日上限 2 次、间隔 4 小时、清醒时段 8:00–21:00、"
        "刚聊过 30 分钟内不问，四个条件同时满足才发。",
        "（6）三维口型同步。语音合成返回字级时间戳，端侧据此逐步驱动口型，不是整段动画。",
        "（7）能力可替换。对话模型、语音识别、语音合成都能换，改配置就在云端与本地之间切；"
        "同一套服务端能跑在局域网、虚拟专网与公网，带令牌鉴权与自动备份。",
    ])

    section(doc, "4.2", "创新点")
    steps(doc, [
        "（1）把入口放在对话上，而不是表单上。老人只需说话，记录、提醒、求助都在对话里完成，"
        "这是与常见健康类应用最根本的差别。",
        "（2）医疗边界由代码守，而不是靠模型自觉。三道检查与固定提示语使得"
        "“闲聊不加免责、医疗必加免责”成为可验证的行为，而不是概率问题。",
        "（3）说话风格只向真人学习。助手自己的回复不参与风格记忆，避免越学越像机器。",
        "（4）主动关心受四重约束。次数、间隔、时段、刚聊过与否同时满足才发，"
        "把“关心”做成可配置的规则，而不是随机推送。",
    ])

    section(doc, "4.3", "异常与降级处理")
    para(doc, "下列情况在代码里都有对应的处理，不会让界面卡死或白屏：")
    steps(doc, [
        "（1）网络中断：正在发送的消息标记为发送失败，可重发；已缓存的历史消息仍可查看。",
        "（2）模型超时：超过 30 秒未返回则按失败处理，提示稍后重试，不影响其它功能。",
        "（3）语音合成不可用：自动退回纯文字，界面提示一次。",
        "（4）语音识别不可用：麦克风图标置灰并提示改用文字输入。",
        "（5）视觉识别不可用：病例上传改为手动填字段，归档流程不变。",
        "（6）权限被拒：给出前往系统设置的指引，其余功能照常。",
        "（7）服务端重启：客户端下一次请求自动重连，不需要重新登录。",
        "（8）会话凭据过期：跳转登录页，登录后回到原页面，已缓存内容不丢。",
    ])

    section(doc, "4.4", "容量与响应说明")
    para(doc, "下列数值都可以在配置里查到，写在这里是为了让部署方对资源有预期：")
    steps(doc, [
        "（1）单次对话请求的模型超时是 30 秒；超时按失败处理，界面提示稍后重试。",
        "（2）单次回复的最大长度限制为 800 个 token，正常聊天用不满，长解释会被截断。",
        "（3）流式返回每 10 秒发一次心跳，用于穿过中间代理的空闲超时。",
        "（4）进入提示词的历史轮数为 8 轮；更早的内容由摘要代替。",
        "（5）历史累计到 48 条触发压缩，压缩后保留最近 16 条原文。",
        "（6）长期记忆每 5 轮整理一次，因此刚说过的话可能要下一轮才进记忆。",
        "（7）主动关心的调度每 600 秒检查一次，所以提醒的触发精度是分钟级，不是秒级。",
        "（8）数据库为单文件，一个家庭的正常使用下体积增长主要来自病例图片，"
        "建议按季度看一下磁盘占用。",
    ])

    section(doc, "4.5", "几处设计取舍")
    para(doc, "有几处看起来“少做了点什么”，其实是权衡后的决定，说明如下：")
    steps(doc, [
        "（1）不开放关闭合规提示。提示会让回答变长，但医疗内容的边界不能交给用户决定；"
        "关掉之后一旦出了事，责任无法界定。",
        "（2）不做语音唤醒。常驻监听在老人家里会引发隐私顾虑，也让手机耗电变快；"
        "改为按住说话，动作明确、可预期。",
        "（3）不做自动定位与紧急呼叫。定位涉及权限与隐私，误触拨号会打扰急救资源；"
        "改为在回答里给出明确的就医与求助建议。",
        "（4）不把家属端做成监控。家属只看日程确认与主动发言摘录，"
        "看全文会让老人觉得被监视，反而不愿用。",
        "（5）不接多个大模型做投票。多模型能提升准确率，但成本与延迟翻倍，"
        "在陪伴场景里“快”比“极致准确”更重要。",
        "（6）数据只存本地。云端托管省事，但健康与病历数据的合规成本高，"
        "交给部署方自持更稳妥。",
    ])

    section(doc, "4.6", "与纯提示词方案的差别")
    para(doc, "同类产品常见做法是只写一段提示词，把语气与安全要求都交给模型。"
              "本软件在此基础上把关键约束下沉到代码，差别如下：")
    table(doc, "表4-1", "两种实现方式的差别",
          ["能力", "纯提示词", "本软件"],
          [
              ["语气与分行", "依赖模型遵守，偶有整段输出", "提示词约束加后置分行处理"],
              ["医疗话题识别", "依赖模型判断", "关键词分层判断，命中即切人设"],
              ["合规提示", "模型可能忘记写", "代码强制写入，不可关闭"],
              ["风险表述拦截", "只能靠提示词要求", "分类、话术检查、后置扫描三道"],
              ["说话风格学习", "通常不做", "只从真人消息学习，5 轮一次"],
              ["主动提问", "多为定时群发", "次数、间隔、时段、刚聊过四重约束"],
              ["能力替换", "换模型需改提示词", "提供者抽象，改配置即可"],
          ], [3.4, 6.2, 8.0])
    para(doc, "把约束写进代码的代价是灵活性下降：改规则要改代码、要重新测试。"
              "但换来的是可验证——同一句话两次运行得到同样的合规处理，"
              "而不是这次模型记得写、下次忘了。")

    # ══════ 第五章
    chapter(doc, "第五章", "数据存储与安全")
    section(doc, "5.1", "数据存储")
    para(doc, "账号、聊天、身体数据、病例与记忆都存在服务端本机的数据库里，不上传第三方。"
              "数据库为单文件 SQLite，第一次启动自动建表，迁移时连同病例图片目录一并复制即可；"
              "由于是标准格式，可用通用工具查看与导出，不锁定于本软件。")
    para(doc, "删除立即生效：删掉的记忆条目不再参与后面的对话，删掉的会话不再出现在列表里。"
              "记忆条目删除后无法撤回，家属可以在同一页面重新录入要点，后续对话会把新内容记进去。")

    section(doc, "5.2", "接口与鉴权")
    para(doc, "接口默认要令牌。聊天类接口除了令牌还要账号会话凭据，两个东西放在两个请求头，"
              "一个管能不能进来，一个管你是谁。令牌不对直接拒，不返回业务数据。")
    para(doc, "服务端按业务拆成 12 组路由：对话、计划、提醒、推送、记忆、账号、会话、长期记忆、"
              "主动关心、家属、健康、病例；另有健康检查、错误上报、语音识别、语音文件四个独立路由。")
    para(doc, "会话凭据过期后客户端重新登录，已缓存的本地消息还能看，不会白屏。"
              "对外提供服务时必须把鉴权模式改为强制，并把令牌换成随机串，与手机端配置保持一致。")

    section(doc, "5.3", "备份与恢复")
    para(doc, "备份用数据库自己的一致性快照，不用直接复制文件：服务在跑的时候复制，"
              "可能拿到还没落盘的旧数据。备份脚本执行后生成带时间戳的压缩包，"
              "里面包含数据库、病例图片目录与一份清单，清单记着文件数与校验值。")
    steps(doc, [
        "（1）备份脚本放在 deploy 目录，执行后生成带时间戳的压缩包。",
        "（2）压缩包里有数据库、病例图片目录与一份清单，清单记着文件数与校验值。",
        "（3）恢复时先停服务，解包覆盖数据目录，再启动。",
        "（4）建议每天定时跑一次，并把压缩包同步到另一块磁盘。",
        "（5）日志按大小轮转，避免长期运行把磁盘写满。",
    ])

    section(doc, "5.4", "日常维护要点")
    para(doc, "部署方需要照看的事项不多，但四件事不能省：")
    steps(doc, [
        "（1）进程看护。服务端以 systemd 或计划任务方式常驻，异常退出后自动拉起；"
        "可用 /healthz 做存活探测。",
        "（2）每日备份。按 5.3 节执行一致性备份并同步到另一块磁盘，保留最近若干份，便于回溯。",
        "（3）磁盘监控。病例图片随时间增长，磁盘剩余空间低于阈值时应及时扩容或归档。",
        "（4）版本更新。服务端升级只涉及替换代码与重启进程，数据库结构变更由启动时的"
        "自动迁移完成；手机端通过重新安装安装包升级，已登录状态在升级后保持有效。",
    ])

    section(doc, "5.5", "服务端模块划分")
    para(doc, "服务端按职责拆成 23 个模块，每个模块只做一件事，便于替换与测试（见表5-1）。")
    table(doc, "表5-1", "服务端模块职责",
          ["模块", "职责", "模块", "职责"],
          [
              ["accounts", "账号注册、登录、头像", "api", "各业务接口与路由注册"],
              ["persona", "双人设判断、提示词拼装", "orchestration", "一次对话的完整编排"],
              ["llm", "对话模型调用（可替换）", "asr", "语音识别（可替换）"],
              ["voice", "语音合成（可替换）", "vision", "图片识别（可替换）"],
              ["wiki", "长期记忆的抽取与存储", "history", "历史压缩与摘要"],
              ["care", "主动关心的调度与限流", "schedule", "计划、提醒与打卡"],
              ["health", "健康指标与趋势", "messaging", "家属消息与留言"],
              ["knowledge", "康养知识检索", "style", "说话风格与合规扫描"],
              ["memory", "会话上下文组装", "storage", "文件与语音存储"],
              ["models", "数据表与存取", "tools", "工具函数（时间、文本）"],
              ["plan", "计划生成与推进", "avatar", "数字人形象资源"],
          ], [2.8, 5.6, 2.8, 5.4])

    section(doc, "5.6", "接口分组")
    para(doc, "接口按业务分成 12 组，另有 4 个独立路由（见表5-2）。分组方式与模块划分对应，"
              "部署时可按组做访问控制与日志分类。")
    table(doc, "表5-2", "接口分组",
          ["分组", "用途", "分组", "用途"],
          [
              ["对话", "发送消息、流式取回复", "计划", "三类计划的增删改查"],
              ["提醒", "到期提醒的生成与确认", "推送", "系统通知与厂商推送"],
              ["记忆", "上下文与会话摘要", "账号", "注册、登录、头像"],
              ["会话", "会话列表与消息分页", "长期记忆", "画像与风格的读写"],
              ["主动关心", "开关、时段与历史", "家属", "绑定、留言、查看"],
              ["健康", "指标录入与趋势", "病例", "上传、识别、归档"],
              ["/healthz", "存活检查", "/v1/asr/transcribe", "语音识别"],
              ["/v1/audio/{id}", "语音文件读取", "/v1/errors", "客户端错误上报"],
          ], [3.0, 5.4, 3.4, 5.2])

    section(doc, "5.7", "日志与排查顺序")
    para(doc, "出问题时的排查顺序建议固定下来，避免东看一处西看一处：")
    steps(doc, [
        "（1）先看 /healthz 是否正常。不正常说明进程或端口有问题，先解决这个。",
        "（2）再看日志里有没有鉴权失败。有的话是令牌不一致，检查两端配置。",
        "（3）然后看模型相关报错。地址、密钥、模型名三者任一不对都会失败。",
        "（4）最后看具体业务错误码（见第八章），按对应的处理方式修。",
    ])
    para(doc, "日志按大小轮转，保留最近若干份。排查时优先看最后一次启动之后的日志，"
              "更早的通常与当前问题无关。")

    # ══════ 第六章
    chapter(doc, "第六章", "典型使用流程")
    section(doc, "6.1", "老人侧：一天的用法")
    para(doc, "下面按一天的时间顺序说明典型用法，可作为上手指引，也是验收时的走查路径。")
    steps(doc, [
        "（1）早上起床后打开软件，助手会先问一句昨晚睡得怎么样，或今天打算做什么。",
        "（2）早饭后吃药前，日程里会出现日常计划的提醒；吃完点打卡，状态变为已完成。",
        "（3）上午想量血压时，进健康档案点记录，填高压与低压保存，趋势图自动更新。",
        "（4）中午或下午想聊天时，按住麦克风说话，松开即发送；助手按陪伴方式回应。",
        "（5）身体不舒服时直接说，比如“起来太猛眼前一黑”，软件会切换健康顾问并提示就医。",
        "（6）拿到检查单时拍照上传，核对识别出的字段后保存，记录进时间轴。",
        "（7）晚上助手会再问一次今天过得怎么样；提到以后要办的事会被记成待回访。",
    ])

    section(doc, "6.2", "家属侧：远程查看与留言")
    para(doc, "家属用自己的账号登录后，主要做三件事：看情况、留言、维护记忆。")
    steps(doc, [
        "（1）首次使用先在“家人管理”里填老人给的邀请码完成绑定。",
        "（2）首页看今日日程确认情况：完成了哪些、哪些没完成；另有连续活跃天数。",
        "（3）需要叮嘱时在会话里留言，支持文字与语音，老人端会看到红点。",
        "（4）发现记忆里某条不准（比如称呼写错），可在“AI 了解我的”里直接改。",
        "（5）老人生病住院期间，可代为上传病历，补充时间轴。",
    ])

    section(doc, "6.3", "机构侧：一套服务端供多户使用")
    para(doc, "社区或养老机构可以部署一套服务端，为多户家庭开账号，"
              "而不是每家装一台机器。做法与注意事项如下：")
    steps(doc, [
        "（1）按第二章部署服务端，把 AUTH_MODE 改为 required，并生成一组随机 API_TOKENS。",
        "（2）为每户老人与家属分别注册账号，数据按账号隔离，互不可见。",
        "（3）手机端只填同一个服务端地址，各户用各自账号登录。",
        "（4）按 5.4 节建立备份与磁盘监控；机构内网需放行服务端端口。",
        "（5）若有数据外传限制，可把模型指向内网自建服务，或改用本地模型。",
    ])

    section(doc, "6.4", "验收走查清单")
    para(doc, "验收时按下列顺序走一遍，能覆盖主要功能与常见故障点，约需 20 分钟：")
    steps(doc, [
        "（1）注册一个新账号，确认拿到 8 位编号；用同名再注册一次，应提示名称已存在。",
        "（2）在“服务器地址”里填一个错误端口，确认提示里带着该地址并给出四条排查方向。",
        "（3）填对地址后测试连接，确认显示耗时；保存后重启软件，确认地址仍在。",
        "（4）发一句闲聊，确认回复分行、无合规提示；再发“我血压有点高”，确认切换健康顾问并加提示。",
        "（5）把模式锁成“只聊家常”，再发医疗问题，确认提示仍然出现。",
        "（6）按住麦克风说一句话，确认文字自动填入输入框、回复可念出。",
        "（7）录入一组血压，先填反高压低压，确认提示；改对后保存，确认趋势图更新。",
        "（8）上传一张检查单，确认字段被回填；清空某个字段再保存，确认不会被自动覆盖。",
        "（9）在日常计划里加一条，确认日历汇总可见；点打卡再取消，确认状态可回退。",
        "（10）用家属账号绑定老人，确认首页出现日程确认情况与主动发言摘录。",
        "（11）家属留言，确认老人端会话出现红点；解绑后确认两边会话消失。",
        "（12）进“AI 了解我的”，删一条记忆，确认后续对话不再引用该条。",
    ])
    para(doc, "走查时若某一步与预期不符，先按 2.4 节核对配置，再按 7.1 节排查；"
              "仍不通时把 /healthz 的返回内容与出问题的账号编号一并记录，便于定位。")

    section(doc, "6.5", "五分钟演示流程")
    para(doc, "汇报或验收演示时，按下列顺序走一遍，能在五分钟内覆盖主要亮点，且不易翻车：")
    steps(doc, [
        "（1）0:00 打开对话页，说一句家常，展示分行短句与口语化回复。",
        "（2）0:40 说“我血压有点高”，展示人设自动切换与末尾合规提示。",
        "（3）1:20 打开人设模式，锁成“只聊家常”，再问医疗问题，展示提示照样出现。",
        "（4）2:00 打开语音，按住说话，展示识别、逐字回复与数字人口型。",
        "（5）3:00 进健康档案，录一组血压，展示趋势图更新。",
        "（6）3:40 进日程，展示三类计划与打卡，点日历看汇总。",
        "（7）4:20 换家属账号，展示今日日程确认情况与留言。",
        "（8）5:00 打开“AI 了解我的”，展示记忆条目与删除后不再引用。",
    ])
    para(doc, "演示前建议先把服务端时间设为白天（主动关心只在 8:00–21:00 触发），"
              "并清掉测试账号里过于随意的手动记录。")

    section(doc, "6.6", "常见误用与纠正")
    para(doc, "试用阶段反复出现的几类用法，记在这里以免再犯：")
    steps(doc, [
        "（1）把健康档案当病历用。健康档案只记三项数值与趋势，诊断、用药、医嘱应记在病例里，"
        "两者分开是为了让趋势图干净。",
        "（2）用特别计划做每日提醒。特别计划是一次性的，过了当天就失效；"
        "每天要做的事应该建成日常计划。",
        "（3）把家属账号当老人账号用。家属账号只读为主，看不到聊天原文；"
        "要看全部内容必须用老人本人账号登录。",
        "（4）在服务端直接改数据库。服务运行中直接改库可能被缓存覆盖，"
        "应先停服务、备份、再改。",
        "（5）用管理员令牌代替账号登录。令牌是接口凭据，不是登录凭据；"
        "两者放在不同请求头，不能互相替代。",
        "（6）把 API_TOKENS 设成短字符串。对外提供服务时令牌应随机生成，"
        "长度不足等于没有鉴权。",
        "（7）指望主动关心当定位器。主动关心只发提问，不采集位置，"
        "老人不回就没有信息，这是隐私边界。",
    ])

    section(doc, "6.7", "不同人群的使用建议")
    para(doc, "同一套功能，不同老人用起来差别很大。下面按人群给出建议，部署方在培训家属时可参考：")
    steps(doc, [
        "（1）识字少、不会打字的老人：主要用语音，只教三个动作——按麦克风说话、点日程打卡、点健康档案记录。",
        "（2）视力尚可、愿意学的老人：可以同时用文字输入，并把大字体模式关掉，一屏能看到更多内容。",
        "（3）记忆力下降的老人：把用药提醒设成日常计划，家属每天看一次日程确认情况；主动关心可适当调高。",
        "（4）长期卧床或行动不便的老人：关掉三维数字人省电，语音播报音量调大，减少看屏幕的负担。",
        "（5）照护者不在身边的家庭：优先把家属绑定做起来，约定每天固定时段看一次家属端，而不是随时刷。",
    ])
    para(doc, "不建议一次把所有功能都教给老人。先教说话，一周后再加打卡，再一周加健康记录，接受度明显更高。")

    # ══════ 第七章
    chapter(doc, "第七章", "常见问题与术语")
    section(doc, "7.1", "常见问题")
    for q, a in [
        ("提示连不上服务器怎么办。",
         "提示里带了正在用的地址。先用手机浏览器打开这个地址的 /healthz，能看到 ok 说明网络通，"
         "再查服务端进程与端口。"),
        ("换网络就连不上。",
         "服务端在局域网里，地址会跟着变。在服务器地址页改新地址，不用重装；"
         "路由器里给服务器绑定固定地址能省掉这一步。"),
        ("手机能连上但打不开页面。",
         "多半是 HOST 还停在 127.0.0.1，只有本机能访问。把它改成 0.0.0.0 或内网地址再重启。"),
        ("语音没声音。",
         "先看系统音量与静音。语音合成服务不可用时软件自动退回纯文字，聊天不受影响。"),
        ("说话识别总是不准。",
         "先说环境。安静处、离麦克风近一点，识别率差很多；老年口音重时把一句话说完整再松手。"),
        ("删了记忆，以前的聊天会变吗。",
         "聊天记录不变，只是后面不再引用被删的条目。"),
        ("家属能看到我和助手聊的内容吗。",
         "家属端只看到日程确认情况与老人主动发言的摘录，看不到完整原文。"),
        ("换手机之后要重新注册吗。",
         "不用。用原账号密码登录、填同一个服务端地址即可，数据都在服务端。"),
        ("备份怎么恢复。",
         "停服务，解包覆盖数据目录，再启动；恢复前建议先备份当前数据。"),
        ("几个人能共用一个服务端吗。",
         "能。每个账号单独注册，数据按账号隔离，服务端地址填同一个即可。"),
        ("数据能不能导出。",
         "能。数据库是单文件 SQLite，可用通用工具直接打开、导出，不锁定于本软件。"),
        ("能不能换成自己的模型。",
         "能。智能体设置里改模型名与接入地址即可，本地模型也支持；换完立刻生效。"),
        ("两位老人的数据会不会串。",
         "不会。每个账号独立存储，家属账号只与自己绑定的老人关联。"),
        ("主动关心会不会太频繁。",
         "默认每日最多 2 次、间隔 4 小时、只在 8:00–21:00 发，刚聊过 30 分钟内不发；"
         "这几个值都可在配置里调。"),
    ]:
        para(doc, q)
        para(doc, a)

    for q, a in [
        ("为什么看不到聊天全文（家属端）。",
         "这是隐私设计。家属端展示日程确认情况与老人主动发言的摘录，完整原文只留在老人账号里。"),
        ("主动关心一天能不能多问几次。",
         "可以。CARE 相关参数在配置里，改每日上限与间隔后重启生效，不必改代码。"),
        ("能不能关掉主动关心。",
         "能。CARE_ENABLED 设为 false 即可，关掉后其余功能不受影响。"),
        ("历史压缩会不会丢内容。",
         "不会丢原文。压缩只影响喂给模型的部分，数据库里的消息仍然完整，可在会话里回看。"),
        ("服务端能不能装在 Windows 上。",
         "能。服务端的依赖都是跨平台的，用计划任务代替 systemd 即可；备份脚本另有 PowerShell 版。"),
        ("手机端能不能不装包，用浏览器。",
         "可以。服务端带网页端入口，桌面浏览器可用；移动浏览器未做适配，建议用安装包。"),
    ]:
        para(doc, q)
        para(doc, a)

    for q, a in [
        ("为什么改完配置没生效。",
         "配置在启动时读入，改完要重启服务端；手机端改服务器地址后会自动重新进入，不用重启。"),
        ("令牌改了，手机端连不上。",
         "两端令牌必须一致。改服务端 API_TOKENS 后，把新令牌同步到手机端的令牌设置页。"),
        ("数据库文件能不能直接打开看。",
         "能。SQLite 是标准单文件格式，用任何通用工具都能查看；但服务运行中不要直接改，"
         "改前先停服务并备份。"),
        ("忘记账号编号怎么办。",
         "在“我的”页可看到当前账号编号；家属绑定需要编号时，从老人端复制即可。"),
        ("同一账号能在两台手机登录吗。",
         "可以，但消息缓存只在本机；两台同时操作时以最后发送的为准。"),
        ("升级会不会丢数据。",
         "不会。服务端升级只替换代码，数据在 data 目录；手机端重装只清本地缓存，"
         "登录后重新拉取。"),
    ]:
        para(doc, q)
        para(doc, a)

    for q, a in [
        ("能不能关闭三维数字人。",
         "可以。在设置里关闭后改为静态头像，聊天与语音不受影响，低端机建议关闭。"),
        ("主动关心没收到是怎么回事。",
         "先看是否在 8:00–21:00、今天是否已问满 2 次、距上次是否不足 4 小时、"
         "是否刚聊过 30 分钟内；四个条件任一不满足都不会发。"),
        ("家属看不到日程确认情况。",
         "确认已完成绑定；未绑定前家属端只显示“还看不到家人的情况”。"),
        ("服务端换了机器，数据怎么搬。",
         "复制 data 目录与 case_files 目录到新机器，改 .env 里的路径，启动即可；"
         "搬之前先做一次一致性备份。"),
    ]:
        para(doc, q)
        para(doc, a)

    section(doc, "7.2", "术语说明")
    for line in [
        "双人设：陪伴助手与健康顾问两套说话方式，由软件按话题判断该用哪套。",
        "合规提示：健康顾问回答末尾的固定提示语，提醒以医嘱为准、及时就医，由程序写入。",
        "长期记忆：从真实对话中提炼、跨会话保留的老人信息与说话习惯。",
        "主动关心：软件按规则主动发起的提问，受每日次数、间隔、时段与刚聊过与否限制。",
        "待回访事项：老人提到的以后要做的事，记下来，到日子再提。",
        "对话摘要：历史过长时压缩出的概括，代替早期原文进入上下文。",
        "清醒时段：允许主动提问的时段，默认 8:00 到 21:00。",
        "历史压缩阈值：触发压缩的条数，默认 48 条，压缩后保留最近 16 条原文。",
        "人设锁定：手动选定一种说话方式后不再自动切换的状态。",
        "降级：某项能力不可用时改用简单实现或关闭该功能，主流程不中断。",
    ]:
        para(doc, line)

    section(doc, "7.3", "已知限制")
    steps(doc, [
        "（1）对话质量取决于所接入的模型。小参数本地模型在语气上可以调好，"
        "但在需要推理的高风险场景上可能漏掉就医提示，因此医疗方向的安全提示始终由代码兜底。",
        "（2）语音识别在方言较重、环境嘈杂时准确率下降，此时建议改用文字输入。",
        "（3）三维数字人对显卡有要求，低端机型建议关闭三维、改用静态头像。",
        "（4）本软件不做诊断，不替代医生；所有健康建议仅供参考，出现异常指标或明显不适应及时就医。",
        "（5）家属端看到的是日程确认与主动发言摘录，不是聊天全文；这是隐私设计，不是功能缺漏。",
        "（6）记忆整理每 5 轮一次，刚说过的话可能要到下一轮整理后才进入记忆。",
    ])

    section(doc, "7.4", "交付物清单")
    para(doc, "随软件交付的文件如下（见表7-1），部署所需的脚本都在 deploy 目录里，"
              "不需要另外找。")
    table(doc, "表7-1", "交付物清单",
          ["文件", "用途"],
          [
              ["deploy.sh", "Linux 一键部署：装依赖、写配置、注册服务、自检"],
              ["bilin-api.service", "systemd 服务单元，负责开机自启与异常重启"],
              ["backup.sh / backup.ps1", "一致性备份，Linux 与 Windows 各一份"],
              ["nginx-bilin.conf / Caddyfile", "公网部署时的反向代理配置"],
              ["setup-proxy.sh", "反向代理的一键配置脚本"],
              ["build-bundle.py", "把部署所需文件打成一个压缩包，便于拷到目标机器"],
              ["zerotier/", "虚拟专网形态的配置脚本与校验工具"],
              ["local-models/", "本地模型部署说明与 Modelfile"],
              ["OPERATIONS.md", "日常运维手册：备份、恢复、排障"],
          ], [6.4, 10.2])
    note = doc.add_paragraph()
    note.paragraph_format.space_before = Pt(4)
    font(note.add_run("说明：上述文件与说明书同版本发布；若目录内缺少某个脚本，"
                      "说明部署包不完整，应重新打包后再部署。"), 9)

    section(doc, "7.5", "文档维护与反馈")
    para(doc, "本说明书与软件同版本发布。若发现某处描述与应用内实际不一致，"
              "以应用内为准，并把不一致的地方记下来反馈，下一版修订。"
              "常见的不一致来源有三类：界面文案微调、配置默认值调整、功能迭代新增。")
    para(doc, "修订时优先改数字：次数、间隔、条数、超时这类参数最容易过期，"
              "也最容易被审查方核对。参数改了就同步改文档，不要留“约”“左右”这种模糊说法。")

    section(doc, "7.6", "版本与发布说明")
    para(doc, f"本说明书对应 {SOFTWARE_VERSION} 版本，为该软件的首次发表版本，涵盖第一章至第七章"
              "描述的全部功能。文中提到的界面元素名称与应用内实际文案一致，便于对照操作；"
              "若因版本更新导致文案微调，以应用内显示为准。")
    para(doc, "后续版本的增补、修复与新增功能不在本说明书范围内。本说明书描述的功能均已实现"
              "并经过测试，不包含规划中的功能。文中出现的人名、编号与数值均为测试数据，"
              "不代表真实用户。")

    # ══════ 第八章
    chapter(doc, "第八章", "附录：错误码与提示语")
    section(doc, "8.1", "常见错误码")
    para(doc, "接口出错时返回统一的错误码与中文提示，客户端按错误码决定怎么展示。"
              "常用错误码如下（见表8-1），排查时先看错误码再看提示。")
    table(doc, "表8-1", "常见错误码与处理",
          ["错误码", "含义", "处理方式"],
          [
              ["auth_required", "缺少或无效的令牌/会话凭据", "检查两端令牌是否一致，重新登录"],
              ["unauthorized", "凭据不属于该资源", "确认账号与会话归属"],
              ["account_name_required", "账号名为空或过长", "名称非空且不超过 20 个字符"],
              ["account_name_taken", "账号名已存在", "换一个名称"],
              ["account_bad_password", "密码不正确", "重新输入；连续失败可让部署方重置"],
              ["account_password_weak", "密码强度不足", "按提示增加长度或复杂度"],
              ["account_number_exhausted", "8 位编号已用满", "清理无用账号或扩展编号方案"],
              ["invalid_request", "请求参数不合法", "按接口文档核对字段"],
              ["bad_request", "请求无法解析", "检查请求体格式与编码"],
              ["empty_text / message_empty", "消息内容为空", "输入内容后再发送"],
              ["message_too_long", "消息超出长度上限", "分段发送"],
              ["health_value_invalid", "健康数值越界或高压小于低压", "按范围提示修正"],
              ["invalid_date / invalid_datetime", "日期或时间格式不对", "使用界面控件选择"],
              ["bind_self / bind_already", "不能绑定自己 / 已绑定", "换一个邀请码或先解绑"],
              ["bind_not_found / no_pending_invite", "邀请码无效或已失效", "重新生成邀请码"],
              ["plan_not_found / plan_state", "计划不存在或状态不允许该操作", "刷新列表后重试"],
              ["memory_not_found / memory_empty", "记忆条目不存在或内容为空", "刷新后重选"],
              ["care_unavailable", "主动关心模块不可用", "检查 CARE_ENABLED 与调度进程"],
              ["wiki_unavailable", "长期记忆服务不可用", "检查 WIKI_ENABLED 与模型配置"],
          ], [5.0, 6.0, 6.6])

    section(doc, "8.2", "提示语约定")
    para(doc, "界面提示语遵循三条约定：一是用口语，不用“参数错误”“操作失败”这类术语；"
              "二是提示里尽量带上可执行的动作或目标（比如带上正在使用的服务器地址）；"
              "三是同一种失败只提示一次，不反复弹窗。")
    table(doc, "表8-2", "提示语示例",
          ["场景", "界面提示", "设计考虑"],
          [
              ["账号名过长", "账号名称太长了，写短一点", "直说要改什么，不用“校验失败”"],
              ["连接失败", "连不上 <地址>，按下面四条检查", "带上地址，家属远程也能判断"],
              ["语音不可用", "语音暂时用不了，先打字吧", "给替代路径，不让人卡住"],
              ["发送失败", "没发出去，点一下重发", "把重发动作直接说出来"],
              ["权限被拒", "需要麦克风权限，去设置里打开", "指向系统设置的位置"],
          ], [3.4, 7.4, 6.8])

    section(doc, "9.4", "编号与命名规则")
    para(doc, "软件内有几套编号，容易混，这里一次说清：")
    steps(doc, [
        "（1）账号编号：8 位定长数字，由服务端按序发放，从 0 开始，不跳号不重复。",
        "（2）会话编号：由服务端生成的字符串，客户端不自行构造。",
        "（3）计划编号：创建时生成，打卡与取消打卡都带这个编号，保证同一天同一项幂等。",
        "（4）图片与语音文件：按上传时间与随机串命名，分别存放在 data 与 case_files 目录。",
    ])
    para(doc, "编号规则的意义在排查：家属报“看不到情况”时拿到账号编号就能定位到人；"
              "报“打卡打不上”时拿到计划编号就能查到那条记录的状态。")

    section(doc, "8.3", "错误码之外的三类提示")
    para(doc, "不是所有问题都会走到接口报错，界面自己也会提示，按性质分三类：")
    steps(doc, [
        "（1）网络类：连不上、超时、DNS 失败。提示里带地址，便于判断是填错还是断网。",
        "（2）权限类：麦克风、摄像头、相册被拒。提示里给系统设置的入口位置。",
        "（3）状态类：语音服务不可用、三维关闭、记忆为空。这类不是错误，是降级或空态，"
        "提示语用中性表述，不用红色警告。",
    ])
    para(doc, "三类提示的措辞不同，目的是让家属远程听老人念一遍提示就能判断大概是什么问题，"
              "而不用猜。")

    # ══════ 第九章
    chapter(doc, "第九章", "附录：数据字段与测试说明")
    section(doc, "9.1", "主要数据字段")
    para(doc, "下列字段是排查数据问题时最常用的，字段名与数据库、接口一致（见表9-1）。")
    table(doc, "表9-1", "主要数据字段",
          ["对象", "字段", "说明"],
          [
              ["账号", "number", "8 位数字编号，按序发放，唯一"],
              ["账号", "name / password", "账号名称（≤20 字符）与密码摘要"],
              ["账号", "avatar", "头像，限制 400000 字符以内"],
              ["健康记录", "item_type", "bloodPressure / bloodSugar / weight 三选一"],
              ["健康记录", "systolic / diastolic", "血压高压 50–300、低压 30–200，须高压大于低压"],
              ["健康记录", "value / measured_at / note", "数值、测量时间、备注"],
              ["病例", "title / hospital", "病例标题、就诊医院"],
              ["病例", "visitDate", "就诊日期，时间轴按此倒序"],
              ["病例", "diagnosis / summary", "诊断结论、摘要（识别结果回填）"],
              ["计划", "planId / title / note", "所属计划、事项标题、备注"],
              ["提醒", "sendAt / sentAt / ackAt", "应发时间、已发时间、确认时间"],
              ["提醒", "status / channel", "状态（待发/已发/已确认）、发送渠道"],
              ["提醒", "repeatCount / repeated", "重复次数、是否再次提醒"],
          ], [2.6, 6.0, 9.0])
    para(doc, "字段设计上有两处刻意的取舍：一是金额、剂量这类敏感数值不设为必填，"
              "避免老人因为填不出而放弃记录；二是删除都做物理删除而不留软删除标记，"
              "让“删了就真的没了”这句话在数据层面成立。")

    section(doc, "9.2", "自动化测试")
    para(doc, "服务端带 713 个自动化用例，分布在 37 个测试文件中，覆盖账号、对话、双人设、"
              "合规扫描、记忆、计划引擎、主动关心、语音、病例、持久化等模块（见表9-2）。"
              "改动代码后先跑测试，再上机验证，能省掉大量手工回归。")
    table(doc, "表9-2", "测试分布（用例数前八）",
          ["测试文件", "用例数", "覆盖内容"],
          [
              ["test_memory", 37, "会话上下文与历史压缩"],
              ["test_accounts", 36, "注册、登录、编号分配、头像"],
              ["test_plan_engine", 35, "三类计划的生成与打卡"],
              ["test_care", 33, "主动关心的次数、间隔、时段限制"],
              ["test_cases", 32, "病例字段回填与归档"],
              ["test_store_persistence", 32, "数据库持久化与重启恢复"],
              ["test_dual_persona", 29, "双人设判断与合规提示"],
              ["test_asr", 28, "语音识别接入与降级"],
          ], [5.4, 2.4, 9.8])
    para(doc, "测试里有两条硬约束值得单独说明：一是双人设的判断必须保证“医疗话题必加提示”，"
              "这条有专门的断言，改动提示词时会被拦下；二是计划打卡必须幂等，"
              "同一天同一项重复打卡不产生多条记录。")

    section(doc, "9.3", "上机验证建议")
    para(doc, "自动化测试验证的是代码逻辑，界面与真机行为还要上机看。建议按下列顺序验证：")
    steps(doc, [
        "（1）用旧机型（Android 8 左右、2GB 内存）装一次，确认界面不卡、三维能关。",
        "（2）用新机型装一次，确认三维形象正常、口型跟着语音变。",
        "（3）断网后打开软件，确认能看到已缓存的历史消息，且提示不误导。",
        "（4）把服务端停掉再发消息，确认失败提示与重发按钮可用。",
        "（5）连续发送 20 条消息，确认列表滚动与历史加载正常。",
        "（6）上传一张模糊的检查单，确认识别失败时仍可手动填字段。",
    ])

    section(doc, "9.5", "版本兼容性")
    para(doc, "服务端与手机端可以各自升级，兼容策略如下：")
    steps(doc, [
        "（1）服务端向前兼容：新增字段不影响老客户端读取，老客户端忽略未知字段即可。",
        "（2）手机端向前兼容：老客户端请求新服务端时，若接口有变化会在响应里给出升级提示。",
        "（3）数据库结构变更由启动时自动迁移完成，不需要人工执行脚本；迁移前建议先备份。",
        "（4）跨大版本升级时，先升服务端再升手机端，避免老服务端读到新客户端的新字段。",
    ])

    path = OUT / "03-软件说明书-比邻AI智慧康养陪伴软件V1.0.docx"
    doc.save(str(path))
    return path


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("  已生成 %s" % build().name)


if __name__ == "__main__":
    main()