"""编排层单测：受控表情抽取、事件顺序、落库、上下文组装、错误路径"""

from __future__ import annotations

import asyncio
import unittest
from collections.abc import AsyncIterator

from app.config import Settings
from app.llm.base import LLMError, LLMProvider
from app.llm.fake import FakeProvider
from app.models.message import ROLE_AGENT, ROLE_ELDER, TYPE_STICKER, TYPE_TEXT, ConversationStore
from app.orchestration import events
from app.orchestration.service import ChatService, StickerExtractor
from app.persona.prompts import PersonaRegistry


class ScriptedProvider(LLMProvider):
    """按脚本吐字的假模型：用来精确控制分片边界与异常注入。"""

    name = "scripted"

    def __init__(self, chunks: list[str], error: Exception | None = None) -> None:
        self.chunks = chunks
        self.error = error
        self.seen_messages: list[list[dict]] = []

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        self.seen_messages.append(messages)
        for chunk in self.chunks:
            yield chunk
        if self.error:
            raise self.error


def build_service(provider: LLMProvider) -> ChatService:
    settings = Settings(llm_provider="fake")
    return ChatService(provider, ConversationStore(), PersonaRegistry(), settings)


def collect(service: ChatService, text: str, conversation_id: str = "c_test") -> list[tuple[str, dict]]:
    async def run() -> list[tuple[str, dict]]:
        return [item async for item in service.generate(conversation_id, text)]

    return asyncio.run(run())


def names(items: list[tuple[str, dict]]) -> list[str]:
    return [name for name, _payload in items]


def joined_tokens(items: list[tuple[str, dict]]) -> str:
    return "".join(payload["t"] for name, payload in items if name == events.EVENT_TOKEN)


class StickerExtractorTests(unittest.TestCase):
    def test_complete_tag(self) -> None:
        extractor = StickerExtractor()
        text, stickers = extractor.feed("妈 好<sticker:love>")
        self.assertEqual(text, "妈 好")
        self.assertEqual(stickers, ["love"])

    def test_tag_split_across_feeds_is_not_leaked(self) -> None:
        """标签被切开时，半个标签也不能当正文发出去。"""
        extractor = StickerExtractor()
        self.assertEqual(extractor.feed("妈 好<stic"), ("妈 好", []))
        self.assertEqual(extractor.feed("ker:pi"), ("", []))
        self.assertEqual(extractor.feed("ll>"), ("", ["pill"]))

    def test_text_after_tag(self) -> None:
        extractor = StickerExtractor()
        text, stickers = extractor.feed("<sticker:love>妈 好")
        self.assertEqual(text, "妈 好")
        self.assertEqual(stickers, ["love"])

    def test_multiple_tags(self) -> None:
        extractor = StickerExtractor()
        text, stickers = extractor.feed("a<sticker:love>b<sticker:hug>c")
        self.assertEqual(text, "abc")
        self.assertEqual(stickers, ["love", "hug"])

    def test_lone_angle_bracket_is_text(self) -> None:
        extractor = StickerExtractor()
        text, stickers = extractor.feed("1 < 2 是不是")
        self.assertEqual(text, "1 < 2 是不是")
        self.assertEqual(stickers, [])

    def test_incomplete_tag_is_dropped_on_flush(self) -> None:
        """半个标签既不提前当正文发出去，也不在收尾时泄露。"""
        extractor = StickerExtractor()
        first, stickers_in_first = extractor.feed("妈 好<sticker:lo")
        self.assertEqual(first, "妈 好")
        self.assertEqual(stickers_in_first, [])
        text, stickers = extractor.flush()
        self.assertEqual(text, "")
        self.assertEqual(stickers, [])

    def test_buffer_does_not_grow_forever(self) -> None:
        """一个永不闭合的 '<' 不能把缓冲区撑爆。"""
        extractor = StickerExtractor()
        text, _ = extractor.feed("<" + "s" * 200)
        self.assertGreater(len(text), 0)


