"""提醒与调度接口契约测试（含「打卡即确认」的跨模块联动）"""

from __future__ import annotations

import unittest
from datetime import datetime

from fastapi.testclient import TestClient

from app.config import Settings
from app.llm.fake import FakeProvider
from app.main import create_app


class Clock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment


class ReminderApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock(datetime(2026, 9, 24, 7, 30))
        self.app = create_app(
            settings=Settings(llm_provider="fake", llm_api_key="", scheduler_enabled=False),
            provider=FakeProvider(delay=0),
            clock=self.clock,
        )
        self.client = TestClient(self.app)

    # ---------------------------------------------------------------- 助手

    def draft_and_confirm(self, elder_id: str = "e_1") -> dict:
        draft = self.client.post(
            "/v1/plans/draft", json={"elderId": elder_id, "polish": False}
        ).json()["plan"]
        confirmed = self.client.post("/v1/plans/confirm", json={"planId": draft["id"]})
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        return confirmed.json()["plan"]

    def tick(self, at: str | None = None) -> dict:
        body = {"at": at} if at else {}
        response = self.client.post("/v1/scheduler/tick", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    # ------------------------------------------------------------ 闸门

    def test_unconfirmed_plan_creates_no_reminder(self) -> None:
        self.client.post("/v1/plans/draft", json={"elderId": "e_1", "polish": False})
        summary = self.tick()["summary"]
        self.assertEqual(summary["created"], 0)
        self.assertEqual(self.client.get("/v1/reminders/inbox", params={"elderId": "e_1"}).json()["count"], 0)

    # ------------------------------------------------------------ 投递

    def test_reminder_lands_in_inbox_after_due(self) -> None:
        self.draft_and_confirm()
        self.tick()
        body = self.client.get("/v1/reminders/inbox", params={"elderId": "e_1"}).json()
        self.assertEqual(body["count"], 0, "还没到点就不该出现在收件箱里")

        result = self.tick("2026-09-24T08:00:00")
        self.assertEqual(result["summary"]["sent"], 1)
        inbox = self.client.get("/v1/reminders/inbox", params={"elderId": "e_1"}).json()
        self.assertEqual(inbox["count"], 1)
        task = inbox["tasks"][0]
        for key in ("id", "planId", "planItemId", "elderId", "title", "label", "level", "levelLabel", "sendAt", "sentAt", "status", "channel"):
            self.assertIn(key, task)
        self.assertEqual(task["sendAt"], "2026-09-24T08:00:00")
        self.assertEqual(task["channel"], "inbox")
        self.assertEqual(task["levelLabel"], "普通提醒")

    def test_reminder_text_reaches_conversation(self) -> None:
        """站内通道会把提醒写进会话——老人打开聊天就能看到"""
        self.draft_and_confirm()
        self.tick("2026-09-24T08:00:00")
        history = self.client.get("/v1/chat/history", params={"conversationId": "c_son"}).json()
        texts = [message.get("text", "") for message in history["messages"]]
        self.assertTrue(any("量完血压" in text for text in texts), texts)

    def test_read_receipt_clears_inbox(self) -> None:
        self.draft_and_confirm()
        self.tick("2026-09-24T08:00:00")
        task = self.client.get("/v1/reminders/inbox", params={"elderId": "e_1"}).json()["tasks"][0]
        marked = self.client.post(
            "/v1/reminders/read", json={"elderId": "e_1", "taskId": task["id"]}
        ).json()
        self.assertEqual(marked["marked"], 1)
        self.assertEqual(self.client.get("/v1/reminders/inbox", params={"elderId": "e_1"}).json()["count"], 0)

    def test_tasks_are_traceable(self) -> None:
        self.draft_and_confirm()
        self.tick("2026-09-24T08:00:00")
        body = self.client.get(
            "/v1/reminders/tasks", params={"elderId": "e_1", "date": "2026-09-24"}
        ).json()
        self.assertEqual(body["date"], "2026-09-24")
        self.assertTrue(body["tasks"])
        statuses = {task["status"] for task in body["tasks"]}
        self.assertIn("sent", statuses)
        self.assertIn("pending", statuses, "当天后面的提醒应已在队列里")

    def test_bad_date_returns_contract_error(self) -> None:
        response = self.client.get("/v1/reminders/tasks", params={"elderId": "e_1", "date": "24/09/2026"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_date")

    # -------------------------------------------------------- 打卡即确认

    def test_checkin_acks_reminder(self) -> None:
        self.draft_and_confirm()
        self.tick("2026-09-24T08:00:00")
        task = self.client.get("/v1/reminders/inbox", params={"elderId": "e_1"}).json()["tasks"][0]

        checkin = self.client.post(
            "/v1/plans/checkin", json={"planItemId": task["planItemId"], "elderId": "e_1"}
        )
        self.assertEqual(checkin.status_code, 200, checkin.text)

        tasks = self.client.get(
            "/v1/reminders/tasks", params={"elderId": "e_1", "date": "2026-09-24"}
        ).json()["tasks"]
        acked = [item for item in tasks if item["planItemId"] == task["planItemId"]]
        self.assertTrue(acked)
        self.assertEqual(acked[0]["status"], "acked")
        self.assertTrue(acked[0]["ackAt"])
        self.assertTrue(acked[0]["readAt"])

        # 取消打卡要能改回来
        self.client.post(
            "/v1/plans/checkin", json={"planItemId": task["planItemId"], "elderId": "e_1", "done": False}
        )
        tasks = self.client.get(
            "/v1/reminders/tasks", params={"elderId": "e_1", "date": "2026-09-24"}
        ).json()["tasks"]
        again = [item for item in tasks if item["planItemId"] == task["planItemId"]][0]
        self.assertEqual(again["status"], "sent")
        self.assertEqual(again["ackAt"], "")

    # ------------------------------------------------------------ 调度状态

    def test_scheduler_status_contract(self) -> None:
        self.draft_and_confirm()
        self.tick()
        status = self.client.get("/v1/scheduler/status").json()
        for key in ("running", "ticks", "lastTickAt", "tickSeconds", "manualTickAllowed", "channels", "counts", "nextSendAt", "weakWindow"):
            self.assertIn(key, status)
        self.assertFalse(status["running"], "测试里关掉了后台循环，只手动 tick")
        self.assertEqual([channel["name"] for channel in status["channels"]], ["inbox", "log"])
        self.assertEqual(status["counts"]["pending"] > 0, True)
        self.assertTrue(status["nextSendAt"].startswith("2026-09-24T"))

    def test_healthz_reports_scheduler(self) -> None:
        body = self.client.get("/healthz").json()
        self.assertIn("scheduler", body)
        self.assertIn("counts", body["scheduler"])

    def test_manual_tick_can_be_disabled(self) -> None:
        app = create_app(
            settings=Settings(
                llm_provider="fake", scheduler_enabled=False, scheduler_manual_tick=False
            ),
            provider=FakeProvider(delay=0),
            clock=self.clock,
        )
        client = TestClient(app)
        response = client.post("/v1/scheduler/tick", json={})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "manual_tick_disabled")

    def test_bad_tick_time_returns_400(self) -> None:
        response = self.client.post("/v1/scheduler/tick", json={"at": "昨天早上"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_datetime")

    # ------------------------------------------------------------ 过期与静默

    def test_expired_reminders_are_skipped_not_backfilled(self) -> None:
        self.draft_and_confirm()
        result = self.tick("2026-09-24T15:00:00")
        self.assertEqual(result["summary"]["sent"], 0)
        self.assertGreater(result["summary"]["skipped"], 0)
        tasks = self.client.get(
            "/v1/reminders/tasks", params={"elderId": "e_1", "date": "2026-09-24"}
        ).json()["tasks"]
        skipped = [task for task in tasks if task["status"] == "skipped"]
        self.assertTrue(skipped)
        self.assertTrue(any("过期" in task["note"] for task in skipped))


if __name__ == "__main__":
    unittest.main()
