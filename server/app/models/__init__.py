"""数据结构与存储（P0 内存实现，P1 起换成 PostgreSQL + 向量库）"""

from .message import (
    ROLE_AGENT,
    ROLE_ELDER,
    ROLE_SYSTEM,
    ConversationStore,
    Message,
    new_id,
    now_iso,
)

__all__ = [
    "ROLE_AGENT",
    "ROLE_ELDER",
    "ROLE_SYSTEM",
    "ConversationStore",
    "Message",
    "new_id",
    "now_iso",
]
