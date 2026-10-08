"""
新功能测试：消息撤回/删除/引用、模型设置、对方智能体代回。

按项目习惯：用 TestClient 打真接口，不 mock 服务层。
"""

from __future__ import annotations

import json
import secrets
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.llm.overrides import MODE_BUILTIN, MODE_CUSTOM, ModelOverride, ModelOverrideStore
from app.llm.resolver import ProviderResolver
from app.config import Settings
from app.main import create_app


class FakeProvider:
    """只吐固定文本的 provider，避免测试依赖外网。"""

    name = "fake"
    model = "fake-model"

    def __init__(self, text: str = "好的，我知道了"):
        self.text = text
        #: 每次 stream 收到的 messages，供断言 prompt 内容
        self.seen: list[list[dict]] = []

    async def stream(self, messages, **kwargs):
        self.seen.append(messages)
        yield self.text


#: 建过的测试客户端，测试结束时统一关库再删临时目录。
#:
#: ⚠️ 必须显式关：Windows 上 SQLite 文件被连接占着时删目录会
#:    `PermissionError: [WinError 32] 另一个程序正在使用此文件`，
#:    而且会在**垃圾回收时**才抛出来，看起来像是"某个用例莫名其妙报错"。
_CLIENTS: list = []


def make_client(provider=None) -> TestClient:
    """建测试客户端。

    ⚠️ 用默认配置会连**真库**（server/data/bilin.db），而注册名是唯一的
    （`account_name_taken`）——跑第二次就全挂了。

    ⚠️⚠️ **不要用 `os.environ["DATABASE_URL"] = ...`** 来做这件事：环境变量是
    进程级的，测试文件在导入期一改，**其它测试文件**（它们用 `create_app()` 的
    默认配置）就会跟着连到真库上去。我第一版就是这么写的，结果全量跑时
    `test_messaging` 里 7 个用例连带挂掉——单独跑却是好的，很容易误判成产品 bug。
    这里改成把 settings 显式传给 `create_app`，只影响本次调用。
    """
    workspace = tempfile.TemporaryDirectory()
    db_url = "sqlite:///" + str(Path(workspace.name) / "test.db").replace("\\", "/")
    settings = Settings(
        llm_provider="fake",
        llm_api_key="",
        scheduler_enabled=False,
        database_url=db_url,
    )
    app = create_app(settings=settings, provider=provider or FakeProvider())
    client = TestClient(app)
    _CLIENTS.append((client, workspace))
    return client


def tearDownModule() -> None:
    """关掉所有测试库连接，再删临时目录（Windows 上不关就删不掉）。"""
    for client, workspace in _CLIENTS:
        try:
            db = getattr(client.app.state, "database", None)
            if db is not None:
                db.close()
        except Exception:  # noqa: BLE001 —— 清理失败不该让测试结果变成错误
            pass
        try:
            workspace.cleanup()
        except Exception:  # noqa: BLE001
            pass
    _CLIENTS.clear()


def register(client: TestClient, name: str) -> dict:
    """注册一个账号。

    名字再加一段随机后缀：即使误连到真库，也不会和其他测试/开发账号撞名。
    """
    unique = name + secrets.token_hex(3)
    res = client.post("/v1/accounts/register", json={
        "name": unique, "password": "test123456", "confirm": "test123456",
    })
    assert res.status_code == 201, res.text
    data = res.json()
    return {"token": data["token"], "account": data["account"]}


def auth(session: dict) -> dict:
    return {"Authorization": "Bearer " + session["token"]}


def family_conversation(client: TestClient, a: dict, b: dict) -> str:
    """让 A 邀请 B、B 同意，返回共享会话 id。

    绑定现在**要对方同意**（见 Binding 的说明），所以测试也必须走完这两步，
    否则拿到的还是 pending，没有共享会话。
    """
    res = client.post("/v1/conversations/bindings",
                      json={"number": b["account"]["number"]}, headers=auth(a))
    assert res.status_code == 201, res.text
    assert res.json()["binding"]["status"] == "pending", res.text

    res = client.post("/v1/conversations/bindings/respond", headers=auth(b),
                      json={"number": a["account"]["number"], "accept": True})
    assert res.status_code == 200, res.text

    res = client.get("/v1/conversations", headers=auth(a))
    for item in res.json()["conversations"]:
        if item["kind"] == "family":
            return item["id"]
    raise AssertionError("同意之后没拿到 family 会话")


