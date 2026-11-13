"""生成四人版《合作开发协议》——用于软著登记的著作权归属证明。

## 为什么做成留空的手写版

协议要**手写签名**才有效，而姓名、身份证号、联系方式这些必须与身份证一致，
程序填进去反而容易错。所以：
  · 已知的固定内容（软件全称、版本号、条款）由程序排好版，保证与申请表逐字一致；
  · 需要本人填写的信息（姓名/身份证号/电话/地址/分工/日期）全部留横线，
    打印后手填、手签。

## 版式要点

  · A4、宋体小四、1.5 倍行距——够宽松，手写填空不挤
  · 「著作权归属」「登记申请」两条加粗强调——这两条是审查重点
  · 签署区做成两列四格，四个人各签各的，不会签串
  · 页脚有页码，避免多页散开

用法：
    python docs/copyright/gen-agreement.py [--out 输出目录]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

SOFTWARE_FULL = "比邻AI智慧康养陪伴软件"
SOFTWARE_VERSION = "V1.0"

PARTIES = ["甲方", "乙方", "丙方", "丁方"]
BLANK = "________________"


def set_font(run, size: float, name: str = "宋体", bold: bool = False) -> None:
    run.font.size = Pt(size)
    run.font.name = name
    run.font.bold = bold
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


def setup(doc: Document) -> None:
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.5)
    section.bottom_margin = Cm(2.2)
    section.left_margin = Cm(2.8)
    section.right_margin = Cm(2.2)

    style = doc.styles["Normal"]
    style.font.name = "宋体"
    style.font.size = Pt(12)
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    fmt = style.paragraph_format
    fmt.space_before = Pt(0)
    fmt.space_after = Pt(4)
    fmt.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE

    # 页脚页码
    footer = section.footer
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    for tag, attrs in (("w:fldChar", {"w:fldCharType": "begin"}), ("w:instrText", None),
                       ("w:fldChar", {"w:fldCharType": "end"})):
        el = OxmlElement(tag)
        for k, v in (attrs or {}).items():
            el.set(qn(k), v)
        if tag == "w:instrText":
            el.set(qn("xml:space"), "preserve")
            el.text = " PAGE "
        run._r.append(el)
    set_font(run, 9)


def para(doc: Document, text: str, *, size: float = 12, bold: bool = False,
         first_indent: bool = False, space_after: float = 4,
         align=WD_ALIGN_PARAGRAPH.JUSTIFY) -> None:
    p = doc.add_paragraph()
    p.alignment = align
    p.paragraph_format.space_after = Pt(space_after)
    if first_indent:
        p.paragraph_format.first_line_indent = Pt(24)
    run = p.add_run(text)
    set_font(run, size, bold=bold)


def clause(doc: Document, title: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(3)
    run = p.add_run(title)
    set_font(run, 12, "黑体", bold=True)


def build(out_dir: Path) -> Path:
    doc = Document()
    setup(doc)

    # 标题
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(2)
    set_font(p.add_run("合作开发协议"), 20, "黑体", bold=True)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(14)
    set_font(p.add_run("（计算机软件著作权归属约定）"), 10.5)

    # 当事人：每人两行。每行宽度都按可用宽度（16cm）配过，
    # 下划线太长会折行，把「联系电话」挤到下一行，很难看。
    for i, role in enumerate(PARTIES):
        gap = 10 if i == len(PARTIES) - 1 else 6
        # 身份证号留 18 个下划线：18 位数字手写需要约 4.5cm，太短写不下
        para(doc, f"{role}（开发者）：{'_' * 8}　　身份证号：{'_' * 18}",
             space_after=2)
        para(doc, f"联系电话：{'_' * 10}　　通讯地址：{'_' * 24}",
             space_after=gap)

    para(doc, "鉴于甲、乙、丙、丁四方共同开发本协议第一条所列软件，为明确该软件的"
              "著作权归属及相关权利义务，经四方协商一致，达成如下协议：", first_indent=True)

    # 第一条
    clause(doc, "第一条　标的软件")
    para(doc, f"软件全称：{SOFTWARE_FULL}", first_indent=True, space_after=2)
    para(doc, f"版本号：{SOFTWARE_VERSION}", first_indent=True, space_after=2)
    para(doc, "开发起止时间：______年____月____日　至　______年____月____日",
         first_indent=True)
    para(doc, "开发完成日期：______年____月____日", first_indent=True)

    # 第二条
    clause(doc, "第二条　开发分工")
    para(doc, "各方就本软件的具体分工如下（按实际参与情况据实填写）：", first_indent=True)
    para(doc, "甲方负责：____________________________________________________________",
         space_after=2)
    para(doc, "乙方负责：____________________________________________________________",
         space_after=2)
    para(doc, "丙方负责：____________________________________________________________",
         space_after=2)
    para(doc, "丁方负责：____________________________________________________________")

    # 第三条
    clause(doc, "第三条　著作权归属")
    para(doc, "1. 本软件著作权由甲、乙、丙、丁四方共同享有，四方均为著作权人。",
         first_indent=True, space_after=2)
    para(doc, "2. 四方约定为共同共有，不区分份额。", first_indent=True, space_after=2)
    para(doc, "（如为按份共有，请在下方填写比例；不填写即视为共同共有、不分份额）",
         first_indent=True, space_after=2)
    para(doc, "　　甲方 ______%　乙方 ______%　丙方 ______%　丁方 ______%",
         space_after=2)
    para(doc, "3. 各方确认，本软件为四方独立开发完成，不侵犯任何第三方的知识产权。",
         first_indent=True)

    # 第四条
    clause(doc, "第四条　登记申请")
    para(doc, "1. 四方一致同意，由" + BLANK + "（姓名）作为申请人，就本软件向"
              "中国版权保护中心办理计算机软件著作权登记，其余三方对此无异议。",
         first_indent=True, space_after=2)
    para(doc, "2. 其余三方同意，登记证书中不另行载明其署名，但不影响其依本协议"
              "享有的著作权。", first_indent=True, space_after=2)
    para(doc, "3. 登记完成后，各方均有权查阅、复制登记证书。", first_indent=True)

    # 第五条
    clause(doc, "第五条　权利行使与收益分配")
    para(doc, "1. 任何一方转让本软件著作权，须经其余三方书面同意。",
         first_indent=True, space_after=2)
    para(doc, "2. 许可他人使用、以本软件出资或设定质押，须经四方协商一致。",
         first_indent=True, space_after=2)
    para(doc, "3. 因许可或转让所得收益，按第三条约定分配；约定不明时由四方平均分配。",
         first_indent=True, space_after=2)
    para(doc, "4. 任一方发现第三方侵犯本软件著作权时，应及时通知其余各方，"
              "四方共同或经协商由一方主张权利，所需费用与所得赔偿按上述比例承担与分配。",
         first_indent=True)

    # 第六条
    clause(doc, "第六条　争议解决")
    para(doc, "因本协议引起的或与本协议有关的争议，四方应友好协商解决；"
              "协商不成的，任何一方均可向" + BLANK + "人民法院提起诉讼。",
         first_indent=True)

    # 第七条
    clause(doc, "第七条　其他")
    para(doc, "1. 本协议未尽事宜，四方可另行签订补充协议，补充协议与本协议具有同等效力。",
         first_indent=True, space_after=2)
    para(doc, "2. 本协议自四方签字之日起生效。", first_indent=True, space_after=2)
    para(doc, "3. 本协议一式四份，四方各执一份，具有同等法律效力。",
         first_indent=True)

    # 签署页独立成页：两列四格的表格若被跨页拆开，会出现"丙方丁方单独漂到下一页、
    # 前面整页空白"的难看局面，也可能让人怀疑漏签。
    doc.add_page_break()
    para(doc, "（以下无正文，为签署页）", space_after=10,
         align=WD_ALIGN_PARAGRAPH.CENTER)

    # 签署区：两列四格
    table = doc.add_table(rows=2, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    labels = [("甲方（签字）：" + BLANK, "日期：______年____月____日"),
              ("乙方（签字）：" + BLANK, "日期：______年____月____日"),
              ("丙方（签字）：" + BLANK, "日期：______年____月____日"),
              ("丁方（签字）：" + BLANK, "日期：______年____月____日")]
    for row in table.rows:
        tr_pr = row._tr.get_or_add_trPr()
        cant = OxmlElement("w:cantSplit")
        tr_pr.append(cant)
    for idx, (line1, line2) in enumerate(labels):
        cell = table.cell(idx // 2, idx % 2)
        cell.width = Cm(8.0)
        cell.text = ""
        p1 = cell.paragraphs[0]
        p1.paragraph_format.space_after = Pt(6)
        set_font(p1.add_run(line1), 11)
        p2 = cell.add_paragraph()
        p2.paragraph_format.space_after = Pt(14)
        set_font(p2.add_run(line2), 11)

    path = out_dir / "05-合作开发协议（四人）.docx"
    doc.save(str(path))
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=r"E:\ppt\比邻AI.ppt\软著材料-终版")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = build(out_dir)
    print("  已生成 %s" % path.name)


if __name__ == "__main__":
    main()
