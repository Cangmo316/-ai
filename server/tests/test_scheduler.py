"""
提醒调度器单测

守的是「提醒到底发出去没有」这件事，以及四条策略规则：
过期不补发、强提醒重复一次、弱提醒超窗不顺延、未确认计划不产生任何提醒。

时间全部由注入的 `clock` 控制——调度逻辑不能只有等到真实时间才能测。
"""

from __future__ import annotations

import asyncio
import unittest
from datetime import date, datetime, timedelta

from app.config import Settings
from app.knowledge.loader import load_knowledge
from app.models.elder import ElderStore
from app.models.message import ConversationStore
from app.plan.engine import PlanEngine
from app.plan.models import STATUS_ACTIVE, CarePlan, PlanItem
from app.plan.store import PlanStore
from app.schedule.channels import ChannelRegistry, InboxChannel, LogChannel, PushChannel
from app.schedule.models import (
    LEVEL_NORMAL,
    LEVEL_STRONG,
    LEVEL_WEAK,
    STATUS_ACKED,
    STATUS_MISSED,
    STATUS_PENDING,
    STATUS_SENT,
    STATUS_SKIPPED,
)
from app.schedule.scheduler import Scheduler
from app.schedule.store import ReminderStore


class FakeClock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment

    def set(self, moment: datetime) -> None:
        self.moment = moment

    def advance(self, **kwargs) -> None:
        self.moment = self.moment + timedelta(**kwargs)


class FailingChannel(PushChannel):
    name = "failing"

    async def deliver(self, task, text):
        from app.schedule.channels import ChannelResult

        return ChannelResult(ok=False, channel=self.name, detail="通道故障")


def build(moment: datetime = datetime(2026, 9, 24, 7, 30), channels=None, **settings_kwargs):
    settings = Settings(llm_provider="fake", scheduler_enabled=False, **settings_kwargs)
    store = PlanStore()
    elders = ElderStore()
    engine = PlanEngine(load_knowledge(), store, elders, settings)
    conversations = ConversationStore()
    registry = channels or ChannelRegistry([InboxChannel(conversations), LogChannel()])
    clock = FakeClock(moment)
    scheduler = Scheduler(
        engine=engine,
        plan_store=store,
        reminders=ReminderStore(),
        channels=registry,
        elders=elders,
        settings=settings,
        clock=clock,
    )
    return scheduler, engine, store, elders, conversations, clock


def confirm_plan(engine: PlanEngine, elder_id: str = "e_1", start: str = "2026-09-24") -> CarePlan:
    plan = engine.build_plan(elder_id, start=start)
    engine.submit(plan)
    engine.confirm(plan)
    return plan


def tick(scheduler: Scheduler, moment: datetime | None = None) -> dict:
    return asyncio.run(scheduler.tick(moment))


class TaskGenerationTests(unittest.TestCase):
    def test_unconfirmed_plan_generates_nothing(self) -> None:
        """闸门在调度器这一层也必须成立：没确认的计划不准产生任何提醒。"""
        scheduler, engine, _store, _elders, _conversations, clock = build()
        plan = engine.build_plan("e_1", start="2026-09-24")
        summary = tick(scheduler)
        self.assertEqual(summary["created"], 0)
        engine.submit(plan)
        summary = tick(scheduler)
        self.assertEqual(summary["created"], 0)
        self.assertEqual(scheduler.reminders.counts(), {})

    def test_tasks_created_for_due_items_only(self) -> None:
        scheduler, engine, _store, _elders, _conversations, clock = build()
        plan = confirm_plan(engine)
        tick(scheduler)
        tasks = scheduler.reminders.all_tasks()
        self.assertTrue(tasks)
        # 只有今天该做的项才有任务（年度/季度项不在窗口内）
        due_items = [item for item, due, done in engine.due_items(plan, date(2026, 9, 24)) if due and not done]
        self.assertEqual(len(tasks), len(due_items))
        for task in tasks:
            self.assertEqual(task.elder_id, "e_1")
            self.assertTrue(task.conversation_id)
            self.assertTrue(task.send_at.startswith("2026-09-24"))

    def test_generation_is_idempotent(self) -> None:
        scheduler, engine, _store, _elders, _conversations, clock = build()
        confirm_plan(engine)
        tick(scheduler)
        first = len(scheduler.reminders.all_tasks())
        tick(scheduler)
        tick(scheduler)
        self.assertEqual(len(scheduler.reminders.all_tasks()), first)

    def test_levels_are_derived(self) -> None:
        scheduler, engine, store, _elders, _conversations, clock = build()
        store.add(
            CarePlan(
                id="plan_lv",
                elder_id="e_1",
                status=STATUS_ACTIVE,
                items=[
                    PlanItem(id="i_strong", time="09:00", type="用药", title="吃药", freq="每日", strong_remind=True),
                    PlanItem(id="i_normal", time="10:00", type="活动", title="散步", freq="每日"),
                    PlanItem(id="i_weak", time="11:00", type="问候", title="聊两句", freq="每日"),
                ],
            )
        )
        tick(scheduler)
        levels = {task.plan_item_id: task.level for task in scheduler.reminders.all_tasks()}
        self.assertEqual(levels["i_strong"], LEVEL_STRONG)
        self.assertEqual(levels["i_normal"], LEVEL_NORMAL)
        self.assertEqual(levels["i_weak"], LEVEL_WEAK)


