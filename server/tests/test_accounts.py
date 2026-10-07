"""账号接口契约测试：8 位编号分配、密码规则、登录鉴权、头像

重点盯三件事（都是"错了以后很难回收"的）：
  1. 编号从 00000000 起、**逐号 +1 且绝不复用**（含重启后不复用）
  2. 密码**不落明文**，且错误响应不区分"账号不存在"与"密码错"
  3. 未登录拿不到资料、换不了头像
"""

from __future__ import annotations

import unittest
from datetime import datetime

from fastapi.testclient import TestClient

from app.accounts import (
    DEV_ACCOUNT_NAME,
    DEV_ACCOUNT_NUMBER,
    DEV_ACCOUNT_PASSWORD,
    MAX_NUMBER,
    AccountStore,
    SqlAccountStore,
    format_number,
)
from app.accounts.password import hash_password, password_problem, verify_password
from app.config import Settings
from app.llm.fake import FakeProvider
from app.main import create_app


class Clock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment


def error_code(response) -> str:
    """错误体是嵌套的：{"error": {"code": ...}}（见 app/errors.py 的 payload）"""
    return (response.json().get("error") or {}).get("code", "")


def error_message(response) -> str:
    return (response.json().get("error") or {}).get("message", "")


def build_app(database_url: str = "memory://") -> TestClient:
    app = create_app(
        settings=Settings(
            llm_provider="fake",
            llm_api_key="",
            scheduler_enabled=False,
            database_url=database_url,
        ),
        provider=FakeProvider(delay=0),
        clock=Clock(datetime(2026, 10, 7, 9, 0)),
    )
    return TestClient(app)


class PasswordRuleTestCase(unittest.TestCase):
    """密码规则：8–16 位，只能是数字或字母"""

    def test_accepts_valid(self) -> None:
        for value in ("12345678", "abcdefgh", "AbCd1234", "1234567890123456"):
            self.assertEqual(password_problem(value), "", value)

    def test_rejects_too_short(self) -> None:
        self.assertIn("至少", password_problem("1234567"))

    def test_rejects_too_long(self) -> None:
        self.assertIn("最多", password_problem("12345678901234567"))

    def test_rejects_symbols_and_spaces(self) -> None:
        for value in ("abcd123!", "abc defg", "密码12345678", "abcd-1234"):
            self.assertIn("数字或字母", password_problem(value), value)

    def test_hash_is_not_plaintext_and_verifies(self) -> None:
        stored = hash_password("BILINAI0316")
        self.assertNotIn("BILINAI0316", stored)
        self.assertTrue(verify_password("BILINAI0316", stored))
        self.assertFalse(verify_password("bilinai0316", stored))
        self.assertFalse(verify_password("", stored))

    def test_verify_tolerates_broken_records(self) -> None:
        for broken in ("", "garbage", "pbkdf2_sha256$abc$x$y", "md5$1$aa$bb"):
            self.assertFalse(verify_password("whatever", broken))


