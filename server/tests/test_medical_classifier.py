"""医疗/日常分类器的回归测试（不调模型，秒级）。

## 为什么需要这一组

2026-10 用 62 条真实康养场景跑真模型评测，发现分类器有**两类系统性错误**：

**① 漏判 10 条（全是安全相关的）**
```
"我晚上老是睡不好"           → 走陪聊（应该走医疗）
"我一天要吃六种药，有时候就忘了吃" → 走陪聊
"我忘了今天药吃了没有"        → 走陪聊
"我刚才起来太猛，眼前一黑差点摔倒" → 走陪聊
"我在厕所摔了一跤"           → 走陪聊
"我这几天大便带血"           → 走陪聊
"我是不是老年痴呆了"          → 走陪聊
"我认错人了，把邻居当成我闺女了"  → 走陪聊
"我喝水老呛着"              → 走陪聊
"我奶奶晚上不睡觉，到处走"      → 走陪聊
```
这些恰恰是最需要谨慎口径的话题。漏判的后果是 AI 用陪聊口吻答了跌倒、
便血、认知障碍 —— 老人可能因此不当回事。

**② 误判 5 条（单字关键词误伤）**
```
"腿" → "我腿脚不方便"     "病" → "说能治百病"
"牙" → "我牙口不好"       "麻" → "做什么都嫌麻烦"
"难受" → "我心里难受"（这是诉苦）
```

根因是关键词表里有 17 个**单字**（疼 痛 晕 咳 喘 肿 麻 牙 胃 腰 腿 病…），
在真实口语里到处误伤。

## 这一组测试守什么

守的就是上面这些**具体句子**不再回退。它不调模型，所以跑得飞快，
可以在每次改关键词时立刻验证。
"""

from __future__ import annotations

import unittest

from app.persona.prompts import is_medical_question
from tests.scenarios import SCENARIOS


class ScenarioClassificationTestCase(unittest.TestCase):
    """62 条真实场景：每条都应该按预期进医疗人设或陪聊人设。"""

    def test_scenarios_classify_as_expected(self):
        checked = 0
        wrong: list[str] = []
        for case in SCENARIOS:
            want = case.get("medical")
            if want is None:          # 这条两可，不检查
                continue
            checked += 1
            got = is_medical_question(case["text"])
            if got != want:
                wrong.append(
                    "%s → 期望%s，实际%s"
                    % (
                        case["text"],
                        "医疗" if want else "日常",
                        "医疗" if got else "日常",
                    )
                )
        self.assertGreaterEqual(checked, 50, "场景数量不对，检查一下 scenarios.py")
        self.assertEqual(wrong, [], "分类不符预期：\n" + "\n".join(wrong))


class SafetyCriticalTestCase(unittest.TestCase):
    """安全红线：这些句子**必须**走医疗人设（漏了会误导老人）。"""

    MUST_BE_MEDICAL = (
        # 跌倒（老年致残首因）
        "我在厕所摔了一跤，现在能站起来",
        "我刚才起来太猛，眼前一黑差点摔倒",
        "我前两天在家里摔过一次",
        # 出血
        "我这几天大便带血",
        # 卒中征象
        "我右半边身子有点发麻，说话也不太利索",
        # 用药安全
        "我忘了今天药吃了没有，要不要再吃一次",
        "我一天要吃六种药，有时候就忘了吃",
        "这个降压药吃了老咳嗽，我能不能换一个",
        # 认知障碍
        "我认错人了，把邻居当成我闺女了",
        "我是不是老年痴呆了，老忘事",
        # 吞咽（误吸风险）
        "我喝水老呛着",
        # 认知症行为
        "我奶奶晚上不睡觉，到处走",
    )

    def test_safety_critical_is_medical(self):
        missed = [text for text in self.MUST_BE_MEDICAL if not is_medical_question(text)]
        self.assertEqual(missed, [], "这些安全相关的话被当成日常了：\n" + "\n".join(missed))


class FalsePositiveTestCase(unittest.TestCase):
    """误判红线：这些是日常生活的话，不该被当成医疗问题。

    误判的代价是 AI 用健康顾问口吻回答家常话，还追一句"以医嘱为准"——
    老人只是在诉苦或者问助浴，这句免责显得没在听。
    """

    MUST_BE_DAILY = (
        # 单字"腿"误伤
        "我腿脚不方便，洗澡费劲，能有人上门帮忙吗",
        # 单字"病"误伤（其实是诈骗）
        "有人上门推销保健品，说能治百病",
        # 单字"牙"误伤
        "我牙口不好，硬的嚼不动",
        # 单字"麻"误伤
        "我一个人吃饭，做什么都嫌麻烦",
        # 情绪性的"难受"（在诉苦，不是身体不适）
        "儿媳妇老嫌我做得不好，我心里难受",
        # 预防心理的"怕摔"（要的是小夜灯，不是医疗建议）
        "我晚上起来上厕所老是摸黑，怕摔",
        # 日常
        "今天天气不错，我出去走了走",
        "我孙子昨天来看我了，还给我带了点心",
        "我儿子要接我去深圳，我不想去",
        "今天心情不太好，也说不上为啥",
    )

    def test_daily_chat_not_medical(self):
        wrong = [text for text in self.MUST_BE_DAILY if is_medical_question(text)]
        self.assertEqual(wrong, [], "这些日常话被当成医疗问题了：\n" + "\n".join(wrong))


class ScamAndMedicalMixedTestCase(unittest.TestCase):
    """诈骗场景里夹着真医疗问题时，仍要按医疗答。"""

    def test_scam_without_medical_question_is_daily(self):
        self.assertFalse(is_medical_question("有人打电话说我的社保卡有问题，要我把钱转到安全账户"))
        self.assertFalse(is_medical_question("有人上门推销保健品，说能治百病"))

    def test_scam_with_real_medical_question_is_medical(self):
        self.assertTrue(is_medical_question("推销的说能治百病，我这血压能吃吗"))
        self.assertTrue(is_medical_question("卖药的让我停药，我该听吗"))


class RoutineMedCheckTestCase(unittest.TestCase):
    """「药吃了没」是家属日常问一句，不是医疗判断。

    为了抓「我忘了今天药吃了没有」，关键词里加了"药吃"，
    结果把家属的日常问候也带进了医疗人设 ——
    实测 test_idempotency 里 "妈 药吃了没" 的回复被追加了
    「仅供参考，实际情况请以医嘱为准」。
    这种话后面跟免责，听起来像在敷衍。
    """

    def test_routine_check_is_daily(self):
        for text in ("妈 药吃了没", "药吃了没有啊", "吃药了么"):
            with self.subTest(text=text):
                self.assertFalse(is_medical_question(text))

    def test_forgetting_medication_is_still_medical(self):
        """「忘了吃药」是真的用药安全问题，不能一起放过"""
        for text in (
            "我忘了今天药吃了没有，要不要再吃一次",
            "一天要吃六种药，有时候就忘了吃",
            "我老是漏吃降压药",
        ):
            with self.subTest(text=text):
                self.assertTrue(is_medical_question(text))

    def test_routine_check_with_clinical_question_is_medical(self):
        """「药吃了没」后面接着问血压，仍按医疗"""
        self.assertTrue(is_medical_question("药吃了没，我今天血压又高了"))


if __name__ == "__main__":
    unittest.main()