class DeliveryTests(unittest.TestCase):
    def test_not_sent_before_due_then_sent_at_due(self) -> None:
        scheduler, engine, _store, _elders, conversations, clock = build()
        confirm_plan(engine)
        tick(scheduler)  # 07:30，还不到任何一个提醒时间
        self.assertEqual(scheduler.reminders.counts().get(STATUS_SENT, 0), 0)

        clock.set(datetime(2026, 9, 24, 8, 0))
        summary = tick(scheduler)
        self.assertEqual(summary["sent"], 1)
        sent = [task for task in scheduler.reminders.all_tasks() if task.status == STATUS_SENT]
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].channel, "inbox")
        self.assertTrue(sent[0].sent_at)
        # 写入会话，端侧拉历史就能看到
        messages = conversations.history("c_son")
        self.assertTrue(any("量完血压" in message.text for message in messages))

    def test_message_text_uses_elder_address(self) -> None:
        scheduler, engine, _store, _elders, _conversations, clock = build()
        confirm_plan(engine)
        clock.set(datetime(2026, 9, 24, 8, 0))
        tick(scheduler)
        task = [item for item in scheduler.reminders.all_tasks() if item.status == STATUS_SENT][0]
        text = scheduler.message_text(task)
        self.assertTrue(text.startswith("妈 "), text)
        self.assertIn(task.title, text)

    def test_message_text_does_not_duplicate_address(self) -> None:
        """计划项标题已经带了称呼时不能再加一次（实测出现过"妈 妈 该吃药了"）"""
        scheduler, engine, store, _elders, _conversations, clock = build()
        store.add(
            CarePlan(
                id="plan_addr",
                elder_id="e_1",
                status=STATUS_ACTIVE,
                items=[
                    PlanItem(id="i1", time="09:00", type="活动", title="妈 出去走走", freq="每日"),
                    PlanItem(id="i2", time="10:00", type="活动", title="出去走走", freq="每日"),
                ],
            )
        )
        tick(scheduler)
        tasks = {task.plan_item_id: task for task in scheduler.reminders.all_tasks()}
        self.assertEqual(scheduler.message_text(tasks["i1"]), "妈 出去走走")
        self.assertEqual(scheduler.message_text(tasks["i2"]), "妈 出去走走")

    def test_expired_tasks_are_skipped_not_backfilled(self) -> None:
        """服务没运行期间错过的提醒不补发——早上 8 点的提醒下午 3 点响只会添乱。"""
        scheduler, engine, _store, _elders, _conversations, clock = build()
        confirm_plan(engine)
        clock.set(datetime(2026, 9, 24, 15, 0))
        summary = tick(scheduler)
        self.assertEqual(summary["sent"], 0)
        skipped = [task for task in scheduler.reminders.all_tasks() if task.status == STATUS_SKIPPED]
        self.assertTrue(skipped)
        for task in skipped:
            self.assertIn("过期", task.note)

    def test_within_grace_still_delivers(self) -> None:
        scheduler, engine, _store, _elders, _conversations, clock = build()
        confirm_plan(engine)
        # 11:30 的提醒，12:00 才 tick —— 正好卡在 30 分钟宽限边界上，应该发
        clock.set(datetime(2026, 9, 24, 12, 0))
        summary = tick(scheduler)
        self.assertGreaterEqual(summary["sent"], 1)
        texts = [
            task.title for task in scheduler.reminders.all_tasks() if task.status == STATUS_SENT
        ]
        self.assertTrue(any("盐" in text for text in texts), texts)

    def test_failed_channel_keeps_task_pending(self) -> None:
        scheduler, engine, _store, _elders, _conversations, clock = build(
            channels=ChannelRegistry([FailingChannel()])
        )
        confirm_plan(engine)
        clock.set(datetime(2026, 9, 24, 8, 0))
        summary = tick(scheduler)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["sent"], 0)
        task = [item for item in scheduler.reminders.all_tasks() if "T08:00:00" in item.send_at][0]
        self.assertEqual(task.status, STATUS_PENDING, "投递失败要留在待投递，下轮重试")
        self.assertIn("投递失败", task.note)

    def test_weak_reminder_outside_window_is_skipped(self) -> None:
        scheduler, engine, store, _elders, _conversations, clock = build()
        store.add(
            CarePlan(
                id="plan_weak",
                elder_id="e_1",
                status=STATUS_ACTIVE,
                items=[
                    PlanItem(id="i_early", time="07:00", type="问候", title="早", freq="每日"),
                    PlanItem(id="i_late", time="21:00", type="问候", title="晚", freq="每日"),
                    PlanItem(id="i_ok", time="10:00", type="问候", title="白天", freq="每日"),
                ],
            )
        )
        tick(scheduler)
        statuses = {
            task.plan_item_id: (task.status, task.note) for task in scheduler.reminders.all_tasks()
        }
        self.assertEqual(statuses["i_early"][0], STATUS_SKIPPED)
        self.assertIn("时间窗", statuses["i_early"][1])
        self.assertEqual(statuses["i_late"][0], STATUS_SKIPPED)
        self.assertEqual(statuses["i_ok"][0], STATUS_PENDING)

    def test_weak_reminder_skipped_when_tick_runs_late(self) -> None:
        """弱提醒在窗口内登记、但延迟到窗口外才投递：也不该发。"""
        scheduler, engine, store, _elders, _conversations, clock = build()
        store.add(
            CarePlan(
                id="plan_weak2",
                elder_id="e_1",
                status=STATUS_ACTIVE,
                items=[PlanItem(id="i_edge", time="19:59", type="问候", title="聊两句", freq="每日")],
            )
        )
        tick(scheduler)
        clock.set(datetime(2026, 9, 24, 20, 30))
        summary = tick(scheduler)
        self.assertEqual(summary["sent"], 0)
        task = scheduler.reminders.all_tasks()[0]
        self.assertEqual(task.status, STATUS_SKIPPED)
        self.assertIn("时间窗", task.note)


