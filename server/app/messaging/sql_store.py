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
        created_at       TEXT NOT NULL DEFAULT ''
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
            "SELECT id, conversation_id, sender_id, sender_name, sender_role, text, created_at "
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
            )
            self._messages.setdefault(message.conversation_id, []).append(message)

        for row in self.db.query("SELECT conversation_id, account_id, read_at FROM read_cursors"):
            self._read_cursor[(row["conversation_id"], row["account_id"])] = row.get("read_at") or ""

        for row in self.db.query(
            "SELECT account_id, peer_id, peer_number, peer_name, conversation_id, created_at "
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
                "INSERT INTO messages (id, conversation_id, sender_id, sender_name, sender_role, text, created_at) "
                "VALUES (" + ", ".join([ph] * 7) + ")",
                (
                    message.id,
                    message.conversation_id,
                    message.sender_id,
                    message.sender_name,
                    message.sender_role,
                    message.text,
                    message.created_at,
                ),
            )
            # 会话的 updated_at 跟着最新消息走（列表按它排序）
            self.db.execute(
                "UPDATE conversations SET updated_at = " + ph + " WHERE id = " + ph,
                (message.created_at, message.conversation_id),
            )
        return message

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
            "(account_id, peer_id, peer_number, peer_name, conversation_id, created_at) VALUES ("
            + ", ".join([ph] * 6) + ") "
            "ON CONFLICT (account_id, peer_id) DO UPDATE SET "
            "peer_number=EXCLUDED.peer_number, peer_name=EXCLUDED.peer_name, "
            "conversation_id=EXCLUDED.conversation_id",
            (
                binding.account_id,
                binding.peer_id,
                binding.peer_number,
                binding.peer_name,
                binding.conversation_id,
                binding.created_at,
            ),
        )

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
