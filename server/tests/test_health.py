"""健康档案接口契约测试

重点：
  1. **数值校验**（血压高低压填反、超范围、非数字都要拦住）
  2. **数据归属**（不能读/删别人的记录）
  3. **注入智能体**：`snapshot_for_prompt()` 要把最近几次数值给到人设 prompt
     ——这是"智能体主动慰问和建议"的依据，它错了整件事就没意义
"""

from __future__ import annotations

import unittest
from datetime import datetime

from fastapi.testclient import TestClient

from app.config import Settings
from app.health import HealthStore, validate_values, summarize
from app.llm.fake import FakeProvider
from app.main import create_app


class Clock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment


def build_app() -> TestClient:
    app = create_app(
        settings=Settings(
            llm_provider="fake",
            llm_api_key="",
            scheduler_enabled=False,
            database_url="memory://",
        ),
        provider=FakeProvider(delay=0),
        clock=Clock(datetime(2026, 10, 7, 10, 0)),
    )
    return TestClient(app)


class ValidateValuesTestCase(unittest.TestCase):
    """纯函数校验（不经过 HTTP，跑得快、错误信息看得清）"""

    def test_blood_pressure_ok(self) -> None:
        values, problem = validate_values("bloodPressure", {"systolic": 128, "diastolic": 82, "pulse": 72})
        self.assertEqual(problem, "")
        self.assertEqual(values["systolic"], 128)
        self.assertEqual(values["diastolic"], 82)
        self.assertEqual(values["pulse"], 72)

    def test_pulse_optional(self) -> None:
        values, problem = validate_values("bloodPressure", {"systolic": 128, "diastolic": 82})
        self.assertEqual(problem, "")
        self.assertNotIn("pulse", values)

    def test_blood_pressure_swapped_is_rejected(self) -> None:
        """高压小于低压 = 一定填反了"""
        _, problem = validate_values("bloodPressure", {"systolic": 80, "diastolic": 120})
        self.assertIn("填反", problem)

    def test_blood_pressure_missing_one_side(self) -> None:
        _, problem = validate_values("bloodPressure", {"systolic": 128})
        self.assertTrue(problem)

    def test_out_of_range_rejected(self) -> None:
        _, problem = validate_values("bloodPressure", {"systolic": 500, "diastolic": 82})
        self.assertIn("不太对", problem)
        _, problem2 = validate_values("weight", {"value": 500})
        self.assertTrue(problem2)

    def test_non_numeric_rejected(self) -> None:
        _, problem = validate_values("weight", {"value": "很重"})
        self.assertIn("数字", problem)

    def test_empty_rejected(self) -> None:
        _, problem = validate_values("bloodSugar", {})
        self.assertTrue(problem)

    def test_unknown_type_rejected(self) -> None:
        _, problem = validate_values("身高", {"value": 170})
        self.assertIn("不认识", problem)

    def test_blood_sugar_timing(self) -> None:
        values, problem = validate_values("bloodSugar", {"value": 6.4, "timing": "空腹"})
        self.assertEqual(problem, "")
        self.assertEqual(values["timing"], "空腹")
        _, bad = validate_values("bloodSugar", {"value": 6.4, "timing": "半夜"})
        self.assertIn("时点", bad)

    def test_decimal_precision(self) -> None:
        values, _ = validate_values("weight", {"value": 62.55})
        self.assertEqual(values["value"], 62.5)  # 一位小数
        values2, _ = validate_values("bloodPressure", {"systolic": 128.6, "diastolic": 82.4})
        self.assertEqual(values2["systolic"], 129)   # 整数项取整
        self.assertEqual(values2["diastolic"], 82)

    def test_summarize(self) -> None:
        self.assertEqual(summarize("bloodPressure", {"systolic": 128, "diastolic": 82}), "128/82 mmHg")
        self.assertEqual(summarize("bloodSugar", {"value": 6.4, "timing": "空腹"}), "6.4 mmol/L（空腹）")
        self.assertEqual(summarize("weight", {"value": 62.5}), "62.5 kg")


class HealthApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.client = build_app()
        self.me = self.register("老人甲")
        self.other = self.register("别人乙")

    def register(self, name: str) -> dict:
        response = self.client.post(
            "/v1/accounts/register",
            json={"name": name, "password": "abcd1234", "confirm": "abcd1234"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        data = response.json()
        return {"token": data["token"], "account": data["account"]}

    def auth(self, who: dict) -> dict:
        return {"Authorization": "Bearer " + who["token"]}

    def add(self, who: dict, item_type: str, values: dict, **extra):
        body = {"itemType": item_type, "values": values}
        body.update(extra)
        return self.client.post("/v1/health/records", json=body, headers=self.auth(who))

    # ---------------------------------------------------------------- 表单定义

    def test_types_need_no_login(self) -> None:
        """填表前要先渲染表单，这时可能还没有登录态"""
        response = self.client.get("/v1/health/types")
        self.assertEqual(response.status_code, 200, response.text)
        types = response.json()["types"]
        keys = [item["itemType"] for item in types]
        # 只保留三项基础数据（心率/血氧/体温已按需求删去）
        self.assertEqual(keys, ["bloodPressure", "bloodSugar", "weight"], keys)
        bp = next(item for item in types if item["itemType"] == "bloodPressure")
        field_keys = [f["key"] for f in bp["fields"]]
        self.assertEqual(field_keys, ["systolic", "diastolic", "pulse"])
        self.assertEqual(bp["unit"], "mmHg")
        self.assertTrue(bp["normalRange"])

    # ---------------------------------------------------------------- 增删查

    def test_requires_login_for_records(self) -> None:
        self.assertEqual(self.client.get("/v1/health/records").status_code, 401)
        self.assertEqual(
            self.client.post("/v1/health/records", json={"itemType": "weight", "values": {"value": 60}}).status_code,
            401,
        )

    def test_add_and_list(self) -> None:
        created = self.add(self.me, "bloodPressure", {"systolic": 128, "diastolic": 82})
        self.assertEqual(created.status_code, 201, created.text)
        record = created.json()["record"]
        self.assertEqual(record["summary"], "128/82 mmHg")
        self.assertEqual(record["itemLabel"], "血压")

        listed = self.client.get("/v1/health/records", headers=self.auth(self.me)).json()
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["records"][0]["id"], record["id"])

    def test_records_sorted_newest_first(self) -> None:
        # 用互不相同的数值：数值相同的话排序会退到 created_at，测不出想测的东西
        self.add(self.me, "weight", {"value": 61}, measuredAt="2026-10-01T08:00:00+08:00")
        self.add(self.me, "weight", {"value": 63}, measuredAt="2026-10-05T08:00:00+08:00")
        self.add(self.me, "weight", {"value": 62}, measuredAt="2026-10-03T08:00:00+08:00")
        records = self.client.get("/v1/health/records", headers=self.auth(self.me)).json()["records"]
        self.assertEqual([r["values"]["value"] for r in records], [63, 62, 61])

    def test_filter_by_type(self) -> None:
        self.add(self.me, "weight", {"value": 62})
        self.add(self.me, "bloodSugar", {"value": 6.4})
        only_sugar = self.client.get(
            "/v1/health/records", params={"itemType": "bloodSugar"}, headers=self.auth(self.me)
        ).json()
        self.assertEqual(only_sugar["count"], 1)
        self.assertEqual(only_sugar["records"][0]["itemType"], "bloodSugar")

    def test_invalid_value_returns_friendly_message(self) -> None:
        response = self.add(self.me, "bloodPressure", {"systolic": 80, "diastolic": 120})
        self.assertEqual(response.status_code, 400)
        error = response.json()["error"]
        self.assertEqual(error["code"], "health_value_invalid")
        self.assertIn("填反", error["message"])

    def test_unknown_item_type(self) -> None:
        response = self.add(self.me, "身高", {"value": 170})
        self.assertEqual(response.status_code, 400)

    def test_summary_lists_all_types(self) -> None:
        self.add(self.me, "weight", {"value": 62.5})
        self.add(self.me, "weight", {"value": 63.0})
        summary = self.client.get("/v1/health/summary", headers=self.auth(self.me)).json()
        weight = next(item for item in summary["items"] if item["itemType"] == "weight")
        self.assertEqual(weight["count"], 2)
        self.assertIsNotNone(weight["latest"])
        # 没记过的项要给 count=0 且 latest=None，而不是消失
        empty = next(item for item in summary["items"] if item["itemType"] == "bloodSugar")
        self.assertEqual(empty["count"], 0)
        self.assertIsNone(empty["latest"])

    # ---------------------------------------------------------------- 归属

    def test_cannot_see_others_records(self) -> None:
        self.add(self.me, "weight", {"value": 62})
        other_list = self.client.get("/v1/health/records", headers=self.auth(self.other)).json()
        self.assertEqual(other_list["count"], 0, "看到了别人的健康记录")

    def test_cannot_delete_others_record(self) -> None:
        record_id = self.add(self.me, "weight", {"value": 62}).json()["record"]["id"]
        response = self.client.delete("/v1/health/records/" + record_id, headers=self.auth(self.other))
        self.assertEqual(response.status_code, 403, response.text)
        # 原记录还在
        self.assertEqual(self.client.get("/v1/health/records", headers=self.auth(self.me)).json()["count"], 1)

    def test_delete_own_record(self) -> None:
        record_id = self.add(self.me, "weight", {"value": 62}).json()["record"]["id"]
        self.assertEqual(
            self.client.delete("/v1/health/records/" + record_id, headers=self.auth(self.me)).status_code, 200
        )
        self.assertEqual(self.client.get("/v1/health/records", headers=self.auth(self.me)).json()["count"], 0)


class PromptInjectionTestCase(unittest.TestCase):
    """健康数值要真的进到人设 prompt 里（"跟智能体挂钩"的关键）"""

    def test_snapshot_for_prompt(self) -> None:
        store = HealthStore()
        elder = "a_1"
        store.add(elder_id=elder, item_type="bloodPressure",
                  values={"systolic": 128, "diastolic": 82}, measured_at="2026-10-07T08:00:00+08:00")
        store.add(elder_id=elder, item_type="bloodPressure",
                  values={"systolic": 158, "diastolic": 96}, measured_at="2026-10-06T08:00:00+08:00")
        store.add(elder_id=elder, item_type="bloodSugar",
                  values={"value": 6.4, "timing": "空腹"}, measured_at="2026-10-07T07:00:00+08:00")

        lines = store.snapshot_for_prompt(elder)
        text = "\n".join(lines)
        self.assertIn("血压", text)
        self.assertIn("128/82", text)
        self.assertIn("158/96", text)
        self.assertIn("血糖", text)
        self.assertIn("6.4", text)
        self.assertIn("空腹", text)
        # 最近的在前面
        self.assertLess(text.index("128/82"), text.index("158/96"))

    def test_snapshot_empty_when_no_records(self) -> None:
        self.assertEqual(HealthStore().snapshot_for_prompt("a_none"), [])

    def test_prompt_contains_health_section(self) -> None:
        from app.persona.prompts import DEFAULT_PERSONAS, build_system_prompt

        persona = DEFAULT_PERSONAS["p_bilin"]
        prompt = build_system_prompt(
            persona,
            elder={"name": "张三", "chronic": ["高血压"]},
            memories=["去年去过海南"],
            health=["血压：128/82（2026-10-07）；158/96（2026-10-06）"],
        )
        self.assertIn("【最近的测量数值】", prompt)
        self.assertIn("128/82", prompt)
        # 必须带上"这不是诊断依据"的约束，否则模型会拿数值下结论
        self.assertIn("不是诊断依据", prompt)
        # 原有的两段不能被挤掉
        self.assertIn("【你记得的事】", prompt)
        self.assertIn("【你想起的往事", prompt)

    def test_prompt_without_health_is_unchanged_shape(self) -> None:
        """没有健康数据时不该出现空标题"""
        from app.persona.prompts import DEFAULT_PERSONAS, build_system_prompt

        prompt = build_system_prompt(DEFAULT_PERSONAS["p_bilin"], elder={"name": "张三"})
        self.assertNotIn("【最近的测量数值】", prompt)

    def test_chat_service_uses_health_provider(self) -> None:
        """ChatService 真的会把 health_provider 的结果交给 prompt"""
        calls = []

        def provider(elder_id: str):
            calls.append(elder_id)
            return ["血压：130/85（2026-10-07）"]

        from app.orchestration.service import ChatService

        service = ChatService.__new__(ChatService)
        service.elder_profiles = {"a_1": {"name": "张三"}}
        service.memory_provider = None
        service.health_provider = provider
        service.case_provider = None
        service.personas = None
        service.settings = type("S", (), {"history_turns": 4})()
        service.store = type("Store", (), {"history": lambda self, cid, limit=0: []})()

        from app.persona.prompts import PersonaRegistry

        service.personas = PersonaRegistry()
        messages = service._build_messages("c_1", service.personas.get(None), "a_1", "今天怎么样")
        self.assertEqual(calls, ["a_1"])
        system = messages[0]["content"]
        self.assertIn("130/85", system)


if __name__ == "__main__":
    unittest.main()
