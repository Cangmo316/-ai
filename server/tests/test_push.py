"""
uni-push 通道与推送标识登记单测

这一层最怕两件事：
1. **没配就假装成功**：那样调度器会以为提醒发出去了，老人什么也收不到
2. **把 cid 当普通 id 到处传**：cid 是设备标识，对外只应回显后 6 位

云函数调用全部用注入的 poster 替换，测试不联网、不需要 uniCloud 账号。
"""

from __future__ import annotations

import asyncio
import unittest
from datetime import datetime

from fastapi.testclient import TestClient

from app.config import Settings
from app.llm.fake import FakeProvider
from app.main import create_app
from app.models.message import ConversationStore
from app.models.push_client import PushClientRegistry
from app.schedule.channels import ChannelRegistry, InboxChannel, UniPushChannel
from app.schedule.models import LEVEL_STRONG, ReminderTask


def make_task(elder_id: str = "e_1") -> ReminderTask:
    return ReminderTask(
        id="rt_test",
        plan_id="plan_test",
        plan_item_id="pi_test",
        elder_id=elder_id,
        conversation_id="c_son",
        title="量完血压记下来 下次给医生看",
        label="08:00 监测",
        level=LEVEL_STRONG,
        send_at="2026-09-24T08:00:00",
    )


class RecordingPoster:
    """假的云函数调用：记录请求，按脚本返回"""

    def __init__(self, responses=None) -> None:
        self.responses = list(responses or [(200, {"code": 0})])
        self.calls: list[dict] = []

    async def __call__(self, url, payload, headers, timeout):
        self.calls.append({"url": url, "payload": payload, "headers": dict(headers), "timeout": timeout})
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]


class BrokenPoster:
    async def __call__(self, url, payload, headers, timeout):
        raise RuntimeError("云函数不可达")


class RegistryTests(unittest.TestCase):
    def test_register_is_idempotent_and_updates_platform(self) -> None:
        registry = PushClientRegistry()
        first = registry.register("e_1", "cid_aaa", platform="android", app_version="1.0")
        again = registry.register("e_1", "cid_aaa", platform="ios")
        self.assertEqual(first.cid, again.cid)
        self.assertEqual(len(registry.all()), 1)
        self.assertEqual(again.platform, "ios")
        self.assertNotEqual(first.updated_at, "")

    def test_multiple_devices_per_elder(self) -> None:
        registry = PushClientRegistry()
        registry.register("e_1", "cid_phone")
        registry.register("e_1", "cid_pad")
        registry.register("e_2", "cid_other")
        self.assertEqual(len(registry.clients_for("e_1")), 2)
        self.assertEqual(len(registry.clients_for("e_2")), 1)
        self.assertEqual(registry.counts()["elders"], 2)

    def test_unregister_and_empty_cid(self) -> None:
        registry = PushClientRegistry()
        registry.register("e_1", "cid_aaa")
        self.assertTrue(registry.unregister("cid_aaa"))
        self.assertFalse(registry.unregister("cid_aaa"))
        with self.assertRaises(ValueError):
            registry.register("e_1", "   ")

    def test_cid_is_masked_in_public_dict(self) -> None:
        registry = PushClientRegistry()
        client = registry.register("e_1", "cid_abcdef123456")
        payload = client.to_dict()
        self.assertEqual(payload["cidTail"], "123456")
        self.assertNotIn("cid_abcdef123456", str(payload["cidTail"]))


