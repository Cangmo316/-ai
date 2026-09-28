"""
比邻AI · 康养计划的数据结构

对应设计方案 §5 的 `care_plan` / `plan_item` / `plan_checkin` 三张表（P1 先内存实现）。

**状态机（设计方案 §3.2，这是产品最关键的一道闸门）**

    draft ──submit──▶ pending_confirm ──confirm──▶ active ──触发调整──▶ adjusting
                            │                        │                    │
                            └──reject──▶ rejected    └──到期/手动──▶ ended ◀┘
                                                                        （调整被家属采纳后回到 active）

两条硬规则，代码里必须能拦住：
1. **未确认的草稿不产生任何提醒**——`PlanStore.active()` 只认 `active`，
   调度器/今日计划/对话卡片全部只从它取数
2. **过渡期旧计划继续执行**——确认新计划的那一刻才把旧计划置为 ended，
   而不是新草稿一生成就把旧的停掉（否则会出现提醒真空）

`rejected` 是设计文档没列、但流程上必须有的终态（家属驳回）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from ..models.message import new_id, now_iso

STATUS_DRAFT = "draft"
STATUS_PENDING = "pending_confirm"
STATUS_ACTIVE = "active"
STATUS_ADJUSTING = "adjusting"
STATUS_ENDED = "ended"
STATUS_REJECTED = "rejected"

# 给端侧/家属端看的中文状态（适老化：不给老人看英文）
STATUS_LABELS = {
    STATUS_DRAFT: "草稿",
    STATUS_PENDING: "等家里人确认",
    STATUS_ACTIVE: "正在执行",
    STATUS_ADJUSTING: "调整中，等家里人确认",
    STATUS_ENDED: "已结束",
    STATUS_REJECTED: "家里人没同意",
}

DEFAULT_DAYS = 90
# 一次计划最多几项：老人一天记不住太多事，宁可少而准
DEFAULT_MAX_ITEMS = 6


def today_str(day: date | None = None) -> str:
    return (day or date.today()).isoformat()


def add_days(start: str, days: int) -> str:
    return (date.fromisoformat(start) + timedelta(days=days)).isoformat()


@dataclass
class PlanItem:
    id: str
    time: str
    type: str
    title: str
    detail: str = ""
    freq: str = "每日"
    strong_remind: bool = False
    weight: float = 0.0
    # 依据：来源 + 版本 + 条目 id（设计方案 §3.2 要求随计划项落库，家属端可见）
    entry_id: str = ""
    source: str = ""
    source_name: str = ""
    version: str = ""
    boundary: str = ""

    def basis_text(self) -> str:
        """给家属看的依据一行文案，例如「国家基本公共卫生服务规范（第三版）· 第三版 §nphis_001」"""
        if not self.source_name:
            return ""
        parts = [self.source_name]
        if self.version:
            parts.append(self.version)
        if self.entry_id:
            parts.append("§" + self.entry_id)
        return " · ".join(parts)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "time": self.time,
            "type": self.type,
            "title": self.title,
            "detail": self.detail,
            "freq": self.freq,
            "strongRemind": self.strong_remind,
            "basis": {
                "entryId": self.entry_id,
                "source": self.source,
                "sourceName": self.source_name,
                "version": self.version,
                "boundary": self.boundary,
                "text": self.basis_text(),
            },
        }


@dataclass
class CarePlan:
    id: str
    elder_id: str
    status: str = STATUS_DRAFT
    items: list[PlanItem] = field(default_factory=list)
    goal: str = ""
    start_date: str = ""
    end_date: str = ""
    created_at: str = field(default_factory=now_iso)
    created_by: str = "agent"
    confirmed_at: str = ""
    confirmed_by: str = ""
    rejected_reason: str = ""
    knowledge_version: str = ""
    sources: list[dict] = field(default_factory=list)
    note: str = ""
    history: list[dict] = field(default_factory=list)

    def log(self, action: str, detail: str = "", actor: str = "") -> None:
        self.history.append(
            {"at": now_iso(), "action": action, "detail": detail, "actor": actor}
        )

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "elderId": self.elder_id,
            "status": self.status,
            "statusLabel": self.status_label,
            "goal": self.goal,
            "startDate": self.start_date,
            "endDate": self.end_date,
            "createdAt": self.created_at,
            "createdBy": self.created_by,
            "confirmedAt": self.confirmed_at,
            "confirmedBy": self.confirmed_by,
            "rejectedReason": self.rejected_reason,
            "knowledgeVersion": self.knowledge_version,
            "sources": self.sources,
            "note": self.note,
            "items": [item.to_dict() for item in self.items],
            "history": self.history,
        }


@dataclass
class PlanCheckin:
    id: str
    plan_id: str
    plan_item_id: str
    elder_id: str
    date: str
    done_at: str = field(default_factory=now_iso)
    source: str = "elder"  # elder | family

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "planId": self.plan_id,
            "planItemId": self.plan_item_id,
            "elderId": self.elder_id,
            "date": self.date,
            "doneAt": self.done_at,
            "source": self.source,
        }


def new_plan_id() -> str:
    return new_id("plan")


def new_item_id() -> str:
    return new_id("pi")