class RepeatAndMissTests(unittest.TestCase):
    def _strong_plan(self, store) -> CarePlan:
        plan = CarePlan(
            id="plan_strong",
            elder_id="e_1",
            status=STATUS_ACTIVE,
            items=[
                PlanItem(id="i_med", time="08:00", type="用药", title="吃药", freq="每日", strong_remind=True),
                PlanItem(id="i_walk", time="15:30", type="活动", title="散步", freq="每日"),
            ],
        )
        store.add(plan)
        return plan

    def test_strong_reminder_repeats_once(self) -> None:
        scheduler, engine, store, _elders, _conversations, clock = build()
        self._strong_plan(store)
        clock.set(datetime(2026, 9, 24, 8, 0))
        tick(scheduler)
        task = [item for item in scheduler.reminders.all_tasks() if item.plan_item_id == "i_med"][0]
        self.assertEqual(task.status, STATUS_SENT)

        clock.set(datetime(2026, 9, 24, 8, 4))
        summary = tick(scheduler)
        self.assertEqual(summary["repeated"], 0, "没到重复间隔不该响第二次")

        clock.set(datetime(2026, 9, 24, 8, 6))
        summary = tick(scheduler)
        self.assertEqual(summary["repeated"], 1)
        self.assertEqual(task.repeat_count, 1)

        clock.set(datetime(2026, 9, 24, 8, 30))
        summary = tick(scheduler)
        self.assertEqual(summary["repeated"], 0, "超过次数上限后不再重复")

    def test_normal_reminder_never_repeats(self) -> None:
        scheduler, engine, store, _elders, _conversations, clock = build()
        self._strong_plan(store)
        clock.set(datetime(2026, 9, 24, 15, 30))
        tick(scheduler)
        clock.set(datetime(2026, 9, 24, 15, 45))
        summary = tick(scheduler)
        self.assertEqual(summary["repeated"], 0)

    def test_stale_task_marked_missed(self) -> None:
        scheduler, engine, store, _elders, _conversations, clock = build()
        self._strong_plan(store)
        clock.set(datetime(2026, 9, 24, 8, 0))
        tick(scheduler)
        clock.set(datetime(2026, 9, 24, 9, 1))
        summary = tick(scheduler)
        self.assertGreaterEqual(summary["missed"], 1)
        task = [item for item in scheduler.reminders.all_tasks() if item.plan_item_id == "i_med"][0]
        self.assertEqual(task.status, STATUS_MISSED)