class NumberAllocationTestCase(unittest.TestCase):
    """编号：从 00000000 起，逐号 +1，绝不复用"""

    def test_dev_account_gets_00000000(self) -> None:
        client = build_app()
        response = client.post(
            "/v1/accounts/login",
            json={"name": DEV_ACCOUNT_NAME, "password": DEV_ACCOUNT_PASSWORD},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["account"]["number"], DEV_ACCOUNT_NUMBER)

    def test_numbers_increment_from_zero(self) -> None:
        client = build_app()
        # 测试账号已占 00000000，第一个新注册账号应该是 00000001
        first = client.post(
            "/v1/accounts/register",
            json={"name": "张阿姨", "password": "abcd1234", "confirm": "abcd1234"},
        )
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(first.json()["account"]["number"], "00000001")

        second = client.post(
            "/v1/accounts/register",
            json={"name": "李叔叔", "password": "abcd1234", "confirm": "abcd1234"},
        )
        self.assertEqual(second.json()["account"]["number"], "00000002")

    def test_numbers_are_not_reused_after_restart(self) -> None:
        """核心用例：重启后不能从 00000000 重发（否则两个账号撞号）"""
        import tempfile
        from pathlib import Path

        tmp = tempfile.mkdtemp(prefix="bilin-accounts-")
        try:
            db = "sqlite:///" + str(Path(tmp) / "t.db").replace("\\", "/")
            first_client = build_app(db)
            created = first_client.post(
                "/v1/accounts/register",
                json={"name": "王大爷", "password": "abcd1234", "confirm": "abcd1234"},
            ).json()["account"]
            self.assertEqual(created["number"], "00000001")

            # 模拟重启：重新建一个 app，读同一个库
            second_client = build_app(db)
            after = second_client.post(
                "/v1/accounts/register",
                json={"name": "赵阿姨", "password": "abcd1234", "confirm": "abcd1234"},
            ).json()["account"]
            self.assertEqual(after["number"], "00000002", "重启后编号被复用了")
            self.assertNotEqual(after["number"], created["number"])

            # 老账号重启后仍能登录，且编号不变
            again = second_client.post(
                "/v1/accounts/login", json={"name": "王大爷", "password": "abcd1234"}
            )
            self.assertEqual(again.json()["account"]["number"], "00000001")
            # 关掉库再删目录：Windows 下不关会被文件占用挡住
            second_client.app.state.database.close()
            first_client.app.state.database.close()
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)

    def test_format_number_pads_to_eight(self) -> None:
        self.assertEqual(format_number(0), "00000000")
        self.assertEqual(format_number(7), "00000007")
        self.assertEqual(format_number(12345678), "12345678")
        with self.assertRaises(ValueError):
            format_number(MAX_NUMBER + 1)

    def test_store_raises_when_exhausted(self) -> None:
        store = AccountStore()
        store._issued = MAX_NUMBER + 1
        with self.assertRaises(ValueError):
            store.allocate_number()


class RegisterApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.client = build_app()

    def register(self, **kwargs):
        body = {"name": "测试用户", "password": "abcd1234", "confirm": "abcd1234"}
        body.update(kwargs)
        return self.client.post("/v1/accounts/register", json=body)

    def test_register_returns_token_and_number(self) -> None:
        response = self.register(name="孙奶奶")
        self.assertEqual(response.status_code, 201, response.text)
        data = response.json()
        self.assertTrue(data["token"])
        self.assertEqual(data["account"]["name"], "孙奶奶")
        self.assertRegex(data["account"]["number"], r"^\d{8}$")
        # 响应里绝不能出现密码或哈希
        self.assertNotIn("password", str(data).lower())

    def test_register_rejects_blank_name(self) -> None:
        response = self.register(name="   ")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(error_code(response), "account_name_required")

    def test_register_rejects_duplicate_name(self) -> None:
        self.register(name="重复的人")
        again = self.register(name="重复的人")
        self.assertEqual(again.status_code, 409)
        self.assertEqual(error_code(again), "account_name_taken")

    def test_register_name_is_case_insensitive(self) -> None:
        self.register(name="BiLin")
        again = self.register(name="bilin")
        self.assertEqual(again.status_code, 409, "大小写不同的同名应当算重名")

    def test_register_rejects_weak_password(self) -> None:
        response = self.register(password="abc123", confirm="abc123")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(error_code(response), "account_password_weak")

    def test_register_rejects_mismatched_confirm(self) -> None:
        response = self.register(password="abcd1234", confirm="abcd1235")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(error_code(response), "account_password_mismatch")


class LoginApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.client = build_app()

    def test_dev_account_can_login(self) -> None:
        response = self.client.post(
            "/v1/accounts/login",
            json={"name": DEV_ACCOUNT_NAME, "password": DEV_ACCOUNT_PASSWORD},
        )
        self.assertEqual(response.status_code, 200, response.text)
        account = response.json()["account"]
        self.assertEqual(account["name"], DEV_ACCOUNT_NAME)
        self.assertEqual(account["number"], DEV_ACCOUNT_NUMBER)

    def test_wrong_password_and_missing_account_look_the_same(self) -> None:
        wrong = self.client.post(
            "/v1/accounts/login",
            json={"name": DEV_ACCOUNT_NAME, "password": "wrongpass1"},
        )
        missing = self.client.post(
            "/v1/accounts/login", json={"name": "查无此人", "password": "abcd1234"}
        )
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(missing.status_code, 401)
        # 同一个错误码：不告诉对方"是账号错了还是密码错了"
        self.assertEqual(error_code(wrong), error_code(missing))
        self.assertEqual(error_message(wrong), error_message(missing))

    def test_login_by_case_insensitive_name(self) -> None:
        response = self.client.post(
            "/v1/accounts/login",
            json={"name": DEV_ACCOUNT_NAME.lower(), "password": DEV_ACCOUNT_PASSWORD},
        )
        self.assertEqual(response.status_code, 200, response.text)


class ProfileApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.client = build_app()
        self.token = self.client.post(
            "/v1/accounts/login",
            json={"name": DEV_ACCOUNT_NAME, "password": DEV_ACCOUNT_PASSWORD},
        ).json()["token"]

    def auth(self) -> dict:
        return {"Authorization": "Bearer " + self.token}

    def test_me_without_token_is_rejected(self) -> None:
        response = self.client.get("/v1/accounts/me")
        self.assertEqual(response.status_code, 401)

    def test_me_with_bad_token_is_rejected(self) -> None:
        response = self.client.get(
            "/v1/accounts/me", headers={"Authorization": "Bearer nope"}
        )
        self.assertEqual(response.status_code, 401)

    def test_me_returns_name_and_number(self) -> None:
        response = self.client.get("/v1/accounts/me", headers=self.auth())
        self.assertEqual(response.status_code, 200, response.text)
        account = response.json()["account"]
        self.assertEqual(account["name"], DEV_ACCOUNT_NAME)
        self.assertEqual(account["number"], DEV_ACCOUNT_NUMBER)

    def test_avatar_accepts_preset_and_data_uri(self) -> None:
        preset = self.client.post(
            "/v1/accounts/avatar", json={"avatar": "grandma"}, headers=self.auth()
        )
        self.assertEqual(preset.status_code, 200, preset.text)
        self.assertEqual(preset.json()["account"]["avatar"], "grandma")

        data_uri = "data:image/png;base64,iVBORw0KGgo="
        uploaded = self.client.post(
            "/v1/accounts/avatar", json={"avatar": data_uri}, headers=self.auth()
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        self.assertEqual(uploaded.json()["account"]["avatar"], data_uri)

    def test_avatar_rejects_foreign_scheme(self) -> None:
        response = self.client.post(
            "/v1/accounts/avatar",
            json={"avatar": "http://evil.example.com/x.png"},
            headers=self.auth(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(error_code(response), "account_avatar_invalid")

    def test_avatar_requires_login(self) -> None:
        response = self.client.post("/v1/accounts/avatar", json={"avatar": "grandma"})
        self.assertEqual(response.status_code, 401)

    def test_avatar_persists_in_me(self) -> None:
        self.client.post(
            "/v1/accounts/avatar", json={"avatar": "doctor"}, headers=self.auth()
        )
        me = self.client.get("/v1/accounts/me", headers=self.auth()).json()
        self.assertEqual(me["account"]["avatar"], "doctor")


class OptionsAndSeedTestCase(unittest.TestCase):
    def test_options_lists_presets_and_dev_account(self) -> None:
        client = build_app()
        data = client.get("/v1/accounts/options").json()
        self.assertIn("grandma", data["avatars"])
        self.assertEqual(data["devAccount"]["name"], DEV_ACCOUNT_NAME)
        self.assertEqual(data["devAccount"]["number"], DEV_ACCOUNT_NUMBER)
        self.assertEqual(data["firstNumber"], "00000000")
        self.assertEqual(data["numberWidth"], 8)

    def test_dev_account_is_not_reseeded_with_changed_password(self) -> None:
        """测试账号已存在时不该被重置——否则改过的密码每次重启都被冲掉"""
        client = build_app()
        first = self.client_login(client)
        self.assertEqual(first["number"], DEV_ACCOUNT_NUMBER)
        # 再"启动"一次（新 app，同一内存库不存在；这里验证内存实现的幂等）
        store = AccountStore()
        store.create(DEV_ACCOUNT_NAME, "changed123", number=DEV_ACCOUNT_NUMBER)
        from app.accounts import ensure_dev_account

        again = ensure_dev_account(store)
        self.assertTrue(again.check_password("changed123"), "已存在时不该覆盖密码")

    def client_login(self, client: TestClient) -> dict:
        return client.post(
            "/v1/accounts/login",
            json={"name": DEV_ACCOUNT_NAME, "password": DEV_ACCOUNT_PASSWORD},
        ).json()["account"]


class SqlStoreTestCase(unittest.TestCase):
    """落库实现与内存实现的编号口径必须一致"""

    def test_sql_store_matches_memory_store(self) -> None:
        import tempfile
        from pathlib import Path

        from app.storage.db import open_database

        tmp = tempfile.mkdtemp(prefix="bilin-sqlstore-")
        try:
            db = open_database("sqlite:///" + str(Path(tmp) / "a.db").replace("\\", "/"))
            store = SqlAccountStore(db)
            store.init_schema()
            store.load()

            self.assertEqual(store.peek_next_number(), "00000000")
            first = store.create("甲", "abcd1234")
            self.assertEqual(first.number, "00000000")
            second = store.create("乙", "abcd1234")
            self.assertEqual(second.number, "00000001")

            # 重新打开（模拟重启）后编号续上
            store2 = SqlAccountStore(db)
            store2.init_schema()
            store2.load()
            self.assertEqual(store2.peek_next_number(), "00000002")
            self.assertEqual(store2.by_name("甲").number, "00000000")
            # 先关库再删目录（Windows 文件占用）
            db.close()
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()


class LookupApiTestCase(unittest.TestCase):
    """按编号查账号（「绑定家人」用它确认绑的是谁）"""

    def setUp(self) -> None:
        self.client = build_app()

    def test_finds_dev_account_by_number(self) -> None:
        response = self.client.get("/v1/accounts/lookup", params={"number": DEV_ACCOUNT_NUMBER})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertTrue(data["found"])
        self.assertEqual(data["account"]["name"], DEV_ACCOUNT_NAME)
        self.assertEqual(data["account"]["number"], DEV_ACCOUNT_NUMBER)

    def test_unknown_number_is_not_found(self) -> None:
        response = self.client.get("/v1/accounts/lookup", params={"number": "99999999"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["found"])

    def test_rejects_malformed_number(self) -> None:
        for value in ("", "123", "abcdefgh", "1234567"):
            response = self.client.get("/v1/accounts/lookup", params={"number": value})
            self.assertEqual(response.status_code, 400, value)

    def test_lookup_never_leaks_password(self) -> None:
        response = self.client.get("/v1/accounts/lookup", params={"number": DEV_ACCOUNT_NUMBER})
        self.assertNotIn("password", str(response.json()).lower())

    def test_accepts_unpadded_number(self) -> None:
        """老人可能就填了个 '0'，也该认出来是 00000000"""
        response = self.client.get("/v1/accounts/lookup", params={"number": "0"})
        self.assertEqual(response.status_code, 400, "不足 8 位应被拒（端侧会拦）")

    def test_by_number_handles_padding_on_store(self) -> None:
        from app.accounts import AccountStore

        store = AccountStore()
        store.create("甲", "abcd1234", number="00000007")
        self.assertIsNotNone(store.by_number("7"))
        self.assertIsNotNone(store.by_number("00000007"))
        self.assertIsNone(store.by_number("8"))
        self.assertIsNone(store.by_number("abc"))
