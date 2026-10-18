"""双人设路由 + 医疗免责 的测试。

需求（原话）：
  「人设卡要默认两部分，一个为日程聊天的人设，一个为医疗相关知识的人设，
   两个人设选择一个回答，根据用户的询问内容转换人设；
   同时在回答时要注意边界，如果提及专业医疗知识，没有认真询问，
   却是日常聊天人设回答，必须要添加以下内容：仅供参考，
   实际情况请以医嘱为准，及时线下就医；
   如果用户在APP上添加了病例信息以及病史，则根据这部分来分析用户提出的问题」
"""
from __future__ import annotations

import unittest

from app.persona.prompts import (
    DEFAULT_PERSONAS,
    KIND_DAILY,
    KIND_MEDICAL,
    MEDICAL_NOTICE,
    PersonaRegistry,
    build_system_prompt,
    choose_persona,
    ensure_medical_notice,
    guard_address,
    has_clinical_content,
    is_medical_question,
)


class MedicalDetectionTestCase(unittest.TestCase):
    def test_daily_smalltalk_is_not_medical(self):
        """纯日常的话不能被判成医疗，否则老人会觉得"聊个天都要看病" """
        daily = [
            "今天天气不错",
            "我孙子来看我了",
            "咱俩唠两句",
            "晚上吃什么好",
            "我想听段戏",
            "你还记得我小时候的事吗",
        ]
        for text in daily:
            with self.subTest(text=text):
                self.assertFalse(is_medical_question(text), text)

    def test_medical_questions_are_detected(self):
        """症状、用药、检查、慢病都算医疗话题"""
        medical = [
            "我头晕",
            "血压有点高怎么办",
            "这个药能不能停",
            "医生说让我去复查",
            "血糖 8.5 严重吗",
            "我这两天睡不着",
            "我胃疼能吃辣吗",
            "这个检查结果偏高",
            "我有高血压能吃咸的吗",
        ]
        for text in medical:
            with self.subTest(text=text):
                self.assertTrue(is_medical_question(text), text)

    def test_weak_phrases_alone_count_as_medical(self):
        """"不舒服""难受"这类本身不是病名，但老人这么说通常就是在说身体"""
        for text in ("我有点不舒服", "今天难受", "浑身不得劲"):
            with self.subTest(text=text):
                self.assertTrue(is_medical_question(text), text)

    def test_empty_text_is_not_medical(self):
        for text in ("", "   ", None):
            self.assertFalse(is_medical_question(text))


class ChoosePersonaTestCase(unittest.TestCase):
    def setUp(self):
        self.registry = PersonaRegistry()

    def test_daily_talk_uses_daily_persona(self):
        persona = choose_persona("今天天气不错", self.registry, "p_son")
        self.assertEqual(persona.kind, KIND_DAILY)
        # 明确指定了角色时要尊重它，而不是一律回退到默认
        self.assertEqual(persona.id, "p_son")

    def test_medical_talk_switches_to_medical_persona(self):
        persona = choose_persona("我头晕得厉害", self.registry, "p_son")
        self.assertEqual(persona.kind, KIND_MEDICAL)
        self.assertEqual(persona.id, "p_medical")

    def test_medical_persona_has_sober_tone(self):
        """医疗人设的语气要稳，不能是"爽朗爱开玩笑"那种"""
        p = self.registry.by_kind(KIND_MEDICAL)
        self.assertIn("稳当", p.traits)
        self.assertNotIn("爱开玩笑", p.traits)

    def test_registry_has_both_kinds(self):
        self.assertIsNotNone(self.registry.by_kind(KIND_DAILY))
        self.assertIsNotNone(self.registry.by_kind(KIND_MEDICAL))


class MedicalNoticeTestCase(unittest.TestCase):
    """免责声明是合规硬要求，这里把每条规则钉住。"""

    def test_appended_when_medical_turn_and_missing(self):
        reply = "血压有点高 先坐下歇会儿 等会儿再量一次"
        out = ensure_medical_notice(reply, medical=True, text="我头晕")
        self.assertIn(MEDICAL_NOTICE, out)
        # 原文必须完整保留，不能把回答吃掉
        self.assertIn("先坐下歇会儿", out)

    def test_not_duplicated_when_model_already_said_it(self):
        """模型自己加了就别再加，否则会出现两句"以医嘱为准" """
        reply = "血压高先歇会儿\n\n仅供参考，实际情况请以医嘱为准，及时线下就医"
        out = ensure_medical_notice(reply, medical=True, text="我头晕")
        self.assertEqual(out.count("以医嘱为准"), 1)

    def test_appended_for_daily_persona_on_medical_content(self):
        """需求重点：日常人设答了医疗内容，也必须带免责"""
        out = ensure_medical_notice("多喝热水", medical=False, text="我血压高")
        self.assertIn(MEDICAL_NOTICE, out)

    def test_not_appended_for_pure_daily_talk(self):
        """纯日常对话不该被加医疗免责，否则每句话都带，老人会烦"""
        out = ensure_medical_notice("好啊 咱聊聊", medical=False, text="今天天气不错")
        self.assertEqual(out, "好啊 咱聊聊")

    def test_empty_reply_is_safe(self):
        self.assertEqual(ensure_medical_notice("", medical=True, text="我头晕"), "")


