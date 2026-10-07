"""
HTTP 层契约测试（用 FastAPI TestClient 跑真实 ASGI 栈）

守的是**端侧解析器能吃下去**这件事：
事件名、字段名、状态码、错误体结构，全都要和 `uni-app/api/README.md` 一致。
"""

from __future__ import annotations

import json
import unittest

from fastapi.testclient import TestClient

from app.config import Settings
from app.llm.fake import FakeProvider
from app.main import create_app


def parse_sse(raw: str) -> list[tuple[str, dict]]:
    """按契约解析 SSE 文本（与 uni-app/api/sse-parse.js 的行为对齐）。"""
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


class ApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        settings = Settings(llm_provider="fake", llm_api_key="")
        self.app = create_app(settings=settings, provider=FakeProvider(delay=0))
        self.client = TestClient(self.app)

    # ------------------------------------------------------------- 流式

    def test_stream_contract(self) -> None:
        with self.client.stream(
            "POST", "/v1/chat/stream", json={"conversationId": "c_api", "text": "妈 药吃了没"}
        ) as response:
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/event-stream", response.headers["content-type"])
            raw = "".join(response.iter_text())

        events = parse_sse(raw)
        self.assertEqual(events[0][0], "meta")
        self.assertEqual(events[-1][0], "done")
        self.assertIn("sticker", [name for name, _ in events])

        text = "".join(payload["t"] for name, payload in events if name == "token")
        self.assertEqual(text, "妈 药吃了没\n吃完喝口热水 别空腹")
        self.assertNotIn("。", text)

        meta = events[0][1]
        self.assertEqual(meta["conversationId"], "c_api")
        self.assertTrue(meta["assistantMsgId"])
        self.assertEqual(meta["persona"]["name"], "比邻AI")

        done = events[-1][1]
        self.assertEqual(done["finishReason"], "stop")
        self.assertEqual(done["assistantMsgId"], meta["assistantMsgId"])

    def test_stream_sse_framing(self) -> None:
        """帧格式：event/data 行 + 空行分隔；中文不转义。"""
        with self.client.stream("POST", "/v1/chat/stream", json={"text": "妈 在吗"}) as response:
            raw = "".join(response.iter_text())
        self.assertTrue(raw.startswith("event: meta\ndata: {"))
        self.assertIn("\n\n", raw)
        self.assertIn("妈", raw)          # 中文直出
        self.assertNotIn("\\u5988", raw)  # 不是转义形式

    def test_stream_empty_text_returns_contract_error(self) -> None:
        response = self.client.post("/v1/chat/stream", json={"text": "   "})
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["error"]["code"], "empty_text")
        self.assertTrue(body["error"]["message"])

    def test_stream_error_event(self) -> None:
        with self.client.stream("POST", "/v1/chat/stream", json={"text": "__error"}) as response:
            raw = "".join(response.iter_text())
        events = parse_sse(raw)
        self.assertEqual(events[0][0], "meta")
        self.assertEqual(events[-1][0], "error")
        payload = events[-1][1]
        self.assertEqual(payload["code"], "server_error")
        self.assertTrue(payload["retryable"])

    # --------------------------------------------------------- 非流式

    def test_send_contract(self) -> None:
        response = self.client.post("/v1/chat/send", json={"conversationId": "c_api", "text": "今天天气怎么样"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        for key in ("conversationId", "assistantMsgId", "persona", "text", "sticker", "card", "finishReason"):
            self.assertIn(key, body)
        self.assertEqual(body["text"], "今天降温了\n出门加件外套")
        self.assertEqual(body["sticker"], "sun")

    def test_send_error_envelope(self) -> None:
        response = self.client.post("/v1/chat/send", json={"text": "__error"})
        self.assertEqual(response.status_code, 502)
        body = response.json()
        self.assertEqual(body["error"]["code"], "server_error")
        self.assertTrue(body["error"]["message"])

    # ------------------------------------------------------------ 历史

    def test_history_roundtrip(self) -> None:
        self.client.post("/v1/chat/send", json={"conversationId": "c_hist", "text": "妈 药吃了没"})
        response = self.client.get("/v1/chat/history", params={"conversationId": "c_hist"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["conversationId"], "c_hist")
        self.assertGreaterEqual(len(body["messages"]), 3)
        for message in body["messages"]:
            self.assertTrue(message["id"])
            self.assertIn(message["role"], ("elder", "agent", "system"))
            self.assertTrue(message["createdAt"])

    def test_history_limit_validation(self) -> None:
        response = self.client.get("/v1/chat/history", params={"conversationId": "c_hist", "limit": 0})
        self.assertEqual(response.status_code, 422)

    # ------------------------------------------------------ 人设 / 自检

    def test_personas(self) -> None:
        response = self.client.get("/v1/personas")
        self.assertEqual(response.status_code, 200)
        personas = response.json()["personas"]
        self.assertGreaterEqual(len(personas), 4)
        names = [item["name"] for item in personas]
        self.assertIn("儿子 小明", names)
        for item in personas:
            self.assertIn("avatarColor", item)
            self.assertNotIn("traits", item)

    def test_healthz_masks_key(self) -> None:
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["llm"]["usesRealModel"])
        self.assertEqual(body["llm"]["provider"], "fake")

    def test_healthz_masks_real_key(self) -> None:
        settings = Settings(
            llm_provider="openai_compat",
            llm_api_key="sk-1234567890abcdef",
            llm_base_url="https://example.invalid/v1",
        )
        app = create_app(settings=settings, provider=FakeProvider(delay=0))
        body = TestClient(app).get("/healthz").json()
        self.assertTrue(body["llm"]["usesRealModel"])
        self.assertEqual(body["llm"]["apiKey"], "sk-1****cdef")
        self.assertNotIn("1234567890", body["llm"]["apiKey"])

    def test_unknown_route_uses_contract_error(self) -> None:
        response = self.client.get("/v1/nope")
        self.assertEqual(response.status_code, 404)
        body = response.json()
        self.assertEqual(body["error"]["code"], "not_found")


if __name__ == "__main__":
    unittest.main()
