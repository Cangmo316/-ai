"""LLM wiki 的测试。

核心要证明三件事：
  1. **合并而不是追加** —— 同一件事说五遍，wiki 里只有一条
  2. **按话题挑节** —— 不相关的小节不注入（否则等于整篇塞，白换方案）
  3. **不污染对话** —— wiki 读写失败绝不影响老人发消息
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.wiki.inject import build_injection
from app.wiki.models import (
    MAX_ITEMS_PER_SECTION,
    WIKI_ELDER,
    WIKI_PERSONA,
    WikiItem,
    WikiPage,
    parse_markdown,
)
from app.wiki.store import WikiStore
from app.wiki.updater import _parse_json, _too_similar, merge_facts


class WikiRoundTripTestCase(unittest.TestCase):
    def test_markdown_roundtrip_keeps_items(self):
        page = WikiPage.empty(WIKI_ELDER, "e_1")
        page.sections["饮食口味"].items.append(WikiItem(text="不爱吃甜的"))
        page.sections["身体状况"].items.append(WikiItem(text="高血压，每天吃氨氯地平"))

        text = page.to_markdown()
        back = parse_markdown(WIKI_ELDER, "e_1", text)

        self.assertEqual(len(back.sections["饮食口味"].items), 1)
        self.assertEqual(back.sections["饮食口味"].items[0].text, "不爱吃甜的")
        self.assertEqual(len(back.sections["身体状况"].items), 1)

    def test_unknown_heading_is_ignored(self):
        """LLM 自创标题不能污染文档结构"""
        text = "# 老人画像\n\n## 基本情况\n- 七十岁\n\n## 我自己编的标题\n- 这条不该进来\n"
        page = parse_markdown(WIKI_ELDER, "e_1", text)
        self.assertNotIn("我自己编的标题", page.sections)
        self.assertEqual(len(page.sections["基本情况"].items), 1)

    def test_human_edited_multiline_item_is_joined(self):
        """人工编辑容易把一条写成两行，应合并成一条而不是丢"""
        text = "## 身体状况\n- 高血压\n  每天吃氨氯地平\n"
        page = parse_markdown(WIKI_ELDER, "e_1", text)
        self.assertEqual(len(page.sections["身体状况"].items), 1)
        self.assertIn("氨氯地平", page.sections["身体状况"].items[0].text)


class MergeTestCase(unittest.TestCase):
    """合并是 wiki 不膨胀的关键 —— 这是"越聊越像"而不是"越聊越乱"的分界。"""

    def setUp(self):
        self.page = WikiPage.empty(WIKI_ELDER, "e_1")

    def test_new_facts_are_added(self):
        added = merge_facts(self.page, {"饮食口味": ["不爱吃甜的"]})
        self.assertEqual(added, 1)
        self.assertEqual(len(self.page.sections["饮食口味"].items), 1)

    def test_same_fact_twice_only_stored_once(self):
        """同一件事说五遍，wiki 里只有一条 —— 核心断言"""
        for _ in range(5):
            merge_facts(self.page, {"饮食口味": ["不爱吃甜的"]})
        self.assertEqual(len(self.page.sections["饮食口味"].items), 1)

    def test_similar_but_different_fact_is_kept(self):
        """「爱听戏」与「爱听京剧」保留两条。

        ⚠️ 这里刻意**不合并**。最初阈值设得松（0.66），
        结果把「叫老人妈」和「叫老人爸」、「不爱吃甜」和「不爱吃辣」
        也合并了 —— 直接丢信息。漏合并只是多一条，过度合并会丢东西，
        所以判重宁可保守。
        """
        merge_facts(self.page, {"兴趣爱好": ["爱听戏"]})
        added = merge_facts(self.page, {"兴趣爱好": ["爱听京剧"]})
        self.assertEqual(added, 1)
        self.assertEqual(len(self.page.sections["兴趣爱好"].items), 2)

    def test_detail_extension_merges_into_one(self):
        """同一件事补充细节时应该合并（子串判定）"""
        merge_facts(self.page, {"身体状况": ["高血压"]})
        added = merge_facts(self.page, {"身体状况": ["高血压，每天吃氨氯地平"]})
        self.assertEqual(added, 0)
        self.assertEqual(len(self.page.sections["身体状况"].items), 1)

    def test_opposite_facts_not_merged(self):
        """「叫老人妈」与「叫老人爸」必须分开 —— 这是不同事实，不能吞"""
        persona_page = WikiPage.empty(WIKI_PERSONA, "e_1")
        merge_facts(persona_page, {"称呼习惯": ["叫老人妈"]})
        added = merge_facts(persona_page, {"称呼习惯": ["叫老人爸"]})
        self.assertEqual(added, 1)
        self.assertEqual(len(persona_page.sections["称呼习惯"].items), 2)

    def test_unknown_section_rejected(self):
        """只接受预定义小节，防止 LLM 把文档写散"""
        added = merge_facts(self.page, {"瞎编的节": ["不该进来"]})
        self.assertEqual(added, 0)
        self.assertNotIn("瞎编的节", self.page.sections)

    def test_too_short_ignored(self):
        """「嗯」「好」这种没有信息量"""
        added = merge_facts(self.page, {"近况": ["嗯", "好"]})
        self.assertEqual(added, 0)

    def test_section_is_capped(self):
        """每节封顶，超了丢最旧的 —— 否则聊三个月会堆成一屏"""
        for i in range(MAX_ITEMS_PER_SECTION + 5):
            merge_facts(self.page, {"近况": ["第%d件事%s" % (i, "x" * i)]})
        self.assertLessEqual(
            len(self.page.sections["近况"].items), MAX_ITEMS_PER_SECTION
        )

    def test_kind_routes_to_right_sections(self):
        """老人画像的节不能被写进说话风格页"""
        persona_page = WikiPage.empty(WIKI_PERSONA, "e_1")
        added = merge_facts(persona_page, {"饮食口味": ["不爱吃甜的"]})
        self.assertEqual(added, 0)


class InjectionTestCase(unittest.TestCase):
    """注入要按话题挑，不能整篇塞 —— 否则等于没换方案。"""

    def setUp(self):
        self.elder = WikiPage.empty(WIKI_ELDER, "e_1")
        self.elder.sections["基本情况"].items.append(WikiItem(text="七十岁，住北京"))
        self.elder.sections["饮食口味"].items.append(WikiItem(text="不爱吃甜的"))
        self.elder.sections["兴趣爱好"].items.append(WikiItem(text="爱听京剧"))

        self.persona = WikiPage.empty(WIKI_PERSONA, "e_1")
        self.persona.sections["称呼习惯"].items.append(WikiItem(text="叫老人妈"))
        self.persona.sections["口头禅"].items.append(WikiItem(text="吃了没"))

    def pages(self):
        return {WIKI_ELDER: self.elder, WIKI_PERSONA: self.persona}

    def test_baseline_sections_always_included(self):
        """基本情况 / 称呼习惯是基本盘，任何话题都带上"""
        shot = build_injection(self.pages(), "今天天气不错")
        joined = "\n".join(shot.elder_lines)
        self.assertIn("七十岁", joined)
        joined_p = "\n".join(shot.persona_lines)
        self.assertIn("叫老人妈", joined_p)

    def test_topic_pulls_matching_section(self):
        """问吃的，饮食口味要进来"""
        shot = build_injection(self.pages(), "我最近想吃点甜的")
        self.assertIn("不爱吃甜的", "\n".join(shot.elder_lines))

    def test_unrelated_section_not_injected(self):
        """问天气，兴趣爱好不该被塞进来"""
        shot = build_injection(self.pages(), "今天有点冷")
        self.assertNotIn("爱听京剧", "\n".join(shot.elder_lines))

    def test_empty_wiki_yields_nothing(self):
        empty = {WIKI_ELDER: WikiPage.empty(WIKI_ELDER, "e_1"), WIKI_PERSONA: WikiPage.empty(WIKI_PERSONA, "e_1")}
        shot = build_injection(empty, "随便说点啥")
        self.assertTrue(shot.is_empty())


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = WikiStore(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_and_load(self):
        page = WikiPage.empty(WIKI_ELDER, "e_1")
        page.sections["饮食口味"].items.append(WikiItem(text="不吃辣"))
        self.assertTrue(self.store.save(page))

        loaded = self.store.load("e_1", WIKI_ELDER, use_cache=False)
        self.assertEqual(len(loaded.sections["饮食口味"].items), 1)
        self.assertEqual(loaded.sections["饮食口味"].items[0].text, "不吃辣")

    def test_missing_file_returns_empty_page(self):
        """读不到不是错误，是"还没记过东西" """
        page = self.store.load("e_never", WIKI_ELDER)
        self.assertTrue(page.is_empty())

    def test_isolation_between_elders(self):
        mine = WikiPage.empty(WIKI_ELDER, "e_1")
        mine.sections["近况"].items.append(WikiItem(text="我的一条"))
        self.store.save(mine)

        other = self.store.load("e_2", WIKI_ELDER)
        self.assertTrue(other.is_empty())

    def test_elder_id_path_traversal_is_sanitized(self):
        """老人 id 拼进路径前必须清洗，不能穿越目录"""
        path = self.store.path_of("../../etc", WIKI_ELDER)
        self.assertNotIn("..", str(path))


class ParseJsonTestCase(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(_parse_json('{"elder":{"近况":["来了"]}}')["elder"]["近况"], ["来了"])

    def test_fenced_json(self):
        raw = '```json\n{"elder":{},"persona":{}}\n```'
        self.assertEqual(_parse_json(raw), {"elder": {}, "persona": {}})

    def test_garbage_returns_empty(self):
        self.assertEqual(_parse_json("我不知道该怎么记"), {})
        self.assertEqual(_parse_json(""), {})


class BatchLearningTestCase(unittest.TestCase):
    """"攒 N 轮学一次"的行为。

    为什么不是每轮学：每轮学要额外一次模型调用（成本翻倍），
    而单轮增量信息很少 —— 效果差别不大、钱差一倍。
    攒 5 轮一起学，一次给模型 5 轮上下文，质量反而更好。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = WikiStore(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_n_turns_trigger_one_call(self):
        import asyncio

        class FakeProvider:
            def __init__(self):
                self.calls = 0
                self.batch_sizes = []

            async def stream(self, messages, **kwargs):
                self.calls += 1
                self.batch_sizes.append(messages[-1]["content"].count("老人说："))
                yield '{"elder":{},"persona":{}}'

        from app.wiki import WikiService

        async def run():
            svc = WikiService(self.store, learn_every=5)
            provider = FakeProvider()
            for i in range(1, 11):
                svc.collect_turn("e_1", "第%d句有点内容的话" % i, "好的", provider)
                await asyncio.sleep(0)
            await svc.drain()
            return provider

        provider = asyncio.run(run())
        # 10 轮 / 5 = 2 次调用（不是 10 次）
        self.assertEqual(provider.calls, 2)
        # 每次都是攒满 5 轮一起学（不是只学最后一轮）
        self.assertEqual(provider.batch_sizes, [5, 5])

    def test_every_turn_mode_still_available(self):
        """learn_every=1 时回到"每轮都学"的老行为"""
        import asyncio

        class FakeProvider:
            def __init__(self):
                self.calls = 0

            async def stream(self, messages, **kwargs):
                self.calls += 1
                yield '{"elder":{},"persona":{}}'

        from app.wiki import WikiService

        async def run():
            svc = WikiService(self.store, learn_every=1)
            provider = FakeProvider()
            for i in range(3):
                svc.collect_turn("e_2", "第%d句话在这里" % i, "好的", provider)
                await asyncio.sleep(0)
            await svc.drain()
            return provider

        self.assertEqual(asyncio.run(run()).calls, 3)

    def test_pending_counts_up_then_resets(self):
        import asyncio

        class FakeProvider:
            async def stream(self, messages, **kwargs):
                yield '{"elder":{},"persona":{}}'

        from app.wiki import WikiService

        async def run():
            svc = WikiService(self.store, learn_every=3)
            provider = FakeProvider()
            counts = []
            for i in range(4):
                svc.collect_turn("e_3", "第%d句有内容的话" % i, "好的", provider)
                await asyncio.sleep(0)
                counts.append(svc.pending_count("e_3"))
            await svc.drain()
            return counts

        counts = asyncio.run(run())
        self.assertEqual(counts[:2], [1, 2])   # 攒着
        self.assertEqual(counts[2], 0)         # 第 3 轮触发后清空


if __name__ == "__main__":
    unittest.main()
