"""
回复被 token 上限截断时的「续写」行为。

背景（用户反馈）：智能体回复过长时会**说到一半直接截断**。
根因是 `llm_max_tokens` 只有 300，模型还没写完就撞上限，
而编排层拿不到"被截断"的信号（`finish_reason` 被丢弃了），
只能把半句话发给老人。

这一份钉住修好之后的行为：
  1. 撞上限时**接着写**，而不是把半句丢出去
  2. 上一段停在句子边界 → **另起一条消息**（端上是第二个气泡），读起来是两段完整的话
  3. 上一段停在半句中间 → 并回同一条，不硬拆（硬拆会两句都读不通）
  4. 续写请求里带上了"已经说过的话"，且明确要求不要重复
  5. 真到了续写上限就收手，不能无休止地续
"""

from __future__ import annotations

import asyncio
import unittest

from app.llm.base import LLMProvider
from app.orchestration import events
from app.orchestration.service import MAX_CONTINUATIONS, ChatService
from app.config import Settings
from app.models.message import ConversationStore
from app.persona.prompts import PersonaRegistry


class TruncatingProvider(LLMProvider):
    """按脚本吐字的假模型，并且能报告"这一轮是被截断的"。

    每个脚本项是 (文本, finish_reason)；模拟真实流：文本逐字吐，
    最后一片带 finish_reason。
    """

    name = "truncating"

    def __init__(self, script: list[tuple[str, str]]) -> None:
        self.script = list(script)
        self.calls: list[list[dict]] = []

    def describe(self) -> dict:
        return {"provider": "truncating"}

    async def stream(self, messages, on_finish=None):
        self.calls.append([dict(m) for m in messages])
        text, reason = self.script.pop(0) if self.script else ("", "stop")
        for ch in text:
            yield ch
        if on_finish is not None:
            on_finish(reason)


def build_service(provider) -> ChatService:
    settings = Settings(llm_provider="fake")
    return ChatService(provider, ConversationStore(), PersonaRegistry(), settings)


def collect(service: ChatService, text: str) -> list[tuple[str, dict]]:
    async def run():
        return [item async for item in service.generate("c_test", text)]

    return asyncio.run(run())


def metas(items) -> list[dict]:
    return [payload for name, payload in items if name == events.EVENT_META]


def tokens(items) -> str:
    return "".join(payload["t"] for name, payload in items if name == events.EVENT_TOKEN)


class ContinuationTestCase(unittest.TestCase):
    def test_ends_at_sentence_boundary_starts_a_second_message(self):
        """上一段停在句号 → 另起一条消息（两个气泡）"""
        provider = TruncatingProvider([
            ("妈 药吃了没。记得喝水。", "length"),
            ("晚上早点睡。", "stop"),
        ])
        items = collect(build_service(provider), "在吗")

        ms = metas(items)
        self.assertEqual(len(ms), 2, "应当发了两条消息（两个 meta）")
        self.assertNotEqual(ms[0]["assistantMsgId"], ms[1]["assistantMsgId"],
                            "两条消息必须是不同的 id，否则端上是同一个气泡")
        self.assertTrue(ms[1].get("continued"), "第二条要标出它是续写")

        # 两条内容合起来是完整的话，且没有丢字
        text = tokens(items)
        self.assertIn("妈 药吃了没", text)
        self.assertIn("晚上早点睡", text)

        # done 收尾只发一次
        self.assertEqual(sum(1 for n, _ in items if n == events.EVENT_DONE), 1)

    def test_stops_mid_sentence_does_not_split(self):
        """上一段停在半句中间 → 并回同一条，不硬拆成两条"""
        provider = TruncatingProvider([
            ("妈 我想跟你说个事，就是关于", "length"),
            ("吃药这件事，你千万别忘了。", "stop"),
        ])
        items = collect(build_service(provider), "在吗")

        ms = metas(items)
        self.assertEqual(len(ms), 1, "停在半句中间时不该另起消息")
        text = tokens(items)
        # 两段都在，而且是连着的
        self.assertIn("就是关于吃药这件事", text)

    def test_continuation_request_carries_what_was_already_said(self):
        """续写要带上已说的内容，并要求别重复"""
        provider = TruncatingProvider([
            ("第一段话说完了。", "length"),
            ("第二段。", "stop"),
        ])
        collect(build_service(provider), "在吗")

        self.assertEqual(len(provider.calls), 2, "应当发生了两次模型调用")
        second = provider.calls[1]
        # 倒数两条：模型的上一轮回答 + 续写指令
        self.assertEqual(second[-1]["role"], "user")
        self.assertIn("接着", second[-1]["content"])
        self.assertIn("不要重复", second[-1]["content"])
        self.assertEqual(second[-2]["role"], "assistant")
        self.assertIn("第一段话说完了", second[-2]["content"])

    def test_gives_up_at_the_limit(self):
        """一直撞上限也要收手，不能无限续"""
        # 全都会撞上限，且每次都停在句末（逼它一直另起消息）
        provider = TruncatingProvider([("又要被截断了。", "length")] * 20)
        items = collect(build_service(provider), "在吗")

        # 首次 + MAX_CONTINUATIONS 次续写
        self.assertEqual(len(provider.calls), MAX_CONTINUATIONS + 1)
        ms = metas(items)
        self.assertEqual(len(ms), MAX_CONTINUATIONS + 1)
        # 有内容产出，且正常收尾（不是抛错）
        self.assertTrue(tokens(items))
        self.assertEqual(sum(1 for n, _ in items if n == events.EVENT_DONE), 1)

    def test_natural_stop_never_continues(self):
        """自然说完（stop）时行为与改动前完全一致：只有一条消息、一次调用"""
        provider = TruncatingProvider([("妈 我在呢。", "stop")])
        items = collect(build_service(provider), "在吗")

        self.assertEqual(len(provider.calls), 1, "没撞上限就不该再调模型")
        self.assertEqual(len(metas(items)), 1)
        # 注意句末的「。」会被风格处理去掉（见 service 模块开头的说明），
        # 这里断言的是"内容没被续写逻辑动过"，不是标点原样
        self.assertEqual(tokens(items), "妈 我在呢")


class FinishReasonParsingTestCase(unittest.TestCase):
    """provider 层：finish_reason 要能正确解析出来（原来被丢弃了）"""

    def test_length_and_stop_are_reported(self):
        from app.llm.openai_compat import OpenAICompatProvider

        provider = OpenAICompatProvider(base_url="https://x.invalid/v1", api_key="k", model="m")
        chunk, reason = provider._parse_line_with_reason(
            'data: {"choices":[{"delta":{"content":"妈"},"finish_reason":null}]}'
        )
        self.assertEqual(chunk, "妈")
        self.assertEqual(reason, "")

        chunk, reason = provider._parse_line_with_reason(
            'data: {"choices":[{"delta":{},"finish_reason":"length"}]}'
        )
        self.assertEqual(chunk, "")
        self.assertEqual(reason, "length")

        chunk, reason = provider._parse_line_with_reason(
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}'
        )
        self.assertEqual(reason, "stop")

    def test_old_single_return_helper_still_works(self):
        """_parse_line 的签名保持不变（别处与既有测试在用）"""
        from app.llm.openai_compat import OpenAICompatProvider

        provider = OpenAICompatProvider(base_url="https://x.invalid/v1", api_key="k", model="m")
        self.assertEqual(
            provider._parse_line('data: {"choices":[{"delta":{"content":"好"}}]}'), "好"
        )
        self.assertEqual(provider._parse_line("data: [DONE]"), "")


if __name__ == "__main__":
    unittest.main()
