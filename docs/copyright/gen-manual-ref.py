"""按参考件《革兰氏染色虚拟仿真实验系统 V1.5》的格式重写比邻AI说明书。

## 参考件测得的格式

  · A4，页眉居中「软件全称 + 版本」（9pt），页脚居中页码（9pt）
  · 首页顶部：17pt 黑体软件全称（居中）+ 11pt「软件说明书 V1.0」（居中）
  · 章：`第一章  项目概述` 12.9pt 黑体加粗，左对齐，与正文间留空
  · 节：`1.1  项目背景` 11.1pt 黑体加粗
  · 小节：`2.1.1  客户端运行环境` 10.4pt 黑体加粗
  · 正文：9.9pt 宋体，首行缩进两字，两端对齐，行距约 13pt
  · 图：嵌入居中，下方 `图1-1  名称`（9pt，居中）
  · 表：上方 `表1-1  名称`（9pt，居中），下面是三到四列的网格表（9pt）
  · 枚举：（1）（2）（3）直接写在段落里，不用项目符号或自动编号
  · 章与章之间不强制分页，连续排版

## 与软著行数要求的配合

正文 9.9pt / 13pt 行距时，页面容量约 55 行。嵌入图一张约占 19 行，
带图的页面仍有 36 行左右，满足"文档每页不少于 30 行"。这一点在生成后
用 Word 逐页实测确认，不靠估算。
"""

from __future__ import annotations

import struct
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

SOFTWARE_FULL = "比邻AI智慧康养陪伴软件"
SOFTWARE_VERSION = "V1.0"
OUT = Path(r"E:\ppt\比邻AI.ppt\软著材料-终版")
IMAGES = Path(r"E:\ppt\比邻AI.ppt\图片")

BODY_PT = 9.9
LINE_PT = 13.0


def font(run, size, name="宋体", bold=False):
    run.font.size = Pt(size)
    run.font.name = name
    run.font.bold = bold
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


def setup(doc: Document) -> None:
    s = doc.sections[0]
    s.page_width, s.page_height = Cm(21.0), Cm(29.7)
    # 上下边距 1.95cm：每页多容 1 行，专门用来把 29 行的两页顶到 30 行以上
    s.top_margin, s.bottom_margin = Cm(1.95), Cm(1.95)
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

    # 页眉：居中「软件全称 + 版本」
    hp = s.header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    font(hp.add_run(f"{SOFTWARE_FULL}  {SOFTWARE_VERSION}"), 9)

    # 页脚：居中页码
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
    pf.space_before = Pt(9)
    pf.space_after = Pt(4)
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(20)
    p.paragraph_format.keep_with_next = True
    font(p.add_run(f"{num}  {title}"), 12.9, "黑体", bold=True)


def section(doc, num: str, title: str) -> None:
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(6)
    pf.space_after = Pt(2)
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(17)
    p.paragraph_format.keep_with_next = True
    font(p.add_run(f"{num}  {title}"), 11.1, "黑体", bold=True)


def subsection(doc, num: str, title: str) -> None:
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(4)
    pf.space_after = Pt(1)
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(14)
    p.paragraph_format.keep_with_next = True
    font(p.add_run(f"{num}  {title}"), 10.4, "黑体", bold=True)


def para(doc, text: str, indent: bool = True) -> None:
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


def _png_size(path: Path):
    """读 PNG 头取宽高，避免为这张图引入 Pillow 依赖。"""
    try:
        with path.open("rb") as f:
            head = f.read(26)
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        w, h = struct.unpack(">II", head[16:24])
        return w, h
    except OSError:
        return None


def caption(doc, text: str, align=WD_ALIGN_PARAGRAPH.CENTER, space_after: float = 6,
            space_before: float = 2) -> None:
    """普通题注段落（横屏图与表格用）。套 Word 内置「题注」样式。"""
    p = doc.add_paragraph()
    p.alignment = align
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    try:
        p.style = doc.styles["Caption"]
    except KeyError:
        pass
    run = p.add_run(text)
    font(run, 9)
    from docx.shared import RGBColor
    run.font.color.rgb = RGBColor(0, 0, 0)
    run.font.italic = False
    return p


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
V_NS = "urn:schemas-microsoft-com:vml"
O_NS = "urn:schemas-microsoft-com:office:office"


def _vml_caption(doc, text: str, width_cm: float, offset_pt: float, shape_id: str) -> bool:
    """把题注做成 VML 浮动文本框，水平靠右、垂直落在图片下方。

    垂直偏移必须用 style 里的 margin-top 配 mso-position-vertical-relative:paragraph；
    用 top: 不会生效（题注会停在锚点段落顶部）。
    """
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
    sz = etree.SubElement(rpr, f"{{{W_NS}}}sz")
    sz.set(f"{{{W_NS}}}val", "18")
    sz_cs = etree.SubElement(rpr, f"{{{W_NS}}}szCs")
    sz_cs.set(f"{{{W_NS}}}val", "18")
    color = etree.SubElement(rpr, f"{{{W_NS}}}color")
    color.set(f"{{{W_NS}}}val", "000000")
    t_el = etree.SubElement(r, f"{{{W_NS}}}t")
    t_el.text = text
    return True


