"""
比邻AI · 提醒任务模型

对应设计方案 §5 的 `reminder_task` 表：`send_at / sent_at / ack_at / status / channel`
五个字段是"提醒到底发出去没有"的唯一凭据，缺了就没法给家属交代。

提醒分级（设计方案 §3.2「提醒可靠性的分级」）：

| 级别 | 适用 | 策略 |
|---|---|---|
| 强提醒 strong | 用药、午餐、复诊 | 到点发，未响应隔几分钟再响一次（有次数上限） |
| 普通提醒 normal | 散步、喝水、测量血压 | 到点发一次，未响应不重复 |
| 弱提醒 weak | 问候、闲聊话题 | 有时间窗（默认 9:00–20:00），**超窗直接不发、不顺延** |

`read_at` 与 `ack_at` 是两件事：
- read = 老人在 App 里看到了这条提醒（端侧拉取后回执）
- ack  = 老人**打卡完成**了这件事
分开记才能回答"提醒送到了但他没做"和"提醒根本没送到"这两种完全不同的情况。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models.message import new_id, now_iso

LEVEL_STRONG = "strong"
LEVEL_NORMAL = "normal"
LEVEL_WEAK = "weak"

LEVEL_LABELS = {
    LEVEL_STRONG: "强提醒",
    LEVEL_NORMAL: "普通提醒",
    LEVEL_WEAK: "弱提醒",
}

STATUS_PENDING = "pending"    # 已登记，还没到点
STATUS_SENT = "sent"          # 已投递
STATUS_ACKED = "acked"        # 老人已打卡
STATUS_MISSED = "missed"      # 投递了但迟迟没响应
STATUS_SKIPPED = "skipped"    # 主动不发（超窗 / 过期 / 计划结束）
STATUS_CANCELED = "canceled"  # 计划变更导致取消

# 中文状态：家属端的"提醒有没有送到"这一栏要能直接给人看，不能出现英文枚举
# （与计划状态的 STATUS_LABELS 同一套做法：英文只留在 status 字段里给程序用）
STATUS_LABELS = {
    STATUS_PENDING: "还没到点",
    STATUS_SENT: "已送出",
    STATUS_ACKED: "已打卡",
    STATUS_MISSED: "没见回应",
    STATUS_SKIPPED: "没发（超出时间窗）",
    STATUS_CANCELED: "已作废（计划换了）",
    "failed": "发送失败",
    "read": "已看过",
    "repeated": "又提醒了一次",
}


@dataclass
class ReminderTask:
    id: str
    plan_id: str
    plan_item_id: str
    elder_id: str
    conversation_id: str
    title: str
    label: str = ""
    detail: str = ""
    level: str = LEVEL_NORMAL
    send_at: str = ""
    created_at: str = field(default_factory=now_iso)
    sent_at: str = ""
    read_at: str = ""
    ack_at: str = ""
    repeat_count: int = 0
    status: str = STATUS_PENDING
    channel: str = ""
    message_id: str = ""
    note: str = ""

    @property
    def level_label(self) -> str:
        return LEVEL_LABELS.get(self.level, self.level)

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "planId": self.plan_id,
            "planItemId": self.plan_item_id,
            "elderId": self.elder_id,
            "title": self.title,
            "label": self.label,
            "detail": self.detail,
            "level": self.level,
            "levelLabel": self.level_label,
            "sendAt": self.send_at,
            "sentAt": self.sent_at,
            "readAt": self.read_at,
            "ackAt": self.ack_at,
            "repeatCount": self.repeat_count,
            "status": self.status,
            "statusLabel": self.status_label,
            "channel": self.channel,
            "messageId": self.message_id,
            "note": self.note,
        }


def new_task_id() -> str:
    return new_id("rt")
