"""计划接口契约测试（含对话里的计划卡片）"""

from __future__ import annotations

import json
import unittest

from fastapi.testclient import TestClient

from app.config import Settings
from app.llm.fake import FakeProvider
from app.main import create_app


def parse_sse(raw: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    name = "message"
    data_lines: list[str] = []
    for line in raw.split("\n"):
        if line.endswith("\r"):
            line = line[:-1]
        if line == "":
            if data_lines:
                events.append((name, json.loads("\n".join(data_lines))))
            name = "message"
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            name = value
        elif field == "data":
            data_lines.append(value)
    if data_lines:
        events.append((name, json.loads("\n".join(data_lines))))
    return events


class PlanApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(
            settings=Settings(llm_provider="fake", llm_api_key=""),
            provider=FakeProvider(delay=0),
        )
        self.client = TestClient(self.app)

    def create_active_plan(self, elder_id: str = "e_1", polish: bool = False) -> dict:
        response = self.client.post(
            "/v1/plans/draft", json={"elderId": elder_id, "polish": polish, "goal": "稳住日常起居"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        plan = response.json()["plan"]
        confirmed = self.client.post("/v1/plans/confirm", json={"planId": plan["id"], "actor": "女儿小丽"})
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        return confirmed.json()["plan"]

    # ------------------------------------------------------------ 生成闸门

    def test_draft_is_pending_and_creates_no_reminder(self) -> None:
        response = self.client.post("/v1/plans/draft", json={"elderId": "e_1", "polish": False})
        body = response.json()
        self.assertEqual(body["plan"]["status"], "pending_confirm")
        self.assertEqual(body["plan"]["statusLabel"], "等家里人确认")
        self.assertTrue(body["plan"]["items"])
        self.assertIn("确认后才生效", body["notice"])

        today = self.client.get("/v1/plans/today", params={"elderId": "e_1"}).json()
        self.assertEqual(today["total"], 0, "未确认的草稿不能产生任何提醒")
        self.assertEqual(today["statusLabel"], "还没有计划")

    def test_draft_can_stay_as_draft(self) -> None:
        response = self.client.post(
            "/v1/plans/draft", json={"elderId": "e_1", "submit": False, "polish": False}
        )
        self.assertEqual(response.json()["plan"]["status"], "draft")
        pending = self.client.get("/v1/plans/pending", params={"elderId": "e_1"}).json()
        self.assertEqual(pending["plans"], [])

    def test_plan_items_carry_basis(self) -> None:
        plan = self.create_active_plan()
        today = self.client.get("/v1/plans/today", params={"elderId": "e_1"}).json()
        self.assertTrue(today["items"])
        for item in today["items"]:
            with self.subTest(item=item["id"]):
                self.assertTrue(item["basis"]["sourceName"])
                self.assertTrue(item["basis"]["version"])
                self.assertIn("§", item["basis"]["text"])
                self.assertTrue(item["basis"]["boundary"])
        self.assertEqual(today["planId"], plan["id"])

    def test_confirm_activates_and_ends_previous(self) -> None:
        first = self.create_active_plan()
        second_draft = self.client.post(
            "/v1/plans/draft", json={"elderId": "e_1", "polish": False}
        ).json()["plan"]
        # 新草稿待确认期间，旧计划继续执行
        today = self.client.get("/v1/plans/today", params={"elderId": "e_1"}).json()
        self.assertEqual(today["planId"], first["id"])
        self.assertGreater(today["total"], 0)

        self.client.post("/v1/plans/confirm", json={"planId": second_draft["id"]})
        today = self.client.get("/v1/plans/today", params={"elderId": "e_1"}).json()
        self.assertEqual(today["planId"], second_draft["id"])

        history = self.client.get("/v1/plans/history", params={"elderId": "e_1"}).json()["plans"]
        statuses = {item["id"]: item["status"] for item in history}
        self.assertEqual(statuses[first["id"]], "ended")
        self.assertEqual(statuses[second_draft["id"]], "active")

    def test_reject_keeps_previous_plan(self) -> None:
        first = self.create_active_plan()
        draft = self.client.post("/v1/plans/draft", json={"elderId": "e_1", "polish": False}).json()["plan"]
        response = self.client.post(
            "/v1/plans/reject", json={"planId": draft["id"], "reason": "时间不合适", "actor": "儿子小明"}
        )
        self.assertEqual(response.json()["plan"]["status"], "rejected")
        self.assertEqual(response.json()["plan"]["rejectedReason"], "时间不合适")
        today = self.client.get("/v1/plans/today", params={"elderId": "e_1"}).json()
        self.assertEqual(today["planId"], first["id"])

    # ---------------------------------------------------------------- 打卡

    def test_checkin_and_undo_flow(self) -> None:
        self.create_active_plan()
        today = self.client.get("/v1/plans/today", params={"elderId": "e_1"}).json()
        item = today["items"][0]

        response = self.client.post(
            "/v1/plans/checkin", json={"planItemId": item["id"], "elderId": "e_1"}
        )
        body = response.json()
        self.assertTrue(body["done"])
        self.assertEqual(body["planItemId"], item["id"])
        self.assertEqual(body["completed"], 1)
        self.assertEqual(body["total"], today["total"])
        self.assertIsNotNone(body["checkin"])

        again = self.client.post(
            "/v1/plans/checkin", json={"planItemId": item["id"], "elderId": "e_1"}
        ).json()
        self.assertEqual(again["checkin"]["id"], body["checkin"]["id"], "重复打卡应幂等")

        undo = self.client.post(
            "/v1/plans/checkin", json={"planItemId": item["id"], "elderId": "e_1", "done": False}
        ).json()
        self.assertFalse(undo["done"])
        self.assertEqual(undo["completed"], 0)

        # 打卡状态在今日计划里可见
        today = self.client.get("/v1/plans/today", params={"elderId": "e_1"}).json()
        self.assertEqual(today["done"], 0)

    def test_checkin_without_active_plan_is_rejected(self) -> None:
        response = self.client.post("/v1/plans/checkin", json={"planItemId": "nope", "elderId": "e_1"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "plan_not_active")

    def test_checkin_unknown_item(self) -> None:
        self.create_active_plan()
        response = self.client.post("/v1/plans/checkin", json={"planItemId": "nope", "elderId": "e_1"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "plan_item_not_found")

    # ------------------------------------------------------ 完成率与调整

    def test_summary_and_adjust(self) -> None:
        plan = self.create_active_plan()
        summary = self.client.get("/v1/plans/summary", params={"elderId": "e_1", "days": 7}).json()
        self.assertTrue(summary["hasPlan"])
        self.assertEqual(summary["planId"], plan["id"])
        self.assertIn("rate", summary["stats"])
        self.assertTrue(summary["suggestion"]["shouldAdjust"])
        self.assertEqual(summary["suggestion"]["advice"], "建议由家属确认后调整；未确认前计划照旧执行")

        adjust = self.client.post("/v1/plans/adjust", json={"planId": plan["id"]}).json()
        self.assertEqual(adjust["plan"]["status"], "adjusting")
        self.assertTrue(adjust["suggestion"]["reasons"])

    def test_summary_without_plan(self) -> None:
        summary = self.client.get("/v1/plans/summary", params={"elderId": "e_3"}).json()
        self.assertFalse(summary["hasPlan"])
        self.assertIsNone(summary["stats"])

    # ------------------------------------------------------------ 错误路径

    def test_unknown_plan_returns_contract_error(self) -> None:
        for path in ("/v1/plans/confirm", "/v1/plans/reject", "/v1/plans/adjust"):
            with self.subTest(path=path):
                response = self.client.post(path, json={"planId": "nope"})
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json()["error"]["code"], "plan_not_found")

    def test_illegal_state_returns_409(self) -> None:
        draft = self.client.post(
            "/v1/plans/draft", json={"elderId": "e_1", "submit": False, "polish": False}
        ).json()["plan"]
        response = self.client.post("/v1/plans/confirm", json={"planId": draft["id"]})
        self.assertEqual(response.status_code, 409)
        body = response.json()
        self.assertEqual(body["error"]["code"], "plan_state")
        self.assertIn("草稿", body["error"]["message"])

    def test_bad_date_returns_400(self) -> None:
        response = self.client.get("/v1/plans/today", params={"elderId": "e_1", "date": "2026/09/24"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_date")

    def test_elders_endpoint_is_marked_demo(self) -> None:
        body = self.client.get("/v1/elders").json()
        self.assertTrue(body["demo"])
        self.assertGreaterEqual(len(body["elders"]), 3)
        self.assertIn("不构成医学建议", body["note"])
        first = body["elders"][0]
        for key in ("id", "name", "age", "chronic", "careLevel"):
            self.assertIn(key, first)

    def test_polish_can_be_enabled_without_breaking_draft(self) -> None:
        body = self.client.post("/v1/plans/draft", json={"elderId": "e_1", "polish": True}).json()
        self.assertIn("polish", body)
        self.assertEqual(body["polish"]["asked"], len(body["plan"]["items"]))
        # 假模型输出不是「序号. 话术」格式 → 全部退回知识库原文，不许出现半成品
        self.assertEqual(body["polish"]["polished"], 0)
        for item in body["plan"]["items"]:
            self.assertTrue(item["title"])

    # -------------------------------------------------------- 对话里的卡片

    def test_chat_attaches_plan_cards_when_asked(self) -> None:
        self.create_active_plan()
        with self.client.stream(
            "POST", "/v1/chat/stream", json={"conversationId": "c_plan", "elderId": "e_1", "text": "今天要做什么"}
        ) as response:
            raw = "".join(response.iter_text())
        events = parse_sse(raw)
        cards = [payload for name, payload in events if name == "card"]
        self.assertTrue(cards, "问「今天要做什么」时应该把今日计划作为卡片发出来")
        self.assertLessEqual(len(cards), 3)
        plan = cards[0]["card"]["plan"]
        for key in ("time", "title", "desc", "state"):
            self.assertIn(key, plan)
        self.assertEqual(cards[0]["card"]["kind"], "plan_item")
        # 卡片排在 done 之前
        self.assertEqual(events[-1][0], "done")

    def test_chat_without_intent_has_no_card(self) -> None:
        self.create_active_plan()
        with self.client.stream(
            "POST", "/v1/chat/stream", json={"conversationId": "c_plan2", "elderId": "e_1", "text": "我今天有点闷"}
        ) as response:
            raw = "".join(response.iter_text())
        events = parse_sse(raw)
        self.assertFalse([payload for name, payload in events if name == "card"])

    def test_chat_without_plan_has_no_card(self) -> None:
        with self.client.stream(
            "POST", "/v1/chat/stream", json={"conversationId": "c_plan3", "elderId": "e_3", "text": "今天要做什么"}
        ) as response:
            raw = "".join(response.iter_text())
        events = parse_sse(raw)
        self.assertFalse([payload for name, payload in events if name == "card"])

    def test_healthz_reports_knowledge_and_plans(self) -> None:
        self.create_active_plan()
        body = self.client.get("/healthz").json()
        self.assertEqual(body["knowledge"]["entries"], 25)
        self.assertEqual(body["knowledge"]["version"], "0.1.0-draft")
        self.assertEqual(len(body["knowledge"]["sources"]), 3)
        self.assertEqual(body["plans"]["active"], 1)
        self.assertGreaterEqual(body["plans"]["total"], 1)


if __name__ == "__main__":
    unittest.main()
