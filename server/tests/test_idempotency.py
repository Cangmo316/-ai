"""
幂等单测（`clientMsgId`）

守的是最实际的一个场景：老人发了一句话，网络抖了一下，端侧没收到 `done` 就重试。
不能让他收到两条一模一样的回复，也不能白花两次模型调用。

关键的负向用例：**第一轮就失败时不能写缓存**——否则端侧重试永远拿到空回复，
这种"越重试越坏"的 bug 最难查。
"""

from __future__ import annotations

import json
import unittest
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from app.config import Settings
from app.llm.base import LLMError, LLMProvider
from app.llm.fake import FakeProvider
from app.main import create_app
from app.models.message import ConversationStore
from app.models.push_client import PushClientRegistry
from app.models.elder import ElderStore
from app.orchestration.idempotency import (
    STATE_DONE,
    STATE_IN_FLIGHT,
    STATE_NEW,
    IdempotencyStore,
)
from app.orchestration.service import ChatService
from app.persona.prompts import PersonaRegistry
from app.plan.engine import PlanEngine
from app.plan.store import PlanStore
from app.knowledge.loader import load_knowledge


class CountingProvider(LLMProvider):
    """数一数模型被调用了几次——这是幂等最直接的证据"""

    name = "counting"

    def __init__(self, text: str = "妈 药吃了没。吃完喝口热水。", delay: float = 0.0) -> None:
        self.text = text
        self.delay = delay
        self.calls = 0

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        self.calls += 1
        for ch in self.text:
            yield ch


class FailingProvider(LLMProvider):
    name = "failing"

    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        self.calls += 1
        raise LLMError("服务器开小差了，一会儿再试", code="server_error")
        yield ""  # pragma: no cover —— 让它是生成器


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


class StoreTests(unittest.TestCase):
    def test_begin_and_complete_lifecycle(self) -> None:
        store = IdempotencyStore()
        state, cached = store.begin("c_son", "m_1")
        self.assertEqual(state, STATE_NEW)
        self.assertIsNone(cached)
        self.assertEqual(store.counts()["in_flight"], 1)

        store.complete("c_son", "m_1", text="妈 药吃了没", stickers=["pill"], assistant_msg_id="a_1")
        state, cached = store.begin("c_son", "m_1")
        self.assertEqual(state, STATE_DONE)
        self.assertEqual(cached.text, "妈 药吃了没")
        self.assertEqual(cached.stickers, ["pill"])
        self.assertEqual(cached.assistant_msg_id, "a_1")

    def test_same_id_different_conversation_is_isolated(self) -> None:
        store = IdempotencyStore()
        store.begin("c_son", "m_1")
        state, _ = store.begin("c_dad", "m_1")
        self.assertEqual(state, STATE_NEW, "不同会话的同名 clientMsgId 不该互相影响")

    def test_in_flight_is_detected(self) -> None:
        store = IdempotencyStore()
        store.begin("c_son", "m_1")
        state, _ = store.begin("c_son", "m_1")
        self.assertEqual(state, STATE_IN_FLIGHT)

    def test_empty_client_msg_id_bypasses_idempotency(self) -> None:
        store = IdempotencyStore()
        self.assertEqual(store.begin("c_son", "")[0], STATE_NEW)
        self.assertEqual(store.begin("c_son", "")[0], STATE_NEW)
        self.assertEqual(store.counts()["total"], 0)

    def test_records_are_capped(self) -> None:
        store = IdempotencyStore(max_entries=5)
        for index in range(20):
            store.begin("c_son", f"m_{index}")
            store.complete("c_son", f"m_{index}", text="x")
        self.assertLessEqual(store.counts()["total"], 5)

    def test_stale_in_flight_is_treated_as_new(self) -> None:
        store = IdempotencyStore(ttl_minutes=0)
        store.begin("c_son", "m_1")
        state, _ = store.begin("c_son", "m_1")
        self.assertEqual(state, STATE_NEW, "卡住太久的记录该让端侧能重新发起")


