"""
比邻AI · 病例病史的落库实现

**文件字节不进库**：SQLite 存大 BLOB 会让库文件膨胀、备份变慢，
而原件只是"留档备查"（真正要被智能体读到的是解析出来的文字）。
所以磁盘存原件、库只存路径与文字。

两张表：
  · `medical_cases`  病历本身（就诊日期/医院/诊断/小结）
  · `case_files`     附件（一份病历可以有多张照片 + 一个 PDF）
"""

from __future__ import annotations

import logging

from ..storage.db import Database
from .models import CaseFile, CaseStore, MedicalCase

logger = logging.getLogger("bilin.docs")

SCHEMA_TEMPLATE = [
    """
    CREATE TABLE IF NOT EXISTS medical_cases (
        id          TEXT PRIMARY KEY,
        elder_id    TEXT NOT NULL,
        kind        TEXT NOT NULL DEFAULT 'other',
        title       TEXT NOT NULL DEFAULT '',
        hospital    TEXT NOT NULL DEFAULT '',
        visit_date  TEXT NOT NULL DEFAULT '',
        diagnosis   TEXT NOT NULL DEFAULT '',
        summary     TEXT NOT NULL DEFAULT '',
        note        TEXT NOT NULL DEFAULT '',
        created_at  TEXT NOT NULL DEFAULT '',
        updated_at  TEXT NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_medical_cases_elder "
    "ON medical_cases (elder_id, visit_date)",
    """
    CREATE TABLE IF NOT EXISTS case_files (
        id              TEXT PRIMARY KEY,
        case_id         TEXT NOT NULL,
        file_type       TEXT NOT NULL DEFAULT 'image',
        filename        TEXT NOT NULL DEFAULT '',
        mime            TEXT NOT NULL DEFAULT '',
        size            INTEGER NOT NULL DEFAULT 0,
        path            TEXT NOT NULL DEFAULT '',
        extracted_text  TEXT NOT NULL DEFAULT '',
        extract_status  TEXT NOT NULL DEFAULT '',
        extract_reason  TEXT NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_case_files_case ON case_files (case_id)",
]


class SqlCaseStore(CaseStore):
    """病例病史的落库实现（写穿透 + 启动加载）"""

    def __init__(self, db: Database, base_dir=None) -> None:
        super().__init__(base_dir=base_dir)
        self.db = db

    # ---------------------------------------------------------------- 启动

    def init_schema(self) -> None:
        if not self.db.enabled:
            return
        self.db.init_schema(SCHEMA_TEMPLATE)

    def load(self) -> int:
        if not self.db.enabled:
            return 0
        for row in self.db.query(
            "SELECT id, elder_id, kind, title, hospital, visit_date, diagnosis, summary, note, "
            "created_at, updated_at FROM medical_cases"
        ):
            case = MedicalCase(
                id=row["id"],
                elder_id=row["elder_id"],
                kind=row.get("kind") or "other",
                title=row.get("title") or "",
                hospital=row.get("hospital") or "",
                visit_date=row.get("visit_date") or "",
                diagnosis=row.get("diagnosis") or "",
                summary=row.get("summary") or "",
                note=row.get("note") or "",
                created_at=row.get("created_at") or "",
                updated_at=row.get("updated_at") or "",
            )
            self._cases[case.id] = case

        for row in self.db.query(
            "SELECT id, case_id, file_type, filename, mime, size, path, extracted_text, "
            "extract_status, extract_reason FROM case_files"
        ):
            case = self._cases.get(row["case_id"])
            if case is None:
                # 孤儿附件：主记录没了就跳过，但不删文件（可能还有用）
                continue
            case.files.append(
                CaseFile(
                    file_id=row["id"],
                    file_type=row.get("file_type") or "image",
                    filename=row.get("filename") or "",
                    mime=row.get("mime") or "",
                    size=int(row.get("size") or 0),
                    path=row.get("path") or "",
                    extracted_text=row.get("extracted_text") or "",
                    extract_status=row.get("extract_status") or "",
                    extract_reason=row.get("extract_reason") or "",
                )
            )
        total = self.count()
        if total:
            logger.info("已加载病例 %s 份（附件 %s 个）", total, sum(len(c.files) for c in self._cases.values()))
        return total

    # ---------------------------------------------------------------- 写

    def create(self, *, elder_id: str, **fields) -> MedicalCase:
        case = super().create(elder_id=elder_id, **fields)
        self._insert_case(case)
        return case

    def _insert_case(self, case: MedicalCase) -> None:
        if not self.db.enabled:
            return
        ph = self.db.placeholder
        self.db.execute(
            "INSERT INTO medical_cases (id, elder_id, kind, title, hospital, visit_date, "
            "diagnosis, summary, note, created_at, updated_at) VALUES ("
            + ", ".join([ph] * 11) + ")",
            (
                case.id, case.elder_id, case.kind, case.title, case.hospital,
                case.visit_date, case.diagnosis, case.summary, case.note,
                case.created_at, case.updated_at,
            ),
        )

    def update(self, case: MedicalCase, **fields) -> MedicalCase:
        updated = super().update(case, **fields)
        if self.db.enabled:
            ph = self.db.placeholder
            self.db.execute(
                "UPDATE medical_cases SET kind=" + ph + ", title=" + ph + ", hospital=" + ph
                + ", visit_date=" + ph + ", diagnosis=" + ph + ", summary=" + ph + ", note=" + ph
                + ", updated_at=" + ph + " WHERE id=" + ph,
                (
                    updated.kind, updated.title, updated.hospital, updated.visit_date,
                    updated.diagnosis, updated.summary, updated.note, updated.updated_at,
                    updated.id,
                ),
            )
        return updated

    def add_file(self, case: MedicalCase, file: CaseFile) -> CaseFile:
        added = super().add_file(case, file)
        if self.db.enabled:
            ph = self.db.placeholder
            self.db.execute(
                "INSERT INTO case_files (id, case_id, file_type, filename, mime, size, path, "
                "extracted_text, extract_status, extract_reason) VALUES ("
                + ", ".join([ph] * 10) + ")",
                (
                    added.file_id, case.id, added.file_type, added.filename, added.mime,
                    added.size, added.path, added.extracted_text, added.extract_status,
                    added.extract_reason,
                ),
            )
            # 附件变了也要刷新病历的 updated_at
            self._touch(case.id, case.updated_at)
        return added

    def remove_file(self, case: MedicalCase, file_id: str) -> CaseFile | None:
        removed = super().remove_file(case, file_id)
        if removed is not None:
            if self.db.enabled:
                self.db.execute(
                    "DELETE FROM case_files WHERE id = " + self.db.placeholder,
                    (removed.file_id,),
                )
                self._touch(case.id, case.updated_at)
            # 库里的记录删了，磁盘上的原件也删掉（否则会一直堆积）
            self.delete_file(removed.path)
        return removed

    def remove(self, case_id: str) -> MedicalCase | None:
        removed = super().remove(case_id)
        if removed is not None and self.db.enabled:
            self.db.execute(
                "DELETE FROM case_files WHERE case_id = " + self.db.placeholder, (removed.id,)
            )
            self.db.execute(
                "DELETE FROM medical_cases WHERE id = " + self.db.placeholder, (removed.id,)
            )
            for item in removed.files:
                self.delete_file(item.path)
        return removed

    def _touch(self, case_id: str, moment: str) -> None:
        self.db.execute(
            "UPDATE medical_cases SET updated_at = " + self.db.placeholder + " WHERE id = " + self.db.placeholder,
            (moment, case_id),
        )
