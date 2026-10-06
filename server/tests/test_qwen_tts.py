"""百炼 Qwen-Audio-TTS Provider 的单元测试（不联网、不需要真实 key）。

重点守住三件事：
1. **事件解析**：`payload.output.sentence.words[]` 的解析要能在几种形状下都работа，
   拿不到时**明确返回空**（上层据此降级），不许伪造时间戳；
2. **单位换算**：百炼给的是**毫秒**且键名是 `begin_time/end_time`，
   而 `from_alignment` 认的是 WhisperX 形状（秒 + `start/end`）—— 转换必须正确；
3. **装配优先级**：`BILIN_TTS_PROVIDER=qwen` 要能覆盖 URL/CMD 两条路。

跑法：`cd server; .\\.venv\\Scripts\\python.exe -m unittest tests.test_qwen_tts -v`
"""

from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.avatar.visemes import from_alignment  # noqa: E402
from app.voice import gateway  # noqa: E402
from app.voice.qwen_tts import (  # noqa: E402
    DEFAULT_MODEL,
    DEFAULT_VOICE,
    QwenTtsProvider,
    _extract_words_from_event,
    build_qwen_provider,
    sdk_available,
    words_to_segments,
)


def event(payload_output: dict) -> str:
    """照阿里云文档的事件形状造一个 on_event 消息。"""
    return json.dumps({"header": {"event": "result-generated"},
                       "payload": {"output": payload_output}})


class EventParsingTest(unittest.TestCase):
    def test_解析_sentence_end_里的字级时间戳(self):
        message = event({
            "type": "sentence-end",
            "original_text": "妈，今天药按时吃了没",
            "sentence": {
                "index": 0,
                "words": [
                    {"text": "妈", "begin_time": 0, "end_time": 180},
                    {"text": "今天", "begin_time": 400, "end_time": 760},
                ],
            },
        })
        words = _extract_words_from_event(message)
        self.assertEqual(len(words), 2)
        self.assertEqual(words[0], {"word": "妈", "start": 0.0, "end": 180.0})
        self.assertEqual(words[1]["word"], "今天")

    def test_兼容顶层_words(self):
        message = event({"type": "sentence-end",
                         "words": [{"text": "你", "begin_time": 0, "end_time": 150}]})
        self.assertEqual(len(_extract_words_from_event(message)), 1)

    def test_兼容驼峰键名(self):
        message = event({"sentence": {"words": [
            {"text": "好", "beginTime": 10, "endTime": 120}]}})
        words = _extract_words_from_event(message)
        self.assertEqual(words[0]["start"], 10.0)

    def test_句子开始阶段_words_为空(self):
        message = event({"type": "sentence-begin", "sentence": {"index": 0, "words": []}})
        self.assertEqual(_extract_words_from_event(message), [])

    def test_坏数据返回空而不是抛错(self):
        for bad in ("not json", "", None, "{}", json.dumps({"payload": None}),
                    json.dumps({"payload": {"output": "字符串而不是对象"}})):
            self.assertEqual(_extract_words_from_event(bad), [], repr(bad))

    def test_缺时间字段的条目被丢掉(self):
        message = event({"sentence": {"words": [
            {"text": "妈"},                                   # 缺时间
            {"begin_time": 0, "end_time": 10},                # 缺文本
            {"text": "好", "begin_time": "x", "end_time": 1},   # 时间不是数
            {"text": "你", "begin_time": 0, "end_time": 150},   # 正常
        ]}})
        words = _extract_words_from_event(message)
        self.assertEqual([w["word"] for w in words], ["你"])


