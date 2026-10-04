"""
P2 三层记忆单测

L2（经历）/ L3（偏好）这套东西最容易"悄悄越界"，所以这里守死的不是功能多少，而是**边界**：

1. **自动整理默认关**：不告知就整理聊天内容，是隐私事故
2. **低置信不进检索**：自动抽出来的东西只有复核通过才允许进上下文
3. **自动整理的记忆家属看不到**：否则"家人端默认看不到聊天原文"会被记忆绕过去
4. **删得掉**：单条删除 + 一键清空（方案明确要求）

另外守住注入形态：只注入检索到的 Top-K，不是把整个记忆库塞进 prompt。
"""

from __future__ import annotations

import asyncio
import json
import unittest
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from app.config import Settings
from app.llm.base import LLMProvider
from app.llm.fake import FakeProvider
from app.main import create_app
from app.memory import (
    AUTO_MIN_CONFIDENCE,
    KIND_EXPERIENCE,
    KIND_PREFERENCE,
    REVIEW_PENDING,
    SOURCE_AUTO,
    MemoryStore,
)
from app.memory.extractor import Candidate, extract_rules, extract_with_llm, remember_from_turn
from app.memory.retrieval import describe, score, search, tokens_of, topics
from app.models.message import ConversationStore
from app.orchestration.idempotency import IdempotencyStore
from app.orchestration.service import ChatService
from app.persona.prompts import PersonaRegistry, build_system_prompt


class CaptureProvider(LLMProvider):
    """把发给模型的 messages 记下来，用来断言"记忆到底有没有进 prompt" """

    name = "capture"

    def __init__(self, text: str = "妈 好。") -> None:
        self.text = text
        self.calls: list[list[dict]] = []

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        self.calls.append(messages)
        for ch in self.text:
            yield ch


class JsonProvider(LLMProvider):
    """模拟模型返回抽取结果（含一个坏行，验证解析容错）"""

    name = "json"

    def __init__(self, payload: str) -> None:
        self.payload = payload

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        for ch in self.payload:
            yield ch


class StoreTests(unittest.TestCase):
    def test_add_and_shape(self) -> None:
        store = MemoryStore()
        entry = store.add("e_1", "老人 2023 年去过海南", kind=KIND_EXPERIENCE, tags=["儿子", "旅行"])
        payload = entry.to_dict()
        self.assertEqual(payload["kindLabel"], "经历")
        self.assertEqual(payload["sourceLabel"], "家里人填写")
        self.assertTrue(payload["visibleToFamily"])
        self.assertEqual(payload["review"], "approved")
        self.assertAlmostEqual(payload["confidence"], 1.0)

    def test_rejects_empty_text_and_bad_kind(self) -> None:
        store = MemoryStore()
        with self.assertRaises(ValueError):
            store.add("e_1", "   ")
        with self.assertRaises(ValueError):
            store.add("e_1", "随便一条", kind="不存在的种类")

    def test_auto_low_confidence_goes_pending_and_hidden_from_family(self) -> None:
        """自动抽取的两条默认值：待复核 + 家属不可见"""
        store = MemoryStore()
        entry = store.add(
            "e_1",
            "老人提过年轻时在厂里当钳工",
            source=SOURCE_AUTO,
            confidence=AUTO_MIN_CONFIDENCE - 0.2,
        )
        self.assertEqual(entry.review, REVIEW_PENDING)
        self.assertFalse(entry.visible_to_family)
        self.assertEqual(len(store.pending_of("e_1")), 1)
        self.assertEqual(len(store.family_view("e_1")), 0, "待复核的不该出现在家属视图里")

    def test_auto_high_confidence_is_usable_but_still_hidden_from_family(self) -> None:
        store = MemoryStore()
        entry = store.add("e_1", "老人爱听戏", kind=KIND_PREFERENCE, source=SOURCE_AUTO, confidence=0.9)
        self.assertEqual(entry.review, "approved")
        self.assertFalse(entry.visible_to_family, "自动整理的记忆默认不给家属看")
        self.assertEqual(len(store.usable_of("e_1")), 1, "但它是可用的（能进对话上下文）")

    def test_update_review_delete_clear(self) -> None:
        store = MemoryStore()
        first = store.add("e_1", "老人 2023 年去过海南")
        second = store.add("e_1", "爱吃面", kind=KIND_PREFERENCE)
        store.add("e_2", "别人的记忆")

        updated = store.update(first.id, text="老人 2023 年跟儿子去过海南", tags=["儿子"])
        self.assertIn("跟儿子", updated.text)
        self.assertEqual(updated.tags, ["儿子"])

        store.review(second.id, approve=False)
        self.assertEqual(second.review, "rejected")
        self.assertEqual(len(store.usable_of("e_1")), 1, "否决后不再可用")

        self.assertTrue(store.delete(first.id))
        self.assertFalse(store.delete(first.id))
        removed = store.clear("e_1")
        self.assertEqual(removed, 1)
        self.assertEqual(len(store.all_of("e_1")), 0)
        self.assertEqual(len(store.all_of("e_2")), 1, "清空只影响这一位老人")

    def test_settings_default_off_and_consent_stamp(self) -> None:
        store = MemoryStore()
        settings = store.settings_for("e_1")
        self.assertFalse(settings.auto_extract, "自动整理必须默认关闭")
        self.assertEqual(settings.consented_at, "")

        store.update_settings("e_1", auto_extract=True)
        self.assertTrue(settings.auto_extract)
        first_stamp = settings.consented_at
        self.assertTrue(first_stamp, "开启时该记下同意时间")

        store.update_settings("e_1", auto_extract=True)
        self.assertEqual(settings.consented_at, first_stamp, "重复开启不刷新同意时间")

    def test_counts(self) -> None:
        store = MemoryStore()
        store.add("e_1", "去过海南")
        store.add("e_1", "爱听戏", kind=KIND_PREFERENCE, source=SOURCE_AUTO, confidence=0.4)
        store.update_settings("e_1", auto_extract=True)
        counts = store.counts()
        self.assertEqual(counts["total"], 2)
        self.assertEqual(counts["pending"], 1)
        self.assertEqual(counts["autoExtractEnabled"], 1)
        self.assertEqual(counts["elders"], 1)


