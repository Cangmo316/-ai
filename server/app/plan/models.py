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

from ..models.message import as_dicts, as_float, as_text, new_id, now_iso

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

    @classmethod
    def from_dict(cls, data: dict) -> "PlanItem":
        """`to_dict()` 的逆运算。

        两处专有的映射口径（改 to_dict 时必须同步改这里）：
        - 五个依据字段是**扁平的 dataclass 字段，到了线上被收进 `basis` 子对象**
          （家属端要把它当一块整体展示），所以这里要从 `basis` 里摊回来
        - `basis.text` 是 `basis_text()` 拼出来的**派生态**，不是数据，读回来直接丢弃
          （留着反而会出现"文案与字段不一致"的脏数据）

        ⚠️ `weight` 不在 `to_dict()` 里（端侧契约 `uni-app/api/README.md` 没有这个字段），
        所以从线上形状读回来的权重一律是 0。这是可接受的：`weight` 只在**生成计划时**
        用来给知识库条目排序，计划一旦生成，它的语义已经落在 title/time/freq 上了。
        这里仍然接受 `weight` 键，是为了兼容"直接把 dataclass 存成 JSON"的调用方。
        """
        basis = data.get("basis")
        basis = basis if isinstance(basis, dict) else {}
        return cls(
            id=as_text(data.get("id")),
            time=as_text(data.get("time")),
            type=as_text(data.get("type")),
            title=as_text(data.get("title")),
            detail=as_text(data.get("detail")),
            freq=as_text(data.get("freq")) or "每日",
            strong_remind=bool(data.get("strongRemind")),
            weight=as_float(data.get("weight")),
            entry_id=as_text(basis.get("entryId")),
            source=as_text(basis.get("source")),
            source_name=as_text(basis.get("sourceName")),
            version=as_text(basis.get("version")),
            boundary=as_text(basis.get("boundary")),
        )


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

    @classmethod
    def from_dict(cls, data: dict) -> "CarePlan":
        """`to_dict()` 的逆运算（落库读回来时用）。

        两个要留意的口径：
        - `statusLabel` 是 `status` 派生的中文标签，**只用于展示**；读回来一律以 `status`
          为准（否则库里一改状态、标签没跟上，老人端就会看到"正在执行"却拿不到提醒）
        - `items` 里的每一项走 `PlanItem.from_dict()`（那里有 basis 的字段名映射）；
          `sources` / `history` 是"结构不固定"的留痕，只保证是 dict 列表

        可选字段全部给了兜底值，与 dataclass 的默认值一致——遇到老版本载荷（少几个键）
        时，读回来的计划不该变成一个字段为 None 的"半成品"。
        """
        items = data.get("items")
        return cls(
            id=as_text(data.get("id")),
            elder_id=as_text(data.get("elderId")),
            status=as_text(data.get("status")) or STATUS_DRAFT,
            items=[
                PlanItem.from_dict(item)
                for item in (items if isinstance(items, list) else [])
                if isinstance(item, dict)
            ],
            goal=as_text(data.get("goal")),
            start_date=as_text(data.get("startDate")),
            end_date=as_text(data.get("endDate")),
            created_at=as_text(data.get("createdAt")) or now_iso(),
            created_by=as_text(data.get("createdBy")) or "agent",
            confirmed_at=as_text(data.get("confirmedAt")),
            confirmed_by=as_text(data.get("confirmedBy")),
            rejected_reason=as_text(data.get("rejectedReason")),
            knowledge_version=as_text(data.get("knowledgeVersion")),
            sources=as_dicts(data.get("sources")),
            note=as_text(data.get("note")),
            history=as_dicts(data.get("history")),
        )


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

    @classmethod
    def from_dict(cls, data: dict) -> "PlanCheckin":
        """`to_dict()` 的逆运算。

        打卡记录是**完成率的唯一凭据**（家属端要拿它算"这几天做了几项"），
        所以这里宁可留一条字段缺失的记录，也不做"看起来不合法就丢掉"的判断——
        丢一条就等于把老人真做过的事抹掉。
        """
        return cls(
            id=as_text(data.get("id")),
            plan_id=as_text(data.get("planId")),
            plan_item_id=as_text(data.get("planItemId")),
            elder_id=as_text(data.get("elderId")),
            date=as_text(data.get("date")),
            done_at=as_text(data.get("doneAt")) or now_iso(),
            source=as_text(data.get("source")) or "elder",
        )


def new_plan_id() -> str:
    return new_id("plan")


def new_item_id() -> str:
    return new_id("pi")
