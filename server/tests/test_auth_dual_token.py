"""鉴权的「双 token 共存」行为。

## 为什么必须测这个

端侧有两个凭据，装在不同的头里：
  · `X-API-Token`  → 接口级 token，过静态门（服务端 API_TOKENS）
  · `Authorization` → 账号会话 token，用来认「你是谁」

一开始服务端的静态门只读 `Authorization`，于是账号接口必然 401：
Authorization 被会话 token 占走了，拿它去和 API_TOKENS 比永远不相等。

这个测试锁住修复后的行为。没有它，以后有人把 `extract_token` 改回
"Authorization 优先"，线上表现是**打开 AUTH_MODE=required 后全站 401**，
而且本地（没开鉴权时）完全测不出来。
"""

from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import MODE_OFF, MODE_REQUIRED, check_request

STATIC = "static-gate-token-for-test"
SESSION = "account-session-token-for-test"


def build_app(auth_mode: str, api_tokens: str) -> FastAPI:
    app = FastAPI()

    class _Settings:
        pass

    settings = _Settings()
    settings.auth_mode = auth_mode
    settings.api_tokens = api_tokens
    app.state.settings = settings

    @app.middleware("http")
    async def gate(request, call_next):
        denied = check_request(request)
        if denied is not None:
            return denied
        return await call_next(request)

    @app.get("/v1/probe")
    def probe():
        return {"ok": True}

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    return app


class DualTokenTest(unittest.TestCase):
    def test_x_api_token_passes_gate(self) -> None:
        client = TestClient(build_app(MODE_REQUIRED, STATIC))
        resp = client.get("/v1/probe", headers={"X-API-Token": STATIC})
        self.assertEqual(resp.status_code, 200)

    def test_gate_prefers_x_api_token_over_authorization(self) -> None:
        """Authorization 放会话 token、X-API-Token 放静态 token —— 必须都能过。"""
        client = TestClient(build_app(MODE_REQUIRED, STATIC))
        resp = client.get(
            "/v1/probe",
            headers={"Authorization": "Bearer " + SESSION, "X-API-Token": STATIC},
        )
        self.assertEqual(resp.status_code, 200, "账号接口同时带两个 token 时被静态门挡掉了")

    def test_session_token_alone_is_rejected(self) -> None:
        """只带会话 token 过不了静态门 —— 这是预期行为，不是 bug。"""
        client = TestClient(build_app(MODE_REQUIRED, STATIC))
        resp = client.get("/v1/probe", headers={"Authorization": "Bearer " + SESSION})
        self.assertEqual(resp.status_code, 401)

    def test_no_token_is_rejected(self) -> None:
        client = TestClient(build_app(MODE_REQUIRED, STATIC))
        self.assertEqual(client.get("/v1/probe").status_code, 401)

    def test_static_token_via_authorization_still_works(self) -> None:
        """老客户端只发 Authorization 时行为不变，不能因为改动而破坏。"""
        client = TestClient(build_app(MODE_REQUIRED, STATIC))
        resp = client.get("/v1/probe", headers={"Authorization": "Bearer " + STATIC})
        self.assertEqual(resp.status_code, 200)

    def test_index_page_stays_public(self) -> None:
        client = TestClient(build_app(MODE_REQUIRED, STATIC))
        self.assertEqual(client.get("/healthz").status_code, 200)

    def test_off_mode_lets_everything_through(self) -> None:
        client = TestClient(build_app(MODE_OFF, STATIC))
        self.assertEqual(client.get("/v1/probe").status_code, 200)

    def test_auto_mode_without_tokens_is_open(self) -> None:
        client = TestClient(build_app("auto", ""))
        self.assertEqual(client.get("/v1/probe").status_code, 200)

    def test_auto_mode_with_tokens_enforces(self) -> None:
        client = TestClient(build_app("auto", STATIC))
        self.assertEqual(client.get("/v1/probe").status_code, 401)
        self.assertEqual(
            client.get("/v1/probe", headers={"X-API-Token": STATIC}).status_code, 200
        )


if __name__ == "__main__":
    unittest.main()
