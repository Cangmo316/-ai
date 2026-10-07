"""
比邻AI · 病例病史（医院单据 / 检查报告）

## 这是什么

健康档案分两层：
  · **基础数据**（血压/血糖/体重）——老人自己量的，是**数值**，看趋势
  · **病例病史**（本模块）——医院给的，是**文书**（出院记录、检查报告、化验单）

两者对智能体的意义不同：基础数据回答"最近身体怎么样"，
病例病史回答"医生说过什么、诊断是什么、在吃什么药"——
后者是**背景知识**，聊天里提起来要准确得多。

## 文件怎么存

原件（图片/PDF）存在本机 `data/case_files/`，数据库只存路径与解析出的文字：
  · 二进制不进库：SQLite 存大 BLOB 会让库膨胀、备份变慢
  · 解析出的文字**单独存一列**：智能体只读文字，不需要每次重新解析

## 图片与 PDF 两条路

  · PDF → `app/docs/pdf.py` 抽文本层；**扫描件抽不出**，这时如实告诉老人"拍张照"
  · 图片 → `app/vision/gateway.py` 识图（Qwen-VL）
两条路的产出都落到 `extracted_text`，对上层是同一件事。
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from ..models.message import now_iso

logger = logging.getLogger("bilin.docs.cases")

#: 病历类型（端侧下拉用）
CASE_KINDS = {
    "outpatient": "门诊病历",
    "inpatient": "住院/出院记录",
    "lab": "化验单",
    "imaging": "检查报告（CT/B超/X光）",
    "prescription": "处方/用药单",
    "physical": "体检报告",
    "other": "其它",
}

#: 附件类型
FILE_IMAGE = "image"
FILE_PDF = "pdf"

#: 单个文件上限（与识图的上限保持一致）
MAX_FILE_BYTES = 8 * 1024 * 1024

#: 病历数上限（防滥用；正常老人不会超过几十份）
MAX_CASES = 200


def kind_label(kind: str) -> str:
    return CASE_KINDS.get(str(kind or ""), CASE_KINDS["other"])


@dataclass
class CaseFile:
    """一份附件的元信息"""

    file_id: str
    file_type: str            # image / pdf
    filename: str = ""
    mime: str = ""
    size: int = 0
    path: str = ""            # 相对 data 目录的路径
    extracted_text: str = ""  # 解析/识别出来的文字
    extract_status: str = ""  # ok / scanned / failed
    extract_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "fileId": self.file_id,
            "fileType": self.file_type,
            "filename": self.filename,
            "mime": self.mime,
            "size": self.size,
            "extractStatus": self.extract_status,
            "extractReason": self.extract_reason,
            "hasText": bool(self.extracted_text.strip()),
            # 文字可能很长，列表里只回前 200 字，全文用详情接口取
            "textPreview": self.extracted_text.strip()[:200],
        }


@dataclass
class MedicalCase:
    id: str
    elder_id: str
    kind: str = "other"
    title: str = ""
    hospital: str = ""
    visit_date: str = ""
    diagnosis: str = ""
    summary: str = ""
    note: str = ""
    files: list[CaseFile] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def kind_label(self) -> str:
        return kind_label(self.kind)

    def to_dict(self, *, with_text: bool = False) -> dict:
        data = {
            "id": self.id,
            "elderId": self.elder_id,
            "kind": self.kind,
            "kindLabel": self.kind_label(),
            "title": self.title,
            "hospital": self.hospital,
            "visitDate": self.visit_date,
            "diagnosis": self.diagnosis,
            "summary": self.summary,
            "note": self.note,
            "files": [f.to_dict() for f in self.files],
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }
        if with_text:
            data["files"] = [
                dict(f.to_dict(), extractedText=f.extracted_text) for f in self.files
            ]
        return data

    def prompt_line(self) -> str:
        """给智能体的一句话（见 CaseStore.snapshot_for_prompt）"""
        parts = []
        when = str(self.visit_date or "")[:10]
        if when:
            parts.append(when)
        parts.append(self.kind_label())
        if self.hospital:
            parts.append(self.hospital)
        head = " ".join(parts)
        detail = self.diagnosis or self.summary or self.title
        if detail:
            return head + "：" + detail
        return head


def new_case_id() -> str:
    return "case_" + secrets.token_hex(6)


def new_file_id() -> str:
    return "cf_" + secrets.token_hex(8)


class CaseStore:
    """病例病史（元信息在内存/库；文件字节在磁盘）"""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._cases: dict[str, MedicalCase] = {}
        self.base_dir = base_dir

    # ---------------------------------------------------------------- 文件

    def files_dir(self) -> Path | None:
        if self.base_dir is None:
            return None
        target = Path(self.base_dir) / "case_files"
        target.mkdir(parents=True, exist_ok=True)
        return target

    def save_bytes(self, file_id: str, suffix: str, data: bytes) -> str:
        """把原件落盘，返回相对路径。没有 base_dir（纯内存模式）就只返回空串。"""
        folder = self.files_dir()
        if folder is None:
            return ""
        name = file_id + (suffix or "")
        (folder / name).write_bytes(data)
        return "case_files/" + name

    def read_bytes(self, relative_path: str) -> bytes | None:
        if not relative_path or self.base_dir is None:
            return None
        target = Path(self.base_dir) / relative_path
        try:
            return target.read_bytes()
        except OSError:
            return None

    def delete_file(self, relative_path: str) -> None:
        if not relative_path or self.base_dir is None:
            return
        try:
            (Path(self.base_dir) / relative_path).unlink(missing_ok=True)
        except OSError:
            pass

    # ---------------------------------------------------------------- 读

    def cases_of(self, elder_id: str) -> list[MedicalCase]:
        """某人的病历，**按就诊时间倒序**（最近的在前）"""
        items = [c for c in self._cases.values() if c.elder_id == str(elder_id or "")]
        items.sort(key=lambda c: (c.visit_date or "", c.created_at or ""), reverse=True)
        return items

    def find(self, case_id: str) -> MedicalCase | None:
        return self._cases.get(str(case_id or ""))

    def count(self) -> int:
        return len(self._cases)

    def all_cases(self) -> list[MedicalCase]:
        return list(self._cases.values())

    # ---------------------------------------------------------------- 写

    def create(self, *, elder_id: str, **fields) -> MedicalCase:
        case = MedicalCase(
            id=new_case_id(),
            elder_id=str(elder_id or ""),
            kind=str(fields.get("kind") or "other"),
            title=str(fields.get("title") or ""),
            hospital=str(fields.get("hospital") or ""),
            visit_date=str(fields.get("visit_date") or ""),
            diagnosis=str(fields.get("diagnosis") or ""),
            summary=str(fields.get("summary") or ""),
            note=str(fields.get("note") or ""),
        )
        self._cases[case.id] = case
        return case

    def update(self, case: MedicalCase, **fields) -> MedicalCase:
        for key in ("kind", "title", "hospital", "visit_date", "diagnosis", "summary", "note"):
            if key in fields and fields[key] is not None:
                setattr(case, key, str(fields[key]))
        case.updated_at = now_iso()
        return case

    def add_file(self, case: MedicalCase, file: CaseFile) -> CaseFile:
        case.files.append(file)
        case.updated_at = now_iso()
        return file

    def remove_file(self, case: MedicalCase, file_id: str) -> CaseFile | None:
        for index, item in enumerate(case.files):
            if item.file_id == file_id:
                case.files.pop(index)
                case.updated_at = now_iso()
                return item
        return None

    def remove(self, case_id: str) -> MedicalCase | None:
        return self._cases.pop(str(case_id or ""), None)

    # ---------------------------------------------------------------- 给智能体

    def snapshot_for_prompt(self, elder_id: str, *, limit: int = 5) -> list[str]:
        """给智能体的一句话摘要（最近几份病历）。

        只给**最近几份的标题级信息**，不把整份病历塞进 prompt：
        一份出院记录几千字，塞进去会挤掉当前对话的上下文。
        需要细节时由对话里的话题带回（未来的检索接进来即可）。
        """
        lines = []
        for case in self.cases_of(elder_id)[:limit]:
            line = case.prompt_line()
            if line:
                lines.append(line)
        return lines

    def known_diagnoses(self, elder_id: str) -> list[str]:
        """从病历里归拢出诊断名（去重、保序）"""
        seen: list[str] = []
        for case in self.cases_of(elder_id):
            text = (case.diagnosis or "").strip()
            if not text:
                continue
            for part in text.replace("，", ",").replace("、", ",").split(","):
                item = part.strip()
                if item and item not in seen:
                    seen.append(item)
        return seen