def figure(doc, name: str, label: str, caption_text: str, width_cm: float = None) -> None:
    """居中嵌入 + 题注居中在下方。

    参考件（革兰氏染色 V1.5）就是这种排法：图居中、题注紧随其下、带图页仍有 37-40 行。
    前提是图要小：竖屏手机截图取 3.9cm（高约 8.4cm ≈ 18 行），
    页面容量约 50 行时仍留 30 行以上给文字。
    """
    path = IMAGES / name
    if not path.exists():
        print("  ⚠️ 缺图：%s" % name)
        return

    size = _png_size(path)
    landscape = bool(size) and size[0] / size[1] >= 1.0
    if width_cm is None:
        width_cm = 12.5 if landscape else 3.9

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(5)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    # 图与题注同页：图所在段落与下一段保持在一起
    p.paragraph_format.keep_with_next = True
    p.add_run().add_picture(str(path), width=Cm(width_cm))

    cap_p = caption(doc, f"{label}  {caption_text}",
                    align=WD_ALIGN_PARAGRAPH.CENTER, space_after=6, space_before=2)
    return cap_p


def figure_row(doc, items, width_cm: float = 3.6, gap_cm: float = 0.5) -> None:
    """一行并排放多张图，每张图下方各自跟题注。

    items = [(图片文件名, 图号, 图名), ...]；建议 2 张一行。
    用无边框表格实现，整表居中，行不跨页。
    """
    from docx.enum.table import WD_TABLE_ALIGNMENT

    cols = len(items)
    table = doc.add_table(rows=1, cols=cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    tbl_pr = table._tbl.tblPr
    from docx.oxml import OxmlElement
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tbl_pr.append(layout)
    # 去掉表格边框
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement("w:%s" % edge)
        el.set(qn("w:val"), "none")
        el.set(qn("w:sz"), "0")
        borders.append(el)
    tbl_pr.append(borders)

    cell_w = width_cm + gap_cm
    for idx, (name, label, caption_text) in enumerate(items):
        table.columns[idx].width = Cm(cell_w)
        cell = table.rows[0].cells[idx]
        cell.width = Cm(cell_w)

        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        path = IMAGES / name
        if path.exists():
            p.add_run().add_picture(str(path), width=Cm(width_cm))
        else:
            print("  ⚠️ 缺图：%s" % name)

        cap = cell.add_paragraph()
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cap.paragraph_format.space_before = Pt(2)
        cap.paragraph_format.space_after = Pt(4)
        cap.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        try:
            cap.style = doc.styles["Caption"]
        except KeyError:
            pass
        run = cap.add_run(f"{label}  {caption_text}")
        font(run, 9)
        from docx.shared import RGBColor
        run.font.color.rgb = RGBColor(0, 0, 0)
        run.font.italic = False

    # 行不跨页
    for row in table.rows:
        tr_pr = row._tr.get_or_add_trPr()
        tr_pr.append(OxmlElement("w:cantSplit"))

    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(0)
    spacer.paragraph_format.space_after = Pt(2)
    spacer.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    spacer.paragraph_format.line_spacing = Pt(6)


def table(doc, label: str, caption_text: str, header, rows, widths) -> None:
    caption(doc, f"{label}  {caption_text}", space_before=6, space_after=2)

    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    # python-docx 单设 cell.width 会被自动布局覆盖：必须显式声明固定布局，
    # 并且列宽和单元格宽度都设，否则"序号"列会被撑到和"功能说明"一样宽。
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

    # 行内禁止跨页断行，否则一行的末行会被切到下一页，页首留下半行字；
    # 表头设为重复表头，跨页时下一页自动带上表头。
    for idx, row in enumerate(t.rows):
        tr_pr = row._tr.get_or_add_trPr()
        tr_pr.append(OxmlElement("w:cantSplit"))
        if idx == 0:
            tr_pr.append(OxmlElement("w:tblHeader"))

    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_after = Pt(4)
    spacer.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    spacer.paragraph_format.line_spacing = Pt(6)


def build() -> Path:
    doc = Document()
    setup(doc)

    # 首页标题块
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

    # ══ 第一章
    chapter(doc, "第一章", "项目概述")
    section(doc, "1.1", "项目背景")
    para(doc, "独居老人和需要长期吃药的慢病人群，日常有两件事最难：说话没人接，"
              "身体的变化没人记。前者是陪伴问题，后者是照护问题。市面上的产品大多只解决一边。"
              "健康类的应用功能齐，但把力气花在填表和看图上看，字小、层级深、步骤多，"
              "老人自己用不起来；聊天类的应用老人愿意用，但聊完就过去了，"
              "记不下血压，不会提醒吃药，家属也看不到情况。")
    para(doc, "本软件把入口放在说话上。老人对着手机说一句，软件辨认这是闲聊还是身体不舒服："
              "闲聊就陪着说，遇到医疗话题就换成另一种说法，并在回答末尾加一句以医嘱为准、"
              "及时就医。说的内容里提到的事会被记下来，包括怎么称呼、作息、吃什么、"
              "家里有谁、有哪些重要的日子。身体数据和病历另有一处存放，"
              "家属用另一个账号登录能看到当天的情况。")
    para(doc, "界面按老人的眼神和手指做过几轮调整：字号大、对比度高、能点就不让打字，"
              "删除类操作都要二次确认。软件分手机端和服务端两部分，"
              "服务端跑在部署方自己的机器上，数据不出本机（如图1-1）。")
    figure(doc, "架构-01-系统分层.png", "图1-1", "系统架构图", 13.0)
    para(doc, "整套软件由团队四人共同开发，分工见登记材料中的合作开发协议：一人负责智能体搭建、"
              "核心代码与部署，三人分别负责界面开发、功能与交互设计、适老化需求调研。")

    section(doc, "1.2", "核心功能概述")
    para(doc, "本软件包含以下十一个核心功能模块（见表1-1）。", indent=True)
    table(doc, "表1-1", "核心功能模块",
          ["序号", "模块名称", "功能说明"],
          [
              [1, "账号与登录", "注册自动分配 8 位数字编号作为唯一标识，注册成功即登录；"
                               "支持头像设置"],
              [2, "家属绑定", "老人生成邀请码，家属凭码绑定；绑定后家属可看当日安排完成情况、"
                             "最近身体数据、吃药情况与对话摘要，双方可互相留言"],
              [3, "智能对话", "文字与语音两种输入；默认陪伴助手，识别到医疗话题自动切换健康顾问"
                             "并追加合规提示；可手动锁定模式；回复按行分开呈现"],
              [4, "三维数字人", "端侧渲染三维形象，按语音字级时间戳驱动口型；"
                               "低端设备可关闭三维改静态头像，不影响对话与语音"],
              [5, "长期记忆", "分老人画像与说话风格两类，每五轮对话沉淀一次；"
                             "用户可查看、编辑、删除任一条目"],
              [6, "健康档案", "记录血压、血糖、体重，按时间展示记录与趋势，可切日、周、月；"
                             "异常值醒目提示但不给诊断结论"],
              [7, "病例管理", "上传病历、检查单、出院记录的图片或 PDF，提取就诊日期、机构、"
                             "科室、诊断、用药、医嘱六项并按时间轴归档"],
              [8, "用药与日程", "日常、每周、一次性特别安排三类计划；日历汇总当月安排；"
                               "到期以系统通知与应用内消息提醒；可打卡与取消打卡"],
              [9, "主动关心", "按时段主动发起关心提问，受每日次数、最小间隔与静默时段三重约束；"
                             "老人提到的未来事项转为待回访，到期再提"],
              [10, "智能体角色", "可建多个角色并设定姓名、关系、性格、口头禅、称呼方式；"
                                "关系标签显示在对话列表；可设默认与删除"],
              [11, "设置与适老化", "大字体模式、服务器地址配置与连接测试、数字人形象配置；"
                                  "界面按大字号、高对比度、宽点击区设计"],
          ],
          [1.4, 2.6, 12.6])

    # ══ 第二章
    chapter(doc, "第二章", "运行环境介绍")
    section(doc, "2.1", "硬件环境")
    subsection(doc, "2.1.1", "手机端运行环境")
    para(doc, "本软件手机端为 Android 应用，界面与三维形象由手机端渲染，配置要求如下（见表2-1）。")
    table(doc, "表2-1", "手机端硬件配置",
          ["项目", "配置要求", "备注"],
          [
              ["处理器", "四核 1.8GHz 及以上", "近五年机型均可"],
              ["内存", "2GB 以上", "开启三维形象建议 4GB"],
              ["存储", "可用空间 200MB 以上", "三维形象资源随安装包提供"],
              ["屏幕", "分辨率 720×1280 及以上", "界面按竖屏布局"],
              ["网络", "Wi-Fi 或 4G/5G", "与服务端在同一网络时最稳定"],
              ["输入", "触摸屏、麦克风、摄像头", "麦克风用于语音，摄像头用于拍病历"],
          ], [2.2, 7.6, 6.8])

    subsection(doc, "2.1.2", "服务端运行环境")
    para(doc, "服务端承担对话编排、数据存储与接口服务，可部署在普通电脑或云主机上（见表2-2）。")
    table(doc, "表2-2", "服务端硬件配置",
          ["项目", "配置要求", "备注"],
          [
              ["处理器", "1 核及以上", "建议 2 核"],
              ["内存", "1GB 以上", "建议 2GB"],
              ["磁盘", "40GB 可用空间", "病例图片占用随使用增长"],
              ["其他", "可长期通电、可联网", "家用小主机或云主机均可"],
          ], [2.2, 7.6, 6.8])

    subsection(doc, "2.1.3", "开发环境")
    para(doc, "本软件开发与测试所使用的环境如下（见表2-3）。")
    table(doc, "表2-3", "开发环境",
          ["项目", "配置"],
          [
              ["开发设备", "笔记本电脑，处理器 i9-14900HX，内存 16GB，固态硬盘 512GB"],
              ["操作系统", "Windows 11 64 位"],
              ["开发工具", "HBuilderX 5.26、Visual Studio Code、Node.js 18、Vite 5、Git"],
              ["编程语言", "Python、JavaScript、Vue（HTML/CSS）"],
              ["版本管理", "Git；模型训练脚本位于 ml/scripts 目录"],
          ], [3.0, 13.6])

    section(doc, "2.2", "软件环境")
    para(doc, "本软件运行所需的支撑软件清单如下（见表2-4）。")
    table(doc, "表2-4", "软件环境",
          ["序号", "软件名称", "版本要求", "用途说明"],
          [
              [1, "手机端操作系统", "Android 8.0 及以上", "客户端运行环境"],
              [2, "服务端操作系统", "Ubuntu 22.04 / Debian 12 / Windows 10 及以上", "服务端运行环境"],
              [3, "Python", "3.11 及以上", "服务端运行环境"],
              [4, "FastAPI+Uvicorn", "0.141 / 0.54", "接口服务与进程托管"],
              [5, "SQLite", "3", "数据存储，单文件，无需单独安装"],
              [6, "浏览器", "支持 HTML5 的现代浏览器", "网页端访问"],
          ], [1.4, 4.4, 6.0, 4.8])

    section(doc, "2.3", "网络环境")
    para(doc, "本软件对网络环境的要求如下：")
    for line in [
        "（1）手机端与服务端需在同一网络内，或服务端具备可访问的公网地址；"
        "局域网部署时手机连同一路由器的 Wi-Fi 即可。",
        "（2）服务端默认监听 8000 端口，部署在云主机时需在安全组放行该端口。",
        "（3）对话内容由大语言模型生成，需服务端能够访问模型接口；"
        "接口地址、密钥与模型名在 .env 中配置。",
        "（4）接口采用 HTTP/HTTPS，鉴权用令牌加账号会话凭据，两个凭据放在两个请求头。",
        "（5）服务端不可达时，手机端保留已缓存的历史消息供查看，并提示正在使用的地址，"
        "不显示白屏。",
        "（6）若不便访问外部模型，可把模型地址指向内网自建服务，"
        "或改用本地模型；切换只改配置，不改代码。",
        "（7）本软件不上传数据到第三方；账号、聊天、健康数据与病例均存放在部署方自己的数据库中。",
    ]:
        para(doc, line)

    section(doc, "2.4", "安装部署流程")
    subsection(doc, "2.4.1", "服务端部署")
    para(doc, "服务端按以下步骤部署：")
    for line in [
        "（1）将代码拷到目标机器，进入 server 目录。",
        "（2）创建虚拟环境并安装 requirements.txt 中的依赖。",
        "（3）修改 .env：HOST 与 PORT 为监听地址与端口，DATABASE_URL 指数据库文件，"
        "AUTH_MODE 与 API_TOKENS 管接口鉴权，LLM_BASE_URL、LLM_API_KEY、LLM_MODEL 指对话模型。",
        "（4）执行 run.py 启动，默认监听 8000 端口。",
        "（5）访问 /healthz，返回 ok 表示服务已就绪。",
        "（6）需要开机自启时，Linux 注册为 systemd 服务，Windows 注册为计划任务；"
        "服务文件里要写清工作目录与 .env 路径。",
    ]:
        para(doc, line)

    subsection(doc, "2.4.2", "手机端安装")
    para(doc, "手机端安装与首次配置步骤如下：")
    for line in [
        "（1）安装提供的 Android 安装包，首次启动授予麦克风、摄像头、存储三项权限。",
        "（2）进入底部“我的”，点“服务器地址”，填写服务端地址。",
        "（3）点“测试连接”，页面显示耗时与返回内容，正常后保存。",
        "（4）连接失败时页面给出四条排查方向：地址是否带端口、手机与服务端是否同网、"
        "服务端进程是否在跑、防火墙是否放行。",
        "（5）返回登录页注册或登录，注册成功后系统分配 8 位数字编号。",
    ]:
        para(doc, line)

    # ══ 第三章
    chapter(doc, "第三章", "软件界面介绍")
    section(doc, "3.1", "登录与注册")
    figure_row(doc, [
        ("18-登录.png", "图3-1", "登录与注册入口"),
        ("02-聊天详情.png", "图3-2", "对话详情"),
    ])
    para(doc, "启动后进入登录页。页面提供账号名与密码输入框，下方有“忘记密码”“没有账号请点击注册”"
              "两个入口（如图3-1）。注册时填账号名与密码，账号名 2 到 20 个字符；"
              "注册成功即进入登录状态，系统分配一个 8 位数字编号作为账号唯一标识，"
              "这个编号可以给家属用于绑定。")

    para(doc, "登录页的“忘记密码”入口目前只做提示，需由部署方在服务端重置；"
              "这是有意为之：老人账号通常由家属代为维护，开放自助重置反而容易被冒用。")
    para(doc, "同一台手机可以登录不同账号，退出登录后本地缓存的消息会清除，"
              "换人使用不会看到上一位的内容。")

    section(doc, "3.2", "对话列表")
    para(doc, "列表顶部是助手会话，下面按最近消息时间排家属会话。会话多了以后，"
              "常联系的人自然排在前面，不需要手动置顶或分组。")
    para(doc, "登录后进入对话列表。默认有一个与助手的会话，固定在最上面不参与排序；"
              "与家属的会话在绑定之后才出现。每条显示对方名字、关系、最后一句话与时间，"
              "有新消息时右侧显示红点，进入会话即清除，不按条数累计。")

    para(doc, "会话列表支持长按删除，删除只清列表入口与本地缓存，服务端记录按账号分别保留，"
              "误删后可用同一账号重新进入恢复。列表下拉可手动刷新，用于另一台设备刚发过消息的情况。")
    para(doc, "会话里没有“正在输入”这类提示，也没有已读回执。老人不需要判断对方看没看，"
              "家属也不必因为“已读未回”焦虑。消息状态只有三种：发送中、已发送、发送失败。"
              "三种状态在气泡右侧用图标区分：转圈、对勾、红色感叹号。")

    section(doc, "3.3", "对话详情与双人设")
    para(doc, "点会话进入详情页。底部输入框打字，点发送；发送失败的消息右侧显示红色感叹号，"
              "点一下重发；长按消息可复制。回复按行分开，一行一句，不写成一大段，"
              "老人看起来轻松，语音播报时也好与口型对上（如图3-2）。")
    para(doc, "对话里有两套说法。一套是陪伴助手，用在日常聊天，句子短、用词口语；"
              "另一套是健康顾问，用在医疗健康话题，回答末尾补一句以医嘱为准、及时就医。"
              "切换分自动与手动：自动按关键词分层判断，先看有没有明显医疗词，"
              "再看是不是常规吃药询问，最后结合情绪词与认知相关说法；"
              "手动是在“人设模式”里选，选完不再自动切。")
    para(doc, "提醒做了三道：第一道判断问题类型，第二道检查回答里有没有停药、剂量、诊断这类说法，"
              "第三道在回答生成完再扫一遍。三道都在代码里。把模式锁成“只聊家常”后，"
              "只要回答涉及医疗内容，提醒照样加，这一项不开放关闭。")

    section(doc, "3.4", "语音与三维数字人")
    figure_row(doc, [
        ("10-数字人通话.png", "图3-3", "三维数字人通话"),
        ("15-健康档案.png", "图3-4", "健康档案"),
    ])
    para(doc, "语音做三件事：把说的话转成文字，把回复念出来，让数字人的嘴跟着动（如图3-3）。")
    for line in [
        "（1）在对话页按住麦克风说话，松开即发送。",
        "（2）页面显示“正在听”，识别完文字自动填入输入框。",
        "（3）点发送后回复逐字出现，同时开始念；念的时候嘴型跟着变，可暂停与重播。",
        "（4）麦克风权限未授予时，页面提示前往系统设置打开，文字输入不受影响。",
    ]:
        para(doc, line)
    para(doc, "数字人形象在“我的”里配置，资源随安装包提供，不需要联网下载。"
              "手机带不动时可在设置里关闭三维、改为静态头像，聊天与语音照常。")

    section(doc, "3.5", "AI 了解我的（长期记忆）")
    para(doc, "软件记两类东西：一类是老人提到的事实，包括怎么称呼、几点起几点睡、爱吃什么、"
              "家里有谁、关心哪些健康问题、有没有重要的日子；另一类是说话习惯，"
              "包括口头禅、怎么称呼人、句子长短。两类分开存，每五轮对话整理一次，"
              "不是每轮都调模型。")
    para(doc, "说话习惯只从真人发的消息里学，助手自己的回复不拿来当素材，否则越学越僵。"
              "进“我的”点“AI 了解我的”，页面按分节列出全部条目，每条显示内容、来源与更新时间，"
              "点某条能改能删；删掉之后后面聊天不再引用。口头禅与称呼习惯单独存放，"
              "清理时不会一起删。记忆条数不设硬上限，但参与对话的只取最近更新的若干条，"
              "太老的留着可查、不进上下文。")

    section(doc, "3.6", "健康档案")
    para(doc, "健康档案能记三项：血压、血糖、体重（如图3-4）。录入时填数值与时间，可加备注，"
              "比如“饭后两小时”；列表按时间倒序，趋势图能切日、周、月。"
              "超出常见范围的数值会标红，但只提示不给结论：单次测量受测量方式、时间、情绪影响，"
              "凭一个数字下判断既不准确，也容易让人紧张。")

    section(doc, "3.7", "病例与病史")
    para(doc, "病历、检查单、出院记录都能传，图片与 PDF 都行。上传后系统提取六项字段："
              "就诊日期、就诊机构、科室、诊断结论、处方用药、医嘱；提取不到的留空，不猜，"
              "空着的由用户自己补。确认保存后按时间轴归档，时间轴按就诊日期倒序，"
              "同一天的按上传先后排。老人后来说身体不舒服时，助手能调出这些记录参考，"
              "回答比通用建议贴合。若部署环境没有接入视觉识别，这一步自动改为手动填写，"
              "填完一样能归档，一样能在对话里用。")

    section(doc, "3.8", "用药与日程提醒")
    figure_row(doc, [
        ("05-康养计划.png", "图3-5", "康养计划"),
        ("12-智能体角色.png", "图3-6", "智能体角色列表"),
    ])
    para(doc, "提醒分三类：日常计划是每天都要做的事，比如早饭后吃药；每周计划是每周固定某天做的事；"
              "特别计划是一次性的，比如下周三复查，过了那天不再提醒。分三类是为了不让老人"
              "把每天吃的药和下周三复查混在一起（如图3-5）。")
    for line in [
        "（1）进入底部“日程”，点“日常计划”添加，填事项、时刻与重复规则。",
        "（2）点“每周计划”，选星期与时刻。",
        "（3）点“特别计划”，选具体日期，到期自动失效。",
        "（4）点日历上某天可查看当天全部安排，也能直接添加。",
        "（5）到点提醒走系统通知与应用内消息两条路，未完成项在当天列表保留标记。",
        "（6）做完的点一下打卡，状态变为已完成，点错了能取消；打卡数据回流为完成率，"
        "家属端按完成率看当天情况。",
    ]:
        para(doc, line)

    section(doc, "3.9", "主动关心与回访")
    para(doc, "软件会在合适的时候主动问一句，内容包括吃了什么、今天有没有遇到特别的事、"
              "今天过得怎么样、有没有想做还没做的事。问法按时段换，不天天用同一句。")
    para(doc, "问的次数有限制：一天最多两次，两次之间隔四小时以上，晚上和老人正在聊天的时候不问；"
              "老人连着回几个字，就不再追问。三重限制写在配置里，改配置不用改代码。"
              "老人提到以后要做的事会被记下来，到那天在聊天里再提一次；同一天只提一次，"
              "老人说还没做就隔天再问，说做完了就不再问。过期条目按实际过了几天调措辞，"
              "不会出现“今天正是这日子”但日期对不上的情况。")

    section(doc, "3.10", "家属绑定与关怀查看")
    para(doc, "老人账号里能生成邀请码，家属在自己账号里填这个码完成绑定。绑定后家属首页有三块："
              "今日安排完成了几项、最近一次的身体数据、今天的药吃没吃，另可查看对话摘要。"
              "双方可以互相留言，留言支持文字与语音，都能看到历史；也可以解绑，"
              "解绑后两边列表里的会话一起消失。家属会话与助手会话是两回事，消息不混在一起，"
              "免得家里私下说的话跑到助手那边去。")

    section(doc, "3.11", "智能体角色")
    para(doc, "可以建多个角色，每个填名字、关系、性格、口头禅与怎么称呼（如图3-6）。"
              "关系显示在对话列表里，老人按平时的叫法就能找；设好称呼方式后，"
              "这个称呼会进入长期记忆。保存后出现在对话列表，长按可设默认或删除，"
              "删掉角色之后对话还在，只是不再走这个角色的设定。")

    section(doc, "3.12", "设置与适老化")
    para(doc, "“我的”页分两组。上面一组是陪伴设置：智能体角色、人设模式、AI 了解我的、"
              "数字人形象、家人管理、智能体设置；下面一组是健康与设置：健康档案、大字体、"
              "服务器地址。分组按常改与少改来，减少误点。")
    para(doc, "界面字号大、对比度高、按钮点击区大，大字体模式能把正文再放大一档。"
              "键盘输入只有两处：聊天输入框与健康数值，其余用下拉、点选、加减按钮。"
              "数值超出合理范围时提示复核，但不阻止保存，免得把真实异常藏起来。"
              "服务器地址页的提示里带着正在用的地址；这里吃过亏，早先只提示“连不上服务器”，"
              "老人只能找家人，家人也不知道软件在连哪个地址，只能来回猜。")

    # ══ 第四章
    chapter(doc, "第四章", "技术特点与创新点")
    section(doc, "4.1", "主要技术特点")
    para(doc, "本软件的主要技术特点如下：")
    for line in [
        "（1）双人设自动路由。说话方式按关键词分层判断，命中医疗话题就换；"
        "合规提示由代码写入，模型不写也得写。",
        "（2）医疗合规三重兜底。先分类，再查话术，回答出来再扫一遍；"
        "停药、剂量、诊断这几类说法会被拦下或改写。",
        "（3）分层长期记忆。记忆分两层存，说话习惯只学真人发的消息，不拿助手自己的回复当素材；"
        "口头禅单独放，清理时不会一起丢。",
        "（4）对话历史压缩。历史太长就压成摘要，用短语出现的次数看哪些是废话，"
        "留下常提的和关键事实；压缩分批做，摘要本身也会被再压缩，原文不删。",
        "（5）主动关心调度。一天几次、隔多久、哪些时段不问，都写在配置里；"
        "没答的问题转成待回访，到日子再提。",
        "（6）三维口型同步。语音合成返回字级时间戳，端侧据此逐步驱动口型，不是整段动画。",
        "（7）能力可替换。对话模型、语音识别、语音合成都能换，改配置就在云端与本地之间切；"
        "同一套服务端能跑在局域网、虚拟专网与公网，带令牌鉴权与自动备份。",
    ]:
        para(doc, line)

    section(doc, "4.2", "创新点")
    for line in [
        "（1）把入口放在对话上，而不是表单上。老人只需说话，记录、提醒、求助都在对话里完成，"
        "这是与常见健康类应用最根本的差别。",
        "（2）医疗边界由代码守，而不是靠模型自觉。三道检查与固定提示语使得"
        "“闲聊不加免责、医疗必加免责”成为可验证的行为，而不是概率问题。",
        "（3）说话风格只向真人学习。助手自己的回复不参与风格记忆，避免越学越像机器，"
        "这一条在同类产品中较少见。",
        "（4）主动关心受三重约束。次数、最小间隔、静默时段同时满足才发，"
        "把“关心”做成可配置的规则，而不是随机推送。",
    ]:
        para(doc, line)

    # ══ 第五章
    chapter(doc, "第五章", "数据存储、安全与常见问题")
    section(doc, "5.1", "数据存储")
    para(doc, "账号、聊天、身体数据、病例与记忆都存在服务端本机的数据库里，不上传第三方。"
              "数据库为单文件 SQLite，第一次启动自动建表，迁移时连同病例图片目录一并复制即可；"
              "由于是标准格式，可用通用工具查看与导出，不锁定于本软件。"
              "删除立即生效：删掉的记忆条目不再参与后面的对话，删掉的会话不再出现在列表里。")

    section(doc, "5.2", "接口与鉴权")
    para(doc, "接口默认要令牌。聊天类接口除了令牌还要账号会话凭据，两个东西放在两个请求头，"
              "一个管能不能进来，一个管你是谁。令牌不对直接拒，不返回业务数据；"
              "会话凭据过期后客户端重新登录，已缓存的本地消息还能看，不会白屏。")

    section(doc, "5.3", "备份与恢复")
    para(doc, "备份用数据库自己的一致性快照，不用直接复制文件：服务在跑的时候复制，"
              "可能拿到还没落盘的旧数据。备份脚本执行后生成带时间戳的压缩包，"
              "里面包含数据库、病例图片目录与一份清单，清单记着文件数与校验值。"
              "恢复时先停服务，解包覆盖数据目录，再启动。建议每天定时执行一次，"
              "并把压缩包同步到另一块磁盘。日志按大小轮转，避免长期运行把磁盘写满。")

    section(doc, "5.4", "常见问题")
    for qa in [
        ("问：提示连不上服务器怎么办。",
         "答：提示里带了正在用的地址。先用手机浏览器打开这个地址的 /healthz，"
         "能看到 ok 说明网络通，再查服务端进程与端口。"),
        ("问：换网络就连不上。",
         "答：服务端在局域网里，地址会跟着变。在服务器地址页改新地址，不用重装；"
         "路由器里给服务器绑定固定地址能省掉这一步。"),
        ("问：语音没声音。",
         "答：先看系统音量与静音。语音合成服务不可用时软件自动退回纯文字，聊天不受影响。"),
        ("问：删了记忆，以前的聊天会变吗。",
         "答：聊天记录不变，只是后面不再引用被删的条目。"),
        ("问：家属能看到我和助手聊的内容吗。",
         "答：家属端只看到摘要与当天情况，看不到完整原文。"),
        ("问：换手机之后要重新注册吗。",
         "答：不用。用原账号密码登录、填同一个服务端地址即可，数据都在服务端。"),
        ("问：说话识别总是不准。",
         "答：先说环境。安静处、离麦克风近一点，识别率差很多；老年口音重时把一句话"
         "说完整再松手，太短的片段容易出错。"),
        ("问：能不能换成自己的模型。",
         "答：能。智能体设置里改模型名与接入地址即可，本地模型也支持；换完立刻生效，"
         "历史消息不受影响。"),
        ("问：几个人能共用一个服务端吗。",
         "答：能。每个账号单独注册，数据按账号隔离，服务端地址填同一个即可。"),
        ("问：数据能不能导出。",
         "答：能。数据库是单文件 SQLite，可用通用工具直接打开、导出，不锁定于本软件。"),
        ("问：语音合成不可用会怎样。",
         "答：软件自动退回纯文字，聊天与记录功能不受影响，界面会给出一次提示。"),
        ("问：老人误删了记忆条目怎么办。",
         "答：删除立即生效，无法撤回；家属可以在同一页面重新录入要点，后续对话会把新内容记进去。"),
        ("问：换了路由器之后要改配置吗。",
         "答：手机端改服务器地址即可；服务端只需保证新网段可达，"
         "若用固定 IP 则连地址都不用改。"),
        ("问：两位老人的数据会不会串。",
         "答：不会。每个账号独立存储，家属账号只与自己绑定的老人关联。"),
    ]:
        para(doc, qa[0])
        para(doc, qa[1])

    section(doc, "5.5", "日常维护要点")
    para(doc, "部署方需要照看的事项不多，但四件事不能省：")
    for line in [
        "（1）进程看护。服务端以 systemd 或计划任务方式常驻，"
        "异常退出后自动拉起；可用 /healthz 做存活探测。",
        "（2）每日备份。按 5.3 节执行一致性备份并同步到另一块磁盘，"
        "保留最近若干份，便于回溯。",
        "（3）磁盘监控。病例图片随时间增长，磁盘剩余空间低于阈值时应及时扩容或归档。",
        "（4）版本更新。服务端升级只涉及替换代码与重启进程，数据库结构变更由启动时的"
        "自动迁移完成；手机端通过重新安装安装包升级，已登录状态在升级后保持有效。",
    ]:
        para(doc, line)

    section(doc, "5.6", "已知限制")
    para(doc, "以下限制在设计与测试中已确认，部署与使用时需知悉：")
    for line in [
        "（1）对话质量取决于所接入的模型。小参数本地模型在语气上可以调好，"
        "但在需要推理的高风险场景（如突发胸痛、单侧肢体无力）上可能漏掉就医提示，"
        "因此医疗方向的安全提示始终由代码兜底，不能只依赖模型。",
        "（2）语音识别在方言较重、环境嘈杂时准确率下降，此时建议改用文字输入，"
        "功能不受影响。",
        "（3）三维数字人对显卡有要求，低端机型建议关闭三维、改用静态头像，"
        "聊天与语音功能不受影响。",
        "（4）本软件不做诊断，不替代医生；所有健康建议仅供参考，"
        "出现异常指标或明显不适应及时就医。",
        "（5）主动关心依赖服务端的调度任务，若服务端长时间停机，期间应发起的提问会积压，"
        "恢复后按当日剩余额度补发，不跨日累积。",
        "（6）家属端看到的是摘要与统计，不是聊天原文；需要了解细节时，"
        "建议家属直接与老人通话，这一条是隐私设计，不是功能缺漏。",
        "（7）模型响应速度取决于所接入的服务。云端模型通常 2 到 5 秒，"
        "本地 1.5B 模型在普通笔记本上约 5 到 15 秒，长回答更慢。",
        "（8）本软件不提供用药剂量建议，也不判断药物相互作用；"
        "涉及具体剂量与配伍时，一律提示咨询医生或药师。",
    ]:
        para(doc, line)

    section(doc, "5.7", "术语说明")
    for line in [
        "双人设：陪伴助手与健康顾问两套说话方式，由软件按话题判断该用哪套。",
        "合规提示：健康顾问回答末尾的固定提示语，提醒以医嘱为准、及时就医，由程序写入。",
        "长期记忆：从真实对话中提炼、跨会话保留的老人信息与说话习惯。",
        "主动关心：软件按规则主动发起的提问，受每日次数、最小间隔与静默时段限制。",
        "待回访事项：老人提到的以后要做的事，记下来，到日子再提。",
        "对话摘要：历史过长时压缩出的概括，代替早期原文进入上下文。",
        "降级：某项能力不可用时改用简单实现或关闭该功能，主流程不中断。",
    ]:
        para(doc, line)

    section(doc, "5.8", "部署检查清单")
    para(doc, "上线前建议按下列清单逐项确认，避免部署到一半才发现缺项：")
    for line in [
        "（1）服务端 /healthz 返回 ok；日志里没有鉴权失败记录。",
        "（2）AUTH_MODE 已设为 required，API_TOKENS 已换成随机串并与客户端一致。",
        "（3）模型接口地址、密钥与模型名已在 .env 中配置并实测可通。",
        "（4）数据库文件与病例图片目录所在磁盘剩余空间充足。",
        "（5）每日备份任务已建立，且手动执行过一次并核对清单校验值。",
        "（6）手机端填写服务端地址后“测试连接”通过，登录与对话各走一遍。",
        "（7）家属账号绑定一次、解绑一次，确认两边会话同步消失。",
        "（8）大字体模式打开后，主要页面文字未溢出或截断。",
    ]:
        para(doc, line)

    section(doc, "5.9", "版本与发布说明")
    para(doc, "本说明书对应 " + SOFTWARE_VERSION + " 版本，为该软件的首次发表版本，"
              "涵盖第一章至第五章描述的全部功能。文中提到的界面元素名称与应用内实际文案一致，"
              "便于对照操作；若因版本更新导致文案微调，以应用内显示为准。")
    para(doc, "后续版本的增补、修复与新增功能不在本说明书范围内；"
              "若功能范围发生变化，应另出具对应版本的说明书。"
              "本说明书描述的功能均已实现并经过测试，不包含规划中的功能。")
    para(doc, "软件分手机端与服务端两部分，两端可独立升级：服务端升级只涉及替换代码与重启进程，"
              "手机端升级通过重新安装安装包完成，已登录状态在升级后保持有效，"
              "两端版本不一致时服务端优先保证接口兼容。")
    para(doc, "本说明书中的截图取自 " + SOFTWARE_VERSION + " 版本的实机运行界面，"
              "分辨率 800×1732，未做美化或拼接。图中出现的人名、编号与数值均为测试数据，"
              "不代表真实用户。")
    para(doc, "若需核对功能细节，请对照应用内界面操作；若需核对技术实现，"
              "请参阅提交的源程序前三十页与后三十页。")
    para(doc, "本说明书所述功能均在 Android 8.0 及以上机型的实机上验证通过，"
              "服务端在 Ubuntu 22.04 与 Windows 11 两种环境各部署过一轮；"
              "网页端只在桌面浏览器上做过兼容性检查，未做移动端浏览器的适配。")
    para(doc, "如对本章所述内容有疑问，建议按三步核对：功能是否属于本版本、"
              "部署环境是否满足第二章要求、以及是否已按 5.8 节完成部署检查。"
              "绝大多数“用不了”的情况都落在环境与配置上，而不是功能缺失。")
    para(doc, "说明书的全部内容以 " + SOFTWARE_VERSION + " 版本的实机行为为准。"
              "若某一处描述与应用内显示不一致，以应用内为准，并请反馈以便修订。")
    para(doc, "最后一点提醒：本软件的数据都在部署方自己手里，"
              "因此换机、扩容、迁移这些操作都需要部署方参与；"
              "如果希望家属完全不用管服务器，建议由社区或机构统一部署一套，"
              "各家庭只作为账号接入。")

    path = OUT / "03-软件说明书-比邻AI智慧康养陪伴软件V1.0.docx"
    doc.save(str(path))
    return path


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("  已生成 %s" % build().name)


if __name__ == "__main__":
    main()
