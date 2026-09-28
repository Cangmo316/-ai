"""
比邻AI · 消息模型与会话存储

**P0 刻意用内存**：现在的目标是打通「端 → 服务 → 模型 → 端」这条链路，
数据库选型（PostgreSQL + 向量库）会跟计划引擎、记忆系统一起定，提前上 ORM 只会返工。
接口按将来落库的形态设计（`history` / `append` / 分页上限），换实现时上层不用改。

字段与端侧 `uni-app/stores/chat.js` 的消息结构对齐，落在同一个契约上。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

ROLE_ELDER = "elder"
ROLE_AGENT = "agent"
ROLE_SYSTEM = "system"

TYPE_TEXT = "text"
TYPE_VOICE = "voice"
TYPE_STICKER = "sticker"
TYPE_CARD = "card"

# 单会话内存里最多保留多少条（P0 只是联调，不追求长期留存）
MAX_MESSAGES = 200


def now_iso() -> str:
    """带本地时区的 ISO8601，端侧 `Date.parse` 直接可用。"""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return prefix + "_" + uuid.uuid4().hex[:12]


@dataclass
class Message:
    id: str
    role: str
    type: str = TYPE_TEXT
    text: str = ""
    sticker: str = ""
    card: dict | None = None
    seconds: int = 0
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        payload = {
            "id": self.id,
            "role": self.role,
            "type": self.type,
            "createdAt": self.created_at,
        }
        if self.text:
            payload["text"] = self.text
        if self.sticker:
            payload["sticker"] = self.sticker
        if self.card:
            payload["card"] = self.card
        if self.seconds:
            payload["seconds"] = self.seconds
        return payload


class ConversationStore:
    """按会话 id 分桶的消息列表。

    并发说明：FastAPI 单事件循环 + 这里的操作都是同步的 append/切片，
    中间没有 await，因此不会被打断；将来换数据库时再引入事务。
    """

    def __init__(self, greeting: str = "妈 我上班去了\n有事就发消息") -> None:
        self._data: dict[str, list[Message]] = {}
        self._greeting = greeting

    def _bucket(self, conversation_id: str) -> list[Message]:
        bucket = self._data.get(conversation_id)
        if bucket is None:
            bucket = []
            if self._greeting:
                bucket.append(
                    Message(id=new_id("a"), role=ROLE_AGENT, type=TYPE_TEXT, text=self._greeting)
                )
            self._data[conversation_id] = bucket
        return bucket

    def append(self, conversation_id: str, message: Message) -> Message:
        bucket = self._bucket(conversation_id)
        bucket.append(message)
        if len(bucket) > MAX_MESSAGES:
            del bucket[: len(bucket) - MAX_MESSAGES]
        return message

    def history(self, conversation_id: str, limit: int = 50) -> list[Message]:
        bucket = self._bucket(conversation_id)
        if limit <= 0:
            return list(bucket)
        return list(bucket[-limit:])

    def clear(self, conversation_id: str | None = None) -> None:
        if conversation_id is None:
            self._data.clear()
        else:
            self._data.pop(conversation_id, None)
