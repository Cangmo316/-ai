"""
比邻AI · 关心记录与回访的数据模型

## 两个概念要分清

**CareAsk（主动问的一次）**
  "今天下午 3 点问了他'今天有啥特别的事没有'，他答'孙子来了'"。
  用来做频率控制（一天问了没、问了几次），也是对话的补充记录。

**FollowUp（答应/约定了的事，到期要回访）**
  "他说下周二去复查" → 记下来，**下周二主动问一句"今天去复查了吧"**。
  这是需求里"在后续的标记日期里再次提出来"的核心 ——
  老人真正感到被在乎，往往不是因为被问了，而是因为**被记住**。

## 为什么回访要单独存

回访有"到期日"和"是否已提过"，与 CareAsk 的生命周期完全不同：
  CareAsk 当天就结束；FollowUp 可能躺一个星期才到期。
混在一张表里会让两边的查询都变得别扭。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# ── 关心问题的类别 ──────────────────────────────────────────────
TOPIC_EAT = "eat"        # 吃了什么
TOPIC_EVENT = "event"    # 有没有遇到特别的事
TOPIC_DAY = "day"        # 今天打算做什么
TOPIC_WISH = "wish"      # 有没有想做的事
TOPIC_FOLLOWUP = "followup"  # 到期的回访（不是新问题，是"再提一次"）

# ── 回访状态 ────────────────────────────────────────────────────
FOLLOWUP_PENDING = "pending"   # 还没到期
FOLLOWUP_DUE = "due"           # 到期了，该提
FOLLOWUP_DONE = "done"         # 已经提过
FOLLOWUP_DROP = "drop"         # 老人说不用了 / 已经取消


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class CareAsk:
    """主动关心的一次提问。"""

    id: str
    elder_id: str
    #: 哪天问的（YYYY-MM-DD），频率控制按它数
    day: str
    topic: str
    question: str
    asked_at: str = field(default_factory=now_iso)
    #: 老人回了什么（他下次说话时补上）
    answer: str = ""
    answered_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "elderId": self.elder_id,
            "day": self.day,
            "topic": self.topic,
            "question": self.question,
            "askedAt": self.asked_at,
            "answer": self.answer,
            "answeredAt": self.answered_at,
        }

    @staticmethod
    def from_dict(data: dict) -> "CareAsk":
        return CareAsk(
            id=str(data.get("id") or ""),
            elder_id=str(data.get("elderId") or ""),
            day=str(data.get("day") or ""),
            topic=str(data.get("topic") or ""),
            question=str(data.get("question") or ""),
            asked_at=str(data.get("askedAt") or ""),
            answer=str(data.get("answer") or ""),
            answered_at=str(data.get("answeredAt") or ""),
        )


@dataclass
class FollowUp:
    """约定了的事，到期要回访。

    例："下周二去复查" → due_day=2026-10-14, text=去复查, raw=下周二去复查
    """

    id: str
    elder_id: str
    #: 什么时候该提（YYYY-MM-DD）
    due_day: str
    #: 约定的内容（"去复查"）
    text: str
    #: 老人原话片段（回访时用来复述，避免张冠李戴）
    raw: str = ""
    status: str = FOLLOWUP_PENDING
    created_at: str = field(default_factory=now_iso)
    #: 提过的时间
    asked_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "elderId": self.elder_id,
            "dueDay": self.due_day,
            "text": self.text,
            "raw": self.raw,
            "status": self.status,
            "createdAt": self.created_at,
            "askedAt": self.asked_at,
        }

    @staticmethod
    def from_dict(data: dict) -> "FollowUp":
        return FollowUp(
            id=str(data.get("id") or ""),
            elder_id=str(data.get("elderId") or ""),
            due_day=str(data.get("dueDay") or ""),
            text=str(data.get("text") or ""),
            raw=str(data.get("raw") or ""),
            status=str(data.get("status") or FOLLOWUP_PENDING),
            created_at=str(data.get("createdAt") or ""),
            asked_at=str(data.get("askedAt") or ""),
        )