class UniPushChannelTests(unittest.TestCase):
    def test_unconfigured_never_reports_success(self) -> None:
        channel = UniPushChannel(send_url="", registry=PushClientRegistry())
        result = asyncio.run(channel.deliver(make_task(), "妈 量血压"))
        self.assertFalse(result.ok)
        self.assertIn("UNIPUSH_SEND_URL", result.detail)
        self.assertFalse(channel.configured)

    def test_no_registered_client(self) -> None:
        channel = UniPushChannel(
            send_url="https://cloud.example.invalid/push",
            registry=PushClientRegistry(),
            poster=RecordingPoster(),
        )
        result = asyncio.run(channel.deliver(make_task(), "妈 量血压"))
        self.assertFalse(result.ok)
        self.assertIn("还没登记", result.detail)

    def test_successful_delivery_payload(self) -> None:
        registry = PushClientRegistry()
        registry.register("e_1", "cid_abcdef123456", platform="android")
        poster = RecordingPoster()
        channel = UniPushChannel(
            send_url="https://cloud.example.invalid/push",
            token="secret-token",
            registry=registry,
            poster=poster,
        )
        result = asyncio.run(channel.deliver(make_task(), "妈 量完血压记下来"))
        self.assertTrue(result.ok, result.detail)
        self.assertEqual(result.channel, "unipush")
        self.assertEqual(len(poster.calls), 1)
        call = poster.calls[0]
        self.assertEqual(call["url"], "https://cloud.example.invalid/push")
        self.assertEqual(call["headers"]["Authorization"], "Bearer secret-token")
        payload = call["payload"]
        self.assertEqual(payload["cid"], "cid_abcdef123456")
        self.assertEqual(payload["content"], "妈 量完血压记下来")
        self.assertEqual(payload["title"], "08:00 监测")
        self.assertTrue(payload["force_notification"], "提醒类消息要在线也创建通知栏")
        self.assertEqual(payload["payload"]["taskId"], "rt_test")
        self.assertEqual(payload["payload"]["level"], LEVEL_STRONG)

    def test_no_token_means_no_authorization_header(self) -> None:
        registry = PushClientRegistry()
        registry.register("e_1", "cid_aaa")
        poster = RecordingPoster()
        channel = UniPushChannel(send_url="https://x.invalid", registry=registry, poster=poster)
        asyncio.run(channel.deliver(make_task(), "妈 量血压"))
        self.assertNotIn("Authorization", poster.calls[0]["headers"])

    def test_multiple_devices_all_get_it(self) -> None:
        registry = PushClientRegistry()
        registry.register("e_1", "cid_phone")
        registry.register("e_1", "cid_pad")
        poster = RecordingPoster()
        channel = UniPushChannel(send_url="https://x.invalid", registry=registry, poster=poster)
        result = asyncio.run(channel.deliver(make_task(), "妈 量血压"))
        self.assertTrue(result.ok)
        self.assertEqual(len(poster.calls), 2)
        self.assertIn("2 台设备", result.detail)

    def test_cloud_function_failure_is_reported(self) -> None:
        registry = PushClientRegistry()
        registry.register("e_1", "cid_aaa")
        channel = UniPushChannel(
            send_url="https://x.invalid",
            registry=registry,
            poster=RecordingPoster([(200, {"code": 401, "msg": "unauthorized"})]),
        )
        result = asyncio.run(channel.deliver(make_task(), "妈 量血压"))
        self.assertFalse(result.ok)
        self.assertIn("401", result.detail)

    def test_http_error_is_reported(self) -> None:
        registry = PushClientRegistry()
        registry.register("e_1", "cid_aaa")
        channel = UniPushChannel(
            send_url="https://x.invalid",
            registry=registry,
            poster=RecordingPoster([(502, "bad gateway")]),
        )
        result = asyncio.run(channel.deliver(make_task(), "妈 量血压"))
        self.assertFalse(result.ok)
        self.assertIn("502", result.detail)

    def test_poster_exception_does_not_escape(self) -> None:
        registry = PushClientRegistry()
        registry.register("e_1", "cid_aaa")
        channel = UniPushChannel(send_url="https://x.invalid", registry=registry, poster=BrokenPoster())
        result = asyncio.run(channel.deliver(make_task(), "妈 量血压"))
        self.assertFalse(result.ok)
        self.assertIn("异常", result.detail)

    def test_registry_falls_back_to_inbox_when_unipush_unavailable(self) -> None:
        """推送没配好时，站内消息必须照常送到——老人的提醒不能因为推送没开就消失"""
        conversations = ConversationStore()
        registry = PushClientRegistry()
        registry.register("e_1", "cid_aaa")
        channels = ChannelRegistry([
            UniPushChannel(send_url="", registry=registry),
            InboxChannel(conversations),
        ])
        result = asyncio.run(channels.deliver(make_task(), "妈 量完血压记下来"))
        self.assertTrue(result.ok)
        self.assertEqual(result.channel, "inbox")
        self.assertTrue(conversations.history("c_son"))


class PushApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(
            settings=Settings(llm_provider="fake", llm_api_key="", scheduler_enabled=False),
            provider=FakeProvider(delay=0),
            clock=lambda: datetime(2026, 9, 24, 7, 30),
        )
        self.client = TestClient(self.app)

    def test_register_and_status_contract(self) -> None:
        response = self.client.post(
            "/v1/push/register",
            json={"cid": "cid_device_987654", "elderId": "e_1", "platform": "android", "appVersion": "1.0.0"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["cidTail"], "987654")
        self.assertNotIn("cid_device_987654", str(body), "登记响应不该回显完整 cid")

        status = self.client.get("/v1/push/status", params={"elderId": "e_1"}).json()
        self.assertEqual(len(status["clients"]), 1)
        self.assertEqual(status["clients"][0]["cidTail"], "987654")
        self.assertFalse(status["unipushConfigured"], "没配 UNIPUSH_SEND_URL 就该是 false")
        self.assertEqual(status["forceNotification"], True)
        self.assertTrue(any(channel["name"] == "inbox" for channel in status["channels"]))

    def test_empty_cid_is_rejected(self) -> None:
        response = self.client.post("/v1/push/register", json={"cid": "   "})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_cid")

    def test_unregister(self) -> None:
        self.client.post("/v1/push/register", json={"cid": "cid_x", "elderId": "e_1"})
        removed = self.client.post("/v1/push/unregister", json={"cid": "cid_x"}).json()
        self.assertTrue(removed["ok"])
        again = self.client.post("/v1/push/unregister", json={"cid": "cid_x"}).json()
        self.assertFalse(again["ok"])
        status = self.client.get("/v1/push/status", params={"elderId": "e_1"}).json()
        self.assertEqual(status["clients"], [])

    def test_status_reports_configured_channel(self) -> None:
        app = create_app(
            settings=Settings(
                llm_provider="fake",
                scheduler_enabled=False,
                unipush_send_url="https://cloud.example.invalid/push",
                unipush_token="t",
            ),
            provider=FakeProvider(delay=0),
            clock=lambda: datetime(2026, 9, 24, 7, 30),
        )
        status = TestClient(app).get("/v1/push/status").json()
        self.assertTrue(status["unipushConfigured"])
        unipush = next(channel for channel in status["channels"] if channel["name"] == "unipush")
        self.assertTrue(unipush["configured"])

    def test_healthz_still_reports_scheduler_channels(self) -> None:
        body = self.client.get("/healthz").json()
        names = [channel["name"] for channel in body["scheduler"]["channels"]]
        self.assertIn("inbox", names)
        self.assertIn("unipush", names)


if __name__ == "__main__":
    unittest.main()
