"""提醒任务存储（P1 内存实现，接口按落库形态设计）"""

from __future__ import annotations

from datetime import date, datetime

from .models import ReminderTask, STATUS_ACKED, STATUS_MISSED, STATUS_PENDING, STATUS_SENT


class ReminderStore:
    def __init__(self) -> None:
        self._tasks: dict[str, ReminderTask] = {}

    # ---------------------------------------------------------------- 登记

    @staticmethod
    def key_for(plan_item_id: str, send_at: str) -> str:
        """同一计划项在同一天的同一时刻只该有一条任务（幂等的依据）"""
        return plan_item_id + "@" + send_at

    def find(self, plan_item_id: str, send_at: str) -> ReminderTask | None:
        key = self.key_for(plan_item_id, send_at)
        for task in self._tasks.values():
            if self.key_for(task.plan_item_id, task.send_at) == key:
                return task
        return None

    def add(self, task: ReminderTask) -> ReminderTask:
        self._tasks[task.id] = task
        return task

    def cancel_for_plan(self, plan_id: str, reason: str = "计划已结束") -> int:
        """计划结束时把还没发的任务取消掉（已发的保留，作为历史记录）"""
        count = 0
        for task in self._tasks.values():
            if task.plan_id == plan_id and task.status == STATUS_PENDING:
                task.status = "canceled"
                task.note = reason
                count += 1
        return count

    # ---------------------------------------------------------------- 查询

    def tasks_of(self, elder_id: str, day: date | str | None = None) -> list[ReminderTask]:
        target = day.isoformat() if isinstance(day, date) else day
        items = [task for task in self._tasks.values() if task.elder_id == elder_id]
        if target:
            items = [task for task in items if task.send_at.startswith(target)]
        items.sort(key=lambda task: task.send_at)
        return items

    def all_tasks(self) -> list[ReminderTask]:
        return list(self._tasks.values())

    def due(self, now: datetime) -> list[ReminderTask]:
        """到点且还没投递的"""
        moment = now.isoformat(timespec="seconds")
        items = [
            task
            for task in self._tasks.values()
            if task.status == STATUS_PENDING and task.send_at <= moment
        ]
        items.sort(key=lambda task: task.send_at)
        return items

    def repeats_due(self, now: datetime, repeat_after_minutes: int, max_repeats: int) -> list[ReminderTask]:
        """已投递、未打卡、超过重复间隔、且重复次数没超上限的强提醒"""
        items: list[ReminderTask] = []
        for task in self._tasks.values():
            if task.status != STATUS_SENT or task.ack_at or task.repeat_count >= max_repeats:
                continue
            if not task.sent_at:
                continue
            sent = datetime.fromisoformat(task.sent_at)
            if (now - sent).total_seconds() >= repeat_after_minutes * 60:
                items.append(task)
        items.sort(key=lambda task: task.send_at)
        return items

    def stale_sent(self, now: datetime, miss_after_minutes: int) -> list[ReminderTask]:
        """投递后迟迟没响应的任务（记 missed，供家属端看完成情况）"""
        items: list[ReminderTask] = []
        for task in self._tasks.values():
            if task.status != STATUS_SENT or task.ack_at or not task.sent_at:
                continue
            sent = datetime.fromisoformat(task.sent_at)
            if (now - sent).total_seconds() >= miss_after_minutes * 60:
                items.append(task)
        return items

    def inbox(self, elder_id: str) -> list[ReminderTask]:
        """老人端要展示的提醒：已投递、还没被看到过（按时间正序）"""
        items = [
            task
            for task in self._tasks.values()
            if task.elder_id == elder_id
            and task.status in (STATUS_SENT, STATUS_ACKED, STATUS_MISSED)
            and not task.read_at
        ]
        items.sort(key=lambda task: task.send_at)
        return items

    def get(self, task_id: str) -> ReminderTask | None:
        return self._tasks.get(task_id)

    # ------------------------------------------------------------ 状态变更

    def mark_read(self, elder_id: str, task_id: str | None = None, now: datetime | None = None) -> int:
        """老人看到了（端侧拉取后回执）。不传 task_id 表示整个收件箱都看了。"""
        stamp = (now or datetime.now()).isoformat(timespec="seconds")
        count = 0
        for task in self.inbox(elder_id):
            if task_id and task.id != task_id:
                continue
            task.read_at = stamp
            count += 1
        return count

    def ack_item(self, elder_id: str, plan_item_id: str, day: date | str, now: datetime | None = None) -> int:
        """打卡即确认：把当天这一项已投递的提醒标成 acked"""
        stamp = (now or datetime.now()).isoformat(timespec="seconds")
        count = 0
        for task in self.tasks_of(elder_id, day):
            if task.plan_item_id != plan_item_id:
                continue
            if task.status in (STATUS_SENT, STATUS_MISSED, STATUS_PENDING):
                if task.status == STATUS_PENDING:
                    # 还没到点就先打了卡：直接销掉，别再提醒
                    task.status = "canceled"
                    task.note = "老人提前打卡，不再提醒"
                else:
                    task.status = STATUS_ACKED
                task.ack_at = stamp
                task.read_at = task.read_at or stamp
                count += 1
        return count

    def unack_item(self, elder_id: str, plan_item_id: str, day: date | str) -> int:
        """取消打卡：提醒回到"已投递未确认"（老人点错了要能改）"""
        count = 0
        for task in self.tasks_of(elder_id, day):
            if task.plan_item_id == plan_item_id and task.status == STATUS_ACKED:
                task.status = STATUS_SENT
                task.ack_at = ""
                count += 1
        return count

    def counts(self) -> dict:
        summary: dict[str, int] = {}
        for task in self._tasks.values():
            summary[task.status] = summary.get(task.status, 0) + 1
        return summary

    def clear(self) -> None:
        self._tasks.clear()
