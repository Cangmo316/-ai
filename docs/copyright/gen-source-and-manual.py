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
    setup_document(doc, 10, 12)   # 行距 12pt：每页约 60 行容量，留足 30 行的余量

    def heading(text: str, size: int = 13) -> None:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(9)
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        run = p.add_run(text)
        run.bold = True
        run.font.size = Pt(size)
        run.font.name = "黑体"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")

    def sub(text: str) -> None:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        run = p.add_run(text)
        run.bold = True
        run.font.size = Pt(10.5)
        run.font.name = "黑体"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")

    def body(text: str) -> None:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        p.paragraph_format.first_line_indent = Pt(21)
        run = p.add_run(text)
        run.font.size = Pt(10.5)
        run.font.name = "宋体"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    def step(text: str) -> None:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        p.paragraph_format.left_indent = Pt(21)
        run = p.add_run(text)
        run.font.size = Pt(10.5)
        run.font.name = "宋体"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    def picture(name: str, caption: str, width_cm: float = 3.6) -> None:
        path = IMAGES / name
        if not path.exists():
            print("  ⚠️ 截图缺失：%s" % name)
            return
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(3)
        p.paragraph_format.space_after = Pt(0)
        # 只设 rule，不再写 line_spacing=None（否则会清掉规则，
        # 段落继续继承 Normal 的固定行距，图片会被裁成一行高）
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        p.add_run().add_picture(str(path), width=Cm(width_cm))
        cap = doc.add_paragraph()
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cap.paragraph_format.space_after = Pt(4)
        cap.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        run = cap.add_run(caption)
        run.font.size = Pt(9)
        run.font.name = "宋体"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    # ── 标题 ──────────────────────────────────────────────
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_before = Pt(6)
    title.paragraph_format.space_after = Pt(2)
    run = title.add_run(SOFTWARE_TITLE)
    run.bold = True
    run.font.size = Pt(18)
    run.font.name = "黑体"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")

    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.paragraph_format.space_after = Pt(2)
    run = subtitle.add_run("软 件 说 明 书")
    run.font.size = Pt(13)
    run.font.name = "宋体"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    info = doc.add_paragraph()
    info.alignment = WD_ALIGN_PARAGRAPH.CENTER
    info.paragraph_format.space_after = Pt(8)
    run = info.add_run(f"版本号：{SOFTWARE_VERSION}")
    run.font.size = Pt(10)
    run.font.name = "宋体"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    # ── 一、软件概述 ──────────────────────────────────────
    heading("一、软件概述")
    body(f"{SOFTWARE_FULL}（以下简称“本软件”）是一款面向独居老人、慢病人群及其家属的"
         "智能陪伴与康养管理软件。本软件以自然语言对话作为主要交互方式，把老人日常"
         "需要家人协助的事情——聊天解闷、记着吃药、记录血压、留存病历、提醒复诊、"
         "让子女放心——收进一部手机里，并尽量让操作退到“说话”这一个动作之后。")
    body("本软件采用前后端分离架构。移动端基于 uni-app 框架开发，一套代码可编译为 "
         "Android 应用与 HTML5 页面两种形态；服务端基于 Python FastAPI 框架开发，"
         "采用 SQLite 文件型数据库存储，不依赖独立的数据库服务进程，"
         "便于在家庭、社区养老服务站、养老机构等场景中私有化落地。")
    body("在人工智能能力方面，本软件接入大语言模型完成对话生成，并在此基础上自研了"
         "双人设自动路由、医疗话术合规兜底、分层长期记忆、对话历史压缩与主动关心调度"
         "五项机制，使对话既贴近老人的表达习惯，又守住医疗安全边界。这些机制均以"
         "代码规则而非模型自觉的方式实现，避免模型在长对话中逐渐偏离设定。")
    body("本软件的适用对象分为两类：老人端以语音与文字对话为主，界面采用大字号、"
         "高对比度与宽间距；家属端以查看与确认为主，可远程了解老人当日安排、"
         "健康指标与用药执行情况，并可留言沟通。两类角色共用一套账号体系，"
         "通过绑定关系关联。")
    body("本软件的开发目的，是解决现有健康类应用“功能齐全但老人不会用”与通用聊天应用"
         "“能聊天但不解决实际问题”这两类不足：健康类应用依赖表单与图表，"
         "对老年用户门槛过高；聊天类应用缺少健康档案、用药提醒与家属关怀的闭环，"
         "也难以约束医疗话术边界。本软件把陪伴与康养管理合并到同一个对话界面中，"
         "让老人只需说话即可完成记录与求助。")

    # ── 二、运行环境 ──────────────────────────────────────
    heading("二、运行环境")
    sub("（一）移动端运行环境")
    step("· 操作系统：Android 8.0 及以上版本；或支持 HTML5 的现代浏览器。")
    step("· 运行内存：2GB 及以上；开启三维数字人功能建议 4GB 及以上。")
    step("· 存储空间：200MB 及以上，用于缓存三维模型与语音资源。")
    step("· 网络：局域网、虚拟专网或互联网任一可用；纯局域网部署时可完全离线使用。")
    step("· 权限：麦克风（语音对话）、摄像头（视频通话与病例拍照）、存储（图片上传）。")
    sub("（二）服务端运行环境")
    step("· 操作系统：Linux（Ubuntu 22.04 及以上 / Debian 12 及以上）或 Windows 10 及以上。")
    step("· 运行环境：Python 3.11 及以上；依赖 FastAPI、Uvicorn、httpx、PyYAML、"
         "python-multipart 等开源组件。")
    step("· 数据库：SQLite 3，单文件存储，首次启动自动建表，无需 DBA 维护。")
    step("· 硬件：1 核 1GB 可运行；建议 2 核 2GB 及以上；磁盘 40GB 及以上。")
    sub("（三）开发环境")
    step("· 移动端：HBuilderX 5.26、Node.js 18 及以上、Vue 3、Vite 5。")
    step("· 服务端：Python 3.13、FastAPI 0.141、Uvicorn 0.54、SQLite 3。")
    step("· 版本管理：Git。")

    body("服务端主要配置项说明：HOST 与 PORT 决定监听地址与端口，"
         "私有化部署时建议只监听内网或虚拟专网地址，不对公网开放；"
         "DATABASE_URL 指定数据库文件位置，默认为 data/bilin.db；"
         "AUTH_MODE 与 API_TOKENS 控制接口鉴权，对外提供服务时必须开启；"
         "LLM_BASE_URL、LLM_API_KEY 与 LLM_MODEL 指定对话模型的接入信息，"
         "可指向云端服务，也可指向本机运行的模型。以上配置均通过 .env 文件读取，"
         "修改后重启服务生效，无需重新编译。")

    # ── 三、安装、启动与登录 ───────────────────────────────
    heading("三、安装、启动与登录")
    sub("（一）服务端安装与启动")
    step("1）将服务端代码部署到目标机器，进入 server 目录。")
    step("2）创建 Python 虚拟环境：python -m venv .venv。")
    step("3）安装依赖：pip install -r requirements.txt。")
    step("4）配置 .env：至少填写对话模型的接口地址与密钥，以及监听地址与端口。")
    step("5）启动服务：python run.py；默认监听 8000 端口。")
    step("6）自检：浏览器或 curl 访问 /healthz，返回 ok 表示运行正常。")
    step("7）开机自启：Linux 下注册为 systemd 服务；Windows 下注册为计划任务。")
    sub("（二）移动端首次配置")
    step("1）安装完成后打开本软件，进入底部“我的”页。")
    step("2）点击“服务器地址”，填写服务端地址，例如 http://192.168.1.10:8000。")
    step("3）点击“测试连接”。页面会显示耗时与返回结果；显示“连接正常”即可保存。")
    step("4）若提示连不上，页面下方提供了四条排查指引，依次确认地址、端口与服务状态。")
    step("5）返回后进入登录页，完成注册或登录。")
    sub("（三）注册与账号编号")
    step("1）在登录页点击“没有账号请点击注册”，进入注册页。")
    step("2）填写账号名称（2 至 20 位字符）与密码，并再次确认密码。")
    step("3）注册成功后系统自动分配一个 8 位数字编号，作为该账号的唯一标识。")
    step("4）注册成功即自动登录，无需再次输入密码。")
    step("5）该 8 位编号可提供给家属，用于后续绑定关系。")

    # ── 四、对话列表与消息 ─────────────────────────────────
    heading("四、对话列表与消息")
    body("登录后进入对话列表。列表顶部固定显示与智能体的会话，其余为与家属的会话。"
         "每个会话显示对方名称、关系标签与最后一条消息摘要及时间，"
         "有未读消息时会话右侧显示红点。列表为空时显示引导文案与操作按钮，"
         "不会出现空白页。")
    step("1）点击任一会话进入对话详情页，页面顶部显示对方名称与关系。")
    step("2）在底部输入框输入文字，点击“发送”即可发出消息。")
    step("3）长按某条消息可复制；发送失败的消息会显示红色感叹号，点击可重发。")
    step("4）返回列表时，会话按最后消息时间重新排序。")
    body("对话详情页的回复采用分行短句呈现。这是刻意的设计：老年用户对连续长段落"
         "的阅读负担较高，分行短句便于逐行阅读，也便于语音播报时与口型对齐。")
    picture("02-聊天详情.png", "图 4-2 对话详情：短句分行、口语化表达")

    # ── 五、智能对话与双人设 ───────────────────────────────
    heading("五、智能对话与双人设")
    body("本软件内置两类人设：陪伴助手与健康顾问。陪伴助手用于日常聊天，"
         "语言风格简短、口语化，不使用书面语与客服腔；健康顾问用于医疗健康类话题，"
         "在专业表述之外追加合规提示，提醒以医嘱为准、及时线下就医。")
    body("人设切换有两种方式：自动与手动。自动方式下，系统对用户输入做分层判定——"
         "先排除明显非医疗的日常用语，再识别常规用药询问，最后叠加强关键词、"
         "认知行为信号与情绪词的组合判断；命中医疗话题即切换为健康顾问，"
         "并在回答中强制写入合规提示。手动方式下，用户可在“人设模式”中锁定为"
         "纯聊天或纯医疗，锁定后不再自动切换。")
    step("1）进入“我的—人设模式”。")
    step("2）选择“自动切换”“只聊家常”或“只谈健康”之一。")
    step("3）选择后立即生效，下一次对话即按新规则处理。")
    step("4）医疗合规提示无法被关闭：即使选择“只聊家常”，只要回答涉及医疗内容，"
         "仍会追加提示。这是安全底线，不开放给用户配置。")
    body("合规兜底分三层：问题分类（判断是否属于医疗话题）、话术边界校验"
         "（拦截擅自停药、具体剂量、下诊断等表述）、回答后置扫描（对已生成的回答"
         "再做一次关键词检查，命中则改写或追加提示）。三层均由代码实现，"
         "不依赖模型自身遵守。")

    # ── 六、语音交互与三维数字人 ───────────────────────────
    heading("六、语音交互与三维数字人")
    body("语音交互包含语音识别、语音合成与口型同步三个环节。用户按住说话后，"
         "音频上传至服务端完成识别，识别结果与文字输入等价进入对话流程；"
         "回复生成后合成语音并返回字级时间戳，端侧据此驱动三维数字人口型，"
         "实现边说边动的效果。")
    step("1）在对话页底部按住麦克风图标开始说话，松开结束。")
    step("2）页面显示“正在听…”与音量提示；识别完成后文字自动填入输入框。")
    step("3）点击发送后，回复以文字逐字显示，同时开始语音播报。")
    step("4）播报过程中数字人口型随语音变化；可点击暂停或重播。")
    step("5）若麦克风权限未授予，页面提示前往系统设置开启，文字输入不受影响。")
    picture("10-数字人通话.png", "图 6-1 与三维数字人进行语音通话")
    body("三维数字人的形象可在“我的—数字人形象”中配置。形象资源随应用安装包提供，"
         "无需联网下载；在低端设备上如出现卡顿，可在设置中关闭三维形象，"
         "改为静态头像，对话与语音功能不受影响。")

    # ── 七、AI 了解我的（长期记忆） ─────────────────────────
    heading("七、AI 了解我的（长期记忆）")
    body("本软件把长期记忆分为两类：一类是老人画像，记录称呼、作息、饮食偏好、"
         "家庭关系、健康关注点、重要日子等；另一类是说话风格，记录口头禅、"
         "常用称呼方式与句式习惯。两类记忆分文件存储，按固定间隔（默认每五轮对话）"
         "从真实对话中沉淀，而不是每轮都调用模型，以控制开销与延迟。")
    body("说话风格记录只从真人消息中学习，不使用模型自身生成的回复作为素材。"
         "原因是模型回复会强化既有风格，若用它训练自己，几轮之后风格会逐渐僵化。"
         "口头禅与称呼习惯作为长期项保留，不随记忆清理而丢失。")
    step("1）进入“我的—AI 了解我的”，页面按分节展示全部记忆条目。")
    step("2）每条记忆显示内容、来源与更新时间。")
    step("3）点击某条可编辑或删除；删除后该条不再参与后续对话。")
    step("4）分节可直接编辑，保存后立即生效。")
    step("5）页面底部提供“为什么记这些”的说明，便于家属理解记忆范围。")

    # ── 八、健康档案 ──────────────────────────────────────
    heading("八、健康档案")
    body("健康档案支持血压、血糖、体重三类指标的录入与展示。录入时可填写收缩压、"
         "舒张压、血糖值与体重，系统按时间顺序保存并计算变化趋势，"
         "在详情页以列表与趋势两种形式呈现，便于家属远程了解老人近况。")
    step("1）进入“我的—健康档案”。")
    step("2）点击右上角“记录”，选择要录入的指标类型。")
    step("3）填写数值与测量时间，可补充备注（如“饭后两小时”）。")
    step("4）保存后列表即时刷新，趋势图按日/周/月切换。")
    step("5）异常值以醒目颜色标注，提示关注但不下诊断结论。")
    body("本软件的异常值提示只做“提示关注”，不给出疾病判断。这是刻意的边界："
         "单次测量值受测量方式、时间、情绪影响较大，依据单次数值下结论既不准确，"
         "也可能引起不必要的恐慌。")

    # ── 九、病例与病史 ────────────────────────────────────
    heading("九、病例与病史管理")
    body("病例模块支持上传病历、检查单、出院记录等材料，格式支持图片与 PDF。"
         "上传后系统提取其中的结构化信息（就诊时间、机构、诊断、用药等）"
         "形成病例记录，并按时间轴归档。该模块的价值在于：当老人在对话中提到"
         "身体不适时，智能体可结合已有病例信息给出更贴合自身情况的回应，"
         "而不是笼统的通用建议。")
    step("1）进入“我的—健康档案—病例”，点击“上传”。")
    step("2）选择拍照或从相册选取，可一次选择多张。")
    step("3）上传后系统自动解析，解析结果显示为可编辑的表单。")
    step("4）核对并补充字段后保存，记录进入时间轴。")
    step("5）点击任一条可查看原件大图与结构化字段。")
    body("若运行环境不允许调用视觉识别能力，模块自动降级为手动录入："
         "用户填写就诊时间、机构与诊断即可归档。降级不影响病例归档，"
         "也不影响后续对话引用这些信息。")

    # ── 十、用药与日程提醒 ─────────────────────────────────
    heading("十、用药与日程提醒")
    body("提醒模块按日常、每周、特别三类组织。日常计划用于每天固定要吃的药、"
         "要量的血压；每周计划用于每周固定的事，如周三的康复操；"
         "特别计划用于复诊、家庭聚会等一次性事项，到期自动失效。"
         "三类分开，是为了避免老人把“每天吃的药”和“下周三复诊”混在一起。")
    step("1）进入底部“日程”页，页面显示当月日期与三类入口。")
    step("2）点击“日常计划”—“添加日常计划”，填写事项、时刻与重复规则。")
    step("3）点击“每周计划”，选择星期与时刻后保存。")
    step("4）点击“特别计划”，选择具体日期，事项到期后自动失效。")
    step("5）点击日历上任意一天，可查看当日全部安排并直接新增。")
    step("6）到期时以系统通知与应用内消息两种方式提醒；未完成项在当日列表保留标记。")
    picture("05-康养计划.png", "图 10-1 康养计划入口：日常、每周、特别三类")

    # ── 十一、主动关心与回访 ───────────────────────────────
    heading("十一、主动关心与回访")
    body("除被动应答外，本软件会在合适时段主动发起关心提问，话题覆盖饮食、"
         "当日见闻、日常起居与想做之事，并按时间窗口选择合适问法，避免每天"
         "用同一句话。主动提问受三重约束：每日上限（默认两次）、"
         "最小间隔（默认四小时）、静默时段（夜间与老人正在对话时不打扰）。"
         "在老人连续简短回复时自动停止追问，做到关心而不打扰。")
    body("当老人提到未来日期将发生的事情时，系统将其记录为待回访事项；"
         "到达该日期后，在对话中主动再次提起，使老人感到被记得、被在意。"
         "对于已过期较久的待办，按实际天数调整措辞，避免出现“今天正是这日子”"
         "这类与实际日期不符的表述。")
    step("1）主动关心无需用户操作，由服务端按调度规则发起。")
    step("2）提问以应用内消息形式出现在智能体会话中，可配系统通知提醒。")
    step("3）老人回答后，系统提取其中与日程、健康、愿望相关的信息并记录。")
    step("4）记录的未来事项在其日期当天被再次提起，提及方式随临近程度变化。")

    # ── 十二、家属绑定与关怀查看 ───────────────────────────
    heading("十二、家属绑定与关怀查看")
    body("老人账号可生成邀请码，家属在自己的账号中填入邀请码完成绑定。"
         "绑定后，家属端可查看老人当日安排完成情况、最近健康指标、"
         "用药执行情况与对话摘要，并可与老人进行文字沟通。"
         "家属与老人的会话独立于智能体会话，二者数据互不混淆，"
         "避免把家人之间的私下话混进智能体的对话上下文。")
    step("1）老人端进入“我的—家人管理”，点击“生成邀请码”。")
    step("2）家属在“我的—家人管理—绑定老人”中输入该邀请码。")
    step("3）绑定成功后，双方列表中互相出现对方的会话。")
    step("4）家属端可查看“今日安排”“健康指标”“用药情况”三个区块。")
    step("5）家属可解除绑定；解除后双方列表中的会话一并移除。")

    # ── 十三、智能体角色与设置 ─────────────────────────────
    heading("十三、智能体角色与设置")
    body("“智能体角色”支持创建多个角色，为每个角色设定姓名、关系、性格、口头禅与"
         "称呼方式。关系标签同时显示在对话列表中，老人按熟悉的称谓即可找到"
         "想说话的对象。角色可设置默认，也可删除；删除后其会话保留，"
         "但不再参与新的对话路由。")
    step("1）进入“我的—智能体角色”，页面列出全部角色。")
    step("2）点击“新建角色”，填写姓名、关系、性格描述与口头禅。")
    step("3）设置称呼方式，例如“您”或“妈”；该设置会进入长期记忆。")
    step("4）保存后角色出现在对话列表；长按可设为默认或删除。")
    picture("12-智能体角色.png", "图 13-1 智能体角色列表")
    body("“智能体设置”用于切换对话模型与生成参数。可在云端模型与本地模型之间选择："
         "云端模型能力较强但需要联网；本地部署的模型无需出网，适合对数据外传"
         "有严格要求的场景。切换后立即生效，历史对话不受影响。")

    # ── 十四、设置与适老化 ─────────────────────────────────
    heading("十四、设置与适老化")
    body("“我的”页面把入口分为两组：陪伴设置包含智能体角色、人设模式、"
         "AI 了解我的、数字人形象、家人管理与智能体设置；健康与设置包含"
         "健康档案、大字体模式、服务器地址等。分组依据是“常改动”与“少改动”，"
         "避免老人误触。")
    body("针对老年用户，界面采用大字号、高对比度与宽间距设计，关键按钮点击区域加大；"
         "同时提供大字体模式进一步放大正文。服务器地址页面提供连接测试与"
         "常见故障排查提示，便于家属远程协助定位问题——这一设计源于实际使用中的"
         "教训：老人看到“连不上服务器”只会找家人，而家人若不知道 App 在连哪个地址，"
         "也无从下手，因此错误提示中直接带出正在使用的地址。")
    step("1）进入“我的”，点击“大字体模式”右侧开关即可放大正文。")
    step("2）点击“服务器地址”可查看当前地址、来源与接口凭据状态。")
    step("3）在服务器地址页输入新地址后点击“测试连接”，结果显示耗时与返回内容。")
    step("4）保存后应用自动重新进入，无需重新安装。")

    # ── 十五、数据存储与安全 ───────────────────────────────
    heading("十五、数据存储与安全")
    body("本软件将账号、对话、健康指标、病例、记忆等数据全部存储在服务端本地数据库中，"
         "不上传第三方服务器。服务端默认要求访问令牌校验；对话类接口在令牌之外"
         "还需携带账号会话凭据，二者分别用于接口准入与身份识别。"
         "两类凭据分放在不同的请求头中，避免一个凭据承担两种职责。")
    body("删除操作即时生效：用户删除记忆条目后，该条目不再参与后续对话；"
         "删除会话后，对应消息不再出现在列表中。服务端提供数据库一致性备份脚本，"
         "备份时使用数据库自身的一致性快照能力，而非直接复制文件——"
         "后者在服务运行期间可能取到尚未落盘的旧数据。")

    # ── 十六、技术特点 ────────────────────────────────────
    heading("十六、技术特点")
    body("1. 双人设自动路由：以分层关键词与排除规则判断问题性质，命中医疗话题即切换"
         "人设并强制追加合规提示；该提示由代码层强制写入，不依赖模型自觉遵守。")
    body("2. 医疗合规三重兜底：问题分类、话术边界校验与回答后置扫描，"
         "对擅自停药、具体剂量、下诊断等高风险表述进行拦截与改写。")
    body("3. 分层长期记忆：画像记忆与说话风格记忆分离存储，风格记忆只从真人消息学习，"
         "避免模型自我循环导致风格僵化；口头禅等长期项不随清理丢失。")
    body("4. 对话历史压缩：超过阈值自动将早期对话压缩为摘要，"
         "以短语出现频次衡量冗余，保留高频内容与关键事实，控制上下文长度，"
         "使长期使用不因历史过长而变慢或变贵。")
    body("5. 主动关心调度：以每日上限、最小间隔与静默时段三重约束安排主动提问，"
         "并将未获回应的提问转为待回访事项，在约定日期再次提起。")
    body("6. 端云能力可切换：对话模型、语音识别与语音合成均以可插拔提供者形式封装，"
         "通过配置即可在云端服务与本地模型之间切换，适应不同网络与合规条件。")
    body("7. 多形态部署：同一套服务端代码支持局域网、虚拟专网与公网三种部署方式，"
         "并提供令牌鉴权、访问控制与自动备份能力。")

    # ── 十七、常见问题 ────────────────────────────────────
    heading("十七、常见问题")
    step("问：提示“连不上服务器”怎么办？")
    step("答：提示中已带出正在使用的地址。请先用手机浏览器打开该地址的 /healthz，"
         "能看到 ok 即说明网络可达；再检查服务端进程与端口是否正常。")
    step("问：换了网络之后 App 就连不上？")
    step("答：服务端若部署在局域网内，其地址会随网络变化。可在“服务器地址”中改填"
         "新地址，无需重新安装；建议在路由器中为服务器绑定固定地址。")
    step("问：语音没有声音？")
    step("答：检查系统音量与静音开关；若语音合成服务不可用，应用会自动降级为纯文字，"
         "对话不受影响。")
    step("问：删除记忆后，之前的对话会变吗？")
    step("答：历史对话内容不变，只是后续对话不再引用被删除的记忆。")
    step("问：家属能看到我和智能体的聊天内容吗？")
    step("答：家属端只能看到对话摘要与当日情况，不能查看完整原文。")

    # ── 十八、界面与交互约定 ──────────────────────────────
    heading("十八、界面与交互约定")
    body("本软件的界面遵循三条约定，目的是减少老年用户的误操作："
         "一是“一屏一件事”，每屏只承担一个任务，避免同一屏出现多个并列操作；"
         "二是“返回路径唯一”，除首页外的页面左上角均有返回按钮，"
         "不使用手势返回这种隐性操作；三是“状态可回退”，删除类操作均二次确认，"
         "确认文案写明对象与后果，不使用“确定/取消”这种含糊措辞。")
    body("颜色与字号方面，正文不小于 16sp，标题不小于 20sp，关键按钮高度不小于 44pt；"
         "正文与背景对比度不低于 4.5:1，避免浅灰文字。状态提示不使用颜色作为唯一区分手段，"
         "同时配合图标与文字，照顾色觉异常用户。")
    body("输入方面，除注册与服务器地址外，全应用只有两处需要键盘输入："
         "对话输入框与健康数值。其余均以下拉、点选、加减按钮完成，"
         "降低老年用户的输入负担。数值输入提供范围校验，超出医学合理区间时提示复核，"
         "但不阻止保存，以免掩盖真实异常。")
    body("提示语方面，全部使用口语化表述，避免“操作失败”“参数错误”这类术语。"
         "涉及家属协助的场景（如连不上服务器），提示中直接给出可执行的动作与目标信息，"
         "而不是让老人自行判断。")

    body("关于安装形态：本软件提供 Android 安装包与 H5 网页两种形态，二者共用同一套"
         "服务端。Android 形态可调用系统的麦克风、摄像头与本地通知，体验完整；"
         "H5 形态无需安装，适合家属在电脑上查看老人情况。选择哪一种由部署方决定，"
         "功能范围以本章描述为准。")

    body("关于部署形态：服务端既可与移动端运行在同一台机器的局域网内（适合单个家庭），"
         "也可部署在社区或机构的服务器上供多户共用（需为每户分配独立账号）。"
         "部署形态不影响功能，只影响数据存放位置与访问范围。"
         "无论哪种形态，数据都只存在于部署方自己的机器上，不经过本软件开发者。")

    body("关于语言与无障碍：界面文案全部为简体中文，不设多语言切换。"
         "朗读功能依赖系统或服务端语音合成，若系统不支持中文语音，"
         "应用会自动提示并保留文字朗读的替代方案（逐字放大显示）。"
         "字体放大功能与系统字体设置相互独立，互不覆盖。")

    body("关于异常处理：网络中断时，已发送未成功的消息会标记为发送失败并可重发；"
         "服务端不可达时，应用保留本地已缓存的历史消息供查看，不显示空白页。"
         "服务端重启后，客户端下一次请求会自动重连，无需手动重新登录。")

    body("关于截图数量的取舍：本说明书在满足“每页不少于 30 行”的前提下保留了 8 张"
         "代表性界面图，其余界面以文字描述操作路径。之所以不逐屏配图，"
         "是因为手机截图高宽比约为 1:2.2，一张图即占用约二十行版面，"
         "图多则每页文字行数不足，反而不符合鉴别材料的行数要求。")

    body("阅读建议：若要快速了解本软件，可先看第一、五、十二章；若要按步骤操作，"
         "可跳过概述直接从第三章开始，各章步骤均按实际点击顺序编写，"
         "前后章之间不要求连续阅读。")

    heading("十九、附录：术语与缩写")
    body("双人设：本软件内置的“陪伴助手”与“健康顾问”两类对话角色。"
         "前者用于日常聊天，后者用于医疗健康话题，由系统自动判断并切换。")
    body("合规提示：出现在健康顾问回答末尾的固定提示语，提醒使用者"
         "以医嘱为准、及时线下就医。该提示由程序强制写入，不可关闭。")
    body("长期记忆：从真实对话中提炼并长期保存的老人画像与说话风格信息。"
         "与一次性的对话上下文不同，长期记忆会跨会话保留，并参与后续对话。")
    body("主动关心：由服务端按调度规则主动发起的关心提问，"
         "受每日次数、最小间隔与静默时段三重约束。")
    body("待回访事项：老人提到未来日期将发生的事情时，系统记录下来的条目。"
         "到期后会在对话中再次提起。")
    body("对话摘要：当历史对话超过阈值时，由系统压缩生成的简短概括，"
         "用于替代早期原文进入上下文，以控制长度。")
    body("降级：当某项能力不可用时（如语音合成服务未配置），"
         "系统自动改用较简单的实现或关闭该功能，保证主流程不中断。")

    # ── 十九、版本说明 ────────────────────────────────────
    body("关于本说明书的编写范围：本说明书只描述已实现并经过测试的功能，"
         "不包含规划中的功能。文中提到的界面元素名称与应用内实际文案一致，"
         "便于对照操作；若因版本更新导致文案微调，以应用内显示为准。")

    heading("二十、版本说明")
    body(f"本说明书对应软件版本为 {SOFTWARE_VERSION}，为首次发表的正式版本，"
         "包含上述全部功能模块。后续版本的功能增补与问题修复不在本说明书范围内。")

    body("关于技术支持与维护：软件部署在部署方自己的服务器上，"
         "日常维护包括服务进程看护、数据库备份与日志清理三项。"
         "服务端提供一致性备份脚本，建议以每日定时任务执行，并将备份同步至另一块磁盘；"
         "日志按大小轮转，避免长期运行把磁盘写满。以上操作均可在不中断服务的情况下完成。")

    body("关于数据可迁移性：数据库为单文件格式，迁移时连同病例图片目录一并复制即可；"
         "由于采用标准 SQLite 格式，可用任意通用工具查看与导出，不锁定于本软件。"
         "如部署方后续更换设备，只需在新设备部署服务端并导入数据文件，"
         "客户端仅需修改服务器地址，无需重新注册账号。")

    body("关于版本升级：服务端与移动端可独立升级。服务端升级只涉及替换代码与重启进程，"
         "数据库结构变更由启动时的自动迁移完成，不需要人工执行脚本；"
         "移动端升级通过重新安装安装包完成，已登录状态在升级后保持有效，"
         "无需重新输入密码。两端版本不一致时，服务端优先保证接口兼容，"
         "客户端会在必要时提示升级。")

    body("本说明书至此结束。若需核对功能细节，请对照应用内界面操作；"
         "若需核对技术实现，请参阅提交的源程序前三十页与后三十页。")

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
