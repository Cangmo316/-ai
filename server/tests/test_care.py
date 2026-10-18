"""主动关心 + 到期回访 的测试。

对应需求原话：
  「智能体需要有人的好奇心，在一些时候需要问老人一些日程的问题，
   比如吃了什么，有没有遇到特别的事，有没有什么想做的事，每天要主动问1-2次，
   这些要记录下来，在后续的标记日期里再次提出来，
   让老人真正认为智能体是在乎他的」
"""

from __future__ import annotations

import random
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from app.care import (
    CareService,
    CareStore,
    FOLLOWUP_DONE,
    MAX_PER_DAY,
    parse_when,
    pick_question,
    topic_label,
)
from app.care.dates import human_day, is_future


class DateParseTestCase(unittest.TestCase):
    """中文相对日期：说得出"下周二"就要算得出是哪天。"""

    def setUp(self):
        # 2026-10-08 是周四
        self.today = date(2026, 10, 8)

    def test_relative_words(self):
        self.assertEqual(parse_when("明天去复查", self.today).day, date(2026, 10, 9))
        self.assertEqual(parse_when("后天闺女来", self.today).day, date(2026, 10, 10))
        self.assertEqual(parse_when("今天有点累", self.today).day, date(2026, 10, 8))

    def test_next_week_weekday(self):
        """下周二 = 10/13（本周一是 10/5，下周一 10/12）"""
        parsed = parse_when("下周二去医院", self.today)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.day, date(2026, 10, 13))
        self.assertEqual(parsed.day.weekday(), 1)

    def test_bare_weekday_means_upcoming(self):
        """只说"周三"：今天是周四，周三已过 → 下周三"""
        parsed = parse_when("周三去拿药", self.today)
        self.assertIsNotNone(parsed)
        self.assertGreaterEqual(parsed.day, self.today)
        self.assertEqual(parsed.day.weekday(), 2)

    def test_month_day(self):
        parsed = parse_when("10月20号去体检", self.today)
        self.assertEqual(parsed.day, date(2026, 10, 20))

    def test_days_later(self):
        self.assertEqual(parse_when("三天后再说", self.today).day, date(2026, 10, 11))

    def test_garbage_returns_none(self):
        """解析不出就是 None —— 宁可不提，也不要在错的日子提错的事"""
        self.assertIsNone(parse_when("我心情不好", self.today))
        self.assertIsNone(parse_when("", self.today))

    def test_today_is_parsed_but_not_a_commitment(self):
        """"今天"本身是合法日期，但**不算将来的约定**（见 FollowUpTestCase）"""
        self.assertEqual(parse_when("我今天心情不好", self.today).day, self.today)

    def test_is_future(self):
        self.assertTrue(is_future(parse_when("明天", self.today), self.today))
        self.assertFalse(is_future(parse_when("昨天去的", self.today), self.today))

    def test_human_day(self):
        self.assertEqual(human_day(date(2026, 10, 8), self.today), "今天")
        self.assertEqual(human_day(date(2026, 10, 9), self.today), "明天")
        self.assertEqual(human_day(date(2026, 10, 13), self.today), "周二")


class QuestionPickTestCase(unittest.TestCase):
    """问题不能天天一样，也不能时间对不上。"""

    def test_morning_asks_about_breakfast(self):
        topic, text = pick_question(7, rng=random.Random(1))
        self.assertTrue(text)
        self.assertIn(topic, ("eat", "day", "event"))

    def test_evening_does_not_ask_about_breakfast(self):
        """下午三点问"早饭吃了吗"像机器人"""
        _, text = pick_question(15, rng=random.Random(2))
        self.assertNotIn("早上", text)
        self.assertNotIn("早饭", text)

    def test_avoid_repeating_last_topic(self):
        """刚问完"吃了啥"紧接着又问"吃了啥"，一眼就是机器"""
        last = ""
        for seed in range(30):
            topic, _ = pick_question(12, last_topic=last, rng=random.Random(seed))
            if last and topic:
                self.assertNotEqual(topic, last, "不应连续两次问同一类")
            last = topic

    def test_all_topics_have_labels(self):
        for topic in ("eat", "event", "day", "wish"):
            self.assertTrue(topic_label(topic))