class ServiceEventTests(unittest.TestCase):
    def test_event_order_and_style(self) -> None:
        """完整链路：meta 打头、done 收尾、正文无句号、表情在正文之后。"""
        service = build_service(FakeProvider(delay=0))
        items = collect(service, "妈 药吃了没")

        self.assertEqual(names(items)[0], events.EVENT_META)
        self.assertEqual(names(items)[-1], events.EVENT_DONE)
        self.assertEqual(joined_tokens(items), "妈 药吃了没\n吃完喝口热水 别空腹")
        self.assertNotIn("。", joined_tokens(items))

        sticker_index = names(items).index(events.EVENT_STICKER)
        self.assertEqual(items[sticker_index][1]["token"], "pill")
        # 表情必须排在所有正文之后（先说人话，再发表情）
        last_token_index = max(i for i, name in enumerate(names(items)) if name == events.EVENT_TOKEN)
        self.assertGreater(sticker_index, last_token_index)

    def test_meta_carries_persona_and_ids(self) -> None:
        service = build_service(FakeProvider(delay=0))
        items = collect(service, "妈 在吗")
        _name, payload = items[0]
        self.assertEqual(payload["conversationId"], "c_test")
        self.assertTrue(payload["assistantMsgId"])
        self.assertEqual(payload["persona"]["name"], "儿子 小明")
        self.assertEqual(payload["persona"]["avatarColor"], "#07C160")
        self.assertNotIn("traits", payload["persona"])

    def test_messages_are_persisted_in_order(self) -> None:
        service = build_service(FakeProvider(delay=0))
        collect(service, "妈 药吃了没")
        stored = service.store.history("c_test")
        # 种子问候 + 老人的话 + 正文 + 表情
        self.assertEqual(stored[0].role, ROLE_AGENT)  # 种子问候
        elder = [m for m in stored if m.role == ROLE_ELDER]
        self.assertEqual(len(elder), 1)
        self.assertEqual(elder[0].text, "妈 药吃了没")
        agents = [m for m in stored if m.role == ROLE_AGENT][1:]
        self.assertEqual(agents[0].type, TYPE_TEXT)
        self.assertEqual(agents[0].text, "妈 药吃了没\n吃完喝口热水 别空腹")
        self.assertEqual(agents[-1].type, TYPE_STICKER)
        self.assertEqual(agents[-1].sticker, "pill")

    def test_sticker_outside_whitelist_is_dropped(self) -> None:
        """模型自己编的 token 必须拦掉，且不能把标签文本泄露给老人。"""
        provider = ScriptedProvider(["妈 好", "<sticker:heart>", "嗯"])
        service = build_service(provider)
        items = collect(service, "妈 好")
        self.assertNotIn(events.EVENT_STICKER, names(items))
        self.assertEqual(joined_tokens(items), "妈 好嗯")
        self.assertNotIn("<", joined_tokens(items))

    def test_llm_error_becomes_error_event_without_agent_messages(self) -> None:
        service = build_service(FakeProvider(delay=0))
        items = collect(service, "__error 妈")
        self.assertEqual(names(items)[0], events.EVENT_META)
        self.assertEqual(names(items)[-1], events.EVENT_ERROR)
        _name, payload = items[-1]
        self.assertEqual(payload["code"], "server_error")
        self.assertTrue(payload["retryable"])
        stored = service.store.history("c_test")
        # 只落库了老人的那句话，没有空气泡
        self.assertEqual([m.role for m in stored[1:]], [ROLE_ELDER])

    def test_unexpected_exception_is_contained(self) -> None:
        provider = ScriptedProvider(["妈 好"], error=RuntimeError("boom"))
        service = build_service(provider)
        items = collect(service, "妈 好")
        self.assertEqual(names(items)[-1], events.EVENT_ERROR)
        payload = items[-1][1]
        self.assertEqual(payload["code"], "internal")

    def test_history_is_injected_into_context(self) -> None:
        provider = ScriptedProvider(["妈 好。"])
        service = build_service(provider)
        collect(service, "第一句")
        collect(service, "第二句")
        messages = provider.seen_messages[-1]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("句末不加句号", messages[0]["content"])
        self.assertIn("不做诊断", messages[0]["content"])
        self.assertIn("<sticker:token>", messages[0]["content"])
        # 用药边界的措辞要求（真模型抽查曾在这里越线：说"这药不能停"）
        self.assertIn("绝不替医生判断", messages[0]["content"])
        self.assertIn("这事得问医生", messages[0]["content"])
        contents = [m["content"] for m in messages if m["role"] != "system"]
        self.assertIn("第一句", contents)
        self.assertEqual(contents[-1], "第二句")

    def test_persona_switch_changes_prompt(self) -> None:
        provider = ScriptedProvider(["嗯。"])
        service = build_service(provider)

        async def run() -> None:
            async for _ in service.generate("c_persona", "在吗", persona_id="p_daughter"):
                pass

        asyncio.run(run())
        system_prompt = provider.seen_messages[-1][0]["content"]
        self.assertIn("女儿 小丽", system_prompt)


