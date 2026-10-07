"""
比邻AI · 会话与消息的落库实现（写穿透 + 启动加载）

沿用仓库既有的「缓存 + 写穿透」范式（见 `app/memory/sql_store.py` 的说明）：
读走内存、写同时落库，所以重启不丢、读路径也不受数据库延迟影响。

**已读用游标（`read_cursors` 一行一人一会话）而不是"每条消息一个已读标记"**：
N 条消息 N 个标记会随消息量线性膨胀，而游标天然支持"批量已读"，
未读数由「不是自己发的 + 晚于游标」算出来（见 models.py 的 unread_count）。
"""

from __future__ import annotations

import logging

from ..storage.db import Database
from .models import (
    KIND_AI,
    KIND_FAMILY,
    STATUS_ACCEPTED,
    Binding,
    Conversation,
    Message,
    MessagingStore,
    kind_of,
    participants_of,
)

logger = logging.getLogger("bilin.messaging")

SCHEMA_TEMPLATE = [
    """
    CREATE TABLE IF NOT EXISTS conversations (
        id          TEXT PRIMARY KEY,
        kind        TEXT NOT NULL,
        owner_id    TEXT NOT NULL DEFAULT '',
        created_at  TEXT NOT NULL DEFAULT '',
        updated_at  TEXT NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_conversations_owner ON conversations (owner_id)",
    """
    CREATE TABLE IF NOT EXISTS messages (
        id               TEXT PRIMARY KEY,
        conversation_id  TEXT NOT NULL,
        sender_id        TEXT NOT NULL DEFAULT '',
        sender_name      TEXT NOT NULL DEFAULT '',
        sender_role      TEXT NOT NULL DEFAULT 'elder',
        text             TEXT NOT NULL DEFAULT '',
        created_at       TEXT NOT NULL DEFAULT '',
        recalled_at      TEXT NOT NULL DEFAULT '',
        quote_id         TEXT NOT NULL DEFAULT ''
    )
    """,
    # 拉历史与算未读都按会话收窄，并且都要按时间排
    "CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages (conversation_id, created_at)",
    """
    CREATE TABLE IF NOT EXISTS read_cursors (
        conversation_id  TEXT NOT NULL,
        account_id       TEXT NOT NULL,
        read_at          TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (conversation_id, account_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS account_bindings (
        account_id       TEXT NOT NULL,
        peer_id          TEXT NOT NULL,
        peer_number      TEXT NOT NULL DEFAULT '',
        peer_name        TEXT NOT NULL DEFAULT '',
        conversation_id  TEXT NOT NULL DEFAULT '',
        created_at       TEXT NOT NULL DEFAULT '',
        status           TEXT NOT NULL DEFAULT 'accepted',
        responded_at     TEXT NOT NULL DEFAULT '',
        initiator        TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (account_id, peer_id)
    )
    """,
]


class SqlMessagingStore(MessagingStore):
    """会话 / 消息 / 已读 / 绑定的落库实现"""

    def __init__(self, db: Database) -> None:
        super().__init__()
        self.db = db

    # ---------------------------------------------------------------- 启动

    def init_schema(self) -> None:
        if not self.db.enabled:
            return
        self.db.init_schema(SCHEMA_TEMPLATE)
        self._migrate()

    def _migrate(self) -> None:
        """
        给**已经存在**的库补新列。

        为什么需要：`CREATE TABLE IF NOT EXISTS` 对已存在的表**什么都不做**，
        所以给 `messages` 加 `recalled_at` / `quote_id` 时，老库不会自动多这两列，
        随后 `load()` 里的 SELECT 会直接报 "no such column"。
        这里先查一遍现有列，缺哪列补哪列（幂等，可重复执行）。
        """
        wanted = (
            ("messages", "recalled_at", "TEXT NOT NULL DEFAULT ''"),
            ("messages", "quote_id", "TEXT NOT NULL DEFAULT ''"),
            # 绑定要对方同意：老库补 status（默认 accepted，老数据继续算已绑定）
            ("account_bindings", "status", "TEXT NOT NULL DEFAULT 'accepted'"),
            ("account_bindings", "responded_at", "TEXT NOT NULL DEFAULT ''"),
            # 谁发起的邀请：没有它，发起方会把自己的邀请当成待办（见 Binding.initiator）
            ("account_bindings", "initiator", "TEXT NOT NULL DEFAULT ''"),
        )
        for table, column, decl in wanted:
            try:
                rows = self.db.query(f"PRAGMA table_info({table})")
            except Exception:  # noqa: BLE001 —— 非 SQLite 方言没有 PRAGMA，退回 information_schema
                try:
                    rows = self.db.query(
                        "SELECT column_name AS name FROM information_schema.columns "
                        "WHERE table_name = " + self.db.placeholder,
                        (table,),
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("读不到 %s 的列信息，跳过迁移", table)
                    continue
            existing = {str(r.get("name") or r.get("column_name") or "") for r in rows}
            if column in existing:
                continue
            try:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
                logger.info("数据库迁移：%s 增加列 %s", table, column)
            except Exception:  # noqa: BLE001 —— 并发/已存在都不该拦住启动
                logger.exception("给 %s 加列 %s 失败（可能已存在）", table, column)

    def load(self) -> int:
        """把库里的会话、消息、已读游标、绑定读进内存"""
        if not self.db.enabled:
            return 0

        for row in self.db.query(
            "SELECT id, kind, owner_id, created_at, updated_at FROM conversations"
        ):
            conversation = Conversation(
                id=row["id"],
                kind=row["kind"] or kind_of(row["id"]),
                owner_id=row.get("owner_id") or "",
                created_at=row.get("created_at") or "",
                updated_at=row.get("updated_at") or "",
            )
            self._conversations[conversation.id] = conversation
            self._messages.setdefault(conversation.id, [])

        for row in self.db.query(
            "SELECT id, conversation_id, sender_id, sender_name, sender_role, text, created_at, "
            "recalled_at, quote_id "
            "FROM messages ORDER BY created_at, id"
        ):
            message = Message(
                id=row["id"],
                conversation_id=row["conversation_id"],
                sender_id=row.get("sender_id") or "",
                sender_name=row.get("sender_name") or "",
                sender_role=row.get("sender_role") or "elder",
                text=row.get("text") or "",
                created_at=row.get("created_at") or "",
                recalled_at=row.get("recalled_at") or "",
                quote_id=row.get("quote_id") or "",
            )
            self._messages.setdefault(message.conversation_id, []).append(message)

        for row in self.db.query("SELECT conversation_id, account_id, read_at FROM read_cursors"):
            self._read_cursor[(row["conversation_id"], row["account_id"])] = row.get("read_at") or ""

        for row in self.db.query(
            "SELECT account_id, peer_id, peer_number, peer_name, conversation_id, created_at, "
            "status, responded_at, initiator "
            "FROM account_bindings"
        ):
            binding = Binding(
                id="b_" + row["account_id"] + "_" + row["peer_id"],
                account_id=row["account_id"],
                peer_id=row["peer_id"],
                peer_number=row.get("peer_number") or "",
                peer_name=row.get("peer_name") or "",
                conversation_id=row.get("conversation_id") or "",
                created_at=row.get("created_at") or "",
                # 老数据没有 status（迁移补的是 accepted），继续算已绑定
                status=row.get("status") or "accepted",
                responded_at=row.get("responded_at") or "",
                initiator=row.get("initiator") or "",
            )
            self._bindings.setdefault(binding.account_id, []).append(binding)

        total = len(self._conversations)
        if total:
            logger.info(
                "已加载会话 %s 条、消息 %s 条、绑定 %s 条",
                total,
                sum(len(v) for v in self._messages.values()),
                sum(len(v) for v in self._bindings.values()),
            )
        return total

    # ---------------------------------------------------------------- 会话

    def _insert_conversation(self, conversation: Conversation) -> None:
        if not self.db.enabled:
            return
        ph = self.db.placeholder
        self.db.execute(
            "INSERT INTO conversations (id, kind, owner_id, created_at, updated_at) VALUES ("
            + ", ".join([ph] * 5) + ") ON CONFLICT (id) DO NOTHING",
            (
                conversation.id,
                conversation.kind,
                conversation.owner_id,
                conversation.created_at,
                conversation.updated_at,
            ),
        )

    def ensure_ai_conversation(self, account_id: str) -> Conversation:
        conversation = super().ensure_ai_conversation(account_id)
        self._insert_conversation(conversation)
        return conversation

    def ensure_family_conversation(self, account_a: str, account_b: str) -> Conversation:
        conversation = super().ensure_family_conversation(account_a, account_b)
        self._insert_conversation(conversation)
        return conversation

    # ---------------------------------------------------------------- 消息

    def add_message(self, conversation_id: str, **kwargs) -> Message:
        message = super().add_message(conversation_id, **kwargs)
        if self.db.enabled:
            ph = self.db.placeholder
            self.db.execute(
                "INSERT INTO messages (id, conversation_id, sender_id, sender_name, sender_role, text, created_at, recalled_at, quote_id) "
                "VALUES (" + ", ".join([ph] * 9) + ")",
                (
                    message.id,
                    message.conversation_id,
                    message.sender_id,
                    message.sender_name,
                    message.sender_role,
                    message.text,
                    message.created_at,
                    message.recalled_at,
                    message.quote_id,
                ),
            )
            # 会话的 updated_at 跟着最新消息走（列表按它排序）
            self.db.execute(
                "UPDATE conversations SET updated_at = " + ph + " WHERE id = " + ph,
                (message.created_at, message.conversation_id),
            )
        return message

    def recall_message(self, message_id: str, at: str) -> bool:
        """把一条消息标记为已撤回（保留正文，只加时间戳，见 models.Message）。"""
        changed = super().recall_message(message_id, at)
        if not changed:
            return False
        if self.db.enabled:
            ph = self.db.placeholder
            self.db.execute(
                "UPDATE messages SET recalled_at = " + ph + " WHERE id = " + ph,
                (at, message_id),
            )
        return True

    def delete_message(self, message_id: str) -> bool:
        """物理删除一条消息（只给"删除"用；撤回走 recall_message）。"""
        changed = super().delete_message(message_id)
        if not changed:
            return False
        if self.db.enabled:
            ph = self.db.placeholder
            self.db.execute("DELETE FROM messages WHERE id = " + ph, (message_id,))
        return True

    # ---------------------------------------------------------------- 已读

    def mark_read(self, conversation_id: str, account_id: str, at: str = "") -> int:
        # ⚠️ 必须把 `at` 透传下去：内存实现用它当已读边界，
        # 漏传会退化成"真实时间"，于是注入时钟的测试与手动 tick 都不准
        newly = super().mark_read(conversation_id, account_id, at)
        cursor = self.read_cursor(conversation_id, account_id)
        if self.db.enabled and cursor:
            ph = self.db.placeholder
            self.db.execute(
                "INSERT INTO read_cursors (conversation_id, account_id, read_at) VALUES ("
                + ", ".join([ph] * 3) + ") "
                "ON CONFLICT (conversation_id, account_id) DO UPDATE SET read_at=EXCLUDED.read_at",
                (str(conversation_id or ""), str(account_id or ""), cursor),
            )
        return newly

    # ---------------------------------------------------------------- 绑定

    def bind(self, **kwargs) -> Binding:
        binding = super().bind(**kwargs)
        self._save_binding(binding)
        # 反向那条也落库
        reverse = self.binding_with(binding.peer_id, binding.account_id)
        if reverse is not None:
            self._save_binding(reverse)
        return binding

    def patch_reverse_binding(self, account_id: str, peer_id: str, *, peer_number: str, peer_name: str) -> None:
        super().patch_reverse_binding(account_id, peer_id, peer_number=peer_number, peer_name=peer_name)
        reverse = self.binding_with(peer_id, account_id)
        if reverse is not None:
            self._save_binding(reverse)

    def _save_binding(self, binding: Binding) -> None:
        if not self.db.enabled:
            return
        ph = self.db.placeholder
        self.db.execute(
            "INSERT INTO account_bindings "
            "(account_id, peer_id, peer_number, peer_name, conversation_id, created_at, status, responded_at, initiator) VALUES ("
            + ", ".join([ph] * 9) + ") "
            "ON CONFLICT (account_id, peer_id) DO UPDATE SET "
            "peer_number=EXCLUDED.peer_number, peer_name=EXCLUDED.peer_name, "
            "conversation_id=EXCLUDED.conversation_id, "
            "status=EXCLUDED.status, responded_at=EXCLUDED.responded_at, initiator=EXCLUDED.initiator",
            (
                binding.account_id,
                binding.peer_id,
                binding.peer_number,
                binding.peer_name,
                binding.conversation_id,
                binding.created_at,
                binding.status,
                binding.responded_at,
                binding.initiator,
            ),
        )

    def respond_invite(self, account_id: str, peer_id: str, accept: bool) -> Binding | None:
        # 会话开通与状态改动都在基类里做（含"同意时才开通"），这里只负责落库
        binding = super().respond_invite(account_id, peer_id, accept)
        if binding is None:
            return None

        me = str(account_id or "")
        peer = str(peer_id or "")
        # 两边状态都要落库：否则重启后一边已同意、一边还在待同意
        for owner, other in ((me, peer), (peer, me)):
            item = self.any_binding_with(owner, other)
            if item is not None:
                self._save_binding(item)
        return binding

    def unbind(self, account_id: str, peer_id: str) -> bool:
        removed = super().unbind(account_id, peer_id)
        if removed and self.db.enabled:
            ph = self.db.placeholder
            # 双向一起删：只删一边会让对方还留着一个"已解绑"的家人
            self.db.execute(
                "DELETE FROM account_bindings WHERE (account_id = " + ph + " AND peer_id = " + ph + ") "
                "OR (account_id = " + ph + " AND peer_id = " + ph + ")",
                (account_id, peer_id, peer_id, account_id),
            )
        return removed
