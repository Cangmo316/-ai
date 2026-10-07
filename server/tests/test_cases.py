"""病例病史接口契约测试

重点：
  1. **PDF 文本抽取**（真的能读出中文，且扫描件要如实说"读不出"）
  2. **文件上传**（建病历、加附件、删附件、取原件）
  3. **归属**（不能看/改/删别人的病历）
  4. **注入智能体**：病例摘要要进人设 prompt
"""

from __future__ import annotations

import unittest
import zlib
from datetime import datetime

from fastapi.testclient import TestClient

from app.config import Settings
from app.docs import CaseStore, extract_text
from app.docs.pdf import PdfResult
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


def make_pdf(text: str) -> bytes:
    """造一份带 ToUnicode CMap 的 PDF（和真实中文 PDF 同一套结构）"""
    codes = []
    pairs = []
    for index, ch in enumerate(text):
        code = 0x1000 + index
        codes.append(code.to_bytes(2, "big"))
        pairs.append("<%04X> <%04X>" % (code, ord(ch)))

    content = b"BT /F1 12 Tf 50 700 Td <" + b"".join(codes).hex().encode() + b"> Tj ET"
    compressed = zlib.compress(content)
    cmap = zlib.compress(("\n".join(["begincmap", "1 beginbfchar"] + pairs + ["endbfchar", "endcmap"])).encode("latin-1"))

    pdf = b"%PDF-1.4\n"
    pdf += b"1 0 obj <</Type/Catalog>> endobj\n"
    pdf += b"2 0 obj <</Length %d /Filter /FlateDecode>>\nstream\n" % len(compressed) + compressed + b"\nendstream endobj\n"
    pdf += b"3 0 obj <</Length %d /Filter /FlateDecode>>\nstream\n" % len(cmap) + cmap + b"\nendstream endobj\n"
    pdf += b"trailer <</Root 1 0 R>>\n%%EOF\n"
    return pdf


def make_scanned_pdf() -> bytes:
    """造一份"整页是图片、没有文本层"的 PDF（扫描件的特征）"""
    image_stream = zlib.compress(b"q 612 0 0 792 0 0 cm /Im0 Do Q")
    pdf = b"%PDF-1.4\n"
    pdf += b"1 0 obj <</Type/Catalog>> endobj\n"
    pdf += b"2 0 obj <</Length %d /Filter /FlateDecode>>\nstream\n" % len(image_stream) + image_stream + b"\nendstream endobj\n"
    pdf += b"trailer <</Root 1 0 R>>\n%%EOF\n"
    return pdf


class PdfExtractTestCase(unittest.TestCase):
    """PDF 抽取（纯函数，不起 HTTP）"""

    def test_extracts_chinese(self) -> None:
        text = "出院记录 患者张某某 诊断 高血压3级 2型糖尿病 医嘱 低盐低脂饮食"
        result = extract_text(make_pdf(text))
        self.assertTrue(result.ok, result.reason)
        self.assertIn("出院记录", result.text)
        self.assertIn("高血压3级", result.text)
        self.assertIn("低盐低脂饮食", result.text)
        self.assertEqual(result.pages, 1)

    def test_scanned_pdf_says_so(self) -> None:
        """扫描件必须如实说"读不出文字"，不能返回乱码"""
        result = extract_text(make_scanned_pdf())
        self.assertFalse(result.ok)
        self.assertTrue(result.looks_scanned)
        self.assertIn("扫描件", result.reason)

    def test_not_a_pdf(self) -> None:
        result = extract_text(b"this is just a text file")
        self.assertFalse(result.ok)
        self.assertIn("不像 PDF", result.reason)

    def test_empty(self) -> None:
        self.assertFalse(extract_text(b"").ok)

    def test_encrypted_pdf(self) -> None:
        pdf = b"%PDF-1.4\n/Encrypt 5 0 R\ntrailer\n%%EOF\n"
        result = extract_text(pdf)
        self.assertTrue(result.encrypted)
        self.assertIn("密码", result.reason)


