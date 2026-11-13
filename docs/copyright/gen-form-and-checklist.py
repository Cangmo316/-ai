"""生成软著申请表（填写内容）与申请材料清单。

为什么单独出这两份：
    中国版权保护中心是**在线填表**，表里几十个字段。如果一边填一边想，
    很容易出现「申请表写的功能」与「说明书写的功能」不一致，被要求补正。
    所以先把答案定稿成一份 docx，照着往里抄，能保证三份材料口径一致。
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

OUT = Path(r"E:\ppt\比邻AI.ppt\软著材料")

SOFTWARE_FULL = "比邻AI智慧康养陪伴软件"
SOFTWARE_SHORT = "比邻AI"
SOFTWARE_VERSION = "V1.0"
SOFTWARE_TITLE = f"{SOFTWARE_FULL}{SOFTWARE_VERSION}"
CODE_LINES = 48672
CODE_FILES = 193


def base_document(title: str, subtitle: str = "") -> Document:
    doc = Document()
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.2)
    section.bottom_margin = Cm(2.0)
    section.left_margin = Cm(2.4)
    section.right_margin = Cm(2.0)

    style = doc.styles["Normal"]
    style.font.name = "宋体"
    style.font.size = Pt(10.5)
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    fmt = style.paragraph_format
    fmt.space_before = Pt(0)
    fmt.space_after = Pt(4)
    fmt.line_spacing_rule = WD_LINE_SPACING.SINGLE

    head = doc.add_paragraph()
    head.alignment = WD_ALIGN_PARAGRAPH.CENTER
    head.paragraph_format.space_after = Pt(2)
    run = head.add_run(title)
    run.bold = True
    run.font.size = Pt(17)
    run.font.name = "黑体"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")

    if subtitle:
        sub = doc.add_paragraph()
        sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
        sub.paragraph_format.space_after = Pt(10)
        run = sub.add_run(subtitle)
        run.font.size = Pt(11)
        run.font.name = "宋体"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    return doc


def heading(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after = Pt(6)
    run = p.add_run(text)
    run.bold = True
    run.font.size = Pt(12)
    run.font.name = "黑体"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")


def body(doc: Document, text: str, indent: bool = True) -> None:
    p = doc.add_paragraph()
    if indent:
        p.paragraph_format.first_line_indent = Pt(21)
    run = p.add_run(text)
    run.font.size = Pt(10.5)
    run.font.name = "宋体"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")


def step(doc: Document, text: str) -> None:
    """条目行：左缩进，不首行缩进（用于操作步骤与要点列表）。"""
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Pt(21)
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run(text)
    run.font.size = Pt(10.5)
    run.font.name = "宋体"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")


def note(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Pt(14)
    run = p.add_run("※ " + text)
    run.font.size = Pt(9)
    run.font.color.rgb = None
    run.font.name = "宋体"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    run.italic = True


def table(doc: Document, rows: list[tuple[str, str]], widths=(4.4, 11.6)) -> None:
    tbl = doc.add_table(rows=0, cols=2)
    tbl.style = "Table Grid"
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    for key, value in rows:
        cells = tbl.add_row().cells
        cells[0].width = Cm(widths[0])
        cells[1].width = Cm(widths[1])
        for idx, cell_text in enumerate((key, value)):
            cell = cells[idx]
            cell.text = ""
            para = cell.paragraphs[0]
            para.paragraph_format.space_after = Pt(2)
            run = para.add_run(cell_text)
            run.font.size = Pt(9.5)
            run.font.name = "宋体"
            run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
            if idx == 0:
                run.bold = True
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def make_form() -> Path:
    doc = base_document("计算机软件著作权登记申请表", "填写内容参考，照此录入线上系统")

    heading(doc, "一、软件基本信息")
    table(doc, [
        ("软件全称", f"{SOFTWARE_FULL}"),
        ("软件简称", f"{SOFTWARE_SHORT}"),
        ("版本号", f"{SOFTWARE_VERSION}"),
        ("软件作品说明", "原创软件，非修改他人软件"),
        ("软件分类", "应用软件 → 医疗健康行业应用软件"),
        ("开发方式", "独立开发"),
        ("权利取得方式", "原始取得"),
        ("权利范围", "全部权利"),
        ("开发完成日期", "2026 年 10 月 25 日"),
        ("首次发表日期", "未发表"),
        ("是否已发表", "否（如后续已在应用商店或公众号发布，需改为“已发表”并填写日期）"),
    ])
    note(doc, "软件全称中不宜出现“中国”“国家”“国际”等字样；名称与版本号须与源程序页眉、"
              "说明书页眉必须逐字一致，否则会被要求补正。")

    heading(doc, "二、著作权人信息")
    table(doc, [
        ("名称（姓名）", "【填写：个人身份证姓名，或单位营业执照全称】"),
        ("证件类型", "【填写：居民身份证 / 营业执照】"),
        ("证件号码", "【填写：身份证号或统一社会信用代码】"),
        ("国籍 / 省份", "中国 / 【填写省份】"),
        ("通信地址", "【填写：可收件的详细地址】"),
        ("邮政编码", "【填写】"),
        ("联系人", "【填写】"),
        ("联系电话", "【填写手机号】"),
        ("电子邮箱", "【填写常用邮箱，补正通知会发这里】"),
    ])
    note(doc, "个人申请须为完全民事行为能力人；单位申请须与营业执照名称完全一致，"
              "并加盖公章。若为多人/多单位合作开发，须另附合作开发协议。")

    heading(doc, "三、开发与运行环境")
    # 线上表单这几个输入框限 50 **字节**（UTF-8 下约 16 个汉字），
    # 所以这里给的是压缩后的值；字节数直接标出来，填表时照着核。
    env_rows = [
        ("开发的硬件环境", "i9-14900HX/16GB/512GB",
         "CPU i9-14900HX、内存 16GB、固态硬盘 512GB"),
        ("运行的硬件环境", "2核2G服务器；Android 8.0手机",
         "服务端 2 核 CPU / 2GB 内存 / 40GB 磁盘；移动端 Android 8.0 及以上手机，"
         "内存 2GB 以上（三维数字人建议 4GB）"),
        ("开发该软件的操作系统", "Windows 11 64位", "Windows 11 64 位"),
        ("软件开发环境 / 开发工具", "HBuilderX;VS Code;Node.js;Git",
         "HBuilderX 5.26、Visual Studio Code、Node.js 18、Vite 5、Git、Python 3.13"),
        ("该软件的运行平台 / 操作系统", "Ubuntu 22.04;Windows 10;Android 8.0",
         "服务端：Ubuntu 22.04 及以上 / Debian 12 及以上 / Windows 10 及以上；"
         "移动端：Android 8.0 及以上；浏览器端：支持 HTML5 的现代浏览器"),
        ("软件运行支撑环境 / 支持软件", "Python 3.11;FastAPI;SQLite 3",
         "Python 3.11 及以上；FastAPI 0.141、Uvicorn 0.54、httpx 0.28、PyYAML 6.0、"
         "python-multipart 0.0.32；SQLite 3"),
        ("编程语言", "Python;JavaScript;Vue", "Python、JavaScript、Vue（HTML/CSS）"),
        ("源程序量", f"{CODE_LINES}行", f"{CODE_LINES} 行（{CODE_FILES} 个代码文件，不含第三方开源库）"),
    ]

    # 断言：任一字段超过 50 字节就报错，避免改文案后又超限
    for field, value, _full in env_rows:
        size = len(value.encode("utf-8"))
        if size > 50:
            raise SystemExit(
                "字段「%s」占 %d 字节，超过表单 50 字节限制：%s" % (field, size, value)
            )

    tbl = doc.add_table(rows=0, cols=3)
    tbl.style = "Table Grid"
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    for field, value, _full in env_rows:
        cells = tbl.add_row().cells
        for idx, width in enumerate((3.6, 6.2, 2.0)):
            cells[idx].width = Cm(width)
        size = len(value.encode("utf-8"))
        for idx, text in enumerate((field, value, "%d 字节" % size)):
            cell = cells[idx]
            cell.text = ""
            para = cell.paragraphs[0]
            para.paragraph_format.space_after = Pt(2)
            run = para.add_run(text)
            run.font.size = Pt(9.5)
            run.font.name = "宋体"
            run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
            if idx == 0:
                run.bold = True
    doc.add_paragraph().paragraph_format.space_after = Pt(2)

    note(doc, "线上表单这几项限 50 字节。一个汉字占 3 字节，50 字节约 16 个汉字。"
              "上表右列的填写值都压到了 50 字节以内，可直接照抄。"
              "中列是完整描述，写说明书或口头解释时用，不要往表单里填。")
    note(doc, "不同批次的系统提示语不一样，有的按字数、有的按字节。"
              "上表的压缩值两种口径都能用，字段里还留了补信息的地方。")
    note(doc, "源程序量按纯数字填（如 48672），不要带千分位逗号，避免系统校验不通过。")

    heading(doc, "四、开发目的、面向领域与主要功能")

    # 线上表单这几栏限 50 字节（UTF-8 下一个汉字 3 字节，约 16 个汉字）。
    # 主要功能/技术特点在不同批次里限制不同，故给两档。
    text_rows = [
        ("开发目的", "为独居老人提供心理陪伴与健康提醒", ""),
        ("面向领域", "智慧养老与家庭健康管理领域", ""),
        ("主要功能（50字节版）", "陪伴、健康档案、用药提醒、家属",
         "最严限制时用这一行"),
        ("主要功能（200字节版）",
         "语音文字对话并自动切换双人设；记录血压血糖体重与趋势；"
         "病历拍照结构化归档；用药与日程提醒；主动关心与回访；家属绑定远程查看",
         "限制宽松时用这一行，信息更全"),
        ("技术特点（50字节版）", "双人设自动切换、医疗合规兜底",
         "最严限制时用这一行"),
        ("技术特点（200字节版）",
         "双人设分层路由与医疗合规三重兜底；分层长期记忆；历史按频次压缩；"
         "关心调度受频次与静默约束；模型语音可本地切换",
         "限制宽松时用这一行"),
    ]

    tbl4 = doc.add_table(rows=0, cols=4)
    tbl4.style = "Table Grid"
    tbl4.alignment = WD_TABLE_ALIGNMENT.CENTER
    for field, value, hint in text_rows:
        cells = tbl4.add_row().cells
        for idx, width in enumerate((3.4, 8.6, 1.8, 2.2)):
            cells[idx].width = Cm(width)
        size = len(value.encode("utf-8"))
        if size > 50 and "200字节" not in field:
            raise SystemExit(
                "字段「%s」占 %d 字节，超过 50 字节限制：%s" % (field, size, value)
            )
        if "200字节" in field and size > 200:
            raise SystemExit(
                "字段「%s」占 %d 字节，超过 200 字节上限：%s" % (field, size, value)
            )
        for idx, text in enumerate((field, value, "%d 字节" % size, hint)):
            cell = cells[idx]
            cell.text = ""
            para = cell.paragraphs[0]
            para.paragraph_format.space_after = Pt(2)
            run = para.add_run(text)
            run.font.size = Pt(9)
            run.font.name = "宋体"
            run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
            if idx == 0:
                run.bold = True
    doc.add_paragraph().paragraph_format.space_after = Pt(2)

    note(doc, "线上表单「开发目的」限 50 字节（约 16 个汉字），上表第一行可直接照抄。"
              "「主要功能」「技术特点」各批次限制不同：先按 50 字节版填；"
              "若表单允许更多，再换 200 字节版。")
    note(doc, "两档都不是唯一答案。表单提示“限 N 字”时把上表的值加长即可。"
              "别超过提示的限制。超了会被截成半句话，比写短更难看。")

    heading(doc, "四之一、详细版：供写说明书使用，不要填入表单")
    body(doc, "下面是与上表同义但更完整的表述。表单填不下，用于写说明书、"
              "向评审或客户解释时使用。")
    body(doc, "【开发目的·详细】")
    body(doc, "做这个软件是因为两件事对不上。健康类的应用功能都齐，但老人用不了："
              "要填表、要看图表，字小、步骤多。聊天类的应用老人会用，但聊完就完了，"
              "记不下血压，不会提醒吃药，家属也看不到情况。"
              "所以把聊天当成入口，老人说什么就记什么，助手按规则决定要不要提醒、"
              "要不要建议去医院。健康数据和病历放在同一个地方，家属用另一个账号看。"
              "界面按老人的眼神和手指做大，能点就不让打字。")
    body(doc, "【面向领域·详细】")
    body(doc, "智慧养老与家庭健康管理领域，适用于居家养老、社区养老服务站、"
              "养老机构日常照护等场景。")
    body(doc, "【主要功能·详细】")
    for item in [
        "1. 账号与家属绑定：注册后自动分配 8 位数字编号；老人可生成邀请码，家属凭码完成绑定。",
        "2. 智能对话：支持文字与语音两种输入方式；默认以陪伴助手身份对话，"
        "识别到医疗健康问题时自动切换为健康顾问身份，并在回答中追加合规提示。",
        "3. 三维数字人：端侧渲染三维形象，按语音的字级时间戳驱动口型，实现拟人化播报。",
        "4. 长期记忆：按固定间隔从真实对话中沉淀老人画像与说话风格，"
        "用户可查看、修改、删除任一条目。",
        "5. 健康档案：录入血压、血糖、体重，按时间展示记录与变化趋势。",
        "6. 病例管理：上传病历与检查单的图片或 PDF，提取结构化信息并按时间轴归档。",
        "7. 用药与日程提醒：支持按日、按周与一次性特别安排三种维度，日历页汇总查看。",
        "8. 主动关心与回访：在合适时段主动发起关心提问，并将老人提到的未来事项"
        "记录为待回访事项，到期自动再次提起。",
        "9. 家属关怀查看：家属可查看老人当日安排完成情况、健康指标、用药执行与对话摘要。",
        "10. 智能体角色：可创建多个角色并设定姓名、关系、性格、口头禅与称呼方式。",
        "11. 设置与适老化：大字体模式、服务器地址配置与连接测试等。",
    ]:
        step(doc, item)
    body(doc, "【技术特点·详细】")
    for item in [
        "1. 两套说话方式按关键词分层判断，命中医疗话题就换。提醒是代码写进去的，"
        "模型不写也得写。",
        "2. 医疗合规做三道：先分类，再查话术，回答出来再扫一遍。"
        "停药、剂量、诊断这几类说法会被拦下或改掉。",
        "3. 记忆分两层存。说话习惯只学真人发的消息，不拿助手自己的回复当素材；"
        "口头禅单独放，清理时不会一起丢。",
        "4. 历史太长就压成摘要，用短语出现的次数看哪些是废话，留下常提的和关键事实。",
        "5. 主动提问有上限：一天几次、隔多久、哪些时段不问，都写死在配置里。"
        "没答的问题转成待回访，到日子再提。",
        "6. 对话模型、语音识别、语音合成都能换，改配置就在云端和本地之间切。",
        "7. 同一套服务端能跑在局域网、虚拟专网和公网，带令牌鉴权和自动备份。",
    ]:
        step(doc, item)

    heading(doc, "五、材料一致性自检")
    table(doc, [
        ("软件全称", "申请表、源程序页眉、说明书页眉三处必须逐字相同"),
        ("版本号", "三处均为 V1.0，不得出现“1.0”“V1”“v1.0”混用"),
        ("源程序量", f"申请表填 {CODE_LINES} 行；源程序文档为前 30 页 + 后 30 页共 60 页"),
        ("主要功能", "申请表所列功能须在说明书中都能找到对应章节与截图"),
        ("开发完成日期", "应早于或等于首次发表日期；未发表的须为已实际完成的日期"),
        ("著作权人", "与身份证/营业执照完全一致，单位申请需加盖公章"),
    ])

    path = OUT / "01-软件著作权登记申请表（填写内容）.docx"
    doc.save(str(path))
    return path


def make_checklist() -> Path:
    doc = base_document("软件著作权申请材料清单与办理说明", SOFTWARE_TITLE)

    heading(doc, "一、官方要求与本目录材料的逐条对照")
    body(doc, "下面这张表左边是官方的原话，右边是这份材料实际做到的程度。"
              "写“实测”的，都是打开 Word 数过页数和每页行数的。")
    table(doc, [
        ("申请文件应纵向排版，文字从左向右",
         "全部材料为 A4 纵向，宋体横向排列 ｜ 达标"),
        ("程序每页不少于 50 行",
         "实测 60 页，逐页 50–51 行（末页 50 行）｜ 达标"),
        ("文档每页不少于 30 行",
         "实测 8 页，逐页 31–47 行，平均 36.1 行 ｜ 达标"),
        ("源程序和文档前、后各连续 30 页",
         "源码合 974 页，超 60 页，按规则提交前 30 页 + 后 30 页 ｜ 达标"),
        ("整个程序和文档不到 60 页的，提交全部",
         "说明书仅 8 页，故全部提交 ｜ 达标"),
        ("鉴别材料页眉的软件版本号应与申请表一致",
         "两份材料页眉均为「比邻AI智慧康养陪伴软件V1.0」，与申请表一致 ｜ 达标"),
        ("有无 V 以申请表中填报为准",
         "申请表填 V1.0，页眉同样带 V ｜ 一致"),
        ("在线打印申请确认签章页，勿更改内容、格式与打印比例",
         "签章页由系统生成打印，不得自行排版（本目录 01 文件只是填写参考）｜ 待你操作"),
        ("签章后上传扫描件（PDF）",
         "个人签字或单位盖章后扫描为 PDF 上传 ｜ 待你操作"),
    ])
    note(doc, "标“待你操作”的两项我没法替你办：签章页要在系统里生成再打印，"
              "还得本人签字或单位盖章。目录里的 01 只是录入时对照用的，不能当签章页交。")

    heading(doc, "二、需要提交的材料")
    table(doc, [
        ("1. 申请表", "线上填报后打印申请确认签章页，签章并扫描上传。"
                     "填写内容照《01-申请表（填写内容）》录入。"),
        ("2. 源程序", "本目录 02 文件（docx 与 pdf 各一份），共 60 页。"
                     "页眉为软件全称+版本号，页脚为页码，每页 50–51 行。"),
        ("3. 软件说明书", "本目录 03 文件，共 8 页，20 个章节，含 6 张运行截图，"
                        "每页不少于 30 行。"),
        ("4. 身份证明", "个人：身份证正反面照片或扫描件；"
                      "单位：加载统一社会信用代码的营业执照副本（加盖公章）。"),
        ("5. 其他", "合作开发需合作开发合同；委托开发需委托开发合同；"
                   "下达任务开发需项目任务书或合同；修改他人软件需原著作权人许可。"),
    ])

    heading(doc, "三、源程序的 60 页规则（本次如何处理）")
    body(doc, f"本软件自有代码 {CODE_LINES} 行（{CODE_FILES} 个文件），按每页 50 行"
              "折合约 974 页，超过 60 页上限。按登记要求提交前 30 页与后 30 页，"
              "共 60 页 3000 行；中间部分不提交。")
    body(doc, "需要特别注意：不要在文档里插入“此处省略若干页”之类的说明行。"
              "一行说明会把总行数顶成 3001 行、页数变 61 页，反而不符合“各 30 页”的要求。"
              "省略的事实写在本清单里即可。")
    note(doc, "统计口径：已排除 three.js、Draco 等第三方开源库（合计 3.5 万余行）"
              "与测试代码。混入他人代码可能被认定为“含他人已登记代码”，"
              "这是源程序材料最常见的补正原因之一。")

    heading(doc, "四、办理流程")
    table(doc, [
        ("1. 注册账号", "中国版权保护中心官网注册并完成实名认证。"),
        ("2. 在线填报", "选择“计算机软件著作权登记”，按《01-申请表》逐项录入。"),
        ("3. 上传材料", "上传源程序与说明书的 PDF、身份证明扫描件、签章页扫描件。"),
        ("4. 提交与缴费", "提交后按系统提示完成缴费。"),
        ("5. 受理与审查", "以形式审查为主。材料有瑕疵会下发补正通知，按通知补正即可。"),
        ("6. 登记公告与发证", "审查通过后予以登记并公告，随后发放登记证书。"),
    ])
    note(doc, "官方收费标准与办理时限以官网当期公示为准，本文件不写具体天数与金额，"
              "避免与最新政策不一致。查阅入口：中国版权保护中心 → 软件登记指南 → 办理时限。")

    heading(doc, "四之一、线上表单的字节限制（实操坑）")
    body(doc, "开发与运行环境相关的几个输入框在线上表单里限 50 字节。"
              "注意是字节不是字：按 UTF-8 编码，一个汉字占 3 字节，"
              "50 字节只够放约 16 个汉字。若按习惯写满一行中文，提交时会被截断或报错。")
    body(doc, "本目录 01 文件的「三、开发与运行环境」已把每个字段压到 50 字节以内，"
              "并在表格右列标出实际字节数，照抄即可。压缩后仍保留关键信息，"
              "例如“运行的硬件环境：2核2G服务器；Android 8.0手机”为 35 字节。")
    body(doc, "另有两处容易忽略：源程序量按纯数字填（如 48672），不要加千分位逗号；"
              "软件名称不得含“中国”“国家”“国际”等字样。")

    heading(doc, "五、办理前必须确认的三件事")
    for item in [
        "著作权人写谁：个人还是单位。写单位时，作品的著作权归属需能解释清楚"
        "（职务作品需任职证明），否则后续维权会受影响。",
        "是否已经发表：已上架应用商店、发布公众号版本、或对外交付演示的，"
        "都属于已发表，需填“已发表”及首次发表日期。填“未发表”与实际不符，"
        "会影响权利稳定性。",
        "软件名称是否可用：不得含“中国”“国家”“国际”等字样；"
        "与已有商标冲突不影响登记，但商用需另做商标检索。",
    ]:
        step(doc, "· " + item)

    heading(doc, "六、本目录文件说明")
    table(doc, [
        ("01-软件著作权登记申请表（填写内容）.docx / .pdf", "照此录入线上系统"),
        ("02-源程序-……V1.0.docx / .pdf", "源程序 60 页，可直接打印或上传"),
        ("03-软件说明书-……V1.0.docx / .pdf", "说明书 8 页，20 章，6 张截图"),
        ("04-软件著作权申请材料清单与办理说明.docx / .pdf", "本文件"),
        ("生成统计.txt", "代码文件清单与行数明细，用于核对源程序量"),
    ])
    note(doc, "如需调整（改软件名称、改版本号、换截图），请修改 docs/copyright/ 下的"
              "生成脚本后重新输出。手工改 docx 很容易破坏“每页 50 行 / 每页 30 行”的版式，"
              "而版式一旦破坏，页数就不对了。")

    path = OUT / "04-软件著作权申请材料清单与办理说明.docx"
    doc.save(str(path))
    return path


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    form = make_form()
    print("  已生成 %s" % form.name)
    checklist = make_checklist()
    print("  已生成 %s" % checklist.name)


if __name__ == "__main__":
    main()