class CareFrequencyTestCase(unittest.TestCase):
    """一天 1-2 次，不多不少。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CareStore(Path(self.tmp.name))
        self.now = datetime(2026, 10, 8, 9, 0).astimezone()
        self.svc = CareService(self.store, clock=lambda: self.now)

    def tearDown(self):
        self.tmp.cleanup()

    def test_asks_at_daytime(self):
        ask = self.svc.ask_now("e_1", rng=random.Random(0))
        self.assertIsNotNone(ask)
        self.assertEqual(self.svc.asked_today("e_1"), 1)

    def test_not_at_night(self):
        """深夜推送会吓着人"""
        self.now = datetime(2026, 10, 8, 23, 30).astimezone()
        svc = CareService(self.store, clock=lambda: self.now)
        self.assertIsNone(svc.ask_now("e_1"))

    def test_gap_between_asks(self):
        self.svc.ask_now("e_1")
        # 立刻再问：被间隔拦住
        self.assertIsNone(self.svc.ask_now("e_1"))
        ok, reason = self.svc.should_ask("e_1")
        self.assertFalse(ok)
        self.assertIn("分钟", reason)

    def test_max_two_per_day(self):
        """答了之后能问到第 2 次，但不会到第 3 次"""
        for hour in (9, 14, 19):
            self.now = datetime(2026, 10, 8, hour, 0).astimezone()
            svc = CareService(self.store, clock=lambda: self.now)
            svc.ask_now("e_1")
            # 每次问完都模拟老人回话（否则"没答就不追问"会拦住后续提问）
            svc.record_answer("e_1", "刚吃过饭")
        self.assertEqual(self.svc.asked_today("e_1"), MAX_PER_DAY)

    def test_delivery_failure_does_not_block_later_asks(self):
        """投递失败不该占掉当天名额。

        踩过的坑：提问先生成并记账，然后才发现"还没有会话可以投递"，
        结果这条没送出去的提问把下一次堵死了（should_ask 认为"上次问了还没答"）。
        修法是 preview_ask / commit_ask 拆开，只有投递成功才记账。
        """
        preview = self.svc.preview_ask("e_1")
        self.assertIsNotNone(preview)
        # 只预览、没 commit（等于投递失败了）
        self.assertEqual(self.svc.asked_today("e_1"), 0)
        ok, _reason = self.svc.should_ask("e_1")
        self.assertTrue(ok, "投递失败后应当还能再问")

    def test_unanswered_ask_not_repeated_same_day(self):
        """上次问了没答，不要紧跟着追问"""
        self.svc.ask_now("e_1")
        self.now = datetime(2026, 10, 8, 15, 0).astimezone()
        svc = CareService(self.store, clock=lambda: self.now)
        ok, reason = svc.should_ask("e_1")
        self.assertFalse(ok)
        self.assertIn("还没答", reason)

    def test_quiet_after_chat(self):
        """他正在聊，突然插一句"吃了吗"很怪"""
        self.svc.note_chat("e_1")
        ok, reason = self.svc.should_ask("e_1")
        self.assertFalse(ok)
        self.assertIn("刚聊过", reason)

    def test_answer_recorded(self):
        self.svc.ask_now("e_1")
        self.now = datetime(2026, 10, 8, 9, 10).astimezone()
        ask = self.svc.record_answer("e_1", "我吃的面条")
        self.assertIsNotNone(ask)
        self.assertEqual(ask.answer, "我吃的面条")


class FollowUpTestCase(unittest.TestCase):
    """需求核心：「在后续的标记日期里再次提出来」。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CareStore(Path(self.tmp.name))
        self.today = date(2026, 10, 8)
        self.now = datetime(2026, 10, 8, 10, 0).astimezone()
        self.svc = CareService(self.store, clock=lambda: self.now)

    def tearDown(self):
        self.tmp.cleanup()

    def test_future_commitment_is_recorded(self):
        item = self.svc.add_followup_if_any("e_1", "下周二去医院复查")
        self.assertIsNotNone(item)
        self.assertEqual(item.due_day, "2026-10-13")
        self.assertIn("复查", item.text)

    def test_past_event_not_recorded(self):
        """说"昨天去医院了"没有"到期"可言"""
        self.assertIsNone(self.svc.add_followup_if_any("e_1", "昨天去医院了"))

    def test_no_date_not_recorded(self):
        self.assertIsNone(self.svc.add_followup_if_any("e_1", "我心情不错"))

    def test_today_not_recorded(self):
        """踩过的坑：老人说"我今天心情不好"，因为含"今天"被记成回访，
        第二天就去问"您今天心情不好那事怎么样了" —— 纯噪音。
        当天的事由主动提问覆盖，不需要回访。
        """
        self.assertIsNone(self.svc.add_followup_if_any("e_1", "我今天心情不好"))

    def test_duplicate_not_recorded_twice(self):
        self.svc.add_followup_if_any("e_1", "下周二去医院复查")
        self.svc.add_followup_if_any("e_1", "下周二去医院复查")
        self.assertEqual(len(self.svc.store.followups("e_1")), 1)

    def test_not_due_yet(self):
        self.svc.add_followup_if_any("e_1", "下周二去医院复查")
        self.assertEqual(self.svc.due_followups("e_1"), [])

    def test_due_on_the_day(self):
        self.svc.add_followup_if_any("e_1", "下周二去医院复查")
        self.now = datetime(2026, 10, 13, 9, 0).astimezone()
        svc = CareService(self.store, clock=lambda: self.now)
        due = svc.due_followups("e_1")
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0].due_day, "2026-10-13")

    def test_overdue_still_surfaces_briefly(self):
        """过了那天一两天还要提（老人可能那天没开 App），但措辞要改"""
        self.svc.add_followup_if_any("e_1", "下周二去医院复查")
        self.now = datetime(2026, 10, 14, 9, 0).astimezone()   # 过期 1 天
        svc = CareService(self.store, clock=lambda: self.now)
        lines = svc.followup_lines("e_1")
        self.assertEqual(len(lines), 1)
        self.assertIn("昨天", lines[0])
        self.assertNotIn("今天正是这日子", lines[0])

    def test_stale_followup_dropped(self):
        """过期太久的回访不再提 —— 三天后再问"闺女来了吗"已经没意义。

        踩过一次：10/9 说"明天闺女来"，10/13 还在问。
        """
        self.svc.add_followup_if_any("e_1", "下周二去医院复查")
        self.now = datetime(2026, 10, 16, 9, 0).astimezone()   # 过期 3 天
        svc = CareService(self.store, clock=lambda: self.now)
        self.assertEqual(svc.due_followups("e_1"), [])
        self.assertEqual(svc.followup_lines("e_1"), [])

    def test_prompt_lines_are_human(self):
        """注入 prompt 的要是人话，不是数据"""
        self.svc.add_followup_if_any("e_1", "下周二去医院复查")
        self.now = datetime(2026, 10, 13, 9, 0).astimezone()
        svc = CareService(self.store, clock=lambda: self.now)
        lines = svc.followup_lines("e_1")
        self.assertEqual(len(lines), 1)
        self.assertIn("今天正是这日子", lines[0])
        # 引用整句话（不是只引用"下周二"这个日期片段）
        self.assertIn("复查", lines[0])
        # 要求它"问一句就够"，别变成催办
        self.assertIn("别追问", lines[0])

    def test_done_not_repeated(self):
        """提过一次就不再提 —— 反复问同一件事会变成催命"""
        item = self.svc.add_followup_if_any("e_1", "下周二去医院复查")
        self.now = datetime(2026, 10, 13, 9, 0).astimezone()
        svc = CareService(self.store, clock=lambda: self.now)
        self.assertTrue(svc.mark_followup_done("e_1", item.id))
        self.assertEqual(svc.due_followups("e_1"), [])
        self.assertEqual(svc.followup_lines("e_1"), [])


class CareSnapshotTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.svc = CareService(CareStore(Path(self.tmp.name)))

    def tearDown(self):
        self.tmp.cleanup()

    def test_snapshot_shape(self):
        data = self.svc.snapshot("e_1")
        for key in ("todayAsks", "maxPerDay", "dueFollowups", "recentAsks"):
            self.assertIn(key, data)


if __name__ == "__main__":
    unittest.main()
