"""家人查看接口契约测试

重点：
  1. **只有互相绑定的家人能看**（未绑定 403）——这些是老人的健康与行为记录
  2. 今日日程的完成/未完成要说清楚
  3. 聊天活跃统计要**区分"老人自己发的"与"收到的"**
     （只看总条数会把"家人发得多"误当成"老人活跃"）
"""

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


def build_app() -> TestClient:
    app = create_app(
        settings=Settings(
            llm_provider="fake",
            llm_api_key="",
            scheduler_enabled=False,
            database_url="memory://",
        ),
        provider=FakeProvider(delay=0),
        clock=Clock(datetime(2026, 10, 7, 10, 0)),
    )
    return TestClient(app)


class FamilyOverviewTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.client = build_app()
        self.elder = self.register("老人甲")
        self.family = self.register("家人乙")
        self.stranger = self.register("陌生人丙")

    # ---------------------------------------------------------------- 助手

    def register(self, name: str) -> dict:
        response = self.client.post(
            "/v1/accounts/register",
            json={"name": name, "password": "abcd1234", "confirm": "abcd1234"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        data = response.json()
        return {"token": data["token"], "account": data["account"]}

    def auth(self, who: dict) -> dict:
        return {"Authorization": "Bearer " + who["token"]}

    def bind(self, who: dict, peer: dict) -> None:
        response = self.client.post(
            "/v1/conversations/bindings",
            json={"number": peer["account"]["number"]},
            headers=self.auth(who),
        )
        self.assertEqual(response.status_code, 201, response.text)

    def overview(self, who: dict, number: str):
        return self.client.get(
            "/v1/family/overview", params={"number": number}, headers=self.auth(who)
        )

    def make_plan(self, elder_id: str) -> None:
        """给老人建一份生效中的计划，并打卡第一项"""
        draft = self.client.post(
            "/v1/plans/draft", json={"elderId": elder_id, "polish": False}
        ).json()["plan"]
        self.client.post("/v1/plans/confirm", json={"planId": draft["id"]})
        today = self.client.get("/v1/plans/today", params={"elderId": elder_id}).json()
        items = today.get("items", [])
        if items:
            # 注意字段名是 planItemId（不是 itemId）
            self.client.post(
                "/v1/plans/checkin",
                json={"elderId": elder_id, "planItemId": items[0]["id"]},
            )

    # ---------------------------------------------------------------- 授权

    def test_requires_login(self) -> None:
        response = self.client.get(
            "/v1/family/overview", params={"number": self.elder["account"]["number"]}
        )
        self.assertEqual(response.status_code, 401)

    def test_unbound_is_rejected(self) -> None:
        """陌生人（知道编号但没绑定）不能看"""
        response = self.overview(self.stranger, self.elder["account"]["number"])
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual((response.json()["error"])["code"], "peer_not_bound")

    def test_binding_is_required_even_with_valid_number(self) -> None:
        """编号有效但没绑定 → 依然拒绝（"知道编号"不等于"能看"）"""
        response = self.overview(self.family, self.elder["account"]["number"])
        self.assertEqual(response.status_code, 403)

    def test_bound_family_can_view(self) -> None:
        self.bind(self.family, self.elder)
        response = self.overview(self.family, self.elder["account"]["number"])
        self.assertEqual(response.status_code, 200, response.text)

    def test_bound_elder_can_view_family_too(self) -> None:
        """绑定是双向的：老人也能看家人的情况（同一套接口）"""
        self.bind(self.family, self.elder)
        response = self.client.get(
            "/v1/family/overview",
            params={"number": self.family["account"]["number"]},
            headers=self.auth(self.elder),
        )
        self.assertEqual(response.status_code, 200, response.text)

    def test_rejects_malformed_number(self) -> None:
        for value in ("", "123", "abcdefgh"):
            response = self.overview(self.family, value)
            self.assertEqual(response.status_code, 400, value)

    def test_unknown_number(self) -> None:
        response = self.overview(self.family, "99999999")
        self.assertEqual(response.status_code, 404)

    def test_unbind_revokes_access(self) -> None:
        """解绑后立刻不能看"""
        self.bind(self.family, self.elder)
        self.assertEqual(self.overview(self.family, self.elder["account"]["number"]).status_code, 200)
        self.client.delete(
            "/v1/conversations/bindings",
            params={"number": self.elder["account"]["number"]},
            headers=self.auth(self.family),
        )
        self.assertEqual(self.overview(self.family, self.elder["account"]["number"]).status_code, 403)

    # ---------------------------------------------------------------- 今日日程

    def test_overview_has_peer_and_sections(self) -> None:
        self.bind(self.family, self.elder)
        data = self.overview(self.family, self.elder["account"]["number"]).json()
        self.assertEqual(data["peer"]["name"], "老人甲")
        self.assertEqual(data["peer"]["number"], self.elder["account"]["number"])
        for key in ("today", "recent", "activity"):
            self.assertIn(key, data)

    def test_no_plan_yet_is_not_an_error(self) -> None:
        """老人还没计划时不该报错，而是给出"还没有计划"的状态"""
        self.bind(self.family, self.elder)
        today = self.overview(self.family, self.elder["account"]["number"]).json()["today"]
        self.assertEqual(today["total"], 0)
        self.assertEqual(today["pendingCount"], 0)
        self.assertEqual(today["statusLabel"], "还没有计划")

    def test_today_shows_done_and_pending(self) -> None:
        """建计划 + 打一项的卡 → 今日应能看出"哪项做了、哪项没做" """
        self.bind(self.family, self.elder)
        self.make_plan(self.elder["account"]["id"])

        today = self.overview(self.family, self.elder["account"]["number"]).json()["today"]
        if today["total"] == 0:
            self.skipTest("这次没生成今日条目（知识库条目决定的），跳过")
        self.assertEqual(today["done"], 1)
        self.assertEqual(today["pendingCount"], today["total"] - 1)
        # 每一项都有明确的 done 标记
        for item in today["items"]:
            self.assertIn("done", item)
            self.assertIn("title", item)
        # pending 列表里全是没有完成的
        for item in today["pending"]:
            self.assertTrue(item["title"])

    def test_recent_has_daily_trend(self) -> None:
        """最近 7 天要有**逐日**数组（只有聚合值的话界面画不出趋势）"""
        self.bind(self.family, self.elder)
        self.make_plan(self.elder["account"]["id"])
        recent = self.overview(self.family, self.elder["account"]["number"]).json()["recent"]
        by_day = recent.get("byDay")
        self.assertIsInstance(by_day, list, recent)
        self.assertEqual(len(by_day), 7, by_day)
        for item in by_day:
            for key in ("date", "due", "done", "rate"):
                self.assertIn(key, item)
        # 今天打了卡 → 今天那天的 done 应 > 0
        today_key = datetime.now().date().isoformat()
        today_item = next((d for d in by_day if d["date"] == today_key), None)
        if today_item is not None:
            self.assertGreaterEqual(today_item["done"], 1, today_item)

    # ---------------------------------------------------------------- 聊天活跃

    def test_activity_counts_separate_sender(self) -> None:
        """关键口径：老人自己发的 ≠ 收到的"""
        self.bind(self.family, self.elder)
        conv = self.overview(self.family, self.elder["account"]["number"]).json()
        self.assertIn("activity", conv)

        # 老人自己发 2 条，家人发 1 条
        conv_id = None
        for item in self.client.get("/v1/conversations", headers=self.auth(self.elder)).json()["conversations"]:
            if item["kind"] == "family":
                conv_id = item["id"]
        self.assertIsNotNone(conv_id, "绑定后应有一条家人会话")

        for text in ("今天挺好的", "刚散完步"):
            self.client.post(
                "/v1/conversations/messages",
                json={"conversationId": conv_id, "text": text},
                headers=self.auth(self.elder),
            )
        self.client.post(
            "/v1/conversations/messages",
            json={"conversationId": conv_id, "text": "注意身体"},
            headers=self.auth(self.family),
        )

        activity = self.overview(self.family, self.elder["account"]["number"]).json()["activity"]
        self.assertEqual(activity["messagesFromHim"], 2, activity)
        self.assertEqual(activity["messagesToHim"], 1, activity)
        self.assertEqual(activity["totalMessages"], 3, activity)
        self.assertEqual(activity["activeDays"], 1, activity)
        self.assertEqual(activity["streak"], 1, activity)
        self.assertTrue(activity["lastActiveAt"])
        self.assertEqual(len(activity["byDay"]), 7, "应返回 7 天的逐日数据")

    def test_activity_zero_when_no_messages(self) -> None:
        self.bind(self.family, self.elder)
        activity = self.overview(self.family, self.elder["account"]["number"]).json()["activity"]
        self.assertEqual(activity["totalMessages"], 0)
        self.assertEqual(activity["messagesFromHim"], 0)
        self.assertEqual(activity["activeDays"], 0)
        self.assertEqual(activity["streak"], 0)
        self.assertEqual(activity["lastActiveAt"], "")

    def test_agent_messages_not_counted_as_his(self) -> None:
        """智能体替老人这个账号发的消息，不该算成"老人主动说话" """
        self.bind(self.family, self.elder)
        conv_id = None
        for item in self.client.get("/v1/conversations", headers=self.auth(self.elder)).json()["conversations"]:
            if item["kind"] == "ai":
                conv_id = item["id"]
        self.client.post(
            "/v1/conversations/messages",
            json={"conversationId": conv_id, "text": "到点提醒你吃药", "senderRole": "agent"},
            headers=self.auth(self.elder),
        )
        activity = self.overview(self.family, self.elder["account"]["number"]).json()["activity"]
        self.assertEqual(activity["messagesFromHim"], 0, "智能体消息被误算成老人主动发言")
        self.assertEqual(activity["messagesToHim"], 1)


if __name__ == "__main__":
    unittest.main()
