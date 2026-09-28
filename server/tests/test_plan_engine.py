"""
计划引擎单测：条目匹配、生成、状态闸门、频率窗口、完成率、话术改写闸门

这一层守的是产品最关键的两条规则：
1. **未确认的草稿不产生任何提醒**（没经过家属的计划不准开始管老人）
2. **过渡期旧计划继续执行**（新草稿待确认期间不能出现提醒真空）
"""

from __future__ import annotations

import asyncio
import unittest
from collections.abc import AsyncIterator
from datetime import date

from app.config import Settings
from app.knowledge.loader import KnowledgeError, load_knowledge, validate_knowledge
from app.llm.base import LLMProvider
from app.models.elder import ElderStore
from app.plan.engine import (
    MAX_PER_TYPE,
    PlanEngine,
    PlanStateError,
    period_bounds,
    period_start,
)
from app.plan.models import (
    STATUS_ACTIVE,
    STATUS_ADJUSTING,
    STATUS_DRAFT,
    STATUS_ENDED,
    STATUS_PENDING,
    STATUS_REJECTED,
    CarePlan,
    PlanItem,
)
from app.plan.store import PlanStore
from app.style.compliance import has_medical_risk, is_clean, scan


class ScriptedProvider(LLMProvider):
    name = "scripted"

    def __init__(self, chunks: list[str]) -> None:
        self.chunks = chunks

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        for chunk in self.chunks:
            yield chunk


def build() -> tuple[PlanEngine, PlanStore, ElderStore]:
    store = PlanStore()
    elders = ElderStore()
    return PlanEngine(load_knowledge(), store, elders, Settings(llm_provider="fake")), store, elders


