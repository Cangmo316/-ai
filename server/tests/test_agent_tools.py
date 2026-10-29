"""智能体工具循环的测试。

## 测什么

1. **工具能执行**：5 个只读 + 2 个写，拿假 store 验证返回值形状与写操作生效
2. **闸门有效**：写记忆只能写进允许的小节；非法工具名不崩
3. **循环真的在循环**：给一个"先要工具、再回答"的假 provider，
   断言它调了两次、且工具结果被塞进了第二次请求
4. **不破坏原路径**：没配工具上下文时，provider 原样透传（回归）

说明：这里不依赖真模型。假 provider 按脚本决定"这次返回工具调用还是文本"。
"""

from __future__ import annotations

import unittest
from datetime import date

from app.orchestration.agent import AgentProvider
from app.tools import ToolContext, execute, openai_tools


# ── 假 store ────────────────────────────────────────────────────


class FakeElders:
    def get(self, elder_id):
        return {"name": "张桂兰", "age": 73, "address": "北京市朝阳区某某路 12 号", "tags": ["高血压"]}


class FakeRecord:
    def __init__(self, summary, at):
        self.summary = summary
        self.created_at = at


class FakeHealth:
    def latest_of(self, elder_id, item_type):
        data = {"血压": "158/96 mmHg", "血糖": "7.2 mmol/L"}
        if item_type in data:
            return FakeRecord(data[item_type], "2026-10-21 08:10")
        return None


class FakePlanEngine:
    def today(self, elder_id, day=None):
        return {
            "date": "2026-10-21",
            "statusLabel": "今天还有 1 项",
            "total": 2,
            "done": 1,
            "items": [
                {"id": "i1", "title": "吃降压药", "time": "08:00", "done": True},
                {"id": "i2", "title": "量血压", "time": "20:00", "done": False},
            ],
        }

    def completion(self, plan, days=7, day=None):
        return {"rate": 0.86, "done": 6, "total": 7}


class FakePlan:
    id = "p1"


class FakeCheckin:
    created_at = "2026-10-21 20:05"


class FakePlanStore:
    def __init__(self):
        self.calls = []

    def active(self, elder_id):
        return FakePlan()

    def checkin(self, plan, plan_item_id, elder_id, day=None, source="elder"):
        self.calls.append((plan_item_id, source))
        return FakeCheckin()


class FakeItem:
    def __init__(self, text):
        self.text = text


class FakeSection:
    def __init__(self, title, items=None):
        self.title = title
        self.items = items or []


class FakePage:
    def __init__(self, sections):
        self.sections = sections


class FakeWikiStore:
    def __init__(self):
        self.saved = []

    def load(self, elder_id, kind):
        return FakePage([
            FakeSection("家庭", [FakeItem("儿子在深圳")]),
            FakeSection("聊过的话题", [FakeItem("昨天说了孙子考试")]),
        ])

    def save(self, page):
        self.saved.append(page)
        return True


class FakeWiki:
    def __init__(self):
        self.store = FakeWikiStore()


def make_ctx():
    return ToolContext(
        elder_id="e_1",
        elders=FakeElders(),
        health=FakeHealth(),
        plan_engine=FakePlanEngine(),
        plan_store=FakePlanStore(),
        wiki=FakeWiki(),
        today=date(2026, 10, 21),
    )


# ── 工具层测试 ──────────────────────────────────────────────────


class ToolRegistryTestCase(unittest.TestCase):
    def test_specs_are_openai_shaped(self):
        tools = openai_tools()
        self.assertGreaterEqual(len(tools), 5)
        for item in tools:
            self.assertEqual(item["type"], "function")
            fn = item["function"]
            self.assertTrue(fn["name"])
            self.assertTrue(fn["description"])
            self.assertEqual(fn["parameters"]["type"], "object")

    def test_get_profile_does_not_leak_full_address(self):
        result = execute("get_profile", {}, make_ctx())
        self.assertEqual(result["name"], "张桂兰")
        # 门牌号不能带出去
        self.assertNotIn("12 号", result.get("city", ""))

    def test_get_today_plan_lists_pending(self):
        result = execute("get_today_plan", {}, make_ctx())
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual([i["title"] for i in result["pending"]], ["量血压"])

    def test_get_vitals_filters_by_type(self):
        ctx = make_ctx()
        one = execute("get_recent_vitals", {"item_type": "血压"}, ctx)
        self.assertEqual(len(one["records"]), 1)
        self.assertIn("158", one["records"][0]["summary"])
        allkinds = execute("get_recent_vitals", {}, ctx)
        self.assertEqual(len(allkinds["records"]), 2)

    def test_week_completion(self):
        result = execute("get_week_completion", {}, make_ctx())
        self.assertAlmostEqual(result["rate"], 0.86)

    def test_unknown_tool_returns_error_not_exception(self):
        result = execute("drop_database", {}, make_ctx())
        self.assertFalse(result["ok"])
        self.assertIn("没有这个工具", result["reason"])

    def test_bad_arguments_do_not_crash(self):
        result = execute("get_recent_vitals", "这不是 JSON", make_ctx())
        self.assertIn("records", result)


