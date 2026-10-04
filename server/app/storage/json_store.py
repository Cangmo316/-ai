"""
比邻AI · 通用的「JSON 载荷表」（会话 / 计划 / 打卡三类实体共用）

**为什么这些实体用 JSON 载荷，而不像记忆那样一个字段一列**

`memories` 表是**列化**的（见 `app/memory/sql_store.py`），因为它的读路径确实要按字段查：
按 `elder_id` 收窄、按 `review` 筛待复核、按 `visible_to_family` 判"家属能不能看到"；
而且"哪条记忆谁能看到"属于隐私与审计范畴，字段摆在明面上才审得清、才查得出来。

会话消息、康养计划、打卡记录不一样，理由有三条，都是当前代码的事实：

1. **它们的读路径全在 Python 里**。会话按 id 取一个列表、计划按 elder_id 过滤再按时间排、
   打卡按 `(plan_item_id, date)` 找一条——现有实现（`MemoryStore` 那一族的同款做法）
   都是"全量读进内存再在 Python 里筛"。SQL 层只承担"把上次的数据原样搬回来"，
   没有任何"用 SQL 查"的需求，列化换不到任何东西
2. **字段多、还带嵌套**。`CarePlan` 15 个字段里有 `items` / `sources` / `history`
   三个嵌套结构；列化就要连嵌套一起拆成多张表，读回来还得重新拼装，
   而拼装出来只有 Python 一个消费者
3. **端侧契约本来就是 JSON**。`to_dict()` 早就定义了线上形状（驼峰、basis 子对象）；
   直接存它，落库前后同一条数据只有一种形状，不会出现"库里一套字段名、接口另一套"的双份映射
   ——那种双份映射正是最容易出现"改了 A 忘了改 B"的地方

**代价写在明处**：这些表没法用 SQL 直接筛（比如"查所有 status=active 的计划"要读出来在
Python 里筛）。真需要按字段查的那天，把某一张表单独列化即可——本文件按表隔离，
列化一张不影响其它表；`memories` 就是先例，两种做法在同一个库里并存没问题。

⚠️ 与 `sql_store.py` 相同的限制：读走内存缓存、写穿透到库，适合单进程部署；
多 worker 同时写会有缓存不一致（见 `db.py` 末尾）。
"""

from __future__ import annotations

import json
import logging

from .db import Database

logger = logging.getLogger("bilin.storage")


def _decode(raw) -> dict | None:
    """载荷解析：只丢这一条并留 warning，一条坏数据不该让整个服务起不来"""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("落库载荷不是合法 JSON，已跳过该行：%s", str(raw)[:80])
        return None
    return data if isinstance(data, dict) else None


