"""会话与消息接口契约测试

重点盯四件事：
  1. **未读数**：不是自己发的、且晚于自己已读边界的条数
  2. **自己发的消息不给自己涨未读**（最容易写错的一处）
  3. **两个账号真的共享一条会话**：A 发的 B 能看到，反之亦然
  4. **越权**：拿到别人的会话 id 也读不到（403）
"""

from __future__ import annotations

import unittest
from datetime import datetime

from fastapi.testclient import TestClient

from app.config import Settings
from app.llm.fake import FakeProvider
from app.main import create_app
from app.messaging import ai_conversation_id, family_conversation_id


class Clock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment


def build_app(database_url: str = "memory://") -> TestClient:
    app = create_app(
        settings=Settings(
            llm_provider="fake",
            llm_api_key="",
            scheduler_enabled=False,
            database_url=database_url,
        ),
        provider=FakeProvider(delay=0),
        clock=Clock(datetime(2026, 10, 7, 10, 0)),
    )
    return TestClient(app)


class MessagingTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.client = build_app()
        # 甲（已有测试账号 00000000 → 比邻AI）
        self.jia = self.login("比邻AI", "BILINAI0316")
        # 乙：新注册一个
        yi = self.client.post(
            "/v1/accounts/register",
            json={"name": "乙奶奶", "password": "abcd1234", "confirm": "abcd1234"},
        ).json()
        self.yi = {"token": yi["token"], "account": yi["account"]}

    # ---------------------------------------------------------------- 助手

    def login(self, name: str, password: str) -> dict:
        response = self.client.post("/v1/accounts/login", json={"name": name, "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        return {"token": data["token"], "account": data["account"]}

    def auth(self, who: dict) -> dict:
        return {"Authorization": "Bearer " + who["token"]}

    def ai_conv(self, who: dict) -> str:
        return ai_conversation_id(who["account"]["id"])

    def send(self, who: dict, conversation_id: str, text: str, role: str = "elder"):
        return self.client.post(
            "/v1/conversations/messages",
            json={"conversationId": conversation_id, "text": text, "senderRole": role},
            headers=self.auth(who),
        )

    def convs(self, who: dict) -> list[dict]:
        response = self.client.get("/v1/conversations", headers=self.auth(who))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["conversations"]

    def conv_of(self, who: dict, conversation_id: str) -> dict:
        for item in self.convs(who):
            if item["id"] == conversation_id:
                return item
        return {}

    # ---------------------------------------------------------------- 鉴权

    def test_requires_login(self) -> None:
        for path in ("/v1/conversations", "/v1/conversations/bindings"):
            self.assertEqual(self.client.get(path).status_code, 401, path)
        self.assertEqual(
            self.client.post("/v1/conversations/messages", json={"text": "hi"}).status_code, 401
        )

    def test_cannot_read_others_conversation(self) -> None:
        """乙拿甲的智能体会话 id 去读 → 403"""
        # 先让甲的会话真的存在（否则拿到的是 404"会话不存在"，测不到越权那一步）
        self.convs(self.jia)
        response = self.client.get(
            "/v1/conversations/messages",
            params={"conversationId": self.ai_conv(self.jia)},
            headers=self.auth(self.yi),
        )
        self.assertEqual(response.status_code, 403, response.text)

    def test_cannot_send_into_others_conversation(self) -> None:
        self.convs(self.jia)
        response = self.send(self.yi, self.ai_conv(self.jia), "插一句")
        self.assertEqual(response.status_code, 403, response.text)

    # ---------------------------------------------------------------- 列表

    def test_ai_conversation_always_listed(self) -> None:
        """没聊过也要能看到智能体会话，否则对话栏目是空的"""
        items = self.convs(self.jia)
        self.assertEqual(len(items), 1, items)
        self.assertEqual(items[0]["kind"], "ai")
        self.assertEqual(items[0]["title"], "比邻AI")
        self.assertEqual(items[0]["unread"], 0)

    def test_empty_text_rejected(self) -> None:
        response = self.send(self.jia, self.ai_conv(self.jia), "   ")
        self.assertEqual(response.status_code, 400)
        self.assertEqual((response.json()["error"])["code"], "message_empty")

    # ---------------------------------------------------------------- 未读

    def test_sender_does_not_accrue_unread(self) -> None:
        """自己发的消息不该给自己涨未读（最容易写错的一处）"""
        conv = self.ai_conv(self.jia)
        self.send(self.jia, conv, "我先说一句")
        self.assertEqual(self.conv_of(self.jia, conv)["unread"], 0)

    def test_unread_counts_others_messages(self) -> None:
        """绑定后乙给甲发两条 → 甲的未读是 2，乙自己是 0"""
        conv = self.bind_and_conv()
        self.send(self.yi, conv, "妈，吃饭了吗")
        self.send(self.yi, conv, "药吃了没")
        self.assertEqual(self.conv_of(self.jia, conv)["unread"], 2)
        self.assertEqual(self.conv_of(self.yi, conv)["unread"], 0)

    def test_mark_read_clears_unread(self) -> None:
        conv = self.bind_and_conv()
        self.send(self.yi, conv, "在吗")
        self.send(self.yi, conv, "看到回我一下")
        self.assertEqual(self.conv_of(self.jia, conv)["unread"], 2)

        response = self.client.post(
            "/v1/conversations/read",
            json={"conversationId": conv},
            headers=self.auth(self.jia),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["marked"], 2)
        self.assertEqual(response.json()["unread"], 0)
        self.assertEqual(self.conv_of(self.jia, conv)["unread"], 0)

    def test_mark_read_is_idempotent(self) -> None:
        conv = self.bind_and_conv()
        self.send(self.yi, conv, "一句")
        first = self.client.post(
            "/v1/conversations/read", json={"conversationId": conv}, headers=self.auth(self.jia)
        ).json()
        second = self.client.post(
            "/v1/conversations/read", json={"conversationId": conv}, headers=self.auth(self.jia)
        ).json()
        self.assertEqual(first["marked"], 1)
        self.assertEqual(second["marked"], 0, "已经读过的消息不该再算一次")

    def test_total_unread_aggregates(self) -> None:
        conv = self.bind_and_conv()
        self.send(self.yi, conv, "一")
        self.send(self.yi, conv, "二")
        self.assertEqual(self.client.get("/v1/conversations", headers=self.auth(self.jia)).json()["totalUnread"], 2)

    # ---------------------------------------------------------------- 共享会话

    def bind_and_conv(self) -> str:
        """发起邀请 + 对方同意，返回共享会话 id。

        绑定现在**要对方同意**（见 messaging/models.Binding）：
        只发邀请拿到的是 pending —— `conversationId` 是空的、也没有共享会话。
        """
        response = self.client.post(
            "/v1/conversations/bindings",
            json={"number": self.yi["account"]["number"]},
            headers=self.auth(self.jia),
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["binding"]["status"], "pending")

        response = self.client.post(
            "/v1/conversations/bindings/respond",
            json={"number": self.jia["account"]["number"], "accept": True},
            headers=self.auth(self.yi),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["binding"]["status"], "accepted")
        return response.json()["binding"]["conversationId"]

    def test_bind_creates_shared_conversation(self) -> None:
        conv = self.bind_and_conv()
        expected = family_conversation_id(self.jia["account"]["id"], self.yi["account"]["id"])
        self.assertEqual(conv, expected)
        # 双方列表里都出现这条会话
        self.assertTrue(self.conv_of(self.jia, conv))
        self.assertTrue(self.conv_of(self.yi, conv))

    def test_bind_is_bidirectional(self) -> None:
        """甲绑乙之后，乙那边也应该看到甲（否则只有一方能发起消息）"""
        self.bind_and_conv()
        bindings = self.client.get("/v1/conversations/bindings", headers=self.auth(self.yi)).json()["bindings"]
        self.assertEqual(len(bindings), 1, bindings)
        self.assertEqual(bindings[0]["peerName"], "比邻AI")
        self.assertEqual(bindings[0]["peerNumber"], "00000000")

    def test_bind_is_idempotent(self) -> None:
        self.bind_and_conv()
        again = self.client.post(
            "/v1/conversations/bindings",
            json={"number": self.yi["account"]["number"]},
            headers=self.auth(self.jia),
        )
        self.assertEqual(again.status_code, 409)
        # 已生效之后再发 → bind_already；还在等同意 → bind_pending（两者都是 409）
        self.assertEqual((again.json()["error"])["code"], "bind_already")

    def test_cannot_bind_self(self) -> None:
        response = self.client.post(
            "/v1/conversations/bindings",
            json={"number": self.jia["account"]["number"]},
            headers=self.auth(self.jia),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual((response.json()["error"])["code"], "bind_self")

    def test_bind_unknown_number(self) -> None:
        response = self.client.post(
            "/v1/conversations/bindings",
            json={"number": "99999999"},
            headers=self.auth(self.jia),
        )
        self.assertEqual(response.status_code, 404)

    def test_bind_requires_eight_digits(self) -> None:
        response = self.client.post(
            "/v1/conversations/bindings", json={"number": "123"}, headers=self.auth(self.jia)
        )
        self.assertEqual(response.status_code, 400)

    def test_both_sides_can_send_and_see(self) -> None:
        """核心用例：双方互相发消息，彼此都看得到完整记录"""
        conv = self.bind_and_conv()
        self.send(self.yi, conv, "妈，我到家了")
        self.send(self.jia, conv, "好，路上冷不冷")
        self.send(self.yi, conv, "不冷，你别忘了吃药")

        jia_view = self.client.get(
            "/v1/conversations/messages", params={"conversationId": conv}, headers=self.auth(self.jia)
        ).json()["messages"]
        yi_view = self.client.get(
            "/v1/conversations/messages", params={"conversationId": conv}, headers=self.auth(self.yi)
        ).json()["messages"]

        self.assertEqual([m["text"] for m in jia_view], ["妈，我到家了", "好，路上冷不冷", "不冷，你别忘了吃药"])
        # 两边看到的是同一份记录
        self.assertEqual([m["id"] for m in jia_view], [m["id"] for m in yi_view])
        # 署名分别是各自的账号名
        self.assertEqual(jia_view[0]["senderName"], "乙奶奶")
        self.assertEqual(jia_view[1]["senderName"], "比邻AI")

    def test_unbind_removes_both_sides(self) -> None:
        self.bind_and_conv()
        response = self.client.delete(
            "/v1/conversations/bindings",
            params={"number": self.yi["account"]["number"]},
            headers=self.auth(self.jia),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get("/v1/conversations/bindings", headers=self.auth(self.jia)).json()["bindings"], [])
        # 对方那边也解掉
        self.assertEqual(self.client.get("/v1/conversations/bindings", headers=self.auth(self.yi)).json()["bindings"], [])

    # ---------------------------------------------------------------- 智能体消息

    def test_agent_reply_same_second_is_unread(self) -> None:
        """回归：同一秒内到达的智能体回复必须算未读。

        踩过的坑：`add_message` 里若把已读游标推"到现在"，
        就会把同一秒刚到的智能体消息一起算成已读，
        接收状态永远显示不出来。游标只该推到我这条消息的时间。
        """
        conv = self.ai_conv(self.jia)
        self.send(self.jia, conv, "你好", role="elder")
        self.send(self.jia, conv, "我是比邻，到点提醒你吃药", role="agent")
        self.assertEqual(self.conv_of(self.jia, conv)["unread"], 1, "智能体回复被误算成已读")

    def test_agent_message_shows_receipt_state(self) -> None:
        """智能体发来的消息：老人读之前是未读，读之后归零（端侧据此显示接收状态）"""
        conv = self.ai_conv(self.jia)
        self.send(self.jia, conv, "你好", role="elder")
        self.send(self.jia, conv, "我是比邻，到点提醒你吃药", role="agent")
        # 智能体那条不是老人发的 → 老人未读 +1
        self.assertEqual(self.conv_of(self.jia, conv)["unread"], 1)
        self.client.post("/v1/conversations/read", json={"conversationId": conv}, headers=self.auth(self.jia))
        self.assertEqual(self.conv_of(self.jia, conv)["unread"], 0)


class MessagingPersistenceTestCase(unittest.TestCase):
    """落库实现：重启后消息与已读状态都要还在"""

    def test_messages_survive_restart(self) -> None:
        import shutil
        import tempfile
        from pathlib import Path

        tmp = tempfile.mkdtemp(prefix="bilin-msg-")
        try:
            db = "sqlite:///" + str(Path(tmp) / "m.db").replace("\\", "/")
            first = build_app(db)
            login = first.post(
                "/v1/accounts/login", json={"name": "比邻AI", "password": "BILINAI0316"}
            ).json()
            account_id = login["account"]["id"]
            conv = ai_conversation_id(account_id)
            headers = {"Authorization": "Bearer " + login["token"]}
            first.post(
                "/v1/conversations/messages",
                json={"conversationId": conv, "text": "重启前说的话"},
                headers=headers,
            )
            first.app.state.database.close()

            # 重启
            second = build_app(db)
            relogin = second.post(
                "/v1/accounts/login", json={"name": "比邻AI", "password": "BILINAI0316"}
            ).json()
            headers2 = {"Authorization": "Bearer " + relogin["token"]}
            items = second.get("/v1/conversations", headers=headers2).json()["conversations"]
            family_or_ai = [c for c in items if c["id"] == conv]
            self.assertEqual(len(family_or_ai), 1, items)
            self.assertEqual(family_or_ai[0]["lastMessage"]["text"], "重启前说的话")
            second.app.state.database.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