class AckTests(unittest.TestCase):
    def test_checkin_acks_reminder(self) -> None:
        scheduler, engine, _store, _elders, _conversations, clock = build()
        plan = confirm_plan(engine)
        clock.set(datetime(2026, 9, 24, 8, 0))
        tick(scheduler)
        task = [item for item in scheduler.reminders.all_tasks() if item.status == STATUS_SENT][0]
        acked = scheduler.ack("e_1", task.plan_item_id, date(2026, 9, 24))
        self.assertEqual(acked, 1)
        self.assertEqual(task.status, STATUS_ACKED)
        self.assertTrue(task.ack_at)
        self.assertTrue(task.read_at, "打卡也算看到了")

        scheduler.unack("e_1", task.plan_item_id, date(2026, 9, 24))
        self.assertEqual(task.status, STATUS_SENT)
        self.assertEqual(task.ack_at, "")

    def test_early_checkin_cancels_pending_reminder(self) -> None:
        """老人提前做了，就别再提醒（不是"漏了一次"，是取消）"""
        scheduler, engine, _store, _elders, _conversations, clock = build()
        confirm_plan(engine)
        tick(scheduler)
        pending = [item for item in scheduler.reminders.all_tasks() if item.status == STATUS_PENDING]
        self.assertTrue(pending)
        scheduler.ack("e_1", pending[0].plan_item_id, date(2026, 9, 24))
        self.assertEqual(pending[0].status, "canceled")
        self.assertIn("提前打卡", pending[0].note)

        clock.set(datetime(2026, 9, 24, 23, 0))
        summary = tick(scheduler)
        self.assertEqual(summary["sent"], 0)


class InboxTests(unittest.TestCase):
    def test_inbox_and_read_receipt(self) -> None:
        scheduler, engine, _store, _elders, _conversations, clock = build()
        confirm_plan(engine)
        clock.set(datetime(2026, 9, 24, 8, 0))
        tick(scheduler)
        inbox = scheduler.reminders.inbox("e_1")
        self.assertEqual(len(inbox), 1)
        self.assertEqual(scheduler.reminders.mark_read("e_1", inbox[0].id, clock()), 1)
        self.assertEqual(scheduler.reminders.inbox("e_1"), [])
        self.assertTrue(inbox[0].read_at)

    def test_inbox_ignores_other_elders(self) -> None:
        scheduler, engine, _store, _elders, _conversations, clock = build()
        confirm_plan(engine, elder_id="e_2")
        clock.set(datetime(2026, 9, 24, 11, 45))  # e_2 的 11:30 午餐提醒已到点
        tick(scheduler)
        self.assertEqual(scheduler.reminders.inbox("e_1"), [])
        self.assertTrue(scheduler.reminders.inbox("e_2"))


class PlanChangeTests(unittest.TestCase):
    def test_new_plan_cancels_old_pending_tasks(self) -> None:
        scheduler, engine, _store, _elders, _conversations, clock = build()
        first = confirm_plan(engine)
        tick(scheduler)
        before = [task for task in scheduler.reminders.all_tasks() if task.status == STATUS_PENDING]
        self.assertTrue(before)

        second = engine.build_plan("e_1", start="2026-09-24")
        engine.submit(second)
        engine.confirm(second)
        summary = tick(scheduler)
        self.assertGreaterEqual(summary["canceled"], len(before))
        for task in before:
            self.assertEqual(task.status, "canceled")
            self.assertIn("计划已变更", task.note)
        # 旧计划的提醒不再被投递
        clock.set(datetime(2026, 9, 24, 23, 0))
        summary = tick(scheduler)
        self.assertEqual(
            len([task for task in scheduler.reminders.all_tasks() if task.plan_id == first.id and task.status == STATUS_SENT]),
            0,
        )


class StatusTests(unittest.TestCase):
    def test_status_reports_channel_and_next_send(self) -> None:
        scheduler, engine, _store, _elders, _conversations, clock = build()
        confirm_plan(engine)
        tick(scheduler)
        status = scheduler.status()
        self.assertFalse(status["running"])
        self.assertEqual(status["ticks"], 1)
        self.assertEqual(status["channels"][0]["name"], "inbox")
        self.assertTrue(status["nextSendAt"].startswith("2026-09-24"))
        self.assertGreater(status["counts"]["pending"], 0)
        self.assertEqual(status["weakWindow"], ["09:00", "20:00"])
        self.assertTrue(status["manualTickAllowed"])

    def test_background_loop_starts_and_stops(self) -> None:
        scheduler, engine, _store, _elders, _conversations, clock = build()
        confirm_plan(engine)

        async def run() -> tuple[bool, bool, int]:
            scheduler.start()
            await asyncio.sleep(0.05)
            running = scheduler.status()["running"]
            await scheduler.stop()
            return running, scheduler.status()["running"], scheduler.ticks

        running, after_stop, ticks = asyncio.run(run())
        self.assertTrue(running)
        self.assertFalse(after_stop)
        self.assertGreaterEqual(ticks, 1, "启动后应立刻跑过一次 tick")


if __name__ == "__main__":
    unittest.main()
