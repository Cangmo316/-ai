"""
比邻AI · 幂等（`clientMsgId`）

场景很具体：老人发了一句话，网络抖了一下，端侧没收到 `done` 就重试。
如果服务端不管这个字段，老人会收到**两条一模一样的回复**（还多花一次模型调用）。

做法（P1 内存实现，接口按落库形态设计）：

    begin(conversation_id, client_msg_id)
      ├─ 第一次见  → ("new", None)              正常生成
      ├─ 正在生成  → ("in_flight", None)        端侧收到 409「这句话我正在回，等我一下」
      └─ 已经生成  → ("done", 缓存结果)          直接回放缓存，**不再调用模型**

为什么重试要复用同一个 clientMsgId：端侧 `stores/chat.js` 的 retry 传的就是上一条本地消息 id，
所以重试天然命中缓存——这正是我们要的"重试不重复"。

⚠️ 缓存只保留最近若干条（`MAX_ENTRIES`），并且只对**成功产出内容**的请求生效：
如果第一轮就失败了（模型鉴权错、超时），不写缓存，端侧重试要能真的重新生成。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ..models.message import now_iso

logger = logging.getLogger("bilin.idempotency")

STATE_NEW = "new"
STATE_IN_FLIGHT = "in_flight"
STATE_DONE = "done"

# 只留最近这么多条（内存版；换成 Redis 后按 TTL 过期）
MAX_ENTRIES = 200
# 缓存有效期：超过就当作新请求（避免"半小时后重试拿到旧回复"这种怪事）
TTL_MINUTES = 30


def _now() -> datetime:
    """带时区的本地时间。

    ⚠️ `now_iso()` 写出来的是**带时区**的 ISO 串，比较时必须用同样带时区的 now，
    否则 `naive` 和 `aware` 相减直接 TypeError（这个坑踩过一次，全部幂等用例都会炸）。
    """
    return datetime.now(timezone.utc).astimezone()


def _parse(stamp: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        # 兼容老数据：没带时区的按本地时间理解
        parsed = parsed.replace(tzinfo=_now().tzinfo)
    return parsed


@dataclass
class IdempotencyRecord:
    conversation_id: str
    client_msg_id: str
    state: str = STATE_IN_FLIGHT
    text: str = ""
    stickers: list[str] = field(default_factory=list)
    assistant_msg_id: str = ""
    created_at: str = field(default_factory=now_iso)
    finished_at: str = ""

    @property
    def age_seconds(self) -> float:
        stamp = _parse(self.created_at)
        if stamp is None:
            return 0.0
        return (_now() - stamp).total_seconds()

    def to_dict(self) -> dict:
        return {
            "conversationId": self.conversation_id,
            "clientMsgId": self.client_msg_id,
            "state": self.state,
            "text": self.text,
            "stickers": list(self.stickers),
            "assistantMsgId": self.assistant_msg_id,
            "createdAt": self.created_at,
            "finishedAt": self.finished_at,
        }


class IdempotencyStore:
    def __init__(self, max_entries: int = MAX_ENTRIES, ttl_minutes: int = TTL_MINUTES) -> None:
        self._records: dict[str, IdempotencyRecord] = {}
        self._order: list[str] = []
        self.max_entries = max_entries
        self.ttl_minutes = ttl_minutes

    @staticmethod
    def key_for(conversation_id: str, client_msg_id: str) -> str:
        return str(conversation_id or "-") + "|" + str(client_msg_id or "-")

    def begin(self, conversation_id: str, client_msg_id: str) -> tuple[str, IdempotencyRecord | None]:
        """开始一次请求。返回 (状态, 已完成时的缓存记录)。"""
        if not client_msg_id:
            # 端侧没给 id（老版本端 / 手工 curl）：不做幂等，按新请求处理
            return STATE_NEW, None

        record = self._records.get(self.key_for(conversation_id, client_msg_id))
        if record is None:
            self._put(
                IdempotencyRecord(conversation_id=conversation_id, client_msg_id=client_msg_id)
            )
            return STATE_NEW, None

        if record.state == STATE_DONE:
            logger.info("命中幂等缓存，直接回放：%s", client_msg_id)
            return STATE_DONE, record

        if record.age_seconds > self.ttl_minutes * 60:
            # 超时未完成的记录当新请求（可能是上次进程挂了）
            self._put(
                IdempotencyRecord(conversation_id=conversation_id, client_msg_id=client_msg_id)
            )
            return STATE_NEW, None

        return STATE_IN_FLIGHT, record

    def complete(
        self,
        conversation_id: str,
        client_msg_id: str,
        text: str,
        stickers: list[str] | None = None,
        assistant_msg_id: str = "",
    ) -> IdempotencyRecord | None:
        """产出成功后落缓存。失败路径不要调这个（让端侧能真的重新生成）。"""
        if not client_msg_id:
            return None
        record = self._records.get(self.key_for(conversation_id, client_msg_id))
        if record is None:
            record = IdempotencyRecord(conversation_id=conversation_id, client_msg_id=client_msg_id)
            self._put(record)
        record.state = STATE_DONE
        record.text = text
        record.stickers = list(stickers or [])
        record.assistant_msg_id = assistant_msg_id
        record.finished_at = now_iso()
        return record

    def get(self, conversation_id: str, client_msg_id: str) -> IdempotencyRecord | None:
        return self._records.get(self.key_for(conversation_id, client_msg_id))

    def release(self, conversation_id: str, client_msg_id: str) -> bool:
        """放开一条**未完成**的记录（生成失败 / 被中断 / 空产出时调用）。

        没有这一步会出大问题：第一次生成失败后记录一直挂在 `in_flight`，
        端侧拿同一个 clientMsgId 重试就会一直收到"这句话我正在回，等我一下"——
        老人点了重试却永远等不到回复，比重复回复更糟。
        已经 DONE 的记录不动（那才是真正该回放的）。
        """
        if not client_msg_id:
            return False
        key = self.key_for(conversation_id, client_msg_id)
        record = self._records.get(key)
        if record is None or record.state == STATE_DONE:
            return False
        self._records.pop(key, None)
        if key in self._order:
            self._order.remove(key)
        return True

    def all(self) -> list[IdempotencyRecord]:
        return list(self._records.values())

    def counts(self) -> dict:
        states: dict[str, int] = {}
        for record in self._records.values():
            states[record.state] = states.get(record.state, 0) + 1
        return {"total": len(self._records), **states}

    def clear(self) -> None:
        self._records.clear()
        self._order.clear()

    # ---------------------------------------------------------------- 内部

    def _put(self, record: IdempotencyRecord) -> None:
        key = self.key_for(record.conversation_id, record.client_msg_id)
        if key not in self._records:
            self._order.append(key)
        self._records[key] = record
        self._purge()
        return None

    def _purge(self) -> None:
        while len(self._order) > self.max_entries:
            oldest = self._order.pop(0)
            self._records.pop(oldest, None)
        # 顺手清掉过期记录（只在有写入时做，成本极低）
        cutoff = _now() - timedelta(minutes=self.ttl_minutes)
        for key in list(self._records.keys()):
            record = self._records[key]
            if record.state == STATE_DONE:
                continue
            stamp = _parse(record.created_at)
            if stamp is not None and stamp < cutoff:
                self._records.pop(key, None)
                if key in self._order:
                    self._order.remove(key)
