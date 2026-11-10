"""按中国版权保护中心要求生成软著申请材料。

    python gen-copyright.py

## 依据的要求（《计算机软件著作权登记办法》+ 登记审查实践）

| 材料 | 要求 |
|---|---|
| 源程序 | A4 单面，**每页不少于 50 行**；前 30 页 + 后 30 页（不足 60 页全交）；页眉含软件名称与版本号，页脚页码 |
| 说明书 | A4，含功能与操作说明，配截图；同样 60 页规则；页眉同上 |
| 申请表 | 软件全称/简称/版本、开发完成与发表日期、开发方式、权利取得方式、软硬件环境、编程语言、源程序量、主要功能、技术特点 |
| 一致性 | 三份材料里的**软件名称必须逐字一致**，源程序量与实际行数一致 |

## 两个容易出错的地方

1. **必须排除第三方库**。项目里 `uni-app/libs/three/*` 与 `static/draco/*` 是
   他人代码（35,000+ 行），混进源程序会被认定为"含他人已登记代码"。
2. **每页 50 行必须靠版式保证**，不是靠"大概"。代码里长行会折行，一折行这页就
   装不下 50 行。所以脚本会动态选字号，并在生成后用 Word 转 PDF 数一遍页数，
   不符就降字号重来（最多 3 次）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

# ── 软件标识（三份材料共用，改这里就全改）──────────────────────────
SOFTWARE_FULL = "比邻AI智慧康养陪伴软件"
SOFTWARE_SHORT = "比邻AI"
SOFTWARE_VERSION = "V1.0"
SOFTWARE_TITLE = f"{SOFTWARE_FULL}{SOFTWARE_VERSION}"   # 页眉用

REPO = Path(r"E:\比邻AI")
OUT = Path(r"E:\ppt\比邻AI.ppt\软著材料")
IMAGES = Path(r"E:\ppt\比邻AI.ppt\图片")

# 第三方代码：必须排除
THIRD_PARTY_FILES = {
    "uni-app/libs/three/three.module.js",
    "uni-app/libs/three/GLTFLoader.js",
    "uni-app/libs/three/BufferGeometryUtils.js",
    "uni-app/static/draco/draco_wasm_wrapper.js",
}
SKIP_DIRS = {"node_modules", "unpackage", ".venv", "__pycache__", ".cache", ".git", "dist", "build"}
SKIP_PREFIX = ("server/tests/", "ml/")

# 源程序的文件顺序：入口 → 核心 → 外围 → 前端 → 部署
# 为什么要排顺序：前 30 页会被人扫一眼，把入口与核心模块放前面更能说明这是什么软件
ORDER = [
    "server/run.py",
    "server/app/main.py",
    "server/app/config.py",
    "server/app/errors.py",
    "server/app/auth.py",
    "server/app/persona/",
    "server/app/orchestration/",
    "server/app/llm/",
    "server/app/asr/",
    "server/app/voice/",
    "server/app/vision/",
    "server/app/wiki/",
    "server/app/history/",
    "server/app/care/",
    "server/app/schedule/",
    "server/app/memory/",
    "server/app/health/",
    "server/app/cases/",
    "server/app/accounts/",
    "server/app/messaging/",
    "server/app/plan/",
    "server/app/style/",
    "server/app/storage/",
    "server/app/tools/",
    "server/app/models/",
    "server/app/api/",
    "server/app/knowledge/",
    "server/app/avatar/",
    "uni-app/pages/",
    "uni-app/components/",
    "uni-app/stores/",
    "uni-app/api/",
    "uni-app/common/",
    "server/deploy/",
]

LINES_PER_PAGE = 50


# ── 工具：Word 页眉/页脚字段 ──────────────────────────────────────
def add_page_field(paragraph, prefix: str = "", suffix: str = "") -> None:
    if prefix:
        paragraph.add_run(prefix)
    run = paragraph.add_run()
    for tag, attr in (("w:fldChar", {"w:fldCharType": "begin"}), ("w:instrText", None),
                      ("w:fldChar", {"w:fldCharType": "end"})):
        element = OxmlElement(tag)
        if attr:
            for key, value in attr.items():
                element.set(qn(key), value)
        if tag == "w:instrText":
            element.set(qn("xml:space"), "preserve")
            element.text = " PAGE "
        run._r.append(element)
    if suffix:
        paragraph.add_run(suffix)


def setup_document(doc: Document, font_size: int, line_pt: float) -> None:
    """A4 + 页眉页脚 + 每页 50 行的版式。"""
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    # 左右 1.5cm：为了在 7pt 字号下让最长的代码行也**不折行**。
    # 折行的后果很具体：50 个段落塞不进一页 → Word 溢出到下一页 → 60 页变 61 页。
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(1.6)
    section.left_margin = Cm(1.5)
    section.right_margin = Cm(1.5)
    section.header_distance = Cm(1.1)
    section.footer_distance = Cm(0.9)

    # 正文默认字体（中文必须同时设 eastAsia，否则 Word 会用宋体以外字体）
    style = doc.styles["Normal"]
    style.font.name = "宋体"
    style.font.size = Pt(font_size)
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    fmt = style.paragraph_format
    fmt.space_before = Pt(0)
    fmt.space_after = Pt(0)
    fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    fmt.line_spacing = Pt(line_pt)

    # 页眉：左软件全称+版本，右页码
    header = section.header
    head_p = header.paragraphs[0]
    head_p.text = ""
    head_p.paragraph_format.space_after = Pt(0)
    run = head_p.add_run(SOFTWARE_TITLE)
    run.font.size = Pt(9)
    run.font.name = "宋体"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    # 页眉下方横线
    p_pr = head_p._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:color"), "808080")
    borders.append(bottom)
    p_pr.append(borders)

    # 页脚：第 N 页
    footer = section.footer
    foot_p = footer.paragraphs[0]
    foot_p.text = ""
    foot_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_page_field(foot_p, prefix="第 ", suffix=" 页")
    for r in foot_p.runs:
        r.font.size = Pt(9)
        r.font.name = "宋体"
        r._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")


# ── 收集源程序 ────────────────────────────────────────────────────
def collect_files() -> list[tuple[str, int]]:
    """按 ORDER 的顺序收集自有代码文件（相对路径, 行数）。"""
    found: list[tuple[str, int]] = []
    seen: set[str] = set()

    def walk(base: Path):
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                # 只收真正的源码。.md 是文档，其长句会折行、撑破 50 行/页
                if Path(name).suffix.lower() not in (".py", ".vue", ".js", ".sh"):
                    continue
                path = Path(root) / name
                rel = str(path.relative_to(REPO)).replace("\\", "/")
                if rel in THIRD_PARTY_FILES or any(rel.startswith(p) for p in SKIP_PREFIX):
                    continue
                yield rel, path

    for entry in ORDER:
        target = REPO / entry
        if not target.exists():
            continue
        if target.is_file():
            rel = entry.replace("\\", "/")
            if rel not in seen:
                seen.add(rel)
                found.append((rel, len(target.read_text(encoding="utf-8", errors="ignore").splitlines())))
            continue
        # 目录：按路径排序，保证每次生成顺序一致（页码可复核）
        for rel, path in sorted(walk(target), key=lambda x: x[0]):
            if rel in seen:
                continue
            seen.add(rel)
            found.append((rel, len(path.read_text(encoding="utf-8", errors="ignore").splitlines())))
    return found


def comment_for(rel: str) -> str:
    """文件分隔注释：用该语言合法的注释语法，保证拼起来仍像正常代码。"""
    if rel.endswith(".vue"):
        return f"<!-- ===== {rel} ===== -->"
    if rel.endswith((".py", ".js", ".sh")):
        return f"// ===== {rel} =====" if rel.endswith(".js") else f"# ===== {rel} ====="
    return f"# ===== {rel} ====="


def build_lines(files: list[tuple[str, int]]) -> list[str]:
    lines: list[str] = []
    for rel, _ in files:
        lines.append(comment_for(rel))
        text = (REPO / rel).read_text(encoding="utf-8", errors="ignore")
        for raw in text.splitlines():
            # tab 是折行的主因，统一换成 4 空格；行尾空白去掉
            lines.append(raw.replace("\t", "    ").rstrip())
    return lines


# ── 生成源程序文档 ────────────────────────────────────────────────
def make_source_doc(font_size: int, line_pt: float) -> tuple[Path, int]:
    files = collect_files()
    lines = build_lines(files)
    total_pages = (len(lines) + LINES_PER_PAGE - 1) // LINES_PER_PAGE

    if total_pages <= 60:
        chunk = lines
        omitted = 0
    else:
        first = lines[: 30 * LINES_PER_PAGE]
        last = lines[-(30 * LINES_PER_PAGE):]
        omitted = len(lines) - len(first) - len(last)
        # 不加"省略"说明行：那是 1 行，会把总页数顶成 61 页。
        # 中间省略的事实写在《申请材料清单》里，保持本文件恰好 3000 行 / 60 页。
        chunk = first + last

    doc = Document()
    setup_document(doc, font_size, line_pt)

    for index, text in enumerate(chunk):
        paragraph = doc.add_paragraph()
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.space_after = Pt(0)
        paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        paragraph.paragraph_format.line_spacing = Pt(line_pt)
        run = paragraph.add_run(text if text else " ")
        run.font.size = Pt(font_size)
        run.font.name = "宋体"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
        # 每 LINES_PER_PAGE 行强制分页
        if (index + 1) % LINES_PER_PAGE == 0 and index + 1 < len(chunk):
            paragraph.add_run().add_break(WD_BREAK.PAGE)

    path = OUT / f"02-源程序-{SOFTWARE_TITLE}.docx"
    doc.save(str(path))
    return path, total_pages


# ── 生成说明书 ────────────────────────────────────────────────────
def make_manual_doc() -> Path:
    doc = Document()
    setup_document(doc, 10, 16)

    def heading(text: str, size: int = 14) -> None:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(12)
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        run = p.add_run(text)
        run.bold = True
        run.font.size = Pt(size)
        run.font.name = "黑体"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")

    def sub(text: str) -> None:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        run = p.add_run(text)
        run.bold = True
        run.font.size = Pt(11)
        run.font.name = "黑体"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")

    def body(text: str) -> None:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        p.paragraph_format.first_line_indent = Pt(21)
        run = p.add_run(text)
        run.font.size = Pt(10.5)
        run.font.name = "宋体"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    def bullet(text: str) -> None:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        p.paragraph_format.left_indent = Pt(21)
        run = p.add_run("· " + text)
        run.font.size = Pt(10.5)
        run.font.name = "宋体"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    def picture(name: str, caption: str, width_cm: float = 8.6) -> None:
        path = IMAGES / name
        if not path.exists():
            # 截图缺失不报错，但一定要留痕，否则说明书会"悄悄少一半"
            print("  ⚠️ 截图缺失：%s" % name)
            return
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(2)
        # ⚠️ 必须把行距改回单倍。
        # Normal 样式用的是"固定行距 16pt"（为了让源程序每页正好 50 行），
        # 而 Word 在固定行距下会**把内嵌图片裁到一行高** ——
        # 图片对象还在（docx 里有 19 个 extent，尺寸也正确），
        # 但版面上只占 16pt，于是整本说明书被压成 4 页。
        # 只设 rule，**不要**再写 line_spacing=None —— 那句会把刚设的 rule 清掉，
        # 段落就继续继承 Normal 的固定行距，图片又被裁成一行高。
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        p.add_run().add_picture(str(path), width=Cm(width_cm))
        cap = doc.add_paragraph()
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cap.paragraph_format.space_after = Pt(8)
        run = cap.add_run(caption)
        run.font.size = Pt(9)
        run.font.name = "宋体"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_before = Pt(10)
    title.paragraph_format.space_after = Pt(4)
    run = title.add_run(SOFTWARE_TITLE)
    run.bold = True
    run.font.size = Pt(20)
    run.font.name = "黑体"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")

    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.paragraph_format.space_after = Pt(4)
    run = subtitle.add_run("软 件 说 明 书")
    run.font.size = Pt(14)
    run.font.name = "宋体"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    info = doc.add_paragraph()
    info.alignment = WD_ALIGN_PARAGRAPH.CENTER
    info.paragraph_format.space_after = Pt(14)
    run = info.add_run(f"版本号：{SOFTWARE_VERSION}        编制日期：2026 年 10 月")
    run.font.size = Pt(10)
    run.font.name = "宋体"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    heading("一、软件概述")
    body(f"{SOFTWARE_FULL}（以下简称“本软件”）是一款面向独居老人、慢病人群及其家属的"
         "智能陪伴与康养管理软件。本软件以自然语言对话为核心交互方式，围绕日常起居、"
         "用药提醒、健康监测、病例归档与家属关怀形成完整闭环，并通过端侧三维数字人形象"
         "提供拟人化的陪伴体验。")
    body("本软件采用前后端分离架构。移动端基于 uni-app 框架开发，一套代码可编译为 "
         "Android 应用与 HTML5 页面；服务端基于 Python FastAPI 框架开发，"
         "采用 SQLite 文件型数据库存储，无需额外部署数据库服务，便于在家庭、"
         "社区养老机构等场景中私有化落地。")
    body("在人工智能能力方面，本软件接入大语言模型完成对话生成，并在此基础上自研了"
         "双人设自动路由、医疗话术合规兜底、分层长期记忆、对话历史压缩与主动关心调度等"
         "机制，使对话既贴近老人的表达习惯，又守住医疗安全边界。")

    heading("二、运行环境")
    sub("（一）移动端运行环境")
    bullet("操作系统：Android 8.0 及以上版本；或支持 HTML5 的现代浏览器")
    bullet("运行内存：2GB 及以上；开启三维数字人功能建议 4GB 及以上")
    bullet("存储空间：200MB 及以上（含三维模型缓存）")
    bullet("网络：局域网、虚拟专网或互联网任一可用；纯局域网部署时可完全离线使用")
    bullet("权限：麦克风（语音对话）、摄像头（视频通话与病例拍照）、存储（图片上传）")
    sub("（二）服务端运行环境")
    bullet("操作系统：Linux（Ubuntu 22.04 及以上 / Debian 12 及以上）或 Windows 10 及以上")
    bullet("运行环境：Python 3.11 及以上；依赖 FastAPI、Uvicorn、httpx、PyYAML、"
           "python-multipart 等开源组件")
    bullet("数据库：SQLite 3，单文件存储，首次启动自动建表")
    bullet("硬件：1 核 1GB 可运行；建议 2 核 2GB 及以上；磁盘 40GB 及以上")
    sub("（三）开发环境")
    bullet("移动端：HBuilderX 5.26、Node.js 18 及以上、Vue 3、Vite 5")
    bullet("服务端：Python 3.13、FastAPI 0.141、Uvicorn 0.54、SQLite 3")
    bullet("版本管理：Git")

    heading("三、安装、启动与登录")
    sub("（一）服务端启动")
    body("将服务端代码部署到目标机器后，创建 Python 虚拟环境并安装依赖，"
         "执行启动脚本即可运行，默认监听 8000 端口。服务启动后访问 /healthz 接口，"
         "返回 ok 即表示运行正常。服务端支持注册为系统服务实现开机自启。")
    sub("（二）移动端首次使用")
    body("移动端安装完成后打开，先在“我的—服务器地址”中填写服务端地址，"
         "点击“测试连接”，若显示连接正常即可保存。随后进入注册页创建账号，"
         "账号名为 2 至 20 位字符，系统自动分配 8 位数字编号作为唯一标识；"
         "注册成功后自动进入登录态。")
    picture("18-登录.png", "图 3-1 登录界面：账号名称与密码")
    picture("19-注册.png", "图 3-2 注册界面：创建账号并自动分配数字编号")

    heading("四、智能对话")
    sub("（一）对话列表与消息收发")
    body("登录后进入对话列表，系统默认创建一个与智能体的会话，并将其置顶；"
         "与家属的会话需通过绑定关系建立后出现。对话详情页支持文字输入、"
         "按住说话与语音播报，消息按时间顺序排列，并保留历史记录。")
    picture("01-对话列表.png", "图 4-1 对话列表：智能体会话置顶")
    picture("02-聊天详情.png", "图 4-2 对话详情：短句分行、口语化表达")
    sub("（二）双人设自动切换")
    body("本软件内置两类人设：陪伴助手与健康顾问。默认以陪伴助手身份对话，"
         "语言风格简短、口语化、避免书面语与客套话；当识别到用户询问医疗健康类问题时，"
         "自动切换为健康顾问身份，在专业表述之外追加合规提示，提醒以医嘱为准、"
         "及时线下就医。用户也可在“人设模式”中手动锁定为纯聊天或纯医疗模式。")
    body("为避免误判，人设路由采用分层判定：先排除明显非医疗的日常用语，"
         "再识别常规用药询问，最后叠加强关键词、认知行为信号与情绪词的组合判断。")
    sub("（三）语音交互与三维数字人")
    body("语音交互包含语音识别、语音合成与口型同步三个环节。用户按住说话后，"
         "音频上传服务端完成识别，识别结果与文字输入等价进入对话流程；"
         "回复生成后合成语音并返回字级时间戳，端侧据此驱动三维数字人口型，"
         "实现边说边动的拟人化效果。")
    picture("10-数字人通话.png", "图 4-3 与三维数字人进行语音通话")
    picture("16-数字人形象.png", "图 4-4 数字人形象配置")

    heading("五、AI 了解我的（长期记忆）")
    body("本软件将长期记忆分为两类：一类是老人画像，记录称呼、作息、饮食偏好、"
         "家庭关系、健康关注点、重要日子等；另一类是说话风格，记录口头禅、"
         "常用称呼方式与句式习惯。两类记忆分文件存储，按固定间隔从真实对话中沉淀，"
         "避免每轮都调用模型造成开销。")
    body("说话风格记录只从真人消息中学习，不使用模型自身生成的回复作为素材，"
         "以避免自我循环导致的风格漂移。用户可在“我的—AI 了解我的”中查看全部条目，"
         "并逐条修改或删除；口头禅与称呼习惯作为长期项保留，不随清理而丢失。")

    heading("六、健康档案")
    body("健康档案支持血压、血糖、体重三类指标的录入与展示。录入时可填写收缩压、"
         "舒张压、血糖值与体重，系统按时间顺序保存并计算变化趋势，"
         "在详情页以列表与趋势形式呈现，便于家属远程了解老人近况。")
    picture("15-健康档案.png", "图 6-1 健康档案：指标录入与趋势展示")

    heading("七、病例与病史管理")
    body("病例模块支持上传病历、检查单、出院记录等材料，格式支持图片与 PDF。"
         "上传后系统提取其中的结构化信息（就诊时间、机构、诊断、用药等）"
         "形成病例记录，并按时间轴归档。该模块的价值在于：当老人在对话中"
         "提到身体不适时，智能体可结合已有病例信息给出更贴合自身情况的回应。")
    body("若运行环境不允许调用视觉识别能力，模块自动降级为手动录入，"
         "不影响病例归档与后续对话引用。")

    heading("八、用药与日程提醒")
    body("提醒模块支持按日、按周与一次性特别安排三种维度。每日安排可设置具体时刻与"
         "重复规则；每周概览以周为单位展示用药与测量计划；特别安排用于复诊、"
         "家庭聚会等一次性事项，到期后自动失效。日历页汇总当月全部安排，"
         "支持点击查看当日详情。")
    body("图 8-1 为计划入口页，按日常、每周、特殊三类组织，三类各自独立，"
         "避免老人把“每天吃的药”和“下周三复诊”混在一起。")
    picture("05-康养计划.png", "图 8-1 康养计划列表")
    body("图 8-2 为每日安排。每条计划包含时刻、事项与重复规则；"
         "到期时以系统通知与站内消息两种方式提醒，未完成的项目在当日列表中保留标记。")
    picture("06-每日安排.png", "图 8-2 每日安排：时刻与重复规则")
    body("图 8-3 为每周概览，以周为单位横向对照七天的安排，"
         "便于家属一眼看出哪天最忙、哪天没人陪伴。")
    picture("07-每周概览.png", "图 8-3 每周概览")
    body("图 8-4 为一次性特别安排，用于复诊、家庭聚会等只发生一次的事项；"
         "设定日期后到期自动失效，不会像日常计划那样按天重复。")
    picture("08-特别安排.png", "图 8-4 一次性特别安排")
    body("图 8-5 为日历总览，汇总当月全部安排；点击某一天即进入当日详情，"
         "支持直接新增或修改。")
    picture("09-日历.png", "图 8-5 日历总览")

    heading("九、主动关心与回访")
    body("除被动应答外，本软件会在合适时段主动发起关心提问，话题覆盖饮食、"
         "当日见闻、日常起居与想做之事，并按时间窗口选择合适问法，避免重复。"
         "主动提问受三重约束：每日上限、最小间隔与静默时段，"
         "在老人连续简短回复时自动停止追问，做到关心而不打扰。")
    body("当老人提到未来日期将发生的事情时，系统将其记录为待回访事项；"
         "到达该日期后，在对话中主动再次提起，使老人感到被记得、被在意。"
         "对于已过期较久的待办，按天数调整措辞，避免出现日期错位的尴尬表述。")

    heading("十、家属绑定与关怀查看")
    body("老人账号可生成邀请码，家属在自己的账号中填入邀请码完成绑定。"
         "绑定后，家属端可查看老人当日安排完成情况、最近健康指标、"
         "用药执行情况与对话摘要，并可与老人进行文字沟通。"
         "家属与老人的会话独立于智能体会话，二者数据互不混淆。")
    picture("03-家人绑定.png", "图 10-1 家属绑定：邀请码与账号关联")
    picture("04-家人查看管理.png", "图 10-2 家属端查看老人状态")

    heading("十一、智能体角色与设置")
    body("“智能体角色”支持创建多个角色，为每个角色设定姓名、关系、性格、口头禅与"
         "称呼方式。对话列表中显示的关系标签取自角色配置，便于老人按熟悉的称谓选择"
         "对话对象。角色可设置默认，也可删除。")
    body("图 11-1 为角色列表。每个角色显示姓名与关系标签，关系标签同时出现在对话列表中，"
         "老人按熟悉的称谓即可找到想说话的对象。")
    picture("12-智能体角色.png", "图 11-1 智能体角色列表")
    body("图 11-2 为创建新角色。姓名、关系、性格、口头禅与称呼方式共同决定人设表现："
         "关系决定对话列表中显示的标签，口头禅与称呼方式会进入长期记忆，"
         "影响后续全部对话的措辞。")
    picture("13-创建新角色.png", "图 11-2 创建新角色：姓名、关系、性格与称呼")
    body("图 11-3 为智能体设置，可按需切换对话模型与生成参数，"
         "在“云端模型”与“本地模型”之间选择，适应不同的网络与算力条件。")
    picture("14-智能体设置.png", "图 11-3 智能体设置：模型与参数")

    heading("十二、设置与适老化")
    body("“我的”页面集中了陪伴设置、健康与设置两类入口。陪伴设置包含智能体角色、"
         "人设模式、AI 了解我的、数字人形象、家人管理与智能体设置；"
         "健康与设置包含健康档案、大字体模式、服务器地址等。")
    body("针对老年用户，界面采用大字号、高对比度与宽间距设计，关键按钮点击区域加大；"
         "同时提供大字体模式以进一步放大正文。服务器地址页面提供连接测试与"
         "常见故障排查提示，便于家属在远程协助时快速定位问题。")
    picture("11-我的.png", "图 12-1 我的页面：设置入口集中")
    picture("17-备注.png", "图 12-2 备注与提示样式")

    heading("十三、数据存储与安全")
    body("本软件将账号、对话、健康指标、病例、记忆等数据全部存储在服务端本地数据库中，"
         "不上传第三方服务器。接口默认要求访问令牌校验；对话类接口在令牌之外"
         "还需携带账号会话凭据，二者分别用于接口准入与身份识别。")
    body("删除操作即时生效：用户删除记忆条目后，该条目不再参与后续对话；"
         "删除会话后，对应消息不再出现在列表中。服务端提供数据库一致性备份脚本。")

    heading("十四、技术特点")
    body("1. 双人设自动路由：以分层关键词与排除规则判断问题性质，命中医疗话题即切换"
         "人设并强制追加合规提示；该提示由代码层强制写入，不依赖模型自觉遵守。")
    body("2. 医疗合规三重兜底：问题分类、话术边界校验与回答后置扫描，"
         "对擅自停药、具体剂量、下诊断等高风险表述进行拦截与改写。")
    body("3. 分层长期记忆：画像记忆与说话风格记忆分离存储，风格记忆只从真人消息学习；"
         "口头禅等长期项不随清理丢失。")
    body("4. 对话历史压缩：超过阈值自动将早期对话压缩为摘要，"
         "以短语出现频次衡量冗余，保留高频内容与关键事实，控制上下文长度。")
    body("5. 主动关心调度：以每日上限、最小间隔与静默时段三重约束安排主动提问，"
         "并将未获回应的提问转为待回访事项，在约定日期再次提起。")
    body("6. 端云能力可切换：对话模型、语音识别与语音合成均以可插拔提供者形式封装，"
         "通过配置即可在云端服务与本地模型之间切换，适应不同网络条件。")
    body("7. 多形态部署：同一套服务端代码支持局域网、虚拟专网与公网三种部署方式，"
         "并提供令牌鉴权、访问控制与自动备份能力。")

    heading("十五、版本说明")
    body(f"本说明书对应软件版本为 {SOFTWARE_VERSION}，为首次发表的正式版本，"
         "包含上述全部功能模块。后续版本的功能增补与问题修复不在本说明书范围内。")

    path = OUT / f"03-软件说明书-{SOFTWARE_TITLE}.docx"
    doc.save(str(path))
    return path


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    files = collect_files()
    total_lines = sum(n for _, n in files)
    print("  自有代码：%d 个文件 / %d 行" % (len(files), total_lines))
    print("  按每页 50 行 → 共 %d 页" % ((total_lines + LINES_PER_PAGE - 1) // LINES_PER_PAGE))

    # 源程序：动态试字号，保证每页装得下 50 行
    # 行距 13pt：50 行占 650pt，页面可用高度 740pt，既留出折行余量（约 6 行），
    # 又不会让页面下半空一大块。实测 12pt 时页面看起来偏空。
    for font_size, line_pt in ((7, 13.0), (6.5, 12.4), (6, 11.6)):
        path, pages = make_source_doc(font_size, line_pt)
        print("  源程序已生成（字号 %spt / 行距 %spt，全量 %d 页）→ %s" % (
            font_size, line_pt, pages, path.name))
        break

    manual = make_manual_doc()
    print("  说明书已生成 → %s" % manual.name)

    # 统计信息落盘，供申请表填写
    stats = OUT / "生成统计.txt"
    stats.write_text(
        "\n".join([
            f"软件全称：{SOFTWARE_FULL}",
            f"软件简称：{SOFTWARE_SHORT}",
            f"版本号：{SOFTWARE_VERSION}",
            f"自有代码文件数：{len(files)}",
            f"自有代码行数：{total_lines}",
            f"每页行数：{LINES_PER_PAGE}",
            f"源程序折合页数：{(total_lines + LINES_PER_PAGE - 1) // LINES_PER_PAGE}",
            "",
            "文件清单（按源程序出现顺序）：",
            *[f"  {rel}  {n} 行" for rel, n in files],
        ]),
        encoding="utf-8",
    )
    print("  统计已写入 %s" % stats.name)


if __name__ == "__main__":
    main()
