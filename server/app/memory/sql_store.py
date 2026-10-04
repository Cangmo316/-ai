"""
比邻AI · 记忆的落库实现（写穿透 + 启动加载）

**为什么是"缓存 + 写穿透"而不是"每次读都查库"**：
检索打分（`retrieval.py`）本来就在内存里做，一位老人几十条记忆全量在内存里毫无压力；
把读路径留在内存里，意味着**打分口径与行为同内存版逐字一致**（同一套用例可以跑两个后端，
这就是 `tests/test_memory_backends.py` 在做的事）。写路径同时落库，所以重启不丢。

⚠️ 代价写在明处：多进程/多 worker 同时写会有缓存不一致（见 db.py 末尾的限制说明）。
当前是单进程 uvicorn，够用；要上多 worker 时把读路径也改成直接查库即可，
本文件已经把 SQL 语句集中在这里，改起来是一处的事。
"""

from __future__ import annotations

import json
import logging

from ..storage.db import Database
from .models import MemoryEntry, MemorySettings, MemoryStore

logger = logging.getLogger("bilin.memory")

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS memories (
        id                TEXT PRIMARY KEY,
        elder_id          TEXT NOT NULL,
        kind              TEXT NOT NULL,
        text              TEXT NOT NULL,
        tags              TEXT NOT NULL DEFAULT '[]',
        source            TEXT NOT NULL,
        confidence        REAL NOT NULL,
        review            TEXT NOT NULL,
        visible_to_family {bool} NOT NULL,
        happened_at       TEXT NOT NULL DEFAULT '',
        created_at        TEXT NOT NULL,
        updated_at        TEXT NOT NULL
    )
    """,
    # 列表与检索都按 elder_id 收窄，复核状态也常用来筛
    "CREATE INDEX IF NOT EXISTS idx_memories_elder ON memories (elder_id, review)",
    "CREATE INDEX IF NOT EXISTS idx_memories_elder_family ON memories (elder_id, visible_to_family)",
    """
    CREATE TABLE IF NOT EXISTS memory_settings (
        elder_id      TEXT PRIMARY KEY,
        auto_extract  {bool} NOT NULL,
        consented_at  TEXT NOT NULL DEFAULT '',
        updated_at    TEXT NOT NULL
    )
    """,
]

_COLUMNS = (
    "id, elder_id, kind, text, tags, source, confidence, review, "
    "visible_to_family, happened_at, created_at, updated_at"
)


def _row_to_entry(row: dict) -> MemoryEntry:
    try:
        tags = json.loads(row.get("tags") or "[]")
    except (ValueError, TypeError):
        tags = []
    return MemoryEntry(
        id=row["id"],
        elder_id=row["elder_id"],
        kind=row["kind"],
        text=row["text"],
        tags=[str(tag) for tag in tags] if isinstance(tags, list) else [],
        source=row["source"],
        confidence=float(row["confidence"]),
        review=row["review"],
        visible_to_family=bool(row["visible_to_family"]),
        happened_at=row.get("happened_at") or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class SqlMemoryStore(MemoryStore):
    """与 `MemoryStore` 接口完全一致，只是每次写都落库、启动时把库读回内存"""

    def __init__(self, db: Database) -> None:
        super().__init__()
        self.db = db
        self.db.init_schema(SCHEMA)
        loaded = self._load()
        logger.info("记忆已从库里加载：%d 条 / 设置 %d 份", loaded[0], loaded[1])

    # ---------------------------------------------------------------- 加载

    def _load(self) -> tuple[int, int]:
        for row in self.db.query("SELECT " + _COLUMNS + " FROM memories"):
            entry = _row_to_entry(row)
            self._entries[entry.id] = entry
        for row in self.db.query("SELECT elder_id, auto_extract, consented_at, updated_at FROM memory_settings"):
            self._settings[row["elder_id"]] = MemorySettings(
                elder_id=row["elder_id"],
                auto_extract=bool(row["auto_extract"]),
                consented_at=row.get("consented_at") or "",
                updated_at=row["updated_at"],
            )
        return len(self._entries), len(self._settings)

    # ---------------------------------------------------------------- 写入

    def _insert(self, entry: MemoryEntry) -> None:
        ph = self.db.placeholder
        self.db.execute(
            "INSERT INTO memories (" + _COLUMNS + ") VALUES (" + ", ".join([ph] * 12) + ")",
            (
                entry.id,
                entry.elder_id,
                entry.kind,
                entry.text,
                json.dumps(entry.tags, ensure_ascii=False),
                entry.source,
                entry.confidence,
                entry.review,
                1 if entry.visible_to_family else 0,
                entry.happened_at,
                entry.created_at,
                entry.updated_at,
            ),
        )

    def _update(self, entry: MemoryEntry) -> None:
        ph = self.db.placeholder
        self.db.execute(
            "UPDATE memories SET kind=" + ph + ", text=" + ph + ", tags=" + ph + ", source=" + ph
            + ", confidence=" + ph + ", review=" + ph + ", visible_to_family=" + ph
            + ", happened_at=" + ph + ", updated_at=" + ph + " WHERE id=" + ph,
            (
                entry.kind,
                entry.text,
                json.dumps(entry.tags, ensure_ascii=False),
                entry.source,
                entry.confidence,
                entry.review,
                1 if entry.visible_to_family else 0,
                entry.happened_at,
                entry.updated_at,
                entry.id,
            ),
        )

    def _save_settings(self, settings: MemorySettings) -> None:
        ph = self.db.placeholder
        # ON CONFLICT 的写法 SQLite 与 PostgreSQL 一致，不用分支
        self.db.execute(
            "INSERT INTO memory_settings (elder_id, auto_extract, consented_at, updated_at) "
            "VALUES (" + ph + ", " + ph + ", " + ph + ", " + ph + ") "
            "ON CONFLICT (elder_id) DO UPDATE SET auto_extract=EXCLUDED.auto_extract, "
            "consented_at=EXCLUDED.consented_at, updated_at=EXCLUDED.updated_at",
            (
                settings.elder_id,
                1 if settings.auto_extract else 0,
                settings.consented_at,
                settings.updated_at,
            ),
        )

    # ------------------------------------------------- 覆盖父类的写操作

    def add(self, *args, **kwargs) -> MemoryEntry:
        entry = super().add(*args, **kwargs)
        self._insert(entry)
        return entry

    def update(self, memory_id: str, **kwargs) -> MemoryEntry | None:
        entry = super().update(memory_id, **kwargs)
        if entry:
            self._update(entry)
        return entry

    def review(self, memory_id: str, approve: bool) -> MemoryEntry | None:
        entry = super().review(memory_id, approve)
        if entry:
            self._update(entry)
        return entry

    def delete(self, memory_id: str) -> bool:
        removed = super().delete(memory_id)
        if removed:
            self.db.execute(
                "DELETE FROM memories WHERE id=" + self.db.placeholder, (memory_id,)
            )
        return removed

    def clear(self, elder_id: str) -> int:
        count = super().clear(elder_id)
        if count:
            self.db.execute(
                "DELETE FROM memories WHERE elder_id=" + self.db.placeholder, (elder_id,)
            )
        return count

    def update_settings(self, elder_id: str, auto_extract: bool | None = None) -> MemorySettings:
        settings = super().update_settings(elder_id, auto_extract=auto_extract)
        self._save_settings(settings)
        return settings