class ToolWriteTestCase(unittest.TestCase):
    def test_remember_fact_writes_into_allowed_section(self):
        ctx = make_ctx()
        result = execute("remember_fact", {"section": "家庭", "text": "女儿下月回国"}, ctx)
        self.assertTrue(result["ok"])
        self.assertEqual(len(ctx.wiki.store.saved), 1)
        saved = ctx.wiki.store.saved[0]
        family = next(s for s in saved.sections if s.title == "家庭")
        self.assertIn("女儿下月回国", [i.text for i in family.items])

    def test_remember_fact_rejects_unknown_section(self):
        ctx = make_ctx()
        result = execute("remember_fact", {"section": "随便写的", "text": "x"}, ctx)
        self.assertFalse(result["ok"])
        self.assertIn("只能记到这些小节里", result["reason"])
        self.assertEqual(ctx.wiki.store.saved, [])

    def test_remember_fact_dedupes(self):
        ctx = make_ctx()
        execute("remember_fact", {"section": "家庭", "text": "儿子在深圳"}, ctx)
        result = execute("remember_fact", {"section": "家庭", "text": "儿子在深圳"}, ctx)
        self.assertTrue(result.get("duplicated"))

    def test_check_in_calls_store_with_agent_source(self):
        ctx = make_ctx()
        result = execute("check_in_plan_item", {"item_id": "i2"}, ctx)
        self.assertTrue(result["ok"])
        self.assertEqual(ctx.plan_store.calls, [("i2", "agent")])


# ── 循环测试（假 provider 按脚本走）────────────────────────────


class ScriptedProvider:
    """第一次返回工具调用，第二次返回文本。"""

    name = "scripted"

    def __init__(self):
        self.calls: list[list[dict]] = []

    async def stream(self, messages, on_finish=None, tools=None, tool_sink=None):
        self.calls.append([dict(m) for m in messages])
        if len(self.calls) == 1:
            # 模拟模型决定调用工具，且**不**产出正文
            if tool_sink is not None:
                tool_sink.append({
                    "id": "call_1",
                    "name": "get_today_plan",
                    "arguments": "{}",
                })
            return
        # 第二次：已经拿到工具结果，开始说话
        for piece in ["今天的药", "已经吃了", "，晚上那次别忘了"]:
            yield piece


class AgentLoopTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_loop_executes_tool_and_answers(self):
        provider = ScriptedProvider()
        agent = AgentProvider(provider, make_ctx())
        chunks = []
        async for chunk in agent.stream([{"role": "system", "content": "sys"}, {"role": "user", "content": "药吃了没"}]):
            chunks.append(chunk)

        text = "".join(chunks)
        self.assertIn("已经吃了", text)
        # 调了两次模型：第一次要工具，第二次出答案
        self.assertEqual(len(provider.calls), 2)
        # 第二次请求里必须带上工具结果（role=tool）
        second = provider.calls[1]
        tool_msgs = [m for m in second if m.get("role") == "tool"]
        self.assertEqual(len(tool_msgs), 1)
        self.assertIn("量血压", tool_msgs[0]["content"])
        # 轨迹留痕
        self.assertEqual(len(agent.trail), 1)
        self.assertEqual(agent.trail[0]["name"], "get_today_plan")
        self.assertTrue(agent.trail[0]["ok"])

    async def test_direct_answer_skips_tools(self):
        class DirectProvider:
            name = "direct"

            def __init__(self):
                self.count = 0

            async def stream(self, messages, on_finish=None, tools=None, tool_sink=None):
                self.count += 1
                yield "好啊"

        provider = DirectProvider()
        agent = AgentProvider(provider, make_ctx())
        chunks = [c async for c in agent.stream([{"role": "user", "content": "你好"}])]
        self.assertEqual("".join(chunks), "好啊")
        self.assertEqual(provider.count, 1)
        self.assertEqual(agent.trail, [])

    async def test_plain_provider_without_tool_support_still_works(self):
        """没 tools 参数的老 provider（如内置 fake）不能被打挂。"""

        class Plain:
            name = "plain"

            async def stream(self, messages):
                yield "在呢"

        agent = AgentProvider(Plain(), make_ctx())
        chunks = [c async for c in agent.stream([{"role": "user", "content": "喂"}])]
        self.assertEqual("".join(chunks), "在呢")


if __name__ == "__main__":
    unittest.main()