# ══════════════════════════════════════════════════════════════════════
# 撤回 / 删除 / 引用
# ══════════════════════════════════════════════════════════════════════


class MessageActionsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.client = make_client()
        self.a = register(self.client, "甲")
        self.b = register(self.client, "乙")
        self.cid = family_conversation(self.client, self.a, self.b)

    def send(self, session, text, **extra):
        body = {"conversationId": self.cid, "text": text, "senderRole": "elder"}
        body.update(extra)
        res = self.client.post("/v1/conversations/messages", json=body, headers=auth(session))
        self.assertEqual(res.status_code, 201, res.text)
        return res.json()["message"]

    def test_recall_clears_text_but_keeps_the_row(self):
        """撤回后**正文不再下发**，但消息还在（双方都看得到"已撤回"）"""
        msg = self.send(self.a, "说错话了")
        res = self.client.post("/v1/conversations/messages/recall",
                               json={"conversationId": self.cid, "messageId": msg["id"]},
                               headers=auth(self.a))
        self.assertEqual(res.status_code, 200, res.text)
        recalled = res.json()["message"]
        self.assertTrue(recalled["recalledAt"])
        self.assertEqual(recalled["text"], "")

        # 从历史里再拉一次，仍然是空正文 + 有撤回时间
        res = self.client.get("/v1/conversations/messages",
                              params={"conversationId": self.cid}, headers=auth(self.b))
        found = [m for m in res.json()["messages"] if m["id"] == msg["id"]]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["text"], "")
        self.assertTrue(found[0]["recalledAt"])

    def test_recall_twice_is_rejected(self):
        msg = self.send(self.a, "重复撤回")
        for _ in range(2):
            res = self.client.post("/v1/conversations/messages/recall",
                                   json={"conversationId": self.cid, "messageId": msg["id"]},
                                   headers=auth(self.a))
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["error"]["code"], "already_recalled")

    def test_cannot_recall_someone_elses_message(self):
        """只能撤自己发的 —— 共享会话里撤对方的等于篡改记录"""
        msg = self.send(self.a, "这条是甲发的")
        res = self.client.post("/v1/conversations/messages/recall",
                               json={"conversationId": self.cid, "messageId": msg["id"]},
                               headers=auth(self.b))
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["error"]["code"], "not_your_message")

    def test_recall_expires_after_window(self):
        msg = self.send(self.a, "两分钟前的消息")
        # 直接把 created_at 改早，模拟超时（不去真等两分钟）
        store = self.client.app.state.messaging
        target = store.find_message(msg["id"])
        target.created_at = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        res = self.client.post("/v1/conversations/messages/recall",
                               json={"conversationId": self.cid, "messageId": msg["id"]},
                               headers=auth(self.a))
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["error"]["code"], "recall_expired")

    def test_recall_unknown_message_is_404(self):
        res = self.client.post("/v1/conversations/messages/recall",
                               json={"conversationId": self.cid, "messageId": "m_nope"},
                               headers=auth(self.a))
        self.assertEqual(res.status_code, 404)

    def test_delete_removes_the_row(self):
        msg = self.send(self.a, "这条要删掉")
        res = self.client.post("/v1/conversations/messages/delete",
                               json={"conversationId": self.cid, "messageId": msg["id"]},
                               headers=auth(self.a))
        self.assertEqual(res.status_code, 200, res.text)
        res = self.client.get("/v1/conversations/messages",
                              params={"conversationId": self.cid}, headers=auth(self.b))
        ids = [m["id"] for m in res.json()["messages"]]
        self.assertNotIn(msg["id"], ids)

    def test_cannot_delete_someone_elses_message(self):
        msg = self.send(self.a, "不许乙删")
        res = self.client.post("/v1/conversations/messages/delete",
                               json={"conversationId": self.cid, "messageId": msg["id"]},
                               headers=auth(self.b))
        self.assertEqual(res.status_code, 403)

    def test_quote_id_is_stored_and_returned(self):
        first = self.send(self.a, "被引用的那条")
        second = self.send(self.a, "带着引用", quoteId=first["id"])
        self.assertEqual(second["quoteId"], first["id"])

    # ── 智能体回复的删除权限（用户反馈："智能体发的消息我删不掉"）──

    def ai_conversation(self, session) -> str:
        res = self.client.get("/v1/conversations", headers=auth(session))
        return next(c for c in res.json()["conversations"] if c["kind"] == "ai")["id"]

    def test_can_delete_own_agent_reply_in_ai_conversation(self):
        """**我自己 AI 会话**里的智能体回复可以删（它就是替我说话的）"""
        ai = self.ai_conversation(self.a)
        agent_msg = self.client.post(
            "/v1/conversations/messages",
            json={"conversationId": ai, "text": "妈 我在呢", "senderRole": "agent"},
            headers=auth(self.a),
        ).json()["message"]
        # 服务端会给智能体一个独立的 sender id（不是我的账号 id）——
        # 这正是原来删不掉的原因
        self.assertTrue(agent_msg["senderId"].startswith("agent:"))
        self.assertNotEqual(agent_msg["senderId"], self.a["account"]["id"])

        res = self.client.post(
            "/v1/conversations/messages/delete",
            json={"conversationId": ai, "messageId": agent_msg["id"]},
            headers=auth(self.a),
        )
        self.assertEqual(res.status_code, 200, res.text)

        res = self.client.get(
            "/v1/conversations/messages", params={"conversationId": ai}, headers=auth(self.a)
        )
        self.assertNotIn(agent_msg["id"], [m["id"] for m in res.json()["messages"]])

    def test_cannot_delete_peer_agent_reply_in_family_conversation(self):
        """**家人会话**里对方智能体代回的**不能删** —— 那是对方记录的一部分"""
        self.send(self.a, "在家吗")
        res = self.client.post(
            "/v1/conversations/messages/auto-reply",
            json={"conversationId": self.cid, "peerName": self.b["account"]["name"]},
            headers=auth(self.a),
        )
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertTrue(body.get("ok"), body)
        agent_msg = body["message"]
        self.assertTrue(agent_msg["senderId"].startswith("agent:"))

        # A 想删掉"对方智能体代 B 回的那条" → 拒绝
        res = self.client.post(
            "/v1/conversations/messages/delete",
            json={"conversationId": self.cid, "messageId": agent_msg["id"]},
            headers=auth(self.a),
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["error"]["code"], "not_your_message")

        # 那条还在（没有被篡改掉）
        res = self.client.get(
            "/v1/conversations/messages", params={"conversationId": self.cid}, headers=auth(self.a)
        )
        self.assertIn(agent_msg["id"], [m["id"] for m in res.json()["messages"]])

    def test_cannot_delete_another_accounts_agent_reply(self):
        """别人 AI 会话里的智能体回复更不能删"""
        b_ai = self.ai_conversation(self.b)
        b_msg = self.client.post(
            "/v1/conversations/messages",
            json={"conversationId": b_ai, "text": "乙的智能体回复", "senderRole": "agent"},
            headers=auth(self.b),
        ).json()["message"]

        res = self.client.post(
            "/v1/conversations/messages/delete",
            json={"conversationId": b_ai, "messageId": b_msg["id"]},
            headers=auth(self.a),
        )
        self.assertEqual(res.status_code, 403)