class RetrievalTests(unittest.TestCase):
    def test_tokens_of_chinese(self) -> None:
        tokens = tokens_of("我去年去过海南")
        self.assertIn("去过", tokens)
        self.assertIn("海南", tokens)
        self.assertNotIn("的", tokens)

    def test_search_ranks_relevant_first_and_drops_irrelevant(self) -> None:
        store = MemoryStore()
        store.add("e_1", "老人 2023 年跟儿子去过海南", tags=["儿子", "旅行"])
        store.add("e_1", "老人爱吃面条", kind=KIND_PREFERENCE, tags=["吃饭"])
        ranked = search(store, "e_1", "你儿子上次带你去海南好玩吗")
        self.assertTrue(ranked)
        self.assertIn("海南", ranked[0][0].text)
        self.assertEqual(search(store, "e_1", "今天天气怎么样"), [], "无关的话不该捞出记忆")

    def test_pending_never_retrieved(self) -> None:
        store = MemoryStore()
        store.add("e_1", "老人去过海南", source=SOURCE_AUTO, confidence=0.3, tags=["旅行"])
        self.assertEqual(search(store, "e_1", "海南"), [])

    def test_score_prefers_tag_hits(self) -> None:
        store = MemoryStore()
        tagged = store.add("e_1", "老人出去玩了", tags=["海南", "旅行"])
        store.add("e_1", "老人说海南的天气不错，海南的椰子好喝，海南的海很蓝")
        ranked = search(store, "e_1", "海南")
        self.assertEqual(ranked[0][0].id, tagged.id, "带标签的该排在前面")
        self.assertGreater(score(tagged, tokens_of("海南")), 0.4)

    def test_topics_aggregates_weights(self) -> None:
        store = MemoryStore()
        store.add("e_1", "爱听戏", kind=KIND_PREFERENCE, tags=["戏曲"])
        store.add("e_1", "也爱听评书", kind=KIND_PREFERENCE, tags=["戏曲", "评书"])
        result = topics(store, "e_1", limit=3)
        self.assertEqual(result[0]["topic"], "戏曲")
        self.assertGreater(result[0]["weight"], result[1]["weight"])

    def test_describe_mentions_source(self) -> None:
        store = MemoryStore()
        entry = store.add("e_1", "老人 2023 年去过海南", happened_at="2023年")
        line = describe(entry)
        self.assertIn("经历", line)
        self.assertIn("2023年", line)
        self.assertIn("家里人填写", line)


