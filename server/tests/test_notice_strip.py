"""日常轮「多余免责」剥离的测试。

## 这条为什么必须有测试

`strip_medical_notice` 是**减法**：剥错了就是把该说的话删掉，
比多留一句免责危险得多。最怕两种情况：
  · 把"我不想活了 → 找医生看看"剥掉（削掉自伤提示）
  · 把整条回复剥成空白

所以这里把这几条边界全部钉住。
"""

from __future__ import annotations

import unittest

from app.persona.prompts import (
    MEDICAL_NOTICE,
    ensure_medical_notice,
    strip_medical_notice,
)


class StripDailyNoticeTestCase(unittest.TestCase):
    def test_strips_trailing_doctor_clause(self):
        """日常闲聊结尾多一句"还是听医生的" → 剥掉。"""
        reply = "会视频了啊 就是麻烦吧\n别一个人瞎琢磨 还是听医生的"
        out = strip_medical_notice(reply, False, "我新学了个手机功能，会视频了")
        self.assertNotIn("听医生的", out)
        self.assertIn("会视频了啊", out)

    def test_strips_full_notice_line(self):
        """整行是免责声明 → 整行删。"""
        reply = "养老院有人伺候 省得收拾屋子\n我陪您一块儿想\n\n" + MEDICAL_NOTICE
        out = strip_medical_notice(reply, False, "养老院和在家请人，哪个更合适")
        self.assertNotIn("仅供参考", out)
        self.assertIn("养老院有人伺候", out)

    def test_keeps_useful_advice_on_same_line(self):
        """一行里混着有用建议和免责 → 只去掉免责那几段。"""
        reply = "钱的事儿得找政府热线 或者税务局\n" + MEDICAL_NOTICE
        out = strip_medical_notice(reply, False, "收到短信说中奖了，让我点链接")
        self.assertNotIn("以医嘱为准", out)
        self.assertIn("政府热线", out)

    def test_never_returns_empty(self):
        """剥完如果是空的，必须还原 —— 不能给老人一条空白回复。"""
        reply = MEDICAL_NOTICE
        out = strip_medical_notice(reply, False, "今天天气不错")
        self.assertTrue(out.strip())


class KeepNoticeTestCase(unittest.TestCase):
    """这些情况**绝不能剥** —— 剥了就是削掉安全提示。"""

    def test_self_harm_keeps_doctor_advice(self):
        reply = "这话我可不敢说\n要是觉得活不下去 就找医生看看 我陪您去"
        out = strip_medical_notice(reply, False, "我不想活了")
        self.assertIn("医生", out)

    def test_cognitive_signal_keeps_doctor_advice(self):
        reply = "找不着东西别着急\n要是老这样 就跟医生说说"
        out = strip_medical_notice(reply, False, "我老是找不到东西，钥匙不知道放哪了")
        self.assertIn("医生", out)

    def test_fall_keeps_doctor_advice(self):
        reply = "先坐下别动\n赶紧给子女打电话 让他们回来陪您去医院"
        out = strip_medical_notice(reply, False, "我在厕所摔了一跤，现在能站起来")
        self.assertIn("医院", out)

    def test_medical_turn_keeps_notice(self):
        reply = "血糖高的人 一天半斤就行 还是听医生的"
        out = strip_medical_notice(reply, True, "我有糖尿病，能吃西瓜吗")
        self.assertIn("医生", out)

    def test_clinical_content_keeps_notice(self):
        """回复里出现临床口径（血压/血糖）→ 该带免责，不剥。"""
        reply = "您血压高 少吃点咸的"
        out = strip_medical_notice(reply, False, "我想吃点甜的")
        self.assertEqual(out, reply)


class RoundTripTestCase(unittest.TestCase):
    """ensure 补上、strip 剥掉，两者判定要对称。"""

    def test_ensure_then_strip_is_noop_for_medical(self):
        reply = "血糖高的人 一天半斤就行"
        text = "我有糖尿病，能吃西瓜吗"
        ensured = ensure_medical_notice(reply, True, text)
        self.assertIn("以医嘱为准", ensured)
        self.assertEqual(strip_medical_notice(ensured, True, text), ensured)

    def test_email_daily_roundtrip_removes_what_ensure_added(self):
        reply = "别忘了关火"
        text = "我出门了"
        ensured = ensure_medical_notice(reply, False, text)
        # 日常话不该被补
        self.assertEqual(ensured, reply)
        self.assertEqual(strip_medical_notice(ensured, False, text), reply)


if __name__ == "__main__":
    unittest.main()
