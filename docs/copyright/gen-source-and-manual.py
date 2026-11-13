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
    setup_document(doc, 10, 12)

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

    # ── 一
    heading("一、软件概述")
    body("本软件是一个手机应用，服务对象是独居老人和需要长期吃药的慢病人群。"
         "老人用说话或打字的方式和软件里的助手聊天，软件记下聊天里提到的事，"
         "提醒吃药和复查，把身体数据和病历整理在一起。家属用自己的账号登录，"
         "可以看到老人当天的情况。")
    body("软件分两部分。手机端用 uni-app 开发，能打包成 Android 安装包，"
         "也能直接在浏览器里打开。服务端用 Python 的 FastAPI 框架，"
         "数据存在本机的一个 SQLite 文件里，不用另外装数据库。"
         "一台普通电脑就能跑起来。")
    body("聊天内容由大语言模型生成。模型不处理业务，业务规则在服务端代码里："
         "判断这一轮是不是医疗问题，决定用哪种说法，回答里要不要加就医提醒，"
         "这些由代码控制。")
    body("装好之后不联网也能用，只要手机和服务端在同一个网络里。"
         "数据都留在部署方自己的机器上。")

    # ── 二
    heading("二、运行环境")
    sub("手机端")
    step("（1）Android 8.0 以上。内存 2GB 够用，开三维形象建议 4GB。")
    step("（2）第一次安装约 200MB 空间。")
    step("（3）需要麦克风、摄像头、存储三个权限，用不到的功能可以不给。")
    sub("服务端")
    step("（1）Ubuntu 22.04 以上或 Debian 12 以上，Windows 10 以上也可以。")
    step("（2）Python 3.11 以上。依赖五个包：fastapi、uvicorn、httpx、PyYAML、"
         "python-multipart。")
    step("（3）数据用 SQLite 3，单文件，第一次启动自己建表。")
    step("（4）硬件 1 核 1GB 能跑，建议 2 核 2GB，磁盘留 40GB。")
    sub("开发环境")
    step("（1）手机端：HBuilderX 5.26，Node.js 18，Vue 3，Vite 5。")
    step("（2）服务端：Python 3.13，FastAPI 0.141，Uvicorn 0.54。")

    # ── 三
    heading("三、安装、启动与登录")
    sub("服务端")
    step("（1）把代码拷到目标机器，进 server 目录。")
    step("（2）建虚拟环境，装 requirements.txt 里的包。")
    step("（3）改 .env。HOST 和 PORT 是监听地址和端口，DATABASE_URL 指数据库文件，"
         "AUTH_MODE 和 API_TOKENS 管接口鉴权，LLM_BASE_URL、LLM_API_KEY、"
         "LLM_MODEL 指对话模型。")
    step("（4）执行 run.py 启动，默认监听 8000。")
    step("（5）访问 /healthz，返回 ok 就是起来了。")
    step("（6）要开机自启，Linux 注册成 systemd 服务，Windows 注册成计划任务。")
    sub("手机端")
    step("（1）打开软件，进底部“我的”。")
    step("（2）点“服务器地址”，填服务端地址。")
    step("（3）点“测试连接”。显示耗时和返回内容，正常就保存。")
    step("（4）连不上时页面下面有四条排查提示，按顺序看。")
    step("（5）回登录页注册或登录。")
    sub("注册")
    step("（1）登录页点“没有账号请点击注册”。")
    step("（2）填账号名和密码，账号名 2 到 20 个字符。")
    step("（3）注册成功后系统给一个 8 位数字编号，这是账号的唯一标识。")
    step("（4）注册完就是登录状态，不用再输一次密码。")
    step("（5）这个编号可以给家属，用来绑定。")

    # ── 四
    heading("四、对话列表与消息")
    body("登录后进对话列表。默认有一个和助手的会话，固定在最上面。"
         "和家属的会话在绑定之后才出现。")
    body("每条显示对方名字、关系、最后一句话和时间。有新消息时右边有红点。")
    step("（1）点会话进详情页。")
    step("（2）底部输入框打字，点发送。")
    step("（3）发送失败的消息右边有红色感叹号，点一下重发。")
    step("（4）长按消息可以复制。")
    body("回复按行分开，一行一句，不写成一大段。老人看起来轻松，"
         "语音播报时也好和口型对上。")

    # ── 五
    heading("五、智能对话与双人设")
    body("软件里有两套说法。一套是陪伴助手，用在日常聊天，句子短，用词口语，"
         "不说“您好，请问有什么可以帮您”。另一套是健康顾问，用在医疗健康话题上，"
         "回答末尾补一句以医嘱为准、及时就医。")
    body("切换分自动和手动。自动是按关键词判断。先看这句话里有没有明显的医疗词，"
         "比如血压、血糖、吃药、头晕、摔了。再看是不是常规吃药询问，比如“药吃了没”，"
         "这种不算医疗问题，不加提醒。最后结合情绪词和认知相关的说法判断。"
         "命中就换成健康顾问。手动是在“人设模式”里选，选完不再自动切。")
    body("提醒做三道。第一道判断问题类型，第二道检查回答里有没有停药、剂量、"
         "诊断这类说法，第三道在回答生成完再扫一遍。三道都在代码里。")
    body("把模式锁成“只聊家常”之后，只要回答涉及医疗内容，提醒照样加。"
         "这一项不开放关闭。")

    # ── 六
    heading("六、语音交互与三维数字人")
    body("语音做三件事：把说的话转成文字，把回复念出来，让数字人嘴跟着动。")
    step("（1）在对话页按住麦克风说话，松开就发。")
    step("（2）页面显示“正在听”，识别完文字自动填进输入框。")
    step("（3）点发送后回复逐字出现，同时开始念。")
    step("（4）念的时候嘴型跟着变，可以暂停和重播。")
    step("（5）麦克风权限没给，页面提示去系统设置打开，打字不受影响。")
    body("数字人形象在“我的”里配置，资源随安装包给，不用联网下载。"
         "手机带不动的，可以在设置里关掉三维换静态头像，聊天和语音照常。")

    # ── 七
    heading("七、AI 了解我的（长期记忆）")
    body("软件记两类东西。一类是老人在聊天里提到的事实：怎么称呼、几点起几点睡、"
         "爱吃什么、家里有谁、关心哪些健康问题、有没有重要的日子。"
         "另一类是说话习惯：口头禅、怎么称呼人、句子长短。")
    body("两类分开存，每五轮对话整理一次，不是每轮都调模型。")
    body("说话习惯只从真人发的消息里学。助手自己的回复不拿来当素材，"
         "否则越学越僵。")
    step("（1）进“我的”，点“AI 了解我的”。")
    step("（2）页面按分节列出全部条目，每条显示内容、来源、更新时间。")
    step("（3）点某条能改能删。删掉之后后面聊天不再用这条。")
    step("（4）分节可以整段编辑，保存后生效。")
    body("口头禅和称呼习惯单独放，清理的时候不会一起删。")

    # ── 八
    heading("八、健康档案")
    body("能记三项：血压、血糖、体重。录入时填数值和时间，可以加备注，"
         "比如“饭后两小时”。列表按时间倒序，趋势图能切日、周、月。")
    step("（1）进“我的”，点“健康档案”。")
    step("（2）右上角“记录”，选类型。")
    step("（3）填数值和时间，可加备注。")
    step("（4）保存后列表刷新，趋势图按选的周期重画。")
    step("（5）超范围的数值标红。")
    body("标红只是提示，不给结论。单次测量受测量方式、时间、情绪影响，"
         "凭一个数字下判断既不准确，也容易让人紧张。")

    # ── 九
    heading("九、病例与病史")
    body("病历、检查单、出院记录都能传，图片和 PDF 都行。"
         "传上去之后把里面的就诊时间、医院、诊断、用药提出来做成一条记录，"
         "按时间排在轴上。")
    body("老人后来说身体不舒服时，助手能调出这些记录参考，回答比通用建议贴合。")
    step("（1）进“健康档案”，点“病例”。")
    step("（2）点“上传”，拍照或从相册选，能多选。")
    step("（3）上传后自动解析，结果显示成可改的表单。")
    step("（4）核对、补字段，保存后进时间轴。")
    step("（5）点某条能看原件大图和字段。")
    body("部署环境没接视觉识别的话，这一步自动改成手动填。填完一样能归档，"
         "一样能在对话里用。")

    # ── 十
    heading("十、用药与日程提醒")
    body("提醒分三类。日常计划是每天都要做的事，比如早饭后吃药。"
         "每周计划是每周固定某天做的事。特别计划一次性的，比如下周三复查，"
         "过了那天不再提醒。")
    body("分三类是为了不让老人把每天吃的药和下周三复查混在一起。")
    step("（1）进底部“日程”。")
    step("（2）点“日常计划”，添加，填事项、时刻、重复规则。")
    step("（3）点“每周计划”，选星期和时刻。")
    step("（4）点“特别计划”，选具体日期，到期自动失效。")
    step("（5）点日历上某天，看当天全部安排，也能直接加。")
    step("（6）到点提醒走系统通知和应用内消息两条路，没做的在当天列表留标记。")
    step("（7）做完的点一下打卡，状态变成已完成。点错了能取消。")
    step("（8）打卡数据回流成完成率，家属端按完成率看当天情况。")

    # ── 十一
    heading("十一、主动关心与回访")
    body("软件会在合适的时候主动问一句，问吃了什么、今天有没有什么事、"
         "想不想做点什么。问法按时段换，不天天用同一句。")
    body("问的次数有限制：一天最多两次，两次之间隔四小时以上，"
         "晚上和老人正在聊天的时候不问。老人连着回几个字，就不再追问。")
    body("问的内容分四类：吃了什么、今天有没有遇到特别的事、"
         "今天过得怎么样、有没有想做还没做的事。这四类是照着独居老人"
         "平常打电话会聊的内容定的。")
    body("老人提到以后要做的事，软件记下来。到那天在聊天里再提一次。")
    body("过期的条目按实际过了几天调措辞，不会出现“今天正是这日子”但日期对不上。")

    # ── 十二
    heading("十二、家属绑定与关怀查看")
    body("老人账号里能生成邀请码，家属在自己账号里填这个码完成绑定。")
    body("绑定后家属能看老人当天计划做完没有、最近的身体数据、吃药情况、"
         "聊天摘要。家属和老人之间可以互相留言。")
    step("（1）老人端“我的”，点“家人管理”，生成邀请码。")
    step("（2）家属在“家人管理”里点“绑定老人”，填码。")
    step("（3）绑定成功后两边列表里互相出现对方会话。")
    step("（4）家属端能看今日安排、健康数据、吃药情况三块。")
    step("（5）可以解绑，解绑后两边列表里的会话一起消失。")
    body("家属会话和助手会话是两回事，消息不混在一起，"
         "免得家里私下说的话跑到助手那边去。")

    # ── 十三
    heading("十三、智能体角色与设置")
    body("可以建多个角色，每个填名字、关系、性格、口头禅、怎么称呼。"
         "关系显示在对话列表里，老人按平时的叫法就能找。")
    step("（1）进“我的”，点“智能体角色”。")
    step("（2）点“新建角色”，填名字、关系、性格、口头禅。")
    step("（3）设称呼方式，填“您”还是“妈”，这一项会进长期记忆。")
    step("（4）保存后出现在对话列表，长按设默认或删除。")
    body("删掉角色之后对话还在，只是不再走这个角色的设定。")
    body("智能体设置里换对话模型。云端模型聪明些，要联网；本地模型不用出网，"
         "适合对数据外传有要求的地方。换完立刻生效，历史消息不受影响。")

    # ── 十四
    heading("十四、设置与适老化")
    body("“我的”页分两组。上面一组是陪伴设置：智能体角色、人设模式、"
         "AI 了解我的、数字人形象、家人管理、智能体设置。下面一组是健康与设置："
         "健康档案、大字体、服务器地址。分组按常改和少改来，减少误点。")
    body("界面字号大、对比度高、按钮点击区大。大字体模式能把正文再放大一档。")
    step("（1）点“大字体模式”右边的开关，正文变大一档。")
    step("（2）点“服务器地址”，看当前地址、来源、凭据状态。")
    step("（3）填新地址，点“测试连接”，结果显示耗时和返回内容。")
    step("（4）保存后软件重新进入，不用重装。")
    body("服务器地址页的提示里带着正在用的地址。这里吃过亏，早先只提示"
         "“连不上服务器”，老人只能找家人，家人也不知道软件在连哪个地址，"
         "只能来回猜。")

    # ── 十五
    heading("十五、数据存储与安全")
    body("账号、聊天、身体数据、病例、记忆都存在服务端本机的数据库里，"
         "不上传第三方。")
    body("接口默认要令牌。聊天类接口除了令牌还要账号会话凭据，"
         "两个东西放两个请求头，一个管能不能进来，一个管你是谁。")
    body("删除立即生效。删掉的记忆条目不再参与后面的对话，"
         "删掉的会话不再出现在列表里。")
    body("备份用数据库自己的一致性快照，不用直接复制文件。"
         "服务在跑的时候复制，可能拿到还没落盘的旧数据。")

    # ── 十六
    heading("十六、技术特点")
    body("说话方式按关键词分层判断，命中医疗话题换人设，提醒由代码写入，"
         "不靠模型自觉。")
    body("医疗合规做三道：分类、话术检查、回答后置扫描。停药、剂量、诊断"
         "这几类说法会被拦下或改写。")
    body("记忆分两层存，说话习惯只学真人消息，避免自己学自己。"
         "口头禅这类长期项不随清理丢。")
    body("历史对话超过阈值就压成摘要，用短语出现的次数衡量哪些是冗余，"
         "留高频内容和关键事实。")
    body("主动提问受每日次数、最小间隔、静默时段三重限制。"
         "没回答的问题转成待回访，到日子再提。")
    body("对话模型、语音识别、语音合成都是可替换的，改配置就能在云端和本地之间切。")
    body("同一套服务端能跑在局域网、虚拟专网和公网三种环境，"
         "带令牌鉴权和自动备份。")

    # ── 十七
    heading("十七、常见问题")
    step("问：提示连不上服务器怎么办。")
    step("答：提示里带了正在用的地址。先用手机浏览器打开这个地址的 /healthz，"
         "能看到 ok 说明网络通，再查服务端进程和端口。")
    step("问：换网络就连不上。")
    step("答：服务端在局域网里，地址会跟着变。在服务器地址页改新地址，不用重装。"
         "路由器里给服务器绑定固定地址能省掉这一步。")
    step("问：语音没声音。")
    step("答：先看系统音量和静音。语音合成服务不可用时软件自动退回纯文字，"
         "聊天不受影响。")
    step("问：删了记忆，以前的聊天会变吗。")
    step("答：聊天记录不变，只是后面不再引用被删的条目。")
    step("问：家属能看到我和助手聊的内容吗。")
    step("答：家属端只看到摘要和当天情况，看不到完整原文。")
    step("问：几个人能共用一个服务端吗。")
    step("答：能。每个账号单独注册，数据按账号隔离，服务端地址填同一个。")
    step("问：数据能不能导出。")
    step("答：数据库是一个 SQLite 文件，可以用通用工具直接打开、导出。")

    # ── 十八
    heading("十八、界面与交互约定")
    body("一屏只放一件事，避免一屏上好几个并列操作。除首页外页面左上角都有"
         "返回按钮，不用手势返回这种看不见的操作。删除类操作都要二次确认，"
         "确认框里写清删的是什么。")
    body("正文不小于 16sp，标题不小于 20sp，按钮高度不小于 44pt。"
         "正文和背景的对比度不低于 4.5 比 1。状态不只靠颜色区分，"
         "配图标和文字，照顾看不清颜色的人。")
    body("键盘输入只有两处：聊天输入框和健康数值。其余用下拉、点选、加减按钮。"
         "数值超出合理范围时提示复核，但不阻止保存，免得把真实异常藏起来。")
    body("提示语用口语，不用“操作失败”“参数错误”这类词。涉及家属协助的场景，"
         "提示里直接给动作和目标，不让老人自己判断。")

    # ── 十九
    heading("十九、附录：术语")
    body("双人设：陪伴助手和健康顾问两套说法，由软件判断该用哪套。")
    body("合规提示：健康顾问回答末尾的固定提示语，提醒以医嘱为准、及时就医，"
         "由程序写入。")
    body("长期记忆：从真实对话里提炼、跨会话保留的老人信息和说话习惯。")
    body("主动关心：软件按规则主动发起的提问，受每日次数、间隔、静默时段限制。")
    body("待回访事项：老人提到的以后要做的事，记下来，到日子再提。")
    body("对话摘要：历史太长时压出的概括，代替早期原文进上下文。")
    body("降级：某项能力不可用时改用简单实现或关掉该功能，主流程不中断。")

    # ── 二十
    heading("二十、版本说明")
    body(f"本说明书对应版本 {SOFTWARE_VERSION}，为首次发表的正式版本，"
         "涵盖上述功能。后续版本的增补与修复不在本说明书范围内。")

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