class PromptContentTestCase(unittest.TestCase):
    def test_medical_prompt_requires_cases_analysis(self):
        """有病历时要"结合病历分析"；没有时要明确说别假装知道"""
        medical = DEFAULT_PERSONAS["p_medical"]

        with_cases = build_system_prompt(
            medical, elder=None, health=["血压 158/96"], cases=["2026-09 社区医院 高血压3级"]
        )
        self.assertIn("必须结合上面记的病历和测量数值来分析", with_cases)

        without = build_system_prompt(medical, elder=None, health=[], cases=[])
        self.assertIn("没有他的病历和测量记录", without)

    def test_medical_prompt_forbids_diagnosis(self):
        medical = DEFAULT_PERSONAS["p_medical"]
        prompt = build_system_prompt(
            medical, elder=None, health=["血压 158/96"], cases=["高血压3级"]
        )
        self.assertIn("只做关联，不做诊断", prompt)
        self.assertIn("不能说「您这是", prompt)

    def test_daily_prompt_has_medical_boundary(self):
        """日常人设也要有"别自己下结论 + 免责"的指引"""
        daily = DEFAULT_PERSONAS["p_chat"]
        prompt = build_system_prompt(daily, elder=None)
        self.assertIn("不做医疗判断", prompt)
        self.assertIn("仅供参考，实际情况请以医嘱为准", prompt)

    def test_medical_persona_includes_health_and_cases(self):
        """需求：两种人设都参考病历 —— 医疗人设当然要注入"""
        medical = DEFAULT_PERSONAS["p_medical"]
        prompt = build_system_prompt(
            medical, elder=None,
            health=["血压 158/96"],
            cases=["2026-09 社区医院 高血压3级"],
        )
        self.assertIn("158/96", prompt)
        self.assertIn("高血压3级", prompt)

    def test_daily_persona_also_includes_cases(self):
        """用户明确要求：两种人设都参考病历"""
        daily = DEFAULT_PERSONAS["p_chat"]
        prompt = build_system_prompt(
            daily, elder=None,
            health=["血压 158/96"],
            cases=["2026-09 社区医院 高血压3级"],
        )
        self.assertIn("158/96", prompt)
        self.assertIn("高血压3级", prompt)


class DisclaimerDuplicateTestCase(unittest.TestCase):
    """模型自己用别的说法表达了"该看医生"时，不能再补一遍。

    实测踩到：模型说"具体还是得听医生的 我陪您一块儿问"，
    代码没认出来又追加了完整声明，变成两句意思重复的话，很机械。
    """

    def test_equivalent_phrasings_suppress_the_notice(self):
        equivalents = [
            "这个得听医生的 别自己停",
            "我陪您一块儿问问医生",
            "得赶紧去医院看看",
            "让医生看您的情况定",
            "按医生说的吃",
        ]
        for reply in equivalents:
            with self.subTest(reply=reply):
                out = ensure_medical_notice(reply, medical=True, text="我头晕")
                self.assertNotIn(MEDICAL_NOTICE, out, reply)
                self.assertEqual(out, reply)

    def test_plain_advice_still_gets_the_notice(self):
        """只说生活照应、没提医生时仍要补"""
        out = ensure_medical_notice("多喝热水 注意休息", medical=True, text="我头晕")
        self.assertIn(MEDICAL_NOTICE, out)


class AddressGuardTestCase(unittest.TestCase):
    """称呼漂移：人设是「您」，模型却说过「妈」。"""

    def test_drift_at_line_start_is_fixed(self):
        self.assertEqual(guard_address("妈 晚上想吃啥", "您"), "您 晚上想吃啥")

    def test_correct_address_untouched(self):
        text = "您今天高兴吧"
        self.assertEqual(guard_address(text, "您"), text)

    def test_possessive_untouched(self):
        """'我妈来看我了' 里的'妈'不是称呼，不能改"""
        text = "我妈来看我了"
        self.assertEqual(guard_address(text, "您"), text)

    def test_other_drift_words(self):
        self.assertEqual(guard_address("老伴 咱俩唠两句", "您"), "您 咱俩唠两句")


class ClinicalContentTestCase(unittest.TestCase):
    """回复内容里的医疗判断。

    需求原话："如果提及专业医疗知识，没有认真询问，却是日常聊天人设回答，
    必须要添加『仅供参考…』" —— 触发条件在**回复**上，不在提问上。
    实测漏过一次：老人问"我想吃点甜的，行不行"（不算医疗提问），
    而 AI 答"您血压高，少吃点"（有血压），当时没补免责。
    """

    def test_reply_mentioning_clinical_terms_is_flagged(self):
        for reply in (
            "您血压高，甜的解馋就行",
            "您这是高血压3级，得注意",
            "这个药不能停，得接着吃",   # 口语说法，书面词"停药"覆盖不到
            "化验结果我看看 指标偏高",
        ):
            with self.subTest(reply=reply):
                self.assertTrue(has_clinical_content(reply), reply)

    def test_routine_care_is_not_clinical(self):
        """日常照应不算专业医疗知识，不该每句都加免责（否则提醒会失效）"""
        for reply in (
            "记得吃药啊",
            "多喝水 早点睡",
            "今天天气不错 出去走走",
        ):
            with self.subTest(reply=reply):
                self.assertFalse(has_clinical_content(reply), reply)

    def test_routine_plus_clinical_still_triggers(self):
        """「记得吃药，血压别升上去」里既有照应也有临床，仍要触发"""
        self.assertTrue(has_clinical_content("记得吃药，血压别升上去"))

    def test_notice_added_when_only_reply_is_clinical(self):
        """核心场景：提问不是医疗问题，但回复提到了临床内容 → 必须补免责"""
        out = ensure_medical_notice(
            "您血压高，少吃点甜的", medical=False, text="我想吃点甜的"
        )
        self.assertIn(MEDICAL_NOTICE, out)

    def test_no_notice_for_pure_routine_reply(self):
        out = ensure_medical_notice("记得吃药啊", medical=False, text="我吃完饭了")
        self.assertNotIn(MEDICAL_NOTICE, out)


if __name__ == "__main__":
    unittest.main()
