"""数据结构与存储（内存实现 + `DATABASE_URL` 打开时的落库实现）"""

from .message import (
    ROLE_AGENT,
    ROLE_ELDER,
    ROLE_SYSTEM,
    ConversationStore,
    Message,
    new_id,
    now_iso,
)
from .sql_store import SqlConversationStore

__all__ = [
    "ROLE_AGENT",
    "ROLE_ELDER",
    "ROLE_SYSTEM",
    "ConversationStore",
    "Message",
    "SqlConversationStore",
    "new_id",
    "now_iso",
]