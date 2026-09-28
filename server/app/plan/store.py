"""
比邻AI · 计划存储（P1 内存实现）

只做存取，不放业务规则——状态流转的闸门在 `engine.py`（那里才看得清"谁能改什么"）。
接口按将来落库的形态设计：一个老人可以有多份计划（历史 + 当前生效 + 待确认），
替换成 PostgreSQL 时上层不用改。
"""

from __future__ import annotations

from datetime import date

from .models import (
    STATUS_ACTIVE,
    STATUS_ADJUSTING,
    STATUS_PENDING,
    CarePlan,
    PlanCheckin,
    new_item_id,
    today_str,
)


class PlanStore:
    def __init__(self) -> None:
        self._plans: dict[str, CarePlan] = {}
        self._checkins: dict[str, PlanCheckin] = {}

    # ---------------------------------------------------------------- 计划

    def add(self, plan: CarePlan) -> CarePlan:
        self._plans[plan.id] = plan
        return plan

    def get(self, plan_id: str) -> CarePlan | None:
        return self._plans.get(plan_id)

    def plans_of(self, elder_id: str) -> list[CarePlan]:
        items = [plan for plan in self._plans.values() if plan.elder_id == elder_id]
        items.sort(key=lambda plan: plan.created_at, reverse=True)
        return items

    def of_status(self, elder_id: str, *statuses: str) -> list[CarePlan]:
        return [plan for plan in self.plans_of(elder_id) if plan.status in statuses]

    def pending(self, elder_id: str) -> list[CarePlan]:
        """待家属确认的计划（家属端用；老人端不该看到这个列表本身）"""
        return self.of_status(elder_id, STATUS_PENDING)

    def active(self, elder_id: str) -> CarePlan | None:
        """**当前生效**的计划。

        这是「未确认不产生提醒」这条硬规则的落点：调度器、今日计划、对话卡片
        全部只从这里取数，草稿/待确认一律拿不到。
        """
        plans = self.of_status(elder_id, STATUS_ACTIVE, STATUS_ADJUSTING)
        if not plans:
            return None
        # 生效中的排前面（adjusting 表示已有调整建议，但旧计划仍在执行）
        plans.sort(key=lambda plan: (plan.status != STATUS_ACTIVE, plan.created_at), reverse=False)
        return plans[0]

    # ---------------------------------------------------------------- 打卡

    def checkin(
        self,
        plan: CarePlan,
        plan_item_id: str,
        elder_id: str,
        day: str | None = None,
        source: str = "elder",
    ) -> PlanCheckin:
        """打卡（同一天同一项幂等：重复点不会产生两条记录）"""
        target = day or today_str()
        existing = self.find_checkin(plan_item_id, target)
        if existing:
            return existing
        record = PlanCheckin(
            id=new_item_id(),
            plan_id=plan.id,
            plan_item_id=plan_item_id,
            elder_id=elder_id,
            date=target,
            source=source,
        )
        self._checkins[record.id] = record
        return record

    def undo_checkin(self, plan_item_id: str, day: str | None = None) -> bool:
        target = day or today_str()
        existing = self.find_checkin(plan_item_id, target)
        if not existing:
            return False
        del self._checkins[existing.id]
        return True

    def find_checkin(self, plan_item_id: str, day: str) -> PlanCheckin | None:
        for record in self._checkins.values():
            if record.plan_item_id == plan_item_id and record.date == day:
                return record
        return None

    def last_checkin(self, plan_item_id: str) -> PlanCheckin | None:
        records = [item for item in self._checkins.values() if item.plan_item_id == plan_item_id]
        if not records:
            return None
        records.sort(key=lambda item: item.date)
        return records[-1]

    def checkins_of(self, elder_id: str, since: str | None = None) -> list[PlanCheckin]:
        records = [item for item in self._checkins.values() if item.elder_id == elder_id]
        if since:
            records = [item for item in records if item.date >= since]
        records.sort(key=lambda item: (item.date, item.done_at))
        return records

    def checkins_on(self, elder_id: str, day: date | str) -> list[PlanCheckin]:
        target = day if isinstance(day, str) else day.isoformat()
        return [item for item in self.checkins_of(elder_id) if item.date == target]

    def clear(self) -> None:
        self._plans.clear()
        self._checkins.clear()
