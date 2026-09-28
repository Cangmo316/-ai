"""
鉴权单测

守两件事：
1. **配了就真的拦住**：没 token / 错 token 一律 401，不能因为"是本机"就放行
2. **公开路径仍然公开**：健康检查与错误码表要能给探针与端侧读，不能被鉴权挡住

以及一条工程约束：`AUTH_MODE=required` 但没配 token 时**必须启动失败**——
"以为开了鉴权其实没开"是这类加固里最危险的状态。
"""

from __future__ import annotations

import json
import unittest

from fastapi.testclient import TestClient

from app.auth import auth_required, extract_token, parse_tokens, token_valid
from app.config import Settings
from app.llm.fake import FakeProvider
from app.main import create_app

TOKEN = "elder-app-token-abc123"


def build(settings: Settings) -> TestClient:
    return TestClient(create_app(settings=settings, provider=FakeProvider(delay=0)))


class AuthHelpersTests(unittest.TestCase):
    def test_parse_tokens_ignores_blanks(self) -> None:
        self.assertEqual(parse_tokens(" a , b ,, c "), ["a", "b", "c"])
        self.assertEqual(parse_tokens(""), [])
        self.assertEqual(parse_tokens(None), [])

    def test_auth_required_resolution(self) -> None:
        self.assertFalse(auth_required(Settings(auth_mode="off", api_tokens=TOKEN)))
        self.assertTrue(auth_required(Settings(auth_mode="required", api_tokens=TOKEN)))
        self.assertTrue(auth_required(Settings(auth_mode="auto", api_tokens=TOKEN)))
        self.assertFalse(auth_required(Settings(auth_mode="auto", api_tokens="")))
        self.assertFalse(auth_required(Settings(auth_mode="", api_tokens="")))

    def test_token_valid_is_exact_match(self) -> None:
        settings = Settings(api_tokens=TOKEN)
        self.assertTrue(token_valid(settings, TOKEN))
        self.assertFalse(token_valid(settings, TOKEN[:-1]))
        self.assertFalse(token_valid(settings, " " + TOKEN))
        self.assertFalse(token_valid(settings, ""))


class AuthEnabledTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = build(
            Settings(
                llm_provider="fake",
                scheduler_enabled=False,
                auth_mode="required",
                api_tokens=TOKEN,
            )
        )
        self.headers = {"Authorization": "Bearer " + TOKEN}

    def test_missing_token_is_rejected_with_contract_error(self) -> None:
        response = self.client.get("/v1/plans/today")
        self.assertEqual(response.status_code, 401)
        body = response.json()["error"]
        self.assertEqual(body["code"], "auth_required")
        self.assertFalse(body["retryable"], "鉴权失败不该给重试按钮")

    def test_wrong_token_is_rejected(self) -> None:
        response = self.client.get("/v1/plans/today", headers={"Authorization": "Bearer wrong-token"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "unauthorized")

    def test_bearer_and_x_api_token_both_work(self) -> None:
        self.assertEqual(self.client.get("/v1/plans/today", headers=self.headers).status_code, 200)
        self.assertEqual(
            self.client.get("/v1/plans/today", headers={"X-API-Token": TOKEN}).status_code, 200
        )

    def test_post_routes_are_protected_too(self) -> None:
        response = self.client.post("/v1/plans/checkin", json={"planItemId": "x"})
        self.assertEqual(response.status_code, 401)
        response = self.client.post(
            "/v1/plans/checkin", json={"planItemId": "x"}, headers=self.headers
        )
        self.assertEqual(response.status_code, 409, "带 token 后应进入业务逻辑（没有生效计划）")

    def test_sse_stream_requires_token(self) -> None:
        response = self.client.post("/v1/chat/stream", json={"text": "妈 在吗"})
        self.assertEqual(response.status_code, 401)

    def test_public_paths_stay_open(self) -> None:
        self.assertEqual(self.client.get("/healthz").status_code, 200)
        self.assertEqual(self.client.get("/v1/errors").status_code, 200)

    def test_healthz_reports_auth_state(self) -> None:
        body = self.client.get("/healthz").json()
        self.assertTrue(body["auth"]["enabled"])
        self.assertEqual(body["auth"]["mode"], "required")
        self.assertEqual(body["auth"]["tokens"], 1)
        self.assertNotIn(TOKEN, json.dumps(body), "健康检查不该回显 token 明文")

    def test_full_flow_works_with_token(self) -> None:
        draft = self.client.post(
            "/v1/plans/draft", json={"elderId": "e_1", "polish": False}, headers=self.headers
        )
        self.assertEqual(draft.status_code, 200, draft.text)
        plan_id = draft.json()["plan"]["id"]
        self.assertEqual(
            self.client.post("/v1/plans/confirm", json={"planId": plan_id}, headers=self.headers).status_code,
            200,
        )
        today = self.client.get("/v1/plans/today", params={"elderId": "e_1"}, headers=self.headers)
        self.assertEqual(today.status_code, 200)
        self.assertGreater(today.json()["total"], 0)


class AuthDisabledTests(unittest.TestCase):
    def test_off_mode_allows_everything(self) -> None:
        client = build(Settings(llm_provider="fake", scheduler_enabled=False, auth_mode="off"))
        self.assertEqual(client.get("/v1/plans/today").status_code, 200)

    def test_auto_without_tokens_is_open_but_reported(self) -> None:
        client = build(Settings(llm_provider="fake", scheduler_enabled=False, auth_mode="auto"))
        self.assertEqual(client.get("/v1/plans/today").status_code, 200)
        body = client.get("/healthz").json()
        self.assertFalse(body["auth"]["enabled"], "auto 且没配 token 时应明确报告未鉴权")

    def test_required_without_tokens_fails_fast(self) -> None:
        """上线最怕"以为开了鉴权其实没开"：那就别启动"""
        with self.assertRaises(ValueError) as ctx:
            create_app(
                settings=Settings(
                    llm_provider="fake", scheduler_enabled=False, auth_mode="required", api_tokens=""
                ),
                provider=FakeProvider(delay=0),
            )
        self.assertIn("API_TOKENS", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