class ServiceIdempotencyTests(unittest.TestCase):
    def build(self, provider, store: IdempotencyStore | None = None) -> ChatService:
        settings = Settings(llm_provider="fake", sse_heartbeat_seconds=0.05)
        return ChatService(
            provider,
            ConversationStore(),
            PersonaRegistry(),
            settings,
            idempotency=store if store is not None else IdempotencyStore(),
        )

    def collect(self, service: ChatService, client_msg_id: str) -> list[tuple[str, dict]]:
        async def run():
            return [
                item
                async for item in service.generate("c_son", "妈 药吃了没", client_msg_id=client_msg_id)
            ]

        import asyncio

        return asyncio.run(run())

    def test_second_request_replays_without_calling_model(self) -> None:
        provider = CountingProvider()
        service = self.build(provider)
        first = self.collect(service, "m_dup")
        second = self.collect(service, "m_dup")

        self.assertEqual(provider.calls, 1, "第二次不该再调模型")
        text_of = lambda events: "".join(p["t"] for n, p in events if n == "token")
        self.assertEqual(text_of(first), "妈 药吃了没\n吃完喝口热水")
        self.assertEqual(text_of(second), text_of(first), "回放内容应与首次一致")
        self.assertTrue(second[0][1].get("replayed"), "回放要能被端侧识别")
        self.assertTrue(second[-1][1].get("replayed"))

    def test_replay_does_not_duplicate_messages_in_store(self) -> None:
        provider = CountingProvider()
        service = self.build(provider)
        self.collect(service, "m_dup")
        before = len(service.store.history("c_son"))
        self.collect(service, "m_dup")
        self.assertEqual(len(service.store.history("c_son")), before, "回放不该重复落库")

    def test_different_client_msg_id_generates_again(self) -> None:
        provider = CountingProvider()
        service = self.build(provider)
        self.collect(service, "m_1")
        self.collect(service, "m_2")
        self.assertEqual(provider.calls, 2)

    def test_failure_does_not_poison_the_cache(self) -> None:
        """第一轮失败时不能写缓存，也不能留下 in-flight 记录——
        否则端侧重试会一直被告知"这句话我正在回，等我一下"，老人永远等不到回复"""
        failing = FailingProvider()
        service = self.build(failing)
        first = self.collect(service, "m_fail")
        self.assertEqual(first[-1][0], "error")
        self.assertIsNone(
            service.idempotency.get("c_son", "m_fail"),
            "失败后该把记录放掉，让重试能真的重新生成",
        )

        # 换个能成功的 provider 重试同一个 id，应该真的重新生成
        provider = CountingProvider()
        service.provider = provider
        second = self.collect(service, "m_fail")
        self.assertEqual(provider.calls, 1)
        self.assertIn("token", [name for name, _ in second])

    def test_no_idempotency_store_means_no_caching(self) -> None:
        provider = CountingProvider()
        settings = Settings(llm_provider="fake")
        service = ChatService(provider, ConversationStore(), PersonaRegistry(), settings)
        self.collect(service, "m_1")
        self.collect(service, "m_1")
        self.assertEqual(provider.calls, 2, "没注入幂等表时按老行为处理")


class IdempotencyApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = CountingProvider(text="妈 好。")
        self.app = create_app(
            settings=Settings(llm_provider="fake", llm_api_key="", scheduler_enabled=False),
            provider=self.provider,
        )
        self.client = TestClient(self.app)

    def test_chat_send_replays_for_same_client_msg_id(self) -> None:
        payload = {"conversationId": "c_dup", "text": "妈 在吗", "clientMsgId": "m_send_1"}
        first = self.client.post("/v1/chat/send", json=payload)
        second = self.client.post("/v1/chat/send", json=payload)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["text"], second.json()["text"])
        self.assertEqual(self.provider.calls, 1, "同一 clientMsgId 不该重复调模型")

    def test_chat_stream_replays_and_marks_replayed(self) -> None:
        payload = {"conversationId": "c_dup2", "text": "妈 在吗", "clientMsgId": "m_stream_1"}
        with self.client.stream("POST", "/v1/chat/stream", json=payload) as response:
            first = parse_sse("".join(response.iter_text()))
        with self.client.stream("POST", "/v1/chat/stream", json=payload) as response:
            second = parse_sse("".join(response.iter_text()))
        self.assertEqual(self.provider.calls, 1)
        self.assertTrue(second[0][1].get("replayed"))
        self.assertEqual(
            "".join(p["t"] for n, p in first if n == "token"),
            "".join(p["t"] for n, p in second if n == "token"),
        )

    def test_in_flight_returns_duplicate_error(self) -> None:
        """两条并发请求用同一个 clientMsgId：第二条要明确告诉端侧"我正在回"，不能重复生成"""
        payload = {"conversationId": "c_race", "text": "妈 在吗", "clientMsgId": "m_race"}
        # 直接操作 app 里的幂等表，模拟"第一条还在生成中"
        self.app.state.idempotency.begin("c_race", "m_race")
        with self.client.stream("POST", "/v1/chat/stream", json=payload) as response:
            events = parse_sse("".join(response.iter_text()))
        self.assertEqual(events[-1][0], "error")
        self.assertEqual(events[-1][1]["code"], "duplicate_request")
        self.assertEqual(self.provider.calls, 0, "重复请求不该触发模型调用")

    def test_healthz_reports_idempotency_counts(self) -> None:
        self.client.post(
            "/v1/chat/send", json={"conversationId": "c_x", "text": "妈 在吗", "clientMsgId": "m_x"}
        )
        body = self.client.get("/healthz").json()
        self.assertGreaterEqual(body["idempotency"]["done"], 1)


if __name__ == "__main__":
    unittest.main()