class ExtractorTests(unittest.TestCase):
    def test_rules_find_experience_and_preference(self) -> None:
        found = extract_rules("我去年跟儿子去过海南，我特别爱听戏")
        kinds = {item.kind for item in found}
        self.assertIn(KIND_EXPERIENCE, kinds)
        self.assertIn(KIND_PREFERENCE, kinds)
        self.assertTrue(any("海南" in item.text for item in found))
        self.assertTrue(all(item.confidence >= AUTO_MIN_CONFIDENCE for item in found))

    def test_rules_ignore_short_or_plain_message(self) -> None:
        self.assertEqual(extract_rules("好"), [])
        self.assertEqual(extract_rules("嗯嗯"), [])

    def test_llm_json_parsing_and_tolerance(self) -> None:
        payload = json.dumps(
            [
                {"kind": "experience", "text": "老人 2021 年搬过家", "tags": ["搬家"], "confidence": 0.9},
                {"kind": "乱写的种类", "text": "忽略我", "confidence": 0.9},
                {"bad": "缺少 text"},
            ],
            ensure_ascii=False,
        )
        provider = JsonProvider("这里是解释文字 " + payload)
        found = asyncio.run(extract_with_llm(provider, "我 2021 年搬过家"))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].text, "老人 2021 年搬过家")

    def test_llm_bad_output_returns_empty(self) -> None:
        self.assertEqual(asyncio.run(extract_with_llm(JsonProvider("我不知道该输出什么"), "随便说说")), [])
        self.assertEqual(asyncio.run(extract_with_llm(None, "随便说说")), [])

    def test_remember_from_turn_respects_switch(self) -> None:
        """开关关着时，一个字都不该写进记忆库（这是默认状态）"""
        store = MemoryStore()
        settings = store.settings_for("e_1")
        added = asyncio.run(
            remember_from_turn(store, settings, "e_1", "我去年跟儿子去过海南")
        )
        self.assertEqual(added, [])
        self.assertEqual(store.counts()["total"], 0)

    def test_remember_from_turn_when_enabled(self) -> None:
        store = MemoryStore()
        settings = store.update_settings("e_1", auto_extract=True)
        added = asyncio.run(
            remember_from_turn(store, settings, "e_1", "我去年跟儿子去过海南")
        )
        self.assertTrue(added)
        entry = store.get(added[0])
        self.assertEqual(entry.source, SOURCE_AUTO)
        self.assertFalse(entry.visible_to_family)

    def test_low_confidence_candidate_stays_pending(self) -> None:
        store = MemoryStore()
        from app.memory.extractor import remember_candidates

        remember_candidates(
            store,
            "e_1",
            [Candidate(kind=KIND_EXPERIENCE, text="老人好像提过老家的桥", confidence=0.4)],
        )
        self.assertEqual(len(store.pending_of("e_1")), 1)
        self.assertEqual(search(store, "e_1", "老家的桥"), [], "待复核的不进检索")

    def test_duplicate_candidates_are_not_stored_twice(self) -> None:
        store = MemoryStore()
        settings = store.update_settings("e_1", auto_extract=True)
        text = "我去年跟儿子去过海南"
        asyncio.run(remember_from_turn(store, settings, "e_1", text))
        before = store.counts()["total"]
        asyncio.run(remember_from_turn(store, settings, "e_1", text))
        self.assertEqual(store.counts()["total"], before, "同一件事说两遍不该存两条")


class PromptTests(unittest.TestCase):
    def test_memories_section_only_when_present(self) -> None:
        persona = PersonaRegistry().get(None)
        plain = build_system_prompt(persona, None, [])
        self.assertNotIn("你想起的往事", plain)

        with_memory = build_system_prompt(persona, None, ["[经历] 老人 2023 年去过海南 · 家里人填写"])
        self.assertIn("你想起的往事", with_memory)
        self.assertIn("海南", with_memory)
        self.assertIn("别硬提、别罗列", with_memory)
        self.assertIn("绝不要编", with_memory)
        # 反"补细节"（实测模型会把记录扩写成一段场景："那会儿你天天发照片"），
        # 但**同时**要求把记录里写到的照实说（否则模型矫枉过正，连"海南"都不肯说），
        # 并且追问细节时不许下结论（实测会说"那是你自己去的"，与记录矛盾）
        self.assertIn("一律不许补、也不许猜", with_memory)
        self.assertIn("照实说", with_memory)
        self.assertIn("邀请", with_memory)
        self.assertNotIn("一律不许补", plain, "没有记忆时不该出现这段规则")