# ══════════════════════════════════════════════════════════════════════
# 智能体设置：模型选择
# ══════════════════════════════════════════════════════════════════════


class ModelSettingTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.client = make_client()
        self.session = register(self.client, "配模型的")
        # 用临时目录的覆盖文件，别污染真机的 data/llm_overrides.json。
        # ⚠️ resolver 里也存着 store 的引用，只换 app.state 上的那份不够——
        #    那样写接口会写进新 store、而 resolver 还从旧的读，
        #    表现是"保存成功但 active.custom 还是 false"（我第一版就踩了这个）。
        store = ModelOverrideStore(Path(self.tmp.name) / "llm_overrides.json")
        self.client.app.state.model_overrides = store
        resolver = getattr(self.client.app.state, "provider_resolver", None)
        if resolver is not None:
            resolver.store = store
            resolver.invalidate()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_default_is_builtin(self):
        res = self.client.get("/v1/chat/model", headers=auth(self.session))
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["setting"]["mode"], MODE_BUILTIN)
        self.assertFalse(data["active"]["custom"])

    def test_custom_requires_all_three_fields(self):
        res = self.client.put("/v1/chat/model", headers=auth(self.session),
                              json={"mode": "custom", "baseUrl": "https://api.example.com/v1"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["error"]["code"], "model_field_missing")

    def test_url_must_look_like_a_url(self):
        res = self.client.put("/v1/chat/model", headers=auth(self.session),
                              json={"mode": "custom", "baseUrl": "api.example.com",
                                    "apiKey": "sk-abcdefghijklmnop", "model": "m"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["error"]["code"], "model_url_invalid")

    def test_save_and_read_back_masks_the_key(self):
        res = self.client.put("/v1/chat/model", headers=auth(self.session), json={
            "mode": "custom", "baseUrl": "https://api.example.com/v1",
            "apiKey": "sk-abcdefghijklmnop", "model": "my-model",
        })
        self.assertEqual(res.status_code, 200, res.text)

        res = self.client.get("/v1/chat/model", headers=auth(self.session))
        setting = res.json()["setting"]
        self.assertEqual(setting["mode"], MODE_CUSTOM)
        self.assertEqual(setting["model"], "my-model")
        self.assertTrue(setting["hasApiKey"])
        # 完整 key 绝不能出现在响应里
        self.assertNotIn("sk-abcdefghijklmnop", json.dumps(res.json()))
        self.assertIn("****", setting["apiKeyMasked"])
        # 并且解析出来**确实在用自定义**
        self.assertTrue(res.json()["active"]["custom"])

    def test_switch_back_to_builtin_clears_custom_fields(self):
        self.client.put("/v1/chat/model", headers=auth(self.session), json={
            "mode": "custom", "baseUrl": "https://api.example.com/v1",
            "apiKey": "sk-abcdefghijklmnop", "model": "my-model",
        })
        self.client.put("/v1/chat/model", headers=auth(self.session), json={"mode": "builtin"})
        res = self.client.get("/v1/chat/model", headers=auth(self.session))
        setting = res.json()["setting"]
        self.assertEqual(setting["mode"], MODE_BUILTIN)
        self.assertEqual(setting["baseUrl"], "")
        self.assertFalse(setting["hasApiKey"])
        self.assertFalse(res.json()["active"]["custom"])

    def test_store_roundtrip_and_isolation(self):
        """存储层：两个账号互不影响；重载后仍在"""
        path = Path(self.tmp.name) / "roundtrip.json"
        store = ModelOverrideStore(path)
        store.save("a_one", ModelOverride(mode=MODE_CUSTOM, base_url="https://x/v1",
                                         api_key="sk-1234567890", model="m1"))
        store.save("a_two", ModelOverride(mode=MODE_BUILTIN))

        again = ModelOverrideStore(path)
        self.assertEqual(again.load(), 2)
        self.assertEqual(again.get("a_one").model, "m1")
        self.assertEqual(again.get("a_two").mode, MODE_BUILTIN)
        # 没配过的账号拿到的是内置模式，不是 None
        self.assertEqual(again.get("a_three").mode, MODE_BUILTIN)

    def test_resolver_falls_back_when_config_incomplete(self):
        """配置不全 → 退回内置，并给出原因（不能让对话打不开）"""
        store = ModelOverrideStore(Path(self.tmp.name) / "fb.json")
        store.save("a_x", ModelOverride(mode=MODE_CUSTOM, base_url="", api_key="", model=""))
        resolver = ProviderResolver(builtin=FakeProvider("内置"), store=store)
        resolved = resolver.resolve("a_x")
        self.assertFalse(resolved.custom)
        self.assertTrue(resolved.fallback_reason)
        self.assertEqual(resolved.provider.text, "内置")

    def test_resolver_caches_until_config_changes(self):
        store = ModelOverrideStore(Path(self.tmp.name) / "cache.json")
        store.save("a_y", ModelOverride(mode=MODE_CUSTOM, base_url="https://api.example.com/v1",
                                        api_key="sk-1234567890", model="m"))
        resolver = ProviderResolver(builtin=FakeProvider("内置"), store=store)
        first = resolver.resolve("a_y")
        self.assertTrue(first.custom)
        self.assertIs(resolver.resolve("a_y"), first)      # 命中缓存
        store.save("a_y", ModelOverride(mode=MODE_BUILTIN))
        self.assertFalse(resolver.resolve("a_y").custom)   # 配置变了立刻生效


# ══════════════════════════════════════════════════════════════════════
# 对方不在线时的智能体代回
# ══════════════════════════════════════════════════════════════════════


class AutoReplyTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = FakeProvider("穿上了，正去医院量血压呢")
        self.client = make_client(self.provider)
        self.a = register(self.client, "甲")
        self.b = register(self.client, "乙")
        self.cid = family_conversation(self.client, self.a, self.b)

    def test_auto_reply_lands_as_agent_with_peer_name(self):
        self.client.post("/v1/conversations/messages", headers=auth(self.a),
                         json={"conversationId": self.cid, "text": "降温了，穿秋裤没",
                               "senderRole": "elder"})
        res = self.client.post("/v1/conversations/messages/auto-reply", headers=auth(self.a),
                               json={"conversationId": self.cid,
                                     "schedule": "他 15:00 去社区医院量血压",
                                     "peerName": self.b["account"]["name"]})
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertTrue(body["ok"], body)

        message = body["message"]
        self.assertEqual(message["senderRole"], "agent")           # 端侧据此显示「AI 发送」
        self.assertTrue(message["senderId"].startswith("agent:"))  # 独立 sender id
        self.assertEqual(message["senderName"], self.b["account"]["name"])

        # 对方也能在共享会话里看到这条
        res = self.client.get("/v1/conversations/messages",
                              params={"conversationId": self.cid}, headers=auth(self.b))
        roles = [m["senderRole"] for m in res.json()["messages"]]
        self.assertIn("agent", roles)

    def test_prompt_contains_history_and_schedule_but_no_private_health(self):
        """代回的 prompt 里有聊天记录与日程，**没有**对方的健康/病例隐私"""
        self.client.post("/v1/conversations/messages", headers=auth(self.a),
                         json={"conversationId": self.cid, "text": "记得吃药啊",
                               "senderRole": "elder"})
        self.client.post("/v1/conversations/messages/auto-reply", headers=auth(self.a),
                         json={"conversationId": self.cid,
                               "schedule": "他下午要去公园下棋",
                               "peerName": self.b["account"]["name"]})

        self.assertTrue(self.provider.seen, "provider 没被调用")
        prompt = json.dumps(self.provider.seen[-1], ensure_ascii=False)
        self.assertIn("记得吃药啊", prompt)      # 两人聊天记录进去了（"越聊越像"靠它）
        self.assertIn("公园下棋", prompt)        # 日程进去了
        # 这几个是**对方的隐私**，代回绝不能带（我们故意不传 elder_id）
        for forbidden in ("【最近的测量数值】", "【他去医院的情况】", "【你记得的事】"):
            self.assertNotIn(forbidden, prompt, "代回 prompt 里不应出现 " + forbidden)

    def test_auto_reply_rejected_for_ai_conversation(self):
        res = self.client.get("/v1/conversations", headers=auth(self.a))
        ai = next(c for c in res.json()["conversations"] if c["kind"] == "ai")
        res = self.client.post("/v1/conversations/messages/auto-reply", headers=auth(self.a),
                               json={"conversationId": ai["id"], "peerName": "乙"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["error"]["code"], "not_a_family_conversation")

    def test_auto_reply_needs_something_to_reply_to(self):
        res = self.client.post("/v1/conversations/messages/auto-reply", headers=auth(self.a),
                               json={"conversationId": self.cid, "peerName": "乙"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["error"]["code"], "nothing_to_reply")

    def test_auto_reply_requires_auth(self):
        res = self.client.post("/v1/conversations/messages/auto-reply",
                               json={"conversationId": self.cid})
        self.assertEqual(res.status_code, 401)


# ══════════════════════════════════════════════════════════════════════
# 绑定要对方同意
# ══════════════════════════════════════════════════════════════════════


class BindConsentTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.client = make_client()
        self.a = register(self.client, "甲")
        self.b = register(self.client, "乙")

    def invite(self, frm, to):
        return self.client.post("/v1/conversations/bindings",
                                json={"number": to["account"]["number"]}, headers=auth(frm))

    def test_invite_is_pending_and_not_yet_bound(self):
        """发起后是 pending：**还没绑定**，也看不到对方数据、没有共享会话"""
        res = self.invite(self.a, self.b)
        self.assertEqual(res.status_code, 201, res.text)
        self.assertEqual(res.json()["binding"]["status"], "pending")

        # A 的会话列表里不应出现 family 会话
        res = self.client.get("/v1/conversations", headers=auth(self.a))
        kinds = [c["kind"] for c in res.json()["conversations"]]
        self.assertNotIn("family", kinds)

        # B 也没把 A 当已绑定的家人
        res = self.client.get("/v1/conversations/bindings", headers=auth(self.b))
        for item in res.json()["bindings"]:
            self.assertNotEqual(item.get("status"), "accepted")

    def test_all_bindings_include_pending_for_both_sides(self):
        """`/bindings/all` 要能看到待同意（家人绑定页靠它显示"已发出邀请"）"""
        self.invite(self.a, self.b)

        res = self.client.get("/v1/conversations/bindings/all", headers=auth(self.a))
        items = res.json()["bindings"]
        self.assertEqual(len(items), 1, res.text)
        self.assertEqual(items[0]["status"], "pending")
        # 发起方 outgoing=true、接收方 false —— 界面据此分两组显示
        self.assertTrue(items[0]["outgoing"])

        res = self.client.get("/v1/conversations/bindings/all", headers=auth(self.b))
        items = res.json()["bindings"]
        self.assertEqual(len(items), 1, res.text)
        self.assertFalse(items[0]["outgoing"])

        # 只回已生效家人的 /bindings 不该出现它
        res = self.client.get("/v1/conversations/bindings", headers=auth(self.a))
        self.assertEqual(res.json()["bindings"], [])

    def test_pending_invite_is_visible_to_the_invitee(self):
        self.invite(self.a, self.b)
        res = self.client.get("/v1/conversations/bindings/pending", headers=auth(self.b))
        pending = res.json()["pending"]
        self.assertEqual(len(pending), 1, res.text)
        self.assertEqual(pending[0]["peerNumber"], self.a["account"]["number"])
        # 发起方那边不该有"等我同意"的邀请
        res = self.client.get("/v1/conversations/bindings/pending", headers=auth(self.a))
        self.assertEqual(res.json()["pending"], [])

    def test_accept_activates_binding_and_opens_conversation(self):
        self.invite(self.a, self.b)
        res = self.client.post("/v1/conversations/bindings/respond", headers=auth(self.b),
                               json={"number": self.a["account"]["number"], "accept": True})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(res.json()["accepted"])
        self.assertEqual(res.json()["binding"]["status"], "accepted")

        # 双方现在都有 family 会话，并且能互相查看
        for who, other in ((self.a, self.b), (self.b, self.a)):
            res = self.client.get("/v1/conversations", headers=auth(who))
            self.assertIn("family", [c["kind"] for c in res.json()["conversations"]])
            res = self.client.get("/v1/family/overview",
                                  params={"number": other["account"]["number"]}, headers=auth(who))
            self.assertEqual(res.status_code, 200, res.text)

    def test_reject_keeps_record_and_does_not_bind(self):
        self.invite(self.a, self.b)
        res = self.client.post("/v1/conversations/bindings/respond", headers=auth(self.b),
                               json={"number": self.a["account"]["number"], "accept": False})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertFalse(res.json()["accepted"])

        # 没绑定：A 看不到 B 的家人数据
        res = self.client.get("/v1/family/overview",
                              params={"number": self.b["account"]["number"]}, headers=auth(self.a))
        self.assertEqual(res.status_code, 403)
        # 且 A 再发一次会被明确告知"对方之前拒绝了"
        res = self.invite(self.a, self.b)
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["error"]["code"], "bind_rejected_before")

    def test_invitee_cannot_be_tricked_into_accepting_own_invite(self):
        """不能替对方点同意：A 自己调 respond 应该失败"""
        self.invite(self.a, self.b)
        res = self.client.post("/v1/conversations/bindings/respond", headers=auth(self.a),
                               json={"number": self.b["account"]["number"], "accept": True})
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["error"]["code"], "no_pending_invite")

    def test_duplicate_invite_is_rejected(self):
        self.invite(self.a, self.b)
        res = self.invite(self.a, self.b)
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["error"]["code"], "bind_pending")

    def test_accept_without_invite_is_404(self):
        res = self.client.post("/v1/conversations/bindings/respond", headers=auth(self.b),
                               json={"number": self.a["account"]["number"], "accept": True})
        self.assertEqual(res.status_code, 404)


if __name__ == "__main__":
    unittest.main()