class CaseStoreTestCase(unittest.TestCase):
    """存储与给智能体的摘要（纯内存）"""

    def test_snapshot_for_prompt(self) -> None:
        store = CaseStore()
        elder = "a_1"
        store.create(
            elder_id=elder, kind="inpatient", visit_date="2026-09-20T00:00:00+08:00",
            hospital="市第一医院", diagnosis="高血压3级，2型糖尿病",
        )
        store.create(
            elder_id=elder, kind="lab", visit_date="2026-10-01T00:00:00+08:00",
            hospital="社区卫生中心", diagnosis="空腹血糖偏高",
        )
        lines = store.snapshot_for_prompt(elder)
        self.assertEqual(len(lines), 2)
        # 最近的在前
        self.assertIn("10-01", lines[0])
        self.assertIn("社区卫生中心", lines[0])
        self.assertIn("高血压3级", lines[1])

    def test_known_diagnoses_dedup(self) -> None:
        store = CaseStore()
        store.create(elder_id="a_1", diagnosis="高血压3级，2型糖尿病")
        store.create(elder_id="a_1", diagnosis="高血压3级，脂肪肝")
        self.assertEqual(store.known_diagnoses("a_1"), ["高血压3级", "2型糖尿病", "脂肪肝"])

    def test_snapshot_empty(self) -> None:
        self.assertEqual(CaseStore().snapshot_for_prompt("a_none"), [])


class AutoFillTestCase(unittest.TestCase):
    """自动填字段（识别结果的第一行常常是"主要信息："这种小标题）"""

    def test_pick_title_skips_section_labels(self) -> None:
        from app.api.cases import _pick_title

        text = "\n".join([
            "主要信息：",
            "医院名称：市第一人民医院",
            "日期：2026-10-01",
            "检查结果：",
            "空腹血糖 7.2 mmol/L",
        ])
        title = _pick_title(text)
        self.assertNotIn("主要信息", title)
        self.assertTrue(title, "应该挑出一条有内容的行")

    def test_pick_title_prefers_value_after_label(self) -> None:
        from app.api.cases import _pick_title

        self.assertEqual(_pick_title("诊断/结论：2型糖尿病、高血压3级"), "2型糖尿病、高血压3级")

    def test_pick_title_empty(self) -> None:
        from app.api.cases import _pick_title

        self.assertEqual(_pick_title(""), "")


