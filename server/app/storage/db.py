"""
比邻AI · 落库管道（DB-API 2.0）

**为什么默认是 SQLite**：这台机器上没有 PostgreSQL、没有 Docker，也不该为了跑通一个
原型去装一个数据库服务；而 Python 标准库自带 `sqlite3`，写入即持久、单文件、零安装。
`DATABASE_URL` 换成 `postgresql://...` 就是同一套 SQL 走 PG——**方言差异只在本文件里**：

| 项 | SQLite | PostgreSQL |
|---|---|---|
| 占位符 | `?` | `%s` |
| 自增 | `INTEGER PRIMARY KEY AUTOINCREMENT` | `SERIAL PRIMARY KEY` |
| 布尔 | 整数 0/1 | `BOOLEAN` |
| 建表幂等 | `CREATE TABLE IF NOT EXISTS` | 同 |
| 驱动 | 标准库 | `pip install psycopg[binary]` |

**为什么不做 ORM**：这张库表结构简单到用不上 ORM；而且仓库的测试哲学是零依赖，
sqlite3 能进 CI、psycopg 不一定能。真要上 ORM，等表结构复杂到需要迁移工具再说。

⚠️ 已知限制（写在明处，别当没看见）：下面的 store 采用**写穿透 + 启动加载**的缓存策略，
适合"一个进程一个实例"的当前部署。**多 worker / 多实例**同时写同一张表时，
各自的内存缓存会不一致——那时要把读路径也落到 SQL（`select` 直接查，不走缓存）。
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger("bilin.storage")

MEMORY_URL = "memory://"


class DatabaseError(RuntimeError):
    """落库层自己抛的错，带人话说明（启动阶段就要能看懂哪里配错了）"""


class Database:
    """一条连接的轻量封装（SQLite 单进程够用；PG 下连接池留给真正需要的时候）"""

    def __init__(self, url: str, base_dir: Path | None = None) -> None:
        self.url = (url or "").strip() or MEMORY_URL
        self.dialect = self._dialect_of(self.url)
        self.path: Path | None = None
        self._lock = threading.Lock()
        self._conn = None

        if self.dialect == "sqlite":
            raw = self.url[len("sqlite://") :]
            if raw in (":memory:", "/:memory:", ""):
                self.path = None  # 内存库：进程内有效，重启即空（测试用）
            else:
                candidate = Path(raw.lstrip("/"))
                if not candidate.is_absolute():
                    candidate = (base_dir or Path.cwd()) / candidate
                self.path = candidate

    # ---------------------------------------------------------------- 解析

    @staticmethod
    def _dialect_of(url: str) -> str:
        lowered = url.lower()
        if lowered.startswith(MEMORY_URL) or lowered in ("memory", "none"):
            return "none"
        if lowered.startswith("sqlite"):
            return "sqlite"
        if lowered.startswith(("postgresql", "postgres")):
            return "postgresql"
        raise DatabaseError(
            "不认识的 DATABASE_URL："
            + url
            + "（支持 memory:// / sqlite:///路径 / postgresql://...）"
        )

    @property
    def placeholder(self) -> str:
        return "%s" if self.dialect == "postgresql" else "?"

    @property
    def enabled(self) -> bool:
        return self.dialect != "none"

    def describe(self) -> str:
        """给 /healthz 与启动日志用的一句话"""
        if self.dialect == "none":
            return "memory（未落库，重启即清空）"
        if self.dialect == "sqlite":
            where = str(self.path) if self.path else "sqlite 内存库"
            return "sqlite · " + where
        return "postgresql"

    # ---------------------------------------------------------------- 连接

    def connect(self):
        if not self.enabled:
            raise DatabaseError("DATABASE_URL=memory:// 时没有连接可用")
        if self._conn is not None:
            return self._conn
        if self.dialect == "sqlite":
            if self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            target = str(self.path) if self.path is not None else ":memory:"
            self._conn = sqlite3.connect(target, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            # WAL：读写不互相阻塞；原型阶段足够（真要并发再换连接池）
            if self.path is not None:
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        else:
            try:
                import psycopg  # type: ignore
            except ImportError as exc:  # pragma: no cover - 取决于部署环境
                raise DatabaseError(
                    "DATABASE_URL 指向 PostgreSQL，但没装驱动：pip install \"psycopg[binary]\""
                ) from exc
            self._conn = psycopg.connect(self.url)
        return self._conn

    def init_schema(self, statements: list[str]) -> None:
        """建表（幂等）。语句按方言在 SQL 里用 {ph} / {bool} / {autoincrement} 占位"""
        if not self.enabled:
            return
        conn = self.connect()
        with self._lock:
            for raw in statements:
                sql = (
                    raw.replace("{autoincrement}", "SERIAL PRIMARY KEY" if self.dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT")
                    .replace("{bool}", "BOOLEAN" if self.dialect == "postgresql" else "INTEGER")
                )
                conn.execute(sql)
            conn.commit()

    # ---------------------------------------------------------------- 读写

    def execute(self, sql: str, params: tuple = ()) -> None:
        conn = self.connect()
        with self._lock:
            conn.execute(sql, params)
            conn.commit()

    def executemany(self, sql: str, rows: list[tuple]) -> None:
        if not rows:
            return
        conn = self.connect()
        with self._lock:
            conn.executemany(sql, rows)
            conn.commit()

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        conn = self.connect()
        with self._lock:
            cursor = conn.execute(sql, params)
            columns = [item[0] for item in cursor.description or []]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None


def open_database(url: str, base_dir: Path | None = None) -> Database:
    """建库并把方言错误在**启动阶段**就报出来（不要等到第一次写记忆才炸）"""
    database = Database(url, base_dir=base_dir)
    if database.enabled:
        database.connect()
        logger.info("落库：%s", database.describe())
    else:
        logger.info("落库：%s", database.describe())
    return database