class KnowledgeTests(unittest.TestCase):
    def test_real_knowledge_base_loads(self) -> None:
        base = load_knowledge()
        self.assertEqual(len(base.entries), 25)
        self.assertEqual(len(base.sources), 3)
        self.assertEqual(base.version, "0.1.0-draft")
        self.assertEqual(validate_knowledge(), [])

    def test_every_entry_has_basis_fields(self) -> None:
        for entry in load_knowledge().entries:
            with self.subTest(entry=entry.id):
                self.assertTrue(entry.source)
                self.assertTrue(entry.version)
                self.assertTrue(entry.boundary)

    def test_broken_yaml_reports_all_problems(self) -> None:
        import tempfile
        from pathlib import Path

        broken = """
meta:
  version: "test"
  sources:
    - id: only_source
      name: 来源
entries:
  - id: bad_1
    source: missing_source
    version: "v1"
    category: 饮食
    audience: [全员]
    advice: 按时吃饭
    detail: 说明
    boundary: 无
    plan_hint: { time: "25:99", type: 不存在, freq: 每两周, strong_remind: maybe, weight: 重 }
    review_by: 明年
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.yaml"
            path.write_text(broken, encoding="utf-8")
            with self.assertRaises(KnowledgeError) as ctx:
                load_knowledge(path)
        problems = ctx.exception.problems
        self.assertTrue(any("source" in item for item in problems))
        self.assertTrue(any("plan_hint.time" in item for item in problems))
        self.assertTrue(any("plan_hint.type" in item for item in problems))
        self.assertTrue(any("plan_hint.freq" in item for item in problems))


class SelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine, self.store, self.elders = build()

    def test_audience_matching_is_condition_specific(self) -> None:
        hypertensive = {entry.id for entry in self.engine.match_entries("e_1")}
        diabetic = {entry.id for entry in self.engine.match_entries("e_2")}
        healthy_old = {entry.id for entry in self.engine.match_entries("e_3")}

        # 高血压专属条目只给高血压老人
        self.assertIn("nphis_006", hypertensive)
        self.assertNotIn("nphis_006", diabetic)
        self.assertNotIn("nphis_006", healthy_old)
        # 65岁以上 的条目给所有老人（三个档案都过 65）
        self.assertIn("nphis_001", healthy_old)
        # 无慢病老人的计划里不该出现慢病随访
        self.assertNotIn("nphis_003", healthy_old)

    def test_selection_rules(self) -> None:
        entries = self.engine.match_entries("e_1")
        times = [entry.time for entry in entries]
        self.assertEqual(len(times), len(set(times)), "同一时刻只能有一条提醒")
        self.assertLessEqual(len(entries), 6)
        # 全员条目受类型上限约束（针对性条目不受限）
        counts: dict[str, int] = {}
        for entry in entries:
            counts[entry.type] = counts.get(entry.type, 0) + 1
        for type_name, count in counts.items():
            with self.subTest(type=type_name):
                self.assertLessEqual(count, MAX_PER_TYPE + 1)

    def test_max_items_is_respected(self) -> None:
        entries = self.engine.match_entries("e_1", max_items=3)
        self.assertEqual(len(entries), 3)

    def test_declared_sources_are_real(self) -> None:
        base = load_knowledge()
        for entry in self.engine.match_entries("e_2"):
            self.assertIn(entry.source, base.sources)


class GenerateAndGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine, self.store, self.elders = build()

    def test_draft_carries_basis_and_period(self) -> None:
        plan = self.engine.build_plan("e_1", start="2026-09-24", days=90)
        self.assertEqual(plan.status, STATUS_DRAFT)
        self.assertEqual(plan.start_date, "2026-09-24")
        self.assertEqual(plan.end_date, "2026-12-22")
        self.assertEqual(plan.knowledge_version, "0.1.0-draft")
        self.assertTrue(plan.sources)
        for item in plan.items:
            with self.subTest(item=item.id):
                self.assertTrue(item.entry_id)
                self.assertTrue(item.version)
                # 依据必须能追溯到具体来源（家属端要看到"这条是照哪份指南来的"）
                self.assertIn(item.source_name, item.basis_text())
                self.assertIn("§" + item.entry_id, item.basis_text())
                self.assertEqual(item.source_name, self.engine.knowledge.source_name(item.source))
        # 高血压老人的计划里必须有针对性条目（nphis3 是主干来源）
        self.assertTrue(any(item.source == "nphis3" for item in plan.items))

    def test_draft_produces_no_reminder(self) -> None:
        """核心闸门：草稿不该出现在今日计划里。"""
        plan = self.engine.build_plan("e_1")
        self.assertIsNone(self.store.active("e_1"))
        today = self.engine.today("e_1")
        self.assertEqual(today["total"], 0)
        self.assertEqual(today["items"], [])

    def test_pending_still_produces_no_reminder(self) -> None:
        plan = self.engine.build_plan("e_1")
        self.engine.submit(plan)
        self.assertEqual(plan.status, STATUS_PENDING)
        self.assertIsNone(self.store.active("e_1"))
        self.assertEqual(self.engine.today("e_1")["total"], 0)
        self.assertEqual(len(self.store.pending("e_1")), 1)

    def test_confirm_activates_and_old_plan_keeps_running_until_then(self) -> None:
        first = self.engine.build_plan("e_1")
        self.engine.submit(first)
        self.engine.confirm(first)
        self.assertEqual(first.status, STATUS_ACTIVE)
        self.assertGreater(self.engine.today("e_1")["total"], 0)

        # 新草稿待确认期间：旧计划继续执行（不能出现提醒真空）
        second = self.engine.build_plan("e_1")
        self.engine.submit(second)
        self.assertEqual(self.store.active("e_1").id, first.id)
        self.assertEqual(first.status, STATUS_ACTIVE)
        self.assertGreater(self.engine.today("e_1")["total"], 0)

        # 新计划确认的那一刻，旧计划才结束
        self.engine.confirm(second)
        self.assertEqual(second.status, STATUS_ACTIVE)
        self.assertEqual(first.status, STATUS_ENDED)
        self.assertEqual(self.store.active("e_1").id, second.id)

    def test_reject_keeps_old_plan(self) -> None:
        first = self.engine.build_plan("e_1")
        self.engine.submit(first)
        self.engine.confirm(first)
        second = self.engine.build_plan("e_1")
        self.engine.submit(second)
        self.engine.reject(second, reason="时间不合适")
        self.assertEqual(second.status, STATUS_REJECTED)
        self.assertEqual(self.store.active("e_1").id, first.id)
        self.assertEqual(self.store.pending("e_1"), [])

    def test_adjusting_flow(self) -> None:
        plan = self.engine.build_plan("e_1")
        self.engine.submit(plan)
        self.engine.confirm(plan)
        self.engine.mark_adjusting(plan, "完成率偏低")
        self.assertEqual(plan.status, STATUS_ADJUSTING)
        # 调整中也算在执行的计划（旧计划不能因此停掉）
        self.assertEqual(self.store.active("e_1").id, plan.id)
        self.engine.adopt_adjustment(plan)
        self.assertEqual(plan.status, STATUS_ACTIVE)

    def test_illegal_transitions_are_rejected(self) -> None:
        plan = self.engine.build_plan("e_1")
        with self.assertRaises(PlanStateError):
            self.engine.confirm(plan)  # 草稿不能直接确认
        self.engine.submit(plan)
        with self.assertRaises(PlanStateError):
            self.engine.submit(plan)  # 不能重复提交
        self.engine.confirm(plan)
        with self.assertRaises(PlanStateError):
            self.engine.confirm(plan)

    def test_history_records_every_transition(self) -> None:
        plan = self.engine.build_plan("e_1")
        self.engine.submit(plan)
        self.engine.confirm(plan, actor="女儿小丽")
        actions = [item["action"] for item in plan.history]
        self.assertEqual(actions, ["draft", "submit", "confirm"])
        self.assertEqual(plan.history[-1]["actor"], "女儿小丽")
        self.assertTrue(plan.confirmed_at)


class TodayAndFrequencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine, self.store, self.elders = build()

    def _active_plan(self, items: list[PlanItem]) -> CarePlan:
        plan = CarePlan(id="plan_test", elder_id="e_1", status=STATUS_ACTIVE, items=items)
        self.store.add(plan)
        return plan

    def test_daily_item_always_shown_even_when_done(self) -> None:
        plan = self._active_plan(
            [PlanItem(id="i_daily", time="08:00", type="监测", title="量血压", freq="每日")]
        )
        self.store.checkin(plan, "i_daily", "e_1", "2026-09-24")
        today = self.engine.today("e_1", date(2026, 9, 24))
        self.assertEqual(today["total"], 1)
        self.assertTrue(today["items"][0]["done"])
        self.assertEqual(today["done"], 1)

    def test_weekly_item_due_all_week_until_done(self) -> None:
        plan = self._active_plan(
            [PlanItem(id="i_week", time="16:00", type="活动", title="社交", freq="每周")]
        )
        # 2026-09-24 是周四，本周一 09-21
        self.assertEqual(period_start("每周", date(2026, 9, 24)), date(2026, 9, 21))
        self.assertEqual(self.engine.today("e_1", date(2026, 9, 24))["total"], 1)  # 周一错过，周四仍提醒
        self.store.checkin(plan, "i_week", "e_1", "2026-09-24")
        self.assertEqual(self.engine.today("e_1", date(2026, 9, 24))["total"], 1)  # 今天做的照常显示
        self.assertTrue(self.engine.today("e_1", date(2026, 9, 24))["items"][0]["done"])
        self.assertEqual(self.engine.today("e_1", date(2026, 9, 25))["total"], 0)  # 本周已完成
        self.assertEqual(self.engine.today("e_1", date(2026, 9, 28))["total"], 1)  # 下周一又该做了

    def test_yearly_item_only_inside_window(self) -> None:
        self._active_plan(
            [PlanItem(id="i_year", time="09:00", type="监测", title="年度体检", freq="每年")]
        )
        self.assertEqual(self.engine.today("e_1", date(2026, 1, 15))["total"], 1)
        self.assertEqual(self.engine.today("e_1", date(2026, 3, 5))["total"], 0)  # 超过 60 天窗口
        self.assertEqual(self.engine.today("e_1", date(2026, 12, 31))["total"], 0)

    def test_quarterly_window_and_bounds(self) -> None:
        self.assertEqual(period_bounds("每季度", date(2026, 9, 24)), (date(2026, 7, 1), date(2026, 9, 30)))
        self._active_plan(
            [PlanItem(id="i_q", time="10:00", type="监测", title="社区随访", freq="每季度")]
        )
        self.assertEqual(self.engine.today("e_1", date(2026, 7, 10))["total"], 1)
        self.assertEqual(self.engine.today("e_1", date(2026, 9, 24))["total"], 0)  # 超过 30 天窗口

    def test_today_reports_status_label(self) -> None:
        plan = self.engine.build_plan("e_1")
        self.engine.submit(plan)
        self.engine.confirm(plan)
        today = self.engine.today("e_1")
        self.assertEqual(today["status"], STATUS_ACTIVE)
        self.assertEqual(today["statusLabel"], "正在执行")
        self.assertEqual(today["planId"], plan.id)


class CheckinAndCompletionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine, self.store, self.elders = build()
        self.plan = self.engine.build_plan("e_1")
        self.engine.submit(self.plan)
        self.engine.confirm(self.plan)

    def test_checkin_is_idempotent_and_undoable(self) -> None:
        item = self.plan.items[0]
        first = self.store.checkin(self.plan, item.id, "e_1", "2026-09-24")
        again = self.store.checkin(self.plan, item.id, "e_1", "2026-09-24")
        self.assertEqual(first.id, again.id, "同一天同一项重复打卡不该产生两条记录")
        self.assertTrue(self.store.undo_checkin(item.id, "2026-09-24"))
        self.assertFalse(self.store.undo_checkin(item.id, "2026-09-24"))

    def test_completion_counts_daily_items(self) -> None:
        daily = [item for item in self.plan.items if item.freq == "每日"]
        self.assertTrue(daily)
        self.store.checkin(self.plan, daily[0].id, "e_1", "2026-09-24")
        stats = self.engine.completion(self.plan, days=3, day=date(2026, 9, 24))
        self.assertEqual(stats["expected"], len(daily) * 3)
        self.assertEqual(stats["done"], 1)
        self.assertLess(stats["rate"], 0.5)

    def test_low_completion_triggers_suggestion(self) -> None:
        stats = self.engine.adjustment_suggestion(self.plan, days=7, day=date(2026, 9, 24))
        self.assertTrue(stats["shouldAdjust"])
        self.assertTrue(any("完成" in reason for reason in stats["reasons"]))
        # 建议只谈提醒安排，不谈治疗
        joined = "；".join(stats["reasons"])
        self.assertFalse(has_medical_risk(joined))

    def test_good_completion_needs_no_adjustment(self) -> None:
        day = date(2026, 9, 24)
        for offset in range(7):
            cursor = date(2026, 9, 18 + offset)
            for item in self.plan.items:
                if item.freq == "每日":
                    self.store.checkin(self.plan, item.id, "e_1", cursor.isoformat())
        stats = self.engine.adjustment_suggestion(self.plan, days=7, day=day)
        self.assertEqual(stats["stats"]["rate"], 1.0)
        self.assertFalse(stats["shouldAdjust"])


class PolishGateTests(unittest.TestCase):
    """LLM 改写话术必须过闸门：越界/过长/带网址一律退回知识库原文。"""

    def setUp(self) -> None:
        self.engine, self.store, self.elders = build()
        self.items = [
            PlanItem(id="i1", time="08:00", type="监测", title="量完血压记一下", entry_id="nphis_006"),
            PlanItem(id="i2", time="11:30", type="午餐", title="每天吃盐不超过5克", entry_id="diet_salt_001"),
        ]
        self.elder = self.elders.get("e_1")

    def _polish(self, chunks: list[str]):
        provider = ScriptedProvider(chunks)
        return asyncio.run(self.engine.polish_items(self.items, self.elder, provider))

    def test_safe_rewrite_is_applied(self) -> None:
        polished, stats = self._polish(["1. 量完血压记一下 下次给医生看。\n2. 做菜少放点盐"])
        self.assertEqual(polished[0].title, "量完血压记一下 下次给医生看")
        self.assertEqual(polished[1].title, "做菜少放点盐")
        self.assertEqual(stats["polished"], 2)
        self.assertEqual(stats["fallback"], 0)

    def test_unsafe_rewrite_falls_back(self) -> None:
        polished, stats = self._polish(["1. 血压高了就加一片药\n2. 这药可以停了"])
        self.assertEqual(polished[0].title, self.items[0].title)
        self.assertEqual(polished[1].title, self.items[1].title)
        self.assertEqual(stats["fallback"], 2)
        self.assertTrue(any("医疗边界" in reason for reason in stats["reasons"]))

    def test_too_long_and_url_fall_back(self) -> None:
        polished, stats = self._polish(
            ["1. 妈 今天记得量血压然后记下来下次去医院的时候带给医生看喏\n2. 看这里 http://a.com"]
        )
        self.assertEqual(polished[0].title, self.items[0].title)
        self.assertEqual(polished[1].title, self.items[1].title)
        self.assertEqual(stats["fallback"], 2)

    def test_malformed_output_falls_back_entirely(self) -> None:
        polished, stats = self._polish(["我改写好了", "但是没按格式输出"])
        self.assertEqual([item.title for item in polished], [item.title for item in self.items])
        self.assertEqual(stats["polished"], 0)
        self.assertEqual(stats["fallback"], 2)

    def test_missing_line_falls_back_only_that_item(self) -> None:
        polished, stats = self._polish(["1. 量完血压就记下来"])
        self.assertEqual(polished[0].title, "量完血压就记下来")
        self.assertEqual(polished[1].title, self.items[1].title)
        self.assertEqual((stats["polished"], stats["fallback"]), (1, 1))

    def test_rewrite_equal_to_original_counts_as_fallback(self) -> None:
        """模型原样返回不算改写（否则统计会说"改写成功"但实际没变）"""
        polished, stats = self._polish(["1. 量完血压记一下\n2. 每天吃盐不超过5克"])
        self.assertEqual([item.title for item in polished], [item.title for item in self.items])
        self.assertEqual((stats["polished"], stats["fallback"]), (0, 2))

    def test_no_provider_keeps_original(self) -> None:
        polished, stats = asyncio.run(self.engine.polish_items(self.items, self.elder, None))
        self.assertEqual([item.title for item in polished], [item.title for item in self.items])
        self.assertEqual(stats["fallback"], 2)


class ComplianceScanTests(unittest.TestCase):
    """与 tools/check-chat-quality.mjs 同一套规则（两处必须同步）。"""

    def test_medication_judgements_are_flagged(self) -> None:
        for text in ("这药不能停", "可以停了", "别吃了", "换一种药", "明天加一片", "剂量调一下"):
            with self.subTest(text=text):
                self.assertTrue(has_medical_risk(text), text)

    def test_adherence_reminders_are_allowed(self) -> None:
        for text in ("药按医生说的吃了吗", "别自己乱停药", "按时吃药 别忘了", "能不能停 得医生看了才定"):
            with self.subTest(text=text):
                self.assertFalse(has_medical_risk(text), text)

    def test_diagnosis_phrases_are_flagged(self) -> None:
        self.assertTrue(has_medical_risk("你就是得了高血压"))
        self.assertTrue(has_medical_risk("你这是糖尿病"))
        self.assertTrue(has_medical_risk("病情加重了"))

    def test_service_tone_is_reported_but_not_medical_risk(self) -> None:
        hints = scan("您好，请问您今天服药了吗")
        self.assertTrue(any("客服用语" in item for item in hints))
        self.assertTrue(is_clean("妈 今天吃药了没"))


if __name__ == "__main__":
    unittest.main()
