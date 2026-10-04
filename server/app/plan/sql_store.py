"""
比邻AI · 计划与打卡的落库实现（写穿透 + 启动加载）

与 `app/memory/sql_store.py` 同一套做法：**读走内存、写同时落库**。

**计划表与打卡表分开存**（`care_plans` / `plan_checkins`）：两者生命周期不同——
计划会一直留着（历史 + 当前生效 + 待确认都有用），打卡是按天累积的流水，量级差很多；
分开存也让"计划结束但打卡记录还在"这种正常情况不会互相牵连。

**为什么用 JSON 载荷**：见 `app/storage/json_store.py` 开头的说明。

⚠️ 这个类能成立的前提是**每次状态流转都调一次 `save()`**（见 `PlanStore.save()` 的注释）。
`engine.py` 里的六个流转方法都补了这一行——漏一个，"重启后计划状态退回"就回来了。
"""

from __future__ import annotations

import logging

from ..storage.db import Database
from ..storage.json_store import JsonPayloadTable
from .models import CarePlan, PlanCheckin, today_str
from .store import PlanStore

logger = logging.getLogger("bilin.plan")

TABLE_PLANS = "care_plans"
TABLE_CHECKINS = "plan_checkins"


class SqlPlanStore(PlanStore):
    """与 `PlanStore` 接口完全一致，只是每次写都落库、启动时把库读回内存"""

    def __init__(self, db: Database) -> None:
        super().__init__()
        self.db = db
        self._plans_table = JsonPayloadTable(db, TABLE_PLANS, "elder_id")
        self._checkins_table = JsonPayloadTable(db, TABLE_CHECKINS, "elder_id")
        self._plans_table.init_schema()
        self._checkins_table.init_schema()
        plans, checkins = self._load()
        logger.info("计划已从库里加载：%d 份计划 / %d 条打卡", plans, checkins)

    # ---------------------------------------------------------------- 加载

    def _load(self) -> tuple[int, int]:
        for row in self._plans_table.load():
            plan = CarePlan.from_dict(row["payload"])
            if not plan.id:
                logger.warning("库里有一份没有 id 的计划，已跳过")
                continue
            self._plans[plan.id] = plan
        for row in self._checkins_table.load():
            record = PlanCheckin.from_dict(row["payload"])
            if not record.id:
                logger.warning("库里有一条没有 id 的打卡，已跳过")
                continue
            self._checkins[record.id] = record
        return len(self._plans), len(self._checkins)

    # ---------------------------------------------------------------- 计划

    def add(self, plan: CarePlan) -> CarePlan:
        result = super().add(plan)
        self._save_plan(plan)
        return result

    def save(self, plan: CarePlan) -> CarePlan:
        result = super().save(plan)
        self._save_plan(plan)
        return result

    def _save_plan(self, plan: CarePlan) -> None:
        # created_at 只是赶在库里留一份实体自己的时间；排序由 JsonPayloadTable 的 seq 负责
        self._plans_table.save(plan.id, plan.elder_id, plan.to_dict(), plan.created_at)

    # ---------------------------------------------------------------- 打卡

    def checkin(
        self,
        plan: CarePlan,
        plan_item_id: str,
        elder_id: str,
        day: str | None = None,
        source: str = "elder",
    ) -> PlanCheckin:
        # 幂等的判断仍然只在父类里做（同一天同一项只留一条），这里只负责"新产生的那条要落库"：
        # 命中已有记录时父类会把同一条返回回来，再 save 一次是多余的写放大
        created = self.find_checkin(plan_item_id, day or today_str()) is None
        record = super().checkin(plan, plan_item_id, elder_id, day=day, source=source)
        if created:
            self._checkins_table.save(
                record.id, record.elder_id, record.to_dict(), record.done_at
            )
        return record

    def undo_checkin(self, plan_item_id: str, day: str | None = None) -> bool:
        existing = self.find_checkin(plan_item_id, day or today_str())
        removed = super().undo_checkin(plan_item_id, day=day)
        if removed and existing is not None:
            # 取消打卡必须真的删行：留着的话重启后完成率会比取消前还高
            self._checkins_table.delete(existing.id)
        return removed

    def clear(self) -> None:
        super().clear()
        self._plans_table.clear()
        self._checkins_table.clear()
