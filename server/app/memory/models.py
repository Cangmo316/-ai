"""
比邻AI · 三层记忆的数据模型（设计方案 §3.4）

三层里的 L1 档案已经在 `app/models/elder.py`（姓名/年龄/慢病/用药/称呼），
这里放 **L2 经历事件**（时间线）与 **L3 兴趣偏好**（动态权重）。

三条硬规则（照设计方案落地，不是我自己加的）：

1. **每条记忆必须带 `source` 与 `confidence`**——家属录入、老人自述、从聊天自动抽取，
   可信度完全不同。自动抽取的低置信内容**不得**用于主动话题（`review="pending"` 扣住）
2. **自动抽取必须显式开启**：`MemorySettings.auto_extract` 默认 `False`。
   方案原文是"从聊天中自动抽取（需明确告知并允许关闭）"——默认开启就是没告知
3. **家人端可见性单独一列 `visible_to_family`**：
   从聊天自动抽取的记忆默认**不对家属可见**。否则"家人端默认看不到聊天原文"这条隐私边界
   会被"记忆"绕过去——家属看到的每条记忆都可能是聊天内容的转述

删除能力同样按方案要求做足：单条删除（`delete`）+ 一键清空（`clear`）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models.message import new_id, now_iso

# ── 记忆种类 ────────────────────────────────────────────────
KIND_EXPERIENCE = "experience"  # L2：经历事件（"2023 年儿子带我去过海南"）
KIND_PREFERENCE = "preference"  # L3：兴趣偏好（"爱听戏""喜欢下棋"）
KIND_PROFILE = "profile"  # L1 的补充（"平时叫她张老师""不吃辣"）

KINDS = (KIND_EXPERIENCE, KIND_PREFERENCE, KIND_PROFILE)

KIND_LABELS = {
    KIND_EXPERIENCE: "经历",
    KIND_PREFERENCE: "喜好",
    KIND_PROFILE: "习惯",
}

# ── 来源（决定可信度与可见性）──────────────────────────────
SOURCE_FAMILY = "family"  # 子女在家人端录入：可信、默认家属可见
SOURCE_ELDER = "elder"  # 老人自己说的：可信、默认家属可见
SOURCE_AUTO = "auto"  # 从聊天自动抽取：默认待复核 + 默认家属不可见

SOURCE_LABELS = {
    SOURCE_FAMILY: "家里人填写",
    SOURCE_ELDER: "老人自己说的",
    SOURCE_AUTO: "从聊天里整理",
}

# ── 复核状态 ────────────────────────────────────────────────
REVIEW_APPROVED = "approved"  # 可用（进入检索与主动话题）
REVIEW_PENDING = "pending"  # 待复核（**不进入检索、不用于主动话题**）
REVIEW_REJECTED = "rejected"  # 已否决（保留痕迹，不再使用）

# 自动抽取的置信度门槛：低于它就只入库待复核，绝不直接拿去做主动话题
AUTO_MIN_CONFIDENCE = 0.75


@dataclass
class MemoryEntry:
    id: str
    elder_id: str
    kind: str
    text: str
    tags: list[str] = field(default_factory=list)
    source: str = SOURCE_FAMILY
    confidence: float = 1.0
    review: str = REVIEW_APPROVED
    visible_to_family: bool = True
    # 事情发生的时间（"2023 年""去年"这种模糊说法也照存，检索时按年份权重用）
    happened_at: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)

    @property
    def source_label(self) -> str:
        return SOURCE_LABELS.get(self.source, self.source)

    @property
    def usable(self) -> bool:
        """能不能用于检索/主动话题：必须是已复核通过的"""
        return self.review == REVIEW_APPROVED

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "elderId": self.elder_id,
            "kind": self.kind,
            "kindLabel": self.kind_label,
            "text": self.text,
            "tags": list(self.tags),
            "source": self.source,
            "sourceLabel": self.source_label,
            "confidence": round(self.confidence, 3),
            "review": self.review,
            "visibleToFamily": self.visible_to_family,
            "happenedAt": self.happened_at,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


@dataclass
class MemorySettings:
    """每位老人一份：自动抽取的开关与同意时间（同意记录将来要落 consent_record）"""

    elder_id: str
    auto_extract: bool = False
    consented_at: str = ""
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        return {
            "elderId": self.elder_id,
            "autoExtract": self.auto_extract,
            "consentedAt": self.consented_at,
            "updatedAt": self.updated_at,
            "notice": "从聊天自动整理记忆需要先明确告知本人并在这里开启；关闭后不再新增，已入库的仍可单条删除或一键清空",
        }


class MemoryStore:
    def __init__(self) -> None:
        self._entries: dict[str, MemoryEntry] = {}
        self._settings: dict[str, MemorySettings] = {}

    # ---------------------------------------------------------------- 录入

    def add(
        self,
        elder_id: str,
        text: str,
        kind: str = KIND_EXPERIENCE,
        tags: list[str] | None = None,
        source: str = SOURCE_FAMILY,
        confidence: float = 1.0,
        happened_at: str = "",
        visible_to_family: bool | None = None,
        review: str | None = None,
    ) -> MemoryEntry:
        text = (text or "").strip()
        if not text:
            raise ValueError("记忆内容不能为空")
        if kind not in KINDS:
            raise ValueError("记忆种类不合法：" + str(kind))

        # 自动抽取的两条默认值：待复核 + 家属不可见。
        # 调用方可以覆盖（例如家属复核通过时），但默认必须是保守的那一侧。
        if review is None:
            review = (
                REVIEW_PENDING
                if source == SOURCE_AUTO and confidence < AUTO_MIN_CONFIDENCE
                else REVIEW_APPROVED
            )
        if visible_to_family is None:
            visible_to_family = source != SOURCE_AUTO

        entry = MemoryEntry(
            id=new_id("mem"),
            elder_id=elder_id,
            kind=kind,
            text=text,
            tags=[tag.strip() for tag in (tags or []) if str(tag).strip()],
            source=source,
            confidence=max(0.0, min(1.0, float(confidence))),
            review=review,
            visible_to_family=bool(visible_to_family),
            happened_at=happened_at or "",
        )
        self._entries[entry.id] = entry
        return entry

    # ---------------------------------------------------------------- 查询

    def get(self, memory_id: str) -> MemoryEntry | None:
        return self._entries.get(memory_id)

    def all_of(self, elder_id: str) -> list[MemoryEntry]:
        items = [entry for entry in self._entries.values() if entry.elder_id == elder_id]
        items.sort(key=lambda entry: entry.created_at, reverse=True)
        return items

    def usable_of(self, elder_id: str, kind: str | None = None) -> list[MemoryEntry]:
        """可用的记忆（已复核通过），检索层只从这里取"""
        return [
            entry
            for entry in self.all_of(elder_id)
            if entry.usable and (kind is None or entry.kind == kind)
        ]

    def family_view(self, elder_id: str) -> list[MemoryEntry]:
        """家人端能看到的：连"家属可见"都要满足（自动抽取的默认不在内）"""
        return [entry for entry in self.usable_of(elder_id) if entry.visible_to_family]

    def pending_of(self, elder_id: str) -> list[MemoryEntry]:
        return [entry for entry in self.all_of(elder_id) if entry.review == REVIEW_PENDING]

    # ---------------------------------------------------------------- 修改

    def update(
        self,
        memory_id: str,
        text: str | None = None,
        tags: list[str] | None = None,
        kind: str | None = None,
        visible_to_family: bool | None = None,
        happened_at: str | None = None,
    ) -> MemoryEntry | None:
        entry = self._entries.get(memory_id)
        if not entry:
            return None
        if text is not None:
            text = text.strip()
            if not text:
                raise ValueError("记忆内容不能为空")
            entry.text = text
        if tags is not None:
            entry.tags = [tag.strip() for tag in tags if str(tag).strip()]
        if kind is not None:
            if kind not in KINDS:
                raise ValueError("记忆种类不合法：" + str(kind))
            entry.kind = kind
        if visible_to_family is not None:
            entry.visible_to_family = bool(visible_to_family)
        if happened_at is not None:
            entry.happened_at = happened_at
        entry.updated_at = now_iso()
        return entry

    def review(self, memory_id: str, approve: bool) -> MemoryEntry | None:
        """家属复核自动抽取的记忆：通过 → 可用；否决 → 保留痕迹但不再用"""
        entry = self._entries.get(memory_id)
        if not entry:
            return None
        entry.review = REVIEW_APPROVED if approve else REVIEW_REJECTED
        entry.updated_at = now_iso()
        return entry

    def delete(self, memory_id: str) -> bool:
        """单条删除（方案要求：记忆库支持单条删除）"""
        return self._entries.pop(memory_id, None) is not None

    def clear(self, elder_id: str) -> int:
        """一键清空（方案要求）——连设置一起留下，但记忆全删"""
        doomed = [entry.id for entry in self._entries.values() if entry.elder_id == elder_id]
        for memory_id in doomed:
            self._entries.pop(memory_id, None)
        return len(doomed)

    # ---------------------------------------------------------------- 设置

    def settings_for(self, elder_id: str) -> MemorySettings:
        settings = self._settings.get(elder_id)
        if settings is None:
            settings = MemorySettings(elder_id=elder_id)
            self._settings[elder_id] = settings
        return settings

    def update_settings(self, elder_id: str, auto_extract: bool | None = None) -> MemorySettings:
        settings = self.settings_for(elder_id)
        if auto_extract is not None:
            settings.auto_extract = bool(auto_extract)
            # 第一次开启时记下同意时间：将来要落 consent_record
            if settings.auto_extract and not settings.consented_at:
                settings.consented_at = now_iso()
        settings.updated_at = now_iso()
        return settings

    # ---------------------------------------------------------------- 统计

    def counts(self) -> dict:
        by_kind: dict[str, int] = {}
        by_source: dict[str, int] = {}
        pending = 0
        for entry in self._entries.values():
            by_kind[entry.kind] = by_kind.get(entry.kind, 0) + 1
            by_source[entry.source] = by_source.get(entry.source, 0) + 1
            if entry.review == REVIEW_PENDING:
                pending += 1
        return {
            "total": len(self._entries),
            "byKind": by_kind,
            "bySource": by_source,
            "pending": pending,
            "elders": len({entry.elder_id for entry in self._entries.values()}),
            "autoExtractEnabled": sum(
                1 for settings in self._settings.values() if settings.auto_extract
            ),
        }
