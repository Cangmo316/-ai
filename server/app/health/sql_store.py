"""
比邻AI · 健康档案的落库实现（写穿透 + 启动加载）

沿用仓库既有的「缓存 + 写穿透」范式（见 `app/memory/sql_store.py`）。

**数值为什么存 JSON 而不是拆成一堆列**：各测量项的字段不一样（血压三个数、
体重一个数），拆列会写成一堆可空字段。存 JSON 后加新指标不用改表结构，
代价是不能直接按数值范围查库——但本项目的用法是"取某人的最近几条"
（走内存，索引在 `(elder_id, item_type, measured_at)` 上），够用。
"""

from __future__ import annotations

import json
import logging

from ..storage.db import Database
from .models import HealthRecord, HealthStore

logger = logging.getLogger("bilin.health")

_COLUMNS = "id, elder_id, item_type, values_json, measured_at, note, source, created_at"

SCHEMA_TEMPLATE = [
    """
    CREATE TABLE IF NOT EXISTS health_records (
        id            TEXT PRIMARY KEY,
        elder_id      TEXT NOT NULL,
        item_type     TEXT NOT NULL,
        values_json   TEXT NOT NULL DEFAULT '{}',
        measured_at   TEXT NOT NULL DEFAULT '',
        note          TEXT NOT NULL DEFAULT '',
        source        TEXT NOT NULL DEFAULT 'manual',
        created_at    TEXT NOT NULL DEFAULT ''
    )
    """,
    # 最常用的读法是"某人某项的最近几条"，索引按这个顺序建
    "CREATE INDEX IF NOT EXISTS idx_health_elder_type "
    "ON health_records (elder_id, item_type, measured_at)",
]


class SqlHealthStore(HealthStore):
    """健康记录的落库实现"""

    def __init__(self, db: Database) -> None:
        super().__init__()
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
            "SELECT " + _COLUMNS + " FROM health_records ORDER BY measured_at"
        ):
            try:
                values = json.loads(row.get("values_json") or "{}")
            except (ValueError, TypeError):
                logger.warning("健康记录数值不是合法 JSON，已跳过：%s", row.get("id"))
                continue
            record = HealthRecord(
                id=row["id"],
                elder_id=row["elder_id"],
                item_type=row["item_type"],
                values=values if isinstance(values, dict) else {},
                measured_at=row.get("measured_at") or "",
                note=row.get("note") or "",
                source=row.get("source") or "manual",
                created_at=row.get("created_at") or "",
            )
            self._records.setdefault(record.elder_id, []).append(record)
        total = self.count()
        if total:
            logger.info("已加载健康记录 %s 条", total)
        return total

    # ---------------------------------------------------------------- 写

    def add(self, **kwargs) -> HealthRecord:
        record = super().add(**kwargs)
        if self.db.enabled:
            ph = self.db.placeholder
            self.db.execute(
                "INSERT INTO health_records (" + _COLUMNS + ") VALUES ("
                + ", ".join([ph] * 8) + ")",
                (
                    record.id,
                    record.elder_id,
                    record.item_type,
                    json.dumps(record.values, ensure_ascii=False),
                    record.measured_at,
                    record.note,
                    record.source,
                    record.created_at,
                ),
            )
        return record

    def remove(self, record_id: str) -> bool:
        removed = super().remove(record_id)
        if removed and self.db.enabled:
            self.db.execute(
                "DELETE FROM health_records WHERE id = " + self.db.placeholder,
                (str(record_id or ""),),
            )
        return removed
