"""
比邻AI · 提醒调度器

一次 tick 做五件事（顺序有意义）：

1. **补齐任务**：为每位老人的 `active` 计划生成当天到点的 `ReminderTask`
   （幂等：同一计划项同一天同一时刻只有一条；**未确认的计划不会生成任何任务**）
2. **取消陈旧任务**：计划的 `plan_id` 已不是当前生效计划时，未发的任务作废
   （换了新计划，旧计划的提醒不能再响）
3. **投递到点任务**：走 `ChannelRegistry`（站内消息 + 将来接的厂商推送）
4. **重复强提醒**：投递后未打卡的强提醒，间隔几分钟再响一次（有次数上限）
5. **判定错过**：投递后迟迟没响应的记 `missed`，家属端据此看到"提醒送到了但没做"

时间处理的两个关键决定：

- **过期不补发**（`REMINDER_GRACE_MINUTES`，默认 30 分钟）：服务没运行期间错过的提醒，
  超宽限期就记 `skipped`。早上 8 点的用药提醒，下午 3 点开机补发一条只会添乱。
- **时间可注入**（构造函数的 `clock`）：调度逻辑不能只有等到真实时间才能测。
  单测直接 `tick(at=某时刻)`，联调可用 `POST /v1/scheduler/tick` 手动推进。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time as clock_time, timedelta

from ..models.message import ROLE_ELDER  # noqa: F401  （保留：便于将来区分提醒来源）
from ..style.compliance import scan
from ..plan.engine import PlanEngine
from ..plan.models import STATUS_ACTIVE, STATUS_ADJUSTING
from ..plan.store import PlanStore
from .channels import ChannelRegistry
from .models import (
    LEVEL_STRONG,
    LEVEL_WEAK,
    STATUS_ACKED,
    STATUS_MISSED,
    STATUS_PENDING,
    STATUS_SENT,
    STATUS_SKIPPED,
    ReminderTask,
    new_task_id,
)
from .store import ReminderStore

logger = logging.getLogger("bilin.schedule")


class Scheduler:
    def __init__(
        self,
        engine: PlanEngine,
        plan_store: PlanStore,
        reminders: ReminderStore,
        channels: ChannelRegistry,
        elders,
        settings,
        clock=None,
    ) -> None:
        self.engine = engine
        self.plan_store = plan_store
        self.reminders = reminders
        self.channels = channels
        self.elders = elders
        self.settings = settings
        self._clock = clock or datetime.now
        self._loop_task: asyncio.Task | None = None
        self.ticks = 0
        self.last_tick_at = ""
        self.last_summary: dict = {}

    # ------------------------------------------------------------ 时间与分级

    def now(self) -> datetime:
        return self._clock()

    @staticmethod
    def level_of(item) -> str:
        """强提醒来自知识库的 strong_remind；问候类算弱提醒（有时间窗、超窗不顺延）"""
        if item.strong_remind:
            return LEVEL_STRONG
        if item.type == "问候":
            return LEVEL_WEAK
        return "normal"

    def _weak_window(self) -> tuple[str, str]:
        window = getattr(self.settings, "weak_reminder_window", ("09:00", "20:00"))
        return (window[0], window[1])

    def _in_weak_window(self, hhmm: str) -> bool:
        start, end = self._weak_window()
        return start <= hhmm <= end

    def message_text(self, task: ReminderTask) -> str:
        """提醒话术：称呼 + 知识库/计划里的提醒正文。

        刻意**不在这里编新话术**——正文来自人工整理的条目，重新组织语言只会引入越界风险。
        这里只做一次越界扫描兜底（命中记警告，仍照发，因为内容来自知识库）。

        称呼要做幂等：计划项标题有可能已经带了称呼（例如模型改写时加上的），
        再补一次就会变成"妈 妈 该吃药了"——实测踩过这个坑。
        """
        elder = self.elders.get(task.elder_id)
        address = str(elder.get("address") or "").strip()
        title = (task.title or "").strip()
        if address and title and not title.startswith(address):
            text = address + " " + title
        else:
            text = title
        for hint in scan(text):
            logger.warning("提醒话术命中越界检查：%s | %s", hint, text)
        return text

    # ---------------------------------------------------------------- 生成

    def ensure_tasks(self, day: date | None = None, moment: datetime | None = None) -> dict:
        """为所有老人的生效计划补齐当天的提醒任务（幂等）

        `moment` 必须跟着 tick 的时间走，否则「手动把时间推到 15 点」时，
        任务生成仍按真实时间判断是否过期，两边结论会打架。
        """
        moment = moment or self.now()
        target = day or moment.date()
        created = skipped = synced = 0

        for elder in self.elders.all():
            elder_id = str(elder.get("id") or "")
            plan = self.plan_store.active(elder_id)
            if not plan or plan.status not in (STATUS_ACTIVE, STATUS_ADJUSTING):
                # 未确认 / 已结束 / 调整中的计划：一条提醒都不生成
                continue
            conversation_id = self.elders.conversation_id(elder_id)
            for item, due, done in self.engine.due_items(plan, target):
                if not due or done:
                    # 不该做的（不在窗口/本周期已完成）或已经做完的，都不需要提醒
                    continue
                send_at = datetime.combine(target, _parse_hhmm(item.time))
                stamp = send_at.isoformat(timespec="seconds")
                existing = self.reminders.find(item.id, stamp)
                if existing:
                    continue

                level = self.level_of(item)
                status = STATUS_PENDING
                note = ""
                if send_at < moment - timedelta(minutes=self.settings.reminder_grace_minutes):
                    status = STATUS_SKIPPED
                    note = "服务未运行期间已过期，不再补发"
                elif level == LEVEL_WEAK and not self._in_weak_window(item.time):
                    status = STATUS_SKIPPED
                    note = "超出弱提醒时间窗，不顺延"

                task = ReminderTask(
                    id=new_task_id(),
                    plan_id=plan.id,
                    plan_item_id=item.id,
                    elder_id=elder_id,
                    conversation_id=conversation_id,
                    title=item.title,
                    label=item.time + " " + item.type,
                    detail=item.detail,
                    level=level,
                    send_at=stamp,
                    status=status,
                    note=note,
                )
                self.reminders.add(task)
                if status == STATUS_SKIPPED:
                    skipped += 1
                    logger.info("登记但不投递（%s）：%s %s", note, task.send_at, task.title)
                else:
                    created += 1
                    logger.info("登记提醒：%s %s [%s]", task.send_at, task.title, task.level_label)

        return {"created": created, "skipped": skipped, "synced": synced}

    def _cancel_stale(self) -> int:
        """把已不是当前生效计划的未发任务作废"""
        canceled = 0
        for task in self.reminders.all_tasks():
            if task.status != STATUS_PENDING:
                continue
            active = self.plan_store.active(task.elder_id)
            if not active or active.id != task.plan_id:
                task.status = "canceled"
                task.note = "计划已变更或结束"
                canceled += 1
        return canceled

    # ---------------------------------------------------------------- 调度

    async def tick(self, at: datetime | None = None) -> dict:
        moment = at or self.now()
        summary = {
            "at": moment.isoformat(timespec="seconds"),
            "created": 0,
            "skipped": 0,
            "canceled": 0,
            "sent": 0,
            "repeated": 0,
            "missed": 0,
            "failed": 0,
        }

        ensure = self.ensure_tasks(moment.date(), moment=moment)
        summary["created"] = ensure["created"]
        summary["skipped"] = ensure["skipped"]
        summary["canceled"] = self._cancel_stale()
        expire_before = (moment - timedelta(minutes=self.settings.reminder_grace_minutes)).isoformat(
            timespec="seconds"
        )

        for task in self.reminders.due(moment):
            # 先判弱提醒时间窗（产品语义上更贴切：这个点就是不该打扰），再判过期
            if task.level == LEVEL_WEAK and not self._in_weak_window(moment.strftime("%H:%M")):
                task.status = STATUS_SKIPPED
                task.note = "超出弱提醒时间窗，不顺延"
                summary["skipped"] += 1
                continue
            # 投递时也要判过期：任务登记时没过期，不代表现在还能发
            # （通道故障、进程卡住、机器休眠都会让任务滞留在这里）
            if task.send_at < expire_before:
                task.status = STATUS_SKIPPED
                task.note = "已过提醒时间，不再补发"
                summary["skipped"] += 1
                continue
            delivered = await self._deliver(task, moment)
            if delivered:
                summary["sent"] += 1
            else:
                summary["failed"] += 1

        # 重复窗口：拖太久的重复没有意义（早上 8 点的用药提醒，9 点才响第二次只会让人困惑），
        # 这类交给下面的"错过"判定
        repeat_deadline = self.settings.reminder_repeat_minutes + self.settings.reminder_grace_minutes
        for task in self.reminders.repeats_due(
            moment, self.settings.reminder_repeat_minutes, self.settings.reminder_max_repeats
        ):
            if task.level != LEVEL_STRONG:
                continue
            if task.sent_at:
                elapsed = (moment - datetime.fromisoformat(task.sent_at)).total_seconds()
                if elapsed > repeat_deadline * 60:
                    continue
            if await self._deliver(task, moment, repeat=True):
                summary["repeated"] += 1

        for task in self.reminders.stale_sent(moment, self.settings.reminder_miss_minutes):
            task.status = STATUS_MISSED
            summary["missed"] += 1
            logger.info("提醒未被响应，记为错过：%s %s", task.send_at, task.title)

        self.ticks += 1
        self.last_tick_at = moment.isoformat(timespec="seconds")
        self.last_summary = summary
        if summary["sent"] or summary["repeated"] or summary["missed"] or summary["failed"]:
            logger.info("调度 tick：%s", summary)
        return summary

    async def _deliver(self, task: ReminderTask, moment: datetime, repeat: bool = False) -> bool:
        text = self.message_text(task)
        result = await self.channels.deliver(task, text)
        if not result.ok:
            task.note = "投递失败：" + (result.detail or "未知原因")
            logger.warning("提醒投递失败（%s）：%s", result.detail, task.title)
            return False
        task.status = STATUS_SENT
        task.sent_at = moment.isoformat(timespec="seconds")
        task.channel = result.channel
        task.message_id = result.message_id or task.message_id
        if repeat:
            task.repeat_count += 1
            logger.info("强提醒重复投递（第 %s 次）：%s", task.repeat_count, task.title)
        return True

    # ------------------------------------------------------------ 打卡回执

    def ack(self, elder_id: str, plan_item_id: str, day: date | str) -> int:
        return self.reminders.ack_item(elder_id, plan_item_id, day, self.now())

    def unack(self, elder_id: str, plan_item_id: str, day: date | str) -> int:
        return self.reminders.unack_item(elder_id, plan_item_id, day)

    # ---------------------------------------------------------------- 状态

    def status(self) -> dict:
        pending = [task for task in self.reminders.all_tasks() if task.status == STATUS_PENDING]
        pending.sort(key=lambda task: task.send_at)
        counts = self.reminders.counts()
        return {
            "running": bool(self._loop_task and not self._loop_task.done()),
            "ticks": self.ticks,
            "lastTickAt": self.last_tick_at,
            "lastSummary": self.last_summary,
            "tickSeconds": self.settings.scheduler_tick_seconds,
            "manualTickAllowed": self.settings.scheduler_manual_tick,
            "channels": self.channels.describe(),
            "counts": {
                "pending": counts.get(STATUS_PENDING, 0),
                "sent": counts.get(STATUS_SENT, 0),
                "acked": counts.get(STATUS_ACKED, 0),
                "missed": counts.get(STATUS_MISSED, 0),
                "skipped": counts.get(STATUS_SKIPPED, 0),
                "canceled": counts.get("canceled", 0),
            },
            "nextSendAt": pending[0].send_at if pending else "",
            "graceMinutes": self.settings.reminder_grace_minutes,
            "repeatMinutes": self.settings.reminder_repeat_minutes,
            "missMinutes": self.settings.reminder_miss_minutes,
            "weakWindow": list(self._weak_window()),
        }

    # ------------------------------------------------------------ 后台循环

    async def run_forever(self) -> None:
        interval = max(1.0, float(self.settings.scheduler_tick_seconds))
        logger.info("提醒调度器启动，每 %s 秒一次 tick", interval)
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 —— 一次 tick 出错不能让调度器停摆
                logger.exception("调度 tick 出错，下一轮继续")
            await asyncio.sleep(interval)

    def start(self) -> None:
        if self._loop_task and not self._loop_task.done():
            return
        self._loop_task = asyncio.create_task(self.run_forever())

    async def stop(self) -> None:
        if not self._loop_task:
            return
        self._loop_task.cancel()
        try:
            await self._loop_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        self._loop_task = None
        logger.info("提醒调度器已停止")


def _parse_hhmm(value: str) -> clock_time:
    try:
        hour, minute = value.split(":")
        return clock_time(int(hour), int(minute))
    except (ValueError, AttributeError):
        return clock_time(9, 0)