class JsonPayloadTable:
    """一张「id + 归属列 + JSON 载荷」的表。

    表结构（`id` 是实体的业务 id，归属列是它的查询收窄维度）：

        id            TEXT PRIMARY KEY   -- 实体 id，重复保存 = 覆盖同一条
        <owner>       TEXT NOT NULL      -- conversation_id 或 elder_id
        payload       TEXT NOT NULL      -- to_dict() 的 JSON
        created_at    TEXT NOT NULL      -- 实体自己的创建时间（排序不靠它，见下）
        seq           INTEGER NOT NULL   -- 写入顺序（本类自己维护）

    **为什么多一个 `seq` 列**：`created_at` 只精确到秒（`now_iso()` 的 timespec="seconds"），
    同一秒里追加的多条消息在库里时间戳完全一样，"按 created_at 排"是不稳定的——
    重启后消息顺序会乱，而消息顺序是会话的语义本身（老人看到的对话就错了）。
    所以顺序由一个单调递增的写入序号负责，时间戳只作为数据保留。

    ⚠️ 同一张表在一个进程里只该有一个 `JsonPayloadTable` 实例：写入序号是进程内自增的，
    两个实例各自维护会写出重号（顺序就不确定了）。这与整个"写穿透 + 内存缓存"的前提一致
    ——单进程一个实例（见 `db.py` 末尾的限制说明）。
    """

    def __init__(self, db: Database, table: str, owner_column: str) -> None:
        self.db = db
        self.table = table
        self.owner_column = owner_column
        # 写入序号：进程内自增；构造时从库里已有的最大值续上（不靠时间戳排顺序）
        self._next_seq = 1

    # ---------------------------------------------------------------- 建表

    def schema_statements(self) -> list[str]:
        return [
            f"""
            CREATE TABLE IF NOT EXISTS {self.table} (
                id                   TEXT PRIMARY KEY,
                {self.owner_column}  TEXT NOT NULL,
                payload              TEXT NOT NULL,
                created_at           TEXT NOT NULL DEFAULT '',
                seq                  INTEGER NOT NULL DEFAULT 0
            )
            """,
            # 按归属列取数是最常用的读法（一个会话的消息 / 一位老人的计划）
            f"CREATE INDEX IF NOT EXISTS idx_{self.table}_{self.owner_column} "
            f"ON {self.table} ({self.owner_column}, seq)",
        ]

    def init_schema(self) -> None:
        """建表（幂等）并把写入序号接到库里已有的最大值之后"""
        if not self.db.enabled:
            return
        self.db.init_schema(self.schema_statements())
        rows = self.db.query("SELECT COALESCE(MAX(seq), 0) AS top FROM " + self.table)
        self._next_seq = int(rows[0]["top"] or 0) + 1 if rows else 1

    # ---------------------------------------------------------------- 读

    def load(self, owner: str | None = None) -> list[dict]:
        """按写入顺序读出载荷。

        返回 `[{"id", "owner", "payload"(已解析成 dict), "created_at"}, ...]`；
        解析失败的行走 `_decode()` 的 warning 分支被跳过。
        """
        sql = "SELECT id, " + self.owner_column + " AS owner, payload, created_at FROM " + self.table
        params: tuple = ()
        if owner is not None:
            sql += " WHERE " + self.owner_column + " = " + self.db.placeholder
            params = (owner,)
        sql += " ORDER BY seq"

        rows: list[dict] = []
        for row in self.db.query(sql, params):
            payload = _decode(row.get("payload"))
            if payload is None:
                continue
            rows.append(
                {
                    "id": row["id"],
                    "owner": row["owner"],
                    "payload": payload,
                    "created_at": row.get("created_at") or "",
                }
            )
        return rows

    def count(self, owner: str | None = None) -> int:
        sql = "SELECT COUNT(*) AS total FROM " + self.table
        params: tuple = ()
        if owner is not None:
            sql += " WHERE " + self.owner_column + " = " + self.db.placeholder
            params = (owner,)
        rows = self.db.query(sql, params)
        return int(rows[0]["total"]) if rows else 0

    # ---------------------------------------------------------------- 写

    def save(self, row_id: str, owner: str, payload: dict, created_at: str = "") -> None:
        """插入或覆盖（同一个 `id` 视为同一条记录，改一次状态不会在库里多出一行）。

        `ON CONFLICT` 的写法 SQLite 与 PostgreSQL 一致，不用方言分支。
        冲突时**刻意不更新 `seq`**：一条计划从 draft 改成 active 只是状态变化，
        它在"写入顺序"里的位置不该跳到最末（否则按顺序加载出来的历史顺序会漂移）。
        """
        ph = self.db.placeholder
        seq = self._next_seq
        self._next_seq += 1
        self.db.execute(
            "INSERT INTO " + self.table + " (id, " + self.owner_column + ", payload, created_at, seq) "
            "VALUES (" + ", ".join([ph] * 5) + ") "
            "ON CONFLICT (id) DO UPDATE SET "
            + self.owner_column + "=EXCLUDED." + self.owner_column + ", "
            "payload=EXCLUDED.payload, created_at=EXCLUDED.created_at",
            (row_id, owner, json.dumps(payload, ensure_ascii=False), created_at, seq),
        )

    def delete(self, row_id: str) -> None:
        """删一条（调用方自己在内存里知道它存在与否，这里不回传行数）"""
        self.db.execute(
            "DELETE FROM " + self.table + " WHERE id=" + self.db.placeholder, (row_id,)
        )

    def delete_owner(self, owner: str) -> None:
        """删一个归属下的全部（取消打卡、清空某个会话）"""
        self.db.execute(
            "DELETE FROM " + self.table + " WHERE " + self.owner_column + "=" + self.db.placeholder,
            (owner,),
        )

    def clear(self) -> None:
        self.db.execute("DELETE FROM " + self.table)
