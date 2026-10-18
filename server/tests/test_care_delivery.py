"""本轮三件事的回归测试：

  ① 智能体代发已删除（家人会话里只有真人消息）
  ② 主动关心只针对在用的那个老人（不骚扰 demo 老人）
  ③ 主动关心走**双通道**（inbox 写会话 + unipush 系统推送）
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.care import CareService, CareStore
from app.care.loop import CareLoop
from app.models.message import ConversationStore, Message, ROLE_ELDER, new_id


class CareTargetingTestCase(unittest.TestCase):
    """需求：主动关心只对用户绑定的这个老人。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.care = CareService(CareStore(Path(self.tmp.name)))
        self.conversations = ConversationStore()

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_targets_before_any_chat(self):
        """还没聊过 → 不关心任何人（老人档案里的 demo 老人不该被骚扰）"""
        loop = CareLoop(
            self.care,
            self.conversations,
            elder_ids=lambda: [e for e in ("e_1", "e_2") if self.care._conversations.get(e)],
        )
        self.assertEqual(loop.targets(), [])

    def test_only_the_active_elder_is_targeted(self):
        """谁在用就只关心谁"""
        self.care.note_conversation("e_1", "ai:a_1")
        loop = CareLoop(
            self.care,
            self.conversations,
            elder_ids=lambda: [e for e in ("e_1", "e_2") if self.care._conversations.get(e)],
        )
        self.assertEqual(loop.targets(), ["e_1"])

    def test_static_list_still_supported(self):
        loop = CareLoop(self.care, self.conversations, elder_ids=["e_9"])
        self.assertEqual(loop.targets(), ["e_9"])

    def test_broken_target_provider_does_not_crash(self):
        """目标算不出来就当没人需要关心，不能让后台循环崩掉"""
        def boom():
            raise RuntimeError("坏了")

        loop = CareLoop(self.care, self.conversations, elder_ids=boom)
        self.assertEqual(loop.targets(), [])


class CareDualChannelTestCase(unittest.TestCase):
    """需求：系统级推送要做 —— 关掉 App 也能收到。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = datetime(2026, 10, 8, 9, 0).astimezone()
        self.care = CareService(CareStore(Path(self.tmp.name)), clock=lambda: self.now)
        self.conversations = ConversationStore()
        self.cid = "ai:a_test"
        self.care.note_conversation("e_1", self.cid)
        self.care._last_chat["e_1"] = datetime(2026, 10, 8, 7, 0).astimezone()
        self.conversations.append(
            self.cid, Message(id=new_id("m"), role=ROLE_ELDER, text="我起来了")
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_both_channels_receive(self):
        """inbox 与 unipush **两条都要发**。

        踩过的坑：ChannelRegistry.deliver 命中第一条成功就返回，
        inbox 一成功 unipush 就永远轮不到 —— 配了推送却从来不推送。
        所以关心走 deliver_all。
        """
        calls = []

        class FakeRegistry:
            def clients_for(self, elder_id):
                class C:
                    cid = "cid-1"

                return [C()]

            def counts(self):
                return {"clients": 1}

        async def fake_poster(url, payload, headers, timeout):
            calls.append(payload)
            return 200, {"code": 0}

        from app.schedule.channels import ChannelRegistry, InboxChannel, UniPushChannel

        unipush = UniPushChannel(
            send_url="https://example.invalid/x",
            token="t",
            registry=FakeRegistry(),
            poster=fake_poster,
        )
        channels = ChannelRegistry([InboxChannel(self.conversations), unipush])

        loop = CareLoop(
            self.care, self.conversations,
            elder_ids=["e_1"], interval=600, channels=channels,
        )

        async def run():
            sent = await loop.tick()
            for _ in range(40):          # 等后台推送任务跑完
                await asyncio.sleep(0.02)
                if calls:
                    break
            return sent

        sent = asyncio.run(run())
        self.assertEqual(len(sent), 1)

        # ① inbox：会话里能看到
        texts = [m.text for m in self.conversations.history(self.cid, limit=0)]
        self.assertIn(sent[0]["question"], texts)

        # ② unipush：系统通知也发了
        self.assertTrue(calls, "系统推送没发出去")
        self.assertEqual(calls[0]["cid"], "cid-1")
        self.assertEqual(calls[0]["content"], sent[0]["question"])

    def test_no_channels_still_writes_conversation(self):
        """没装配通道时退回"只写会话"，行为不能退步"""
        loop = CareLoop(self.care, self.conversations, elder_ids=["e_1"], interval=600)
        sent = asyncio.run(loop.tick())
        self.assertEqual(len(sent), 1)
        texts = [m.text for m in self.conversations.history(self.cid, limit=0)]
        self.assertIn(sent[0]["question"], texts)


class AgentSendRemovedTestCase(unittest.TestCase):
    """需求：智能体代发在陪伴上没有意义，删掉。"""

    def test_auto_reply_endpoint_is_gone(self):
        from fastapi.testclient import TestClient

        from app.config import Settings
        from app.main import create_app

        app = create_app(settings=Settings(llm_provider="fake", scheduler_enabled=False))
        client = TestClient(app)
        response = client.post("/v1/conversations/messages/auto-reply", json={})
        self.assertEqual(response.status_code, 404)

    def test_sender_role_agent_is_treated_as_human(self):
        """老端侧还传 agent 也不该造出 agent sender 的记录。"""
        from fastapi.testclient import TestClient

        from app.config import Settings
        from app.main import create_app

        app = create_app(settings=Settings(llm_provider="fake", scheduler_enabled=False))
        client = TestClient(app)
        reg = client.post(
            "/v1/accounts/register",
            json={"name": "丙测试", "password": "abcd1234", "confirm": "abcd1234"},
        ).json()
        token = {"Authorization": "Bearer " + reg["token"]}
        account_id = reg["account"]["id"]
        cid = "ai:" + account_id

        res = client.post(
            "/v1/conversations/messages",
            json={"conversationId": cid, "text": "假装我是智能体", "senderRole": "agent"},
            headers=token,
        )
        self.assertEqual(res.status_code, 201, res.text)
        message = res.json()["message"]
        self.assertFalse(
            message["senderId"].startswith("agent:"),
            "代发已删除，不该再出现 agent sender id",
        )
        self.assertEqual(message["senderId"], account_id)


if __name__ == "__main__":
    unittest.main()