class UnitConversionTest(unittest.TestCase):
    """百炼毫秒 → WhisperX 秒；再喂给 from_alignment 应得到 tts-aligned 与正确时长。"""

    def test_毫秒转秒(self):
        words = [{"word": "妈", "start": 0.0, "end": 180.0}]
        segments = words_to_segments(words)
        self.assertEqual(segments[0]["start"], 0.0)
        self.assertAlmostEqual(segments[0]["end"], 0.18, places=6)

    def test_接上_from_alignment_得到_tts_aligned(self):
        words = [
            {"word": "妈", "start": 0.0, "end": 180.0},
            {"word": "今天", "start": 400.0, "end": 760.0},
        ]
        payload = from_alignment(words_to_segments(words), "a_1")
        self.assertEqual(payload["source"], "tts-aligned")
        # 760ms + 120ms 收尾
        self.assertAlmostEqual(payload["durationMs"], 880, delta=5)
        chars = [cue["c"] for cue in payload["cues"] if cue["c"]]
        self.assertEqual(chars, ["妈", "今", "天"])

    def test_坏条目跳过(self):
        self.assertEqual(words_to_segments([None, {}, {"word": "好"}]), [])


class DegradeTest(unittest.TestCase):
    """不许静默假装成功。"""

    def setUp(self):
        self._saved = {key: os.environ.get(key) for key in
                       ("BILIN_TTS_PROVIDER", "BILIN_TTS_URL", "BILIN_TTS_CMD",
                        "DASHSCOPE_API_KEY", "BILIN_TTS_MODEL", "BILIN_TTS_VOICE",
                        "BILIN_DASHSCOPE_WS_URL")}
        for key in self._saved:
            os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_没装_sdk_时明确失败(self):
        import asyncio
        provider = QwenTtsProvider(api_key="sk-fake")
        # 用 asyncio.run（不要用 get_event_loop：Python 3.13 下全量跑测试时
        # 事件循环可能已被别的用例关掉，会抛 RuntimeError 而不是跑我们的断言）
        result = asyncio.run(provider.synthesize("你好"))
        self.assertFalse(result.ok)
        if sdk_available():
            # 装了 SDK 的话应该是"没有 key"或"调用异常"这类原因，而不是空 reason
            self.assertTrue(result.reason)
        else:
            self.assertIn("dashscope", result.reason)

    def test_没配_key_时明确失败(self):
        import asyncio
        provider = QwenTtsProvider(api_key="")
        result = asyncio.run(provider.synthesize("你好"))
        self.assertFalse(result.ok)
        self.assertTrue(result.reason)

    def test_空文本明确失败(self):
        import asyncio
        provider = QwenTtsProvider(api_key="sk-fake")
        result = asyncio.run(provider.synthesize("   "))
        self.assertFalse(result.ok)
        self.assertTrue(result.reason)

    def test_装配优先级_qwen_覆盖_url_与_cmd(self):
        os.environ["BILIN_TTS_PROVIDER"] = "qwen"
        os.environ["BILIN_TTS_URL"] = "http://example.invalid/tts"
        os.environ["BILIN_TTS_CMD"] = "python nothing.py"
        self.assertIsInstance(gateway.build_tts_provider(), QwenTtsProvider)

    def test_没有_provider_变量时走_url(self):
        os.environ["BILIN_TTS_URL"] = "http://example.invalid/tts"
        self.assertIsInstance(gateway.build_tts_provider(), gateway.HttpTtsProvider)

    def test_默认仍是_Null(self):
        self.assertIsInstance(gateway.build_tts_provider(), gateway.NullTtsProvider)

    def test_describe_在_qwen_下报_alignReady_为真(self):
        os.environ["BILIN_TTS_PROVIDER"] = "qwen"
        info = gateway.describe()
        self.assertEqual(info["tts"], "QwenTtsProvider")
        # 百炼自带字级时间戳 → 不需要额外对齐
        self.assertTrue(info["alignReady"])
        self.assertIn("托管路线", info["note"])

    def test_默认参数与文档一致(self):
        provider = build_qwen_provider()
        self.assertEqual(provider.model, DEFAULT_MODEL)
        self.assertEqual(provider.voice, DEFAULT_VOICE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
