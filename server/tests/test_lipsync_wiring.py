"""编排层与语音的接线测试：**lipsync 事件是否真的用真时间戳**。

为什么单独测这一层：`from_alignment` 与 Provider 各自都有测试，
但"编排层到底用没用真时间戳"是**接线问题** —— 接错了会静默退回估算版
（口型照动，只是不准），不写这条断言根本发现不了。

跑法：`cd server; .\\.venv\\Scripts\\python.exe -m unittest tests.test_lipsync_wiring -v`
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.orchestration import events  # noqa: E402
from app.orchestration.service import ChatService  # noqa: E402
from app.voice.gateway import TtsProvider, TtsResult  # noqa: E402


class FakeAlignedTts(TtsProvider):
    """假装是百炼：音频 + 字级时间戳一起给。"""

    def __init__(self, segments=None, ok=True, reason=""):
        self.segments = segments if segments is not None else [
            {"word": "妈", "start": 0.00, "end": 0.18},
            {"word": "今天", "start": 0.40, "end": 0.76},
        ]
        self.ok = ok
        self.reason = reason
        self.calls = 0

    async def synthesize(self, text: str, voice: str = "") -> TtsResult:
        self.calls += 1
        return TtsResult(
            audio_path="/tmp/fake.mp3" if self.ok else "",
            ok=self.ok,
            reason=self.reason,
            extra={"word_segments": self.segments, "word_timestamps_ok": bool(self.segments)},
        )


class FakeNoTimestampTts(TtsProvider):
    """有音频但**没有**字级时间戳（音色不支持）→ 应回退估算版。"""

    async def synthesize(self, text: str, voice: str = "") -> TtsResult:
        return TtsResult(audio_path="/tmp/fake.mp3", ok=True, reason="",
                         extra={"word_segments": [], "word_timestamps_ok": False})


class FakeFailingTts(TtsProvider):
    async def synthesize(self, text: str, voice: str = "") -> TtsResult:
        return TtsResult(ok=False, reason="云端不可达")


def build_service(voice) -> ChatService:
    """构造一个**不依赖模型与存储**的最小 ChatService，只为调 `_build_lipsync`。

    `_build_lipsync` 只用到 `self.voice`，所以其余入参给 None 即可 ——
    这样测试不必拉起 LLM / store / persona，跑得快也不会因外部依赖而脆。
    """
    service = ChatService.__new__(ChatService)      # 跳过 __init__ 的依赖装配
    service.voice = voice
    return service


class LipsyncWiringTest(unittest.TestCase):
    def test_有真时间戳时用_tts_aligned(self):
        provider = FakeAlignedTts()
        service = build_service(provider)
        payload = asyncio.run(service._build_lipsync("妈，今天药按时吃了没", "a_1"))
        self.assertEqual(payload["source"], "tts-aligned")
        self.assertEqual(provider.calls, 1, "应该真的调了 TTS")
        # 时间轴来自对齐数据（760ms 末字 + 120ms 收尾）
        self.assertAlmostEqual(payload["durationMs"], 880, delta=5)

    def test_没有时间戳时回退估算(self):
        service = build_service(FakeNoTimestampTts())
        payload = asyncio.run(service._build_lipsync("妈，今天药按时吃了没", "a_1"))
        self.assertEqual(payload["source"], "estimated")
        self.assertGreater(len(payload["cues"]), 0, "回退也必须给出可用的口型")

    def test_TTS_失败时回退估算而不是抛错(self):
        service = build_service(FakeFailingTts())
        payload = asyncio.run(service._build_lipsync("你好", "a_1"))
        self.assertEqual(payload["source"], "estimated")

    def test_没配语音时走估算(self):
        from app.voice.gateway import NullTtsProvider
        service = build_service(NullTtsProvider())
        payload = asyncio.run(service._build_lipsync("你好", "a_1"))
        self.assertEqual(payload["source"], "estimated")

    def test_两条路径的契约形状一致(self):
        aligned = asyncio.run(build_service(FakeAlignedTts())._build_lipsync("妈，今天", "a_1"))
        estimated = asyncio.run(build_service(FakeFailingTts())._build_lipsync("妈，今天", "a_1"))
        self.assertEqual(sorted(aligned.keys()), sorted(estimated.keys()))
        self.assertIn("cues", aligned)
        self.assertIn("cues", estimated)

    def test_事件名是_lipsync(self):
        # 契约层的不变量：端侧只听 `lipsync` 这个名字
        self.assertEqual(events.EVENT_LIPSYNC, "lipsync")
        frame = events.lipsync_frame({"assistantMsgId": "a_1", "cues": []})
        self.assertTrue(frame.startswith("event: lipsync\n"))
        self.assertIn("data: ", frame)


if __name__ == "__main__":
    unittest.main(verbosity=2)