class CaseApiTestCase(unittest.TestCase):
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

    def create_case(self, who: dict, **form):
        data = {"kind": "outpatient", "hospital": "市医院", "visitDate": "2026-10-01"}
        data.update(form)
        return self.client.post("/v1/cases", data=data, headers=self.auth(who))

    # ---------------------------------------------------------------- 类型

    def test_types_need_no_login(self) -> None:
        response = self.client.get("/v1/cases/types")
        self.assertEqual(response.status_code, 200, response.text)
        kinds = [item["kind"] for item in response.json()["types"]]
        for expected in ("outpatient", "inpatient", "lab", "imaging", "prescription", "physical"):
            self.assertIn(expected, kinds)

    def test_vision_status(self) -> None:
        response = self.client.get("/v1/cases/vision/status")
        self.assertEqual(response.status_code, 200)
        self.assertIn("provider", response.json())

    # ---------------------------------------------------------------- 增删改查

    def test_requires_login(self) -> None:
        self.assertEqual(self.client.get("/v1/cases").status_code, 401)

    def test_create_text_only(self) -> None:
        response = self.create_case(self.me, diagnosis="高血压3级", summary="医生让低盐")
        self.assertEqual(response.status_code, 201, response.text)
        case = response.json()["case"]
        self.assertEqual(case["kindLabel"], "门诊病历")
        self.assertEqual(case["diagnosis"], "高血压3级")
        self.assertEqual(case["files"], [])

    def test_list_sorted_by_visit_date(self) -> None:
        self.create_case(self.me, visitDate="2026-09-01", diagnosis="早")
        self.create_case(self.me, visitDate="2026-10-01", diagnosis="晚")
        cases = self.client.get("/v1/cases", headers=self.auth(self.me)).json()["cases"]
        self.assertEqual([c["diagnosis"] for c in cases], ["晚", "早"])

    def test_update_case(self) -> None:
        case_id = self.create_case(self.me, diagnosis="写错了").json()["case"]["id"]
        response = self.client.patch(
            "/v1/cases/" + case_id, json={"diagnosis": "高血压3级"}, headers=self.auth(self.me)
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["case"]["diagnosis"], "高血压3级")

    def test_delete_case(self) -> None:
        case_id = self.create_case(self.me).json()["case"]["id"]
        self.assertEqual(self.client.delete("/v1/cases/" + case_id, headers=self.auth(self.me)).status_code, 200)
        self.assertEqual(self.client.get("/v1/cases", headers=self.auth(self.me)).json()["count"], 0)

    def test_unknown_case(self) -> None:
        self.assertEqual(self.client.get("/v1/cases/case_nope", headers=self.auth(self.me)).status_code, 404)

    # ---------------------------------------------------------------- 归属

    def test_cannot_read_others_case(self) -> None:
        case_id = self.create_case(self.me).json()["case"]["id"]
        response = self.client.get("/v1/cases/" + case_id, headers=self.auth(self.other))
        self.assertEqual(response.status_code, 403, response.text)

    def test_cannot_delete_others_case(self) -> None:
        case_id = self.create_case(self.me).json()["case"]["id"]
        response = self.client.delete("/v1/cases/" + case_id, headers=self.auth(self.other))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get("/v1/cases", headers=self.auth(self.me)).json()["count"], 1)

    def test_others_cases_not_listed(self) -> None:
        self.create_case(self.me)
        self.assertEqual(self.client.get("/v1/cases", headers=self.auth(self.other)).json()["count"], 0)

    # ---------------------------------------------------------------- 文件

    def test_upload_pdf_extracts_text(self) -> None:
        """上传带文本层的 PDF → 自动抽出文字并落进附件"""
        pdf = make_pdf("出院记录 诊断 高血压3级 医嘱 按时服药")
        response = self.client.post(
            "/v1/cases",
            data={"kind": "inpatient", "visitDate": "2026-09-20"},
            files=[("files", ("record.pdf", pdf, "application/pdf"))],
            headers=self.auth(self.me),
        )
        self.assertEqual(response.status_code, 201, response.text)
        case = response.json()["case"]
        self.assertEqual(len(case["files"]), 1)
        item = case["files"][0]
        self.assertEqual(item["fileType"], "pdf")
        self.assertEqual(item["extractStatus"], "ok")
        self.assertTrue(item["hasText"])
        self.assertIn("高血压3级", item["extractedText"])
        # 自动把识别结果填进了空字段（老人不用再手打一遍）
        self.assertTrue(case["summary"] or case["title"])

    def test_upload_scanned_pdf_reports_scanned(self) -> None:
        """扫描件：如实报"读不出"，而不是假装成功"""
        response = self.client.post(
            "/v1/cases",
            data={"kind": "imaging"},
            files=[("files", ("scan.pdf", make_scanned_pdf(), "application/pdf"))],
            headers=self.auth(self.me),
        )
        self.assertEqual(response.status_code, 201, response.text)
        item = response.json()["case"]["files"][0]
        self.assertEqual(item["extractStatus"], "scanned")
        self.assertFalse(item["hasText"])
        self.assertIn("扫描件", item["extractReason"])

    def test_upload_rejects_unsupported_type(self) -> None:
        response = self.client.post(
            "/v1/cases",
            data={"kind": "other"},
            files=[("files", ("note.txt", b"hello", "text/plain"))],
            headers=self.auth(self.me),
        )
        # 病历本身建起来了，但不支持的附件被拒绝并给出原因
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["case"]["files"], [])
        self.assertTrue(body["problems"])
        self.assertIn("只支持", body["problems"][0])

    def test_upload_empty_file(self) -> None:
        response = self.client.post(
            "/v1/cases",
            data={"kind": "other"},
            files=[("files", ("empty.pdf", b"", "application/pdf"))],
            headers=self.auth(self.me),
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["problems"])

    def test_add_and_remove_file(self) -> None:
        case_id = self.create_case(self.me).json()["case"]["id"]
        added = self.client.post(
            "/v1/cases/" + case_id + "/files",
            files={"file": ("a.pdf", make_pdf("化验单 血糖 6.4"), "application/pdf")},
            headers=self.auth(self.me),
        )
        self.assertEqual(added.status_code, 201, added.text)
        files = added.json()["case"]["files"]
        self.assertEqual(len(files), 1)

        removed = self.client.delete(
            "/v1/cases/" + case_id + "/files/" + files[0]["fileId"], headers=self.auth(self.me)
        )
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertEqual(removed.json()["case"]["files"], [])

    def test_raw_file_download(self) -> None:
        pdf = make_pdf("原件内容")
        case = self.client.post(
            "/v1/cases",
            data={"kind": "lab"},
            files=[("files", ("x.pdf", pdf, "application/pdf"))],
            headers=self.auth(self.me),
        ).json()["case"]
        file_id = case["files"][0]["fileId"]
        response = self.client.get(
            "/v1/cases/" + case["id"] + "/files/" + file_id + "/raw", headers=self.auth(self.me)
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, pdf)
        self.assertEqual(response.headers["content-type"], "application/pdf")

    def test_cannot_download_others_raw(self) -> None:
        pdf = make_pdf("别人的")
        case = self.client.post(
            "/v1/cases",
            data={"kind": "lab"},
            files=[("files", ("x.pdf", pdf, "application/pdf"))],
            headers=self.auth(self.me),
        ).json()["case"]
        file_id = case["files"][0]["fileId"]
        response = self.client.get(
            "/v1/cases/" + case["id"] + "/files/" + file_id + "/raw", headers=self.auth(self.other)
        )
        self.assertEqual(response.status_code, 403)


