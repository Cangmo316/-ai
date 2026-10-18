"""对话历史压缩 + 频率分析 + 口头禅长期记忆 的测试。

对应需求原话：
  「自动压缩历史对话，超过阈值自动压缩，保留关键信息丢弃冗余，
   对话冗余的定义在于其中内容的出现频率为准，优先保留出现次数多的语句写进记忆，
   wiki 学习的部分也是出现频率较高的话题以及老人的表达习惯，
   因为人也是会变的，但有些口头禅需要保留，作为长期记忆」
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.history.compactor import (
    Turn,
    build_compress_messages,
    build_turns,
    clip_summary,
    parse_summary,
    should_compress,
    split_for_compress,
)
from app.history.frequency import count_phrases
from app.wiki.models import (
    MAX_ITEMS_PER_SECTION,
    PERSISTENT_SECTIONS,
    WIKI_ELDER,
    WIKI_PERSONA,
    WikiItem,
    WikiPage,
)
from app.wiki.updater import merge_facts


class FrequencyTestCase(unittest.TestCase):
    """冗余按"出现频率"判定 —— 反复说的才是常态。"""

    def test_repeated_phrase_is_found(self):
        turns = ["慢慢来 不着急", "慢慢来 我这人就这样", "你慢慢来 别催我"]
        phrases = count_phrases(turns)
        texts = [p.text for p in phrases]
        self.assertTrue(any("慢慢来" in t for t in texts), texts)
        top = next(p for p in phrases if "慢慢来" in p.text)
        self.assertEqual(top.turns, 3)

    def test_one_off_phrase_not_returned(self):
        """只说一次的算过场话，不该进高频列表"""
        turns = ["我昨天去了趟公园", "今天天气不错", "晚上吃面条"]
        phrases = count_phrases(turns)
        self.assertEqual(phrases, [])

    def test_phrase_in_single_turn_is_ignored(self):
        """同一句话里重复多次不算习惯（必须在多轮里出现）"""
        turns = ["哈哈哈哈 哈哈哈哈 哈哈哈哈"]
        self.assertEqual(count_phrases(turns), [])

    def test_long_phrase_suppresses_its_substring(self):
        """长串已命中时不再重复报它包含的短串"""
        turns = ["我血压高要吃药", "我血压高要注意", "我血压高"]
        phrases = count_phrases(turns, limit=10)
        texts = [p.text for p in phrases]
        # 应该有较长的命中，但不该同时列出它的所有子串
        self.assertLessEqual(len(texts), 3, texts)


class CompressTriggerTestCase(unittest.TestCase):
    def test_below_threshold_does_not_compress(self):
        self.assertFalse(should_compress(10, 48))
        self.assertFalse(should_compress(48, 48))

    def test_above_threshold_compresses(self):
        self.assertTrue(should_compress(49, 48))

    def test_split_keeps_recent(self):
        messages = list(range(100))
        old, recent = split_for_compress(messages, keep_recent=16)
        self.assertEqual(len(recent), 16)
        self.assertEqual(len(old), 84)
        # 保留的是**最近**的
        self.assertEqual(recent[-1], 99)

    def test_short_history_not_split(self):
        old, recent = split_for_compress(list(range(5)), keep_recent=16)
        self.assertEqual(old, [])
        self.assertEqual(len(recent), 5)


class TurnBuildingTestCase(unittest.TestCase):
    def _msg(self, role, text):
        class M:
            pass

        m = M()
        m.role = role
        m.text = text
        return m

    def test_pairs_are_built(self):
        msgs = [
            self._msg("elder", "我今天挺好的"),
            self._msg("agent", "那就好"),
            self._msg("elder", "我想吃面"),
        ]
        turns = build_turns(msgs)
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0].elder, "我今天挺好的")
        self.assertEqual(turns[0].agent, "那就好")
        # 最后一条只有老人说，agent 为空
        self.assertEqual(turns[1].agent, "")

    def test_empty_text_skipped(self):
        msgs = [self._msg("elder", ""), self._msg("agent", "  ")]
        self.assertEqual(build_turns(msgs), [])


class CompressPromptTestCase(unittest.TestCase):
    def test_prompt_includes_frequency(self):
        """压缩时的提示词必须带上频率统计 —— 那是"优先保留"的依据"""
        turns = [Turn(elder="慢慢来 不着急", agent="好"), Turn(elder="慢慢来 别急", agent="嗯")]
        messages = build_compress_messages(turns, previous_summary="")
        user_block = messages[-1]["content"]
        self.assertIn("反复出现的内容", user_block)
        self.assertIn("慢慢来", user_block)

    def test_prompt_carries_previous_summary(self):
        """旧摘要要带上，否则每压一次就把更早的记忆丢掉"""
        messages = build_compress_messages([Turn(elder="新的一句话", agent="好")], "旧的摘要内容")
        self.assertIn("旧的摘要内容", messages[-1]["content"])

    def test_prompt_asks_to_keep_one_off_facts(self):
        """一次性但重要的安排（时间/地点）也要留 —— 纯按频率会丢掉"""
        messages = build_compress_messages([Turn(elder="下周二去复查", agent="好")], "")
        self.assertIn("时间", messages[0]["content"])
        self.assertIn("即使只出现一次", messages[0]["content"])


class SummaryClipTestCase(unittest.TestCase):
    def test_short_summary_unchanged(self):
        self.assertEqual(clip_summary("· 他血压高", 100), "· 他血压高")

    def test_long_summary_keeps_tail(self):
        """"人也是会变的"：超长时保留**近期**内容"""
        body = "\n".join("· 第%d条旧事" % i for i in range(100))
        clipped = clip_summary(body, 200)
        self.assertLessEqual(len(clipped), 240)
        # 末尾的（近期的）应当留下
        self.assertIn("第99条旧事", clipped)

    def test_parse_strips_fence(self):
        raw = "```\n· 他七十三岁\n· 住北京\n```"
        out = parse_summary(raw)
        self.assertNotIn("```", out)
        self.assertIn("他七十三岁", out)


class PersistentSectionTestCase(unittest.TestCase):
    """口头禅是长期记忆，不该被近期内容挤掉（需求原话）。"""

    def test_catchphrase_section_is_marked_persistent(self):
        self.assertIn("口头禅", PERSISTENT_SECTIONS)

    def test_catchphrase_not_trimmed_when_full(self):
        page = WikiPage.empty(WIKI_PERSONA, "e_1")
        # 塞超过上限的口头禅。
        # 文本要**差异够大**，否则会被判重合并（那说明判重正常工作，不是本节要测的）。
        samples = [
            "哎呀我的天", "真是没辙", "你说是不是", "行了行了", "别忙活",
            "吃了吗", "慢慢来", "不急不急", "没事没事", "我瞅瞅",
            "你说呢", "哪儿的话", "成成成", "老样子", "得嘞",
            "就那样", "算了算了", "咋整", "咋办呢", "回头再说",
        ]
        for text in samples:
            merge_facts(page, {"口头禅": [text]})
        self.assertGreater(
            len(page.sections["口头禅"].items), MAX_ITEMS_PER_SECTION,
            "口头禅不该被裁剪（长期记忆）",
        )

    def test_volatile_section_still_trimmed(self):
        """易变的小节（近况）仍然按最近优先裁剪"""
        page = WikiPage.empty(WIKI_ELDER, "e_1")
        samples = [
            "去公园了", "买了苹果", "下雨没出门", "孙子来了", "看戏去了",
            "量了血压", "睡了个午觉", "修了水管", "晒了被子", "剪了头发",
            "逛了菜场", "换了灯泡", "擦了窗户", "听了广播", "扫了院子",
            "煮了粥", "晒了太阳", "收了快递", "洗了衣服", "浇了花",
        ]
        for text in samples:
            merge_facts(page, {"近况": [text]})
        self.assertLessEqual(len(page.sections["近况"].items), MAX_ITEMS_PER_SECTION)

    def test_repeated_item_moves_to_end(self):
        """反复提到的条目会移到末尾（等于刷新），裁剪时不会被丢掉"""
        page = WikiPage.empty(WIKI_ELDER, "e_1")
        merge_facts(page, {"近况": ["老张来看我了"]})
        merge_facts(page, {"近况": ["去公园了"]})
        # 再提一次旧的
        merge_facts(page, {"近况": ["老张来看我了"]})
        texts = [i.text for i in page.sections["近况"].items]
        self.assertEqual(texts[-1], "老张来看我了", "重复提到的应被刷新到末尾")
        self.assertEqual(len(texts), 2, "不该重复追加")


if __name__ == "__main__":
    unittest.main()
