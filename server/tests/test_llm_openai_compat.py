"""
真实模型客户端（OpenAI 兼容）单测

用 `httpx.MockTransport` 伪造上游，不需要 key、不联网。
守三件事：
1. **只取 content，绝不把 reasoning_content 混进正文**（推理模型的思维链一旦下发到老人端，
   既听不懂又可能夹带诊疗措辞，属红线）
2. 上游的脏行（心跳、非 JSON、[DONE]）不能打断整条流
3. 鉴权/额度/5xx 要翻译成老人能听懂的话，并且 retryable 标对
"""

from __future__ import annotations

import asyncio
import json
import unittest

import httpx

from app.llm.base import LLMError
from app.llm.openai_compat import OpenAICompatProvider


def make_provider(handler) -> OpenAICompatProvider:
    return OpenAICompatProvider(
        base_url="https://llm.example.invalid/v1",
        api_key="sk-test-key",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )


def sse_body(lines: list[dict | str]) -> bytes:
    parts = []
    for line in lines:
        if isinstance(line, str):
            parts.append(line)
        else:
            parts.append("data: " + json.dumps(line, ensure_ascii=False))
    return ("\n\n".join(parts) + "\n\n").encode("utf-8")


def delta(content: str | None = None, reasoning: str | None = None) -> dict:
    payload: dict = {"choices": [{"delta": {}}]}
    if content is not None:
        payload["choices"][0]["delta"]["content"] = content
    if reasoning is not None:
        payload["choices"][0]["delta"]["reasoning_content"] = reasoning
    return payload


def collect(provider: OpenAICompatProvider, messages: list[dict]) -> list[str]:
    async def run() -> list[str]:
        return [chunk async for chunk in provider.stream(messages)]

    return asyncio.run(run())


class StreamParsingTests(unittest.TestCase):
    def test_reasoning_content_is_never_forwarded(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=sse_body(
                    [
                        delta(reasoning="老人可能血压高，应该建议调整用药……"),
                        delta(content="妈", reasoning="再想想"),
                        delta(content=" 好"),
                        "[DONE]",
                    ]
                ),
            )

        chunks = collect(make_provider(handler), [{"role": "user", "content": "妈 在吗"}])
        self.assertEqual(chunks, ["妈", " 好"])
        self.assertNotIn("用药", "".join(chunks))

    def test_heartbeat_and_garbage_lines_do_not_break_stream(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=sse_body(
                    [
                        ": ping",
                        "这不是 JSON",
                        delta(content="妈"),
                        "event: done",
                        delta(content=" 好"),
                        "[DONE]",
                    ]
                ),
            )

        chunks = collect(make_provider(handler), [{"role": "user", "content": "x"}])
        self.assertEqual(chunks, ["妈", " 好"])

    def test_content_as_parts_list(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = sse_body(
                [
                    {"choices": [{"delta": {"content": [{"type": "text", "text": "妈"}]}}]},
                    {"choices": [{"delta": {"content": [{"type": "text", "text": "好"}]}}]},
                    "[DONE]",
                ]
            )
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

        self.assertEqual(collect(make_provider(handler), []), ["妈", "好"])

    def test_request_payload_and_headers(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["auth"] = request.headers.get("authorization")
            captured["payload"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse_body(["[DONE]"]))

        collect(make_provider(handler), [{"role": "user", "content": "妈 在吗"}])
        self.assertEqual(captured["url"], "https://llm.example.invalid/v1/chat/completions")
        self.assertEqual(captured["auth"], "Bearer sk-test-key")
        self.assertTrue(captured["payload"]["stream"])
        self.assertEqual(captured["payload"]["model"], "test-model")
        self.assertEqual(captured["payload"]["messages"][0]["content"], "妈 在吗")


class ErrorMappingTests(unittest.TestCase):
    def _expect_error(self, status_code: int, body: dict | None = None) -> LLMError:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code, json=body or {"error": {"message": "upstream detail"}})

        with self.assertRaises(LLMError) as ctx:
            collect(make_provider(handler), [])
        return ctx.exception

    def test_401_is_not_retryable(self) -> None:
        error = self._expect_error(401)
        self.assertEqual(error.code, "llm_auth")
        self.assertFalse(error.retryable)
        self.assertIn("模型还没配置好", error.message)

    def test_404_model_not_found(self) -> None:
        error = self._expect_error(404)
        self.assertEqual(error.code, "llm_model_not_found")
        self.assertFalse(error.retryable)

    def test_429_is_retryable(self) -> None:
        error = self._expect_error(429)
        self.assertEqual(error.code, "llm_rate_limited")
        self.assertTrue(error.retryable)

    def test_500_is_retryable(self) -> None:
        error = self._expect_error(500)
        self.assertEqual(error.code, "llm_unavailable")
        self.assertTrue(error.retryable)
        self.assertIn("服务器开小差了", error.message)

    def test_timeout_maps_to_llm_timeout(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("too slow", request=request)

        with self.assertRaises(LLMError) as ctx:
            collect(make_provider(handler), [])
        self.assertEqual(ctx.exception.code, "llm_timeout")
        self.assertTrue(ctx.exception.retryable)

    def test_network_error_maps_to_unavailable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route", request=request)

        with self.assertRaises(LLMError) as ctx:
            collect(make_provider(handler), [])
        self.assertEqual(ctx.exception.code, "llm_unavailable")

    def test_missing_api_key_fails_fast(self) -> None:
        provider = OpenAICompatProvider(
            base_url="https://llm.example.invalid/v1", api_key="", model="test-model"
        )
        with self.assertRaises(LLMError) as ctx:
            collect(provider, [])
        self.assertEqual(ctx.exception.code, "llm_auth")
        self.assertFalse(ctx.exception.retryable)

    def test_error_message_is_human_readable(self) -> None:
        error = self._expect_error(500)
        for forbidden in ("Internal Server Error", "Traceback", "http"):
            self.assertNotIn(forbidden, error.message)


if __name__ == "__main__":
    unittest.main()