class CasePromptInjectionTestCase(unittest.TestCase):
    """病例要真的进 prompt"""

    def test_prompt_contains_cases_section(self) -> None:
        from app.persona.prompts import DEFAULT_PERSONAS, build_system_prompt

        prompt = build_system_prompt(
            DEFAULT_PERSONAS["p_bilin"],
            elder={"name": "张三"},
            health=["血压：128/82（2026-10-07）"],
            cases=["2026-09-20 住院/出院记录 市第一医院：高血压3级"],
        )
        self.assertIn("【他去医院的情况】", prompt)
        self.assertIn("高血压3级", prompt)
        self.assertIn("按原话讲", prompt)
        # 三段并存，互不挤掉
        self.assertIn("【最近的测量数值】", prompt)
        self.assertIn("【你记得的事】", prompt)

    def test_prompt_without_cases(self) -> None:
        from app.persona.prompts import DEFAULT_PERSONAS, build_system_prompt

        prompt = build_system_prompt(DEFAULT_PERSONAS["p_bilin"], elder={"name": "张三"})
        self.assertNotIn("【他去医院的情况】", prompt)

    def test_chat_service_uses_case_provider(self) -> None:
        calls = []

        def provider(elder_id: str):
            calls.append(elder_id)
            return ["2026-10-01 化验单 社区医院：空腹血糖偏高"]

        from app.orchestration.service import ChatService
        from app.persona.prompts import PersonaRegistry

        service = ChatService.__new__(ChatService)
        service.elder_profiles = {"a_1": {"name": "张三"}}
        service.memory_provider = None
        service.health_provider = None
        service.case_provider = provider
        service.personas = PersonaRegistry()
        service.settings = type("S", (), {"history_turns": 4})()
        service.store = type("Store", (), {"history": lambda self, cid, limit=0: []})()

        messages = service._build_messages("c_1", service.personas.get(None), "a_1", "今天怎么样")
        self.assertEqual(calls, ["a_1"])
        self.assertIn("空腹血糖偏高", messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
