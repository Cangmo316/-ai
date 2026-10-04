"""
比邻AI · 会话的落库实现（写穿透 + 启动加载）

与 `app/memory/sql_store.py` 同一套做法：**读走内存、写同时落库**。
这么做的直接好处是落库前后行为逐字一致——`tests/test_store_persistence.py` 用同一套断言
跑内存版与 SQL 版，只有在"关掉再开"这一步才分叉。

**为什么消息用 JSON 载荷而不是列化**：理由在 `app/storage/json_store.py` 开头写清楚了
（读路径全在 Python、字段带嵌套、端侧契约本来就是 JSON），而记忆表之所以列化，
是因为隐私与审计要按字段查。两张表的差异是刻意的，不是随手选的。

⚠️ 已知限制同 `db.py`：单进程够用；多 worker 同时写会有缓存不一致。
"""

from __future__ import annotations

import logging

from ..storage.db import Database
from ..storage.json_store import JsonPayloadTable
from .message import MAX_MESSAGES, ConversationStore, Message

logger = logging.getLogger("bilin.chat")

TABLE = "conversation_messages"


class SqlConversationStore(ConversationStore):
    """与 `ConversationStore` 接口完全一致，只是每次写都落库、启动时把库读回内存"""

    def __init__(self, db: Database, greeting: str | None = None) -> None:
        # greeting 的默认值只在父类里写一次：这里不重复那句问候语，避免两处不一致
        if greeting is None:
            super().__init__()
        else:
            super().__init__(greeting=greeting)
        self.db = db
        self._table = JsonPayloadTable(db, TABLE, "conversation_id")
        self._table.init_schema()
        conversations, messages = self._load()
        logger.info("会话已从库里加载：%d 个会话 / %d 条消息", conversations, messages)

    # ---------------------------------------------------------------- 加载

    def _load(self) -> tuple[int, int]:
        """把库里的消息按写入顺序装回各个会话桶。

        这里**不补问候语**：问候语在它被创建的那一刻就已经落库了（见 `_bucket`），
        重新补一句会多出一条端侧没见过的消息。
        """
        conversations = 0
        messages = 0
        for row in self._table.load():
            message = Message.from_dict(row["payload"])
            if not message.id:
                logger.warning("库里有一条没有 id 的消息，已跳过（%s）", row["owner"])
                continue
            bucket = self._data.get(row["owner"])
            if bucket is None:
                bucket = []
                self._data[row["owner"]] = bucket
                conversations += 1
            bucket.append(message)
            messages += 1
        return conversations, messages

    # ---------------------------------------------------------------- 写入

    def _bucket(self, conversation_id: str) -> list[Message]:
        """父类是"懒建桶并塞一句问候语"，这里在新建桶时把那句问候语也落库。

        为什么连问候语都要存：它是这个会话的**第一条消息**（老人进对话页看到的第一句话）。
        不落库的话，重启后同一个会话会重新生成一条问候语——id 变了、createdAt 也变了，
        端侧本地缓存里的那条与服务端历史回填的那条就对不上，同一条问候会显示成两条。
        """
        fresh = conversation_id not in self._data
        bucket = super()._bucket(conversation_id)
        if fresh and bucket:
            greeting = bucket[0]
            self._table.save(greeting.id, conversation_id, greeting.to_dict(), greeting.created_at)
        return bucket

    def append(self, conversation_id: str, message: Message) -> Message:
        bucket = self._bucket(conversation_id)
        # 父类会在超上限时裁掉最老的消息；被裁掉的也得从库里删，
        # 否则重启后读回来的条数比内存版多，两端行为分叉
        overflow = max(0, len(bucket) + 1 - MAX_MESSAGES)
        dropped = [item.id for item in bucket[:overflow]] if overflow else []

        result = super().append(conversation_id, message)
        self._table.save(message.id, conversation_id, message.to_dict(), message.created_at)
        for message_id in dropped:
            self._table.delete(message_id)
        return result

    def clear(self, conversation_id: str | None = None) -> None:
        super().clear(conversation_id)
        if conversation_id is None:
            self._table.clear()
        else:
            self._table.delete_owner(conversation_id)
