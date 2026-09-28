"""
「句末不加句号」规则单测（设计方案 §3.1 三层保险之三）

设计要求：**≥30 条边界用例（含混排、数字、缩写、多句）**。

另外三条不变量对所有用例成立，单独用 property 用例守：
    - 全角句号「。」永远不该出现在输出里（它必然是句末）
    - 输出首尾无空白
    - 逐字喂入（流式）与整段喂入（一次性）结果逐字一致
"""

from __future__ import annotations

import unittest

from app.style.punctuation import StyleStreamer, apply_style

# (输入, 期望输出, 说明)
CASES: list[tuple[str, str, str]] = [
    # ── 基本：末尾句号去掉 ───────────────────────────────
    ("妈 药吃了没。", "妈 药吃了没", "单句末尾全角句号"),
    ("妈 药吃了没.", "妈 药吃了没", "单句末尾半角点"),
    ("挺好的。", "挺好的", "短句"),
    ("嗯。", "嗯", "极短句"),
    ("100。", "100", "纯数字结尾"),
    ("。开头没有内容", "开头没有内容", "开头的句号被丢弃"),
    ("。", "", "只有一个句号"),
    ("", "", "空串"),
    ("   ", "", "只有空白"),

    # ── 多句：句号替换为换行 ─────────────────────────────
    ("妈 药吃了没。吃完喝口热水", "妈 药吃了没\n吃完喝口热水", "两句"),
    ("妈。药。吃。了。没", "妈\n药\n吃\n了\n没", "五个短句"),
    ("妈 血压 130.5 有点高。少放盐。", "妈 血压 130.5 有点高\n少放盐", "多句混合小数"),
    ("好。好。", "好\n好", "重复短句，末尾换行不留"),
    ("。。", "", "连续句号不产生空行"),
    ("妈 你好\n\n再聊", "妈 你好\n再聊", "空行折叠"),
    ("妈 你好\n\n\n再聊", "妈 你好\n再聊", "多个空行折叠"),
    ("\n妈 好", "妈 好", "行首换行丢弃"),
    ("妈 好。  ", "妈 好", "句号后的尾随空格不留空行"),

    # ── 小数保护：/(\d)\.(\d)/ ──────────────────────────
    ("吃2.5mg就行。", "吃2.5mg就行", "小数 + 单位"),
    ("剂量是 2.5 mg。", "剂量是 2.5 mg", "小数后有空格"),
    ("血压 120.5 还行。", "血压 120.5 还行", "三位整数 + 一位小数"),
    ("一共 3.14 元。", "一共 3.14 元", "圆周率"),
    ("1.2.3 版本。", "1.2.3 版本", "多段数字（版本号）"),
    ("第1.2条。", "第1.2条", "条文编号"),
    ("3.5mg。", "3.5mg", "小数紧邻句号"),

    # ── 缩写保护 ────────────────────────────────────────
    ("No.3 那个。", "No.3 那个", "No. + 数字"),
    ("Mr. Wang 来了。", "Mr. Wang 来了", "Mr."),
    ("kg. 是单位。", "kg. 是单位", "单位缩写"),
    ("e.g. 这样。", "e.g. 这样", "e.g."),
    ("U.S. 那边。", "U.S. 那边", "单字母首字母缩写"),
    ("a.", "a", "单字母 + 末尾点：当句末处理"),
    ("等一会儿 Dr. 李。", "等一会儿 Dr. 李", "Dr. 混排"),

    # ── 省略号保留 ──────────────────────────────────────
    ("等一会儿…", "等一会儿…", "全角省略号"),
    ("我想想...", "我想想...", "半角三点省略号"),
    ("嗯…再说。", "嗯…再说", "省略号 + 句末句号"),
    ("这个嘛…。", "这个嘛…", "省略号后跟句号"),

    # ── 其他标点不受影响 ────────────────────────────────
    ("药吃了没？", "药吃了没？", "问号保留"),
    ("好！！！", "好！！！", "感叹号保留"),
    ("妈 你在家吗？我一会儿回去。", "妈 你在家吗？我一会儿回去", "问号 + 句末句号"),
    ("白菜、萝卜都买了。", "白菜、萝卜都买了", "顿号保留"),

    # ── 混排与边界 ──────────────────────────────────────
    ("妈 今天降温了。秋裤穿上没。别冻着", "妈 今天降温了\n秋裤穿上没\n别冻着", "三句混排"),
    ("吃2.5mg。别忘了。", "吃2.5mg\n别忘了", "小数 + 多句"),
    ("  妈  好  ", "妈  好", "内部空格保留，首尾去掉"),
    ("妈\n好。", "妈\n好", "显式换行 + 末尾句号"),

    # ── characterization：已知取舍（要改就得是有意识的改）────
    ("abc.def", "abc\ndef", "字母间的点按句末处理（不识别域名）"),
    ("www.baidu.com", "www\nbaidu\ncom", "网址会被拆行（prompt 已禁止输出网址）"),
    ("1. 第一件事", "1\n第一件事", "序号点按句末处理"),
]


class StyleCaseTests(unittest.TestCase):
    def test_cases(self) -> None:
        for source, expected, note in CASES:
            with self.subTest(note=note, source=source):
                self.assertEqual(apply_style(source), expected, f"{note}：{source!r}")

    def test_case_count_meets_requirement(self) -> None:
        """设计方案要求 ≥30 条边界用例。"""
        self.assertGreaterEqual(len(CASES), 30)

    def test_no_full_width_stop_survives(self) -> None:
        """不变量：全角句号必然是句末，输出里不该再有它。"""
        for source, _expected, _note in CASES:
            with self.subTest(source=source):
                self.assertNotIn("。", apply_style(source))

    def test_output_is_stripped(self) -> None:
        for source, _expected, _note in CASES:
            with self.subTest(source=source):
                result = apply_style(source)
                self.assertEqual(result, result.strip())


class StyleStreamingTests(unittest.TestCase):
    """流式路径必须与一次性路径逐字一致，否则会出现「打字时一个样、降级后另一个样」。"""

    def _stream(self, text: str, chunk_size: int) -> str:
        streamer = StyleStreamer()
        out = []
        for index in range(0, len(text), chunk_size):
            out.append(streamer.feed(text[index : index + chunk_size]))
        out.append(streamer.flush())
        return "".join(out)

    def test_stream_matches_batch_char_by_char(self) -> None:
        for source, expected, note in CASES:
            with self.subTest(note=note):
                self.assertEqual(self._stream(source, 1), expected)

    def test_stream_matches_batch_three_chars(self) -> None:
        for source, expected, note in CASES:
            with self.subTest(note=note):
                self.assertEqual(self._stream(source, 3), expected)

    def test_decimal_split_across_chunks(self) -> None:
        """「2.5」被切成三片时不能拆行——这是流式后处理存在的唯一理由。"""
        self.assertEqual(self._stream("吃2.5mg。", 1), "吃2.5mg")
        self.assertEqual(self._stream("吃2.5mg。", 2), "吃2.5mg")

    def test_ellipsis_split_across_chunks(self) -> None:
        self.assertEqual(self._stream("我想想...", 1), "我想想...")
        self.assertEqual(self._stream("我想想...", 2), "我想想...")

    def test_no_text_is_released_before_flush_for_trailing_stop(self) -> None:
        """末尾句号要等到 flush 才被丢弃，中途不能提前吐出换行。"""
        streamer = StyleStreamer()
        emitted = streamer.feed("妈 好。")
        self.assertEqual(emitted, "妈 好")
        self.assertEqual(streamer.flush(), "")


if __name__ == "__main__":
    unittest.main()