class SlowFirstTokenProvider(LLMProvider):
    """模拟推理模型：要等一会儿才吐第一个 content token。"""

    name = "slow"

    def __init__(self, first_token_delay: float) -> None:
        self.first_token_delay = first_token_delay

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        await asyncio.sleep(self.first_token_delay)
        yield "妈"


class HeartbeatTests(unittest.TestCase):
    def test_heartbeat_while_waiting_for_first_token(self) -> None:
        """等模型期间必须发心跳，否则端侧 20s 首字节看门狗会把连接掐掉。"""
        settings = Settings(llm_provider="fake", sse_heartbeat_seconds=0.05)
        service = ChatService(
            SlowFirstTokenProvider(0.2), ConversationStore(), PersonaRegistry(), settings
        )

        async def run() -> list[str]:
            return [frame async for frame in service.stream_sse("c_hb", "在吗")]

        frames = asyncio.run(run())
        raw = "".join(frames)
        self.assertIn(events.HEARTBEAT, raw)
        self.assertLess(raw.index(": ping"), raw.index("event: token"))

    def test_no_heartbeat_when_model_is_fast(self) -> None:
        """模型很快时不该插心跳（免得端侧做无谓的解析）。"""
        settings = Settings(llm_provider="fake", sse_heartbeat_seconds=5.0)
        service = ChatService(FakeProvider(delay=0), ConversationStore(), PersonaRegistry(), settings)

        async def run() -> list[str]:
            return [frame async for frame in service.stream_sse("c_fast", "妈 在吗")]

        raw = "".join(asyncio.run(run()))
        self.assertNotIn(": ping", raw)
        self.assertIn("event: done", raw)


class ReplyOnceTests(unittest.TestCase):
    def test_reply_once_shape(self) -> None:
        service = build_service(FakeProvider(delay=0))
        result = asyncio.run(service.reply_once("c_json", "今天天气怎么样"))
        self.assertEqual(set(result), {
            "conversationId", "assistantMsgId", "persona", "text", "sticker", "card", "finishReason",
        })
        self.assertEqual(result["text"], "今天降温了\n出门加件外套")
        self.assertEqual(result["sticker"], "sun")
        self.assertIsNone(result["card"])
        self.assertEqual(result["finishReason"], "stop")
        self.assertNotIn("。", result["text"])

    def test_reply_once_raises_llm_error(self) -> None:
        service = build_service(FakeProvider(delay=0))
        with self.assertRaises(LLMError) as ctx:
            asyncio.run(service.reply_once("c_json", "__error"))
        self.assertEqual(ctx.exception.code, "server_error")

    def test_stream_and_once_agree_on_text(self) -> None:
        """同一句话，流式拼出来的正文与一次性回复必须逐字一致。"""
        text = "妈 我血压 130.5 有点高。少放盐。"
        streamed = joined_tokens(collect(build_service(FakeProvider(delay=0)), text))
        once = asyncio.run(build_service(FakeProvider(delay=0)).reply_once("c_same", text))
        self.assertEqual(streamed, once["text"])


if __name__ == "__main__":
    unittest.main()