class ServiceInjectionTests(unittest.TestCase):
    def build(self, store: MemoryStore, provider) -> ChatService:
        def memories_for(elder_id: str, query: str):
            return [describe(entry) for entry, _ in search(store, elder_id, query, limit=5)]

        self.after_turn_calls: list[tuple[str, str]] = []

        async def after_turn(elder_id: str, text: str) -> None:
            self.after_turn_calls.append((elder_id, text))
            await remember_from_turn(store, store.settings_for(elder_id), elder_id, text)

        return ChatService(
            provider,
            ConversationStore(),
            PersonaRegistry(),
            Settings(llm_provider="fake", sse_heartbeat_seconds=0.05),
            memory_provider=memories_for,
            after_turn=after_turn,
            idempotency=IdempotencyStore(),
        )

    def collect(self, service: ChatService, text: str, client_msg_id: str = "") -> None:
        async def run():
            return [item async for item in service.generate("c_son", text, client_msg_id=client_msg_id)]

        asyncio.run(run())

    def test_relevant_memory_reaches_prompt(self) -> None:
        store = MemoryStore()
        store.add("e_1", "老人 2023 年跟儿子去过海南", tags=["儿子", "旅行"])
        store.add("e_1", "老人爱吃面条", kind=KIND_PREFERENCE, tags=["吃饭"])
        provider = CaptureProvider()
        service = self.build(store, provider)

        self.collect(service, "你儿子上次带我去哪玩来着")
        system = provider.calls[0][0]["content"]
        self.assertIn("海南", system)
        self.assertNotIn("面条", system, "无关的记忆不该占上下文")

    def test_no_memory_no_section(self) -> None:
        store = MemoryStore()
        provider = CaptureProvider()
        service = self.build(store, provider)
        self.collect(service, "今天天气不错")
        self.assertNotIn("你想起的往事", provider.calls[0][0]["content"])

    def test_after_turn_runs_once_and_respects_switch(self) -> None:
        store = MemoryStore()
        provider = CaptureProvider()
        service = self.build(store, provider)

        self.collect(service, "我去年跟儿子去过海南")
        self.assertEqual(len(self.after_turn_calls), 1)
        self.assertEqual(store.counts()["total"], 0, "开关没开，不该写入")

        store.update_settings("e_1", auto_extract=True)
        self.collect(service, "我去年跟儿子去过海南")
        self.assertEqual(store.counts()["total"], 1)

    def test_replay_does_not_re_extract(self) -> None:
        store = MemoryStore()
        store.update_settings("e_1", auto_extract=True)
        provider = CaptureProvider()
        service = self.build(store, provider)

        self.collect(service, "我去年跟儿子去过海南", client_msg_id="m_1")
        self.collect(service, "我去年跟儿子去过海南", client_msg_id="m_1")
        self.assertEqual(len(self.after_turn_calls), 1, "幂等回放不该再整理一次记忆")


class MemoryApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(
            settings=Settings(llm_provider="fake", scheduler_enabled=False),
            provider=FakeProvider(delay=0),
        )
        self.client = TestClient(self.app)

    def test_create_list_delete_flow(self) -> None:
        created = self.client.post(
            "/v1/memories",
            json={"elderId": "e_1", "kind": "experience", "text": "老人 2023 年跟儿子去过海南", "tags": ["儿子"]},
        )
        self.assertEqual(created.status_code, 200, created.text)
        memory_id = created.json()["memory"]["id"]

        listed = self.client.get("/v1/memories", params={"elderId": "e_1"}).json()
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["memories"][0]["text"], "老人 2023 年跟儿子去过海南")

        patched = self.client.patch(f"/v1/memories/{memory_id}", json={"text": "老人 2023 年去过海南"})
        self.assertEqual(patched.json()["memory"]["text"], "老人 2023 年去过海南")

        removed = self.client.delete(f"/v1/memories/{memory_id}")
        self.assertTrue(removed.json()["ok"])
        again = self.client.delete(f"/v1/memories/{memory_id}")
        self.assertEqual(again.status_code, 404)
        self.assertEqual(again.json()["error"]["code"], "memory_not_found")
        self.assertFalse(again.json()["error"]["retryable"])

    def test_empty_text_is_rejected_with_contract_error(self) -> None:
        response = self.client.post("/v1/memories", json={"elderId": "e_1", "text": "   "})
        self.assertEqual(response.status_code, 400)
        self.assertIn(response.json()["error"]["code"], ("invalid_request", "memory_empty"))

    def test_search_query(self) -> None:
        self.client.post("/v1/memories", json={"elderId": "e_1", "text": "老人 2023 年去过海南", "tags": ["旅行"]})
        self.client.post("/v1/memories", json={"elderId": "e_1", "text": "老人爱吃面", "kind": "preference"})
        found = self.client.get("/v1/memories", params={"elderId": "e_1", "q": "海南好玩吗"}).json()
        self.assertEqual(found["count"], 1)
        self.assertIn("score", found["memories"][0])

    def test_clear(self) -> None:
        self.client.post("/v1/memories", json={"elderId": "e_1", "text": "第一条"})
        self.client.post("/v1/memories", json={"elderId": "e_1", "text": "第二条"})
        cleared = self.client.post("/v1/memories/clear", json={"elderId": "e_1"}).json()
        self.assertEqual(cleared["removed"], 2)
        self.assertEqual(self.client.get("/v1/memories", params={"elderId": "e_1"}).json()["count"], 0)

    def test_settings_default_off_then_enable(self) -> None:
        default = self.client.get("/v1/memories/settings", params={"elderId": "e_1"}).json()["settings"]
        self.assertFalse(default["autoExtract"])
        enabled = self.client.put(
            "/v1/memories/settings", json={"elderId": "e_1", "autoExtract": True}
        ).json()["settings"]
        self.assertTrue(enabled["autoExtract"])
        self.assertTrue(enabled["consentedAt"])

    def test_pending_review_flow_and_family_privacy(self) -> None:
        """自动整理的低置信条目：默认列表里看不到 → 复核通过后才可见、可检索"""
        store = self.app.state.memories
        entry = store.add(
            "e_1", "老人好像提过老家的桥", source="auto", confidence=0.4, tags=["老家"]
        )

        listed = self.client.get("/v1/memories", params={"elderId": "e_1"}).json()
        self.assertEqual(listed["count"], 0, "待复核的默认不出现在列表里")
        self.assertEqual(listed["pendingCount"], 1)

        with_pending = self.client.get(
            "/v1/memories", params={"elderId": "e_1", "includePending": True, "scope": "all"}
        ).json()
        self.assertEqual(with_pending["count"], 1)

        # 家属视图：即使通过了复核，自动整理的记忆默认也不给家属看
        self.client.post("/v1/memories/review", json={"id": entry.id, "approve": True})
        family = self.client.get("/v1/memories", params={"elderId": "e_1"}).json()
        self.assertEqual(family["count"], 0, "自动整理的记忆不该出现在家人视图")
        elder_view = self.client.get("/v1/memories", params={"elderId": "e_1", "scope": "all"}).json()
        self.assertEqual(elder_view["count"], 1)
        self.assertEqual(
            self.client.get("/v1/memories", params={"elderId": "e_1", "q": "老家的桥"}).json()["count"],
            1,
            "复核通过后可以参与检索",
        )

    def test_family_entered_memory_is_visible_to_family(self) -> None:
        self.client.post("/v1/memories", json={"elderId": "e_1", "text": "老人 2023 年去过海南"})
        family = self.client.get("/v1/memories", params={"elderId": "e_1"}).json()
        self.assertEqual(family["count"], 1)

    def test_topics_endpoint(self) -> None:
        self.client.post(
            "/v1/memories",
            json={"elderId": "e_1", "kind": "preference", "text": "爱听戏", "tags": ["戏曲"]},
        )
        body = self.client.get("/v1/memories/topics", params={"elderId": "e_1"}).json()
        self.assertEqual(body["topics"][0]["topic"], "戏曲")

    def test_error_table_and_healthz_include_memory(self) -> None:
        codes = [row["code"] for row in self.client.get("/v1/errors").json()["codes"]]
        self.assertIn("memory_not_found", codes)
        health = self.client.get("/healthz").json()
        self.assertIn("memory", health)
        self.assertEqual(health["memory"]["total"], 0)


if __name__ == "__main__":
    unittest.main()
