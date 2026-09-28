"""
错误码表单测

这张表是跨语言契约的一部分：端侧按 code 决定"能不能重试 / 要不要提示重新登录 / 展示哪句话"。
所以它自己要满足几条硬要求：
- 每个码都有 HTTP 状态、人话文案、retryable
- 文案里不能出现英文异常名或堆栈（它会直接展示给老人）
- 未知码有兜底，不能抛异常
"""

from __future__ import annotations

import re
import unittest

from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import ERROR_TABLE, api_error, code_for_status, payload, spec_of, table
from app.llm.fake import FakeProvider
from app.main import create_app

# 会直接展示给老人的文案里不该出现的东西
FORBIDDEN = ("Error", "Traceback", "Exception", "None", "http", "HTTP", "null", "undefined")


class ErrorTableTests(unittest.TestCase):
    def test_every_code_is_complete(self) -> None:
        for code, spec in ERROR_TABLE.items():
            with self.subTest(code=code):
                self.assertTrue(code)
                self.assertIn(spec.status, (400, 401, 403, 404, 405, 409, 422, 429, 500, 502, 503, 504))
                self.assertTrue(spec.message.strip())
                self.assertIsInstance(spec.retryable, bool)

    def test_messages_are_human_readable(self) -> None:
        for code, spec in ERROR_TABLE.items():
            with self.subTest(code=code):
                for word in FORBIDDEN:
                    self.assertNotIn(word, spec.message, f"{code} 的文案里出现了 {word}")
                self.assertFalse(re.search(r"[A-Za-z]{6,}", spec.message), spec.message)

    def test_codes_are_lowercase_snake(self) -> None:
        for code in ERROR_TABLE:
            with self.subTest(code=code):
                self.assertRegex(code, r"^[a-z][a-z0-9_]*$")

    def test_auth_errors_are_not_retryable(self) -> None:
        """鉴权/格式类错误不该给端侧"重试"按钮——重试一百次也还是失败"""
        self.assertFalse(spec_of("unauthorized").retryable)
        self.assertFalse(spec_of("auth_required").retryable)
        self.assertFalse(spec_of("invalid_request").retryable)
        self.assertFalse(spec_of("plan_state").retryable)
        self.assertTrue(spec_of("internal").retryable)
        self.assertTrue(spec_of("llm_timeout").retryable)

    def test_plan_state_is_conflict(self) -> None:
        self.assertEqual(spec_of("plan_state").status, 409)
        self.assertEqual(spec_of("plan_not_active").status, 409)

    def test_unknown_code_falls_back_without_raising(self) -> None:
        spec = spec_of("someone_forgot_to_register_this")
        self.assertEqual(spec.status, 400)
        body = payload("someone_forgot_to_register_this")
        self.assertEqual(body["error"]["code"], "someone_forgot_to_register_this")

    def test_payload_can_override_message(self) -> None:
        body = payload("plan_state", "计划当前是「草稿」，不能确认")
        self.assertEqual(body["error"]["message"], "计划当前是「草稿」，不能确认")
        self.assertEqual(body["error"]["code"], "plan_state")

    def test_api_error_response(self) -> None:
        response = api_error("plan_not_found")
        self.assertEqual(response.status_code, 404)
        response = api_error("internal", "数据库连不上，一会儿再试")
        self.assertEqual(response.status_code, 500)

    def test_code_for_status_mapping(self) -> None:
        self.assertEqual(code_for_status(401), "unauthorized")
        self.assertEqual(code_for_status(404), "not_found")
        self.assertEqual(code_for_status(422), "invalid_request")
        self.assertEqual(code_for_status(405), "method_not_allowed")
        self.assertEqual(code_for_status(418), "http_error")
        self.assertEqual(code_for_status(503), "internal")

    def test_table_is_sorted_and_serializable(self) -> None:
        rows = table()
        self.assertEqual(len(rows), len(ERROR_TABLE))
        self.assertEqual([row["code"] for row in rows], sorted(row["code"] for row in rows))
        for row in rows:
            self.assertIn("retryable", row)


class ErrorApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(
            create_app(
                settings=Settings(llm_provider="fake", scheduler_enabled=False),
                provider=FakeProvider(delay=0),
            )
        )

    def test_error_table_endpoint_is_public_and_complete(self) -> None:
        response = self.client.get("/v1/errors")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["codes"]), len(ERROR_TABLE))
        self.assertIn("retryable", body["note"])

    def test_unknown_route_uses_table(self) -> None:
        response = self.client.get("/v1/nope")
        self.assertEqual(response.status_code, 404)
        body = response.json()["error"]
        self.assertEqual(body["code"], "not_found")
        self.assertFalse(body["retryable"])

    def test_validation_error_uses_table(self) -> None:
        response = self.client.get("/v1/chat/history", params={"limit": 0})
        self.assertEqual(response.status_code, 422)
        body = response.json()["error"]
        self.assertEqual(body["code"], "invalid_request")
        self.assertFalse(body["retryable"])

    def test_all_error_bodies_carry_code_message_retryable(self) -> None:
        probes = [
            ("get", "/v1/nope", None),
            ("post", "/v1/chat/stream", {"text": "  "}),
            ("post", "/v1/plans/confirm", {"planId": "nope"}),
            ("post", "/v1/plans/checkin", {"planItemId": "x"}),
            ("get", "/v1/reminders/tasks", {"date": "24/09/2026"}),
            ("get", "/v1/plans/today", {"date": "2026/09/24"}),
        ]
        for method, path, body in probes:
            with self.subTest(path=path):
                if method == "get":
                    response = self.client.get(path, params=body)
                else:
                    response = self.client.post(path, json=body)
                self.assertGreaterEqual(response.status_code, 400)
                error = response.json()["error"]
                self.assertTrue(error["code"])
                self.assertTrue(error["message"])
                self.assertIn("retryable", error)


if __name__ == "__main__":
    unittest.main()
