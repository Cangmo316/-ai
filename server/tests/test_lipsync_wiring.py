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

    def __init__(self, segments=None, ok=True, reason="", audio_path="/tmp/fake.mp3",
                 duration_ms=0):
        self.segments = segments if segments is not None else [
            {"word": "妈", "start": 0.00, "end": 0.18},
            {"word": "今天", "start": 0.40, "end": 0.76},
        ]
        self.ok = ok
        self.reason = reason
        # 音频路径可注入：要断言"audio 事件真的带上了音频"时必须指向**存在**的文件，
        # 否则 _store_audio 读文件失败会静默返回 None，把接线问题盖成"没配 TTS"
        self.audio_path = audio_path
        self.duration_ms = duration_ms
        self.calls = 0

    async def synthesize(self, text: str, voice: str = "") -> TtsResult:
        self.calls += 1
        return TtsResult(
            audio_path=self.audio_path if self.ok else "",
            duration_ms=self.duration_ms,
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


class AudioEventWiringTest(unittest.TestCase):
    """audio 事件必须**真的产出**（且先于 lipsync 发出）。

    守的是真机踩过的坑：`_last_audio_payload` 是 `_build_lipsync()` **内部**合成 TTS 时
    才写进去的，第一版代码"先取 payload 再合成"，取到的永远是 None ——
    配了百炼 TTS 也一个 audio 事件都不发，端侧表现就是"数字人没声音"。
    """

    def setUp(self):
        import tempfile
        self.workdir = tempfile.mkdtemp(prefix="bilin-wiring-")
        self.audio_path = os.path.join(self.workdir, "fake.mp3")
        with open(self.audio_path, "wb") as handle:
            handle.write(b"ID3\x03" + b"\x00" * 2048)     # 有内容的假音频

    def _service(self, voice):
        service = ChatService.__new__(ChatService)
        service.voice = voice
        service._last_audio_payload = None
        from app.voice.audio_store import get_store
        service.audio_store = get_store()
        return service

    def test_音频与口型一起产出且音频非空(self):
        provider = FakeAlignedTts(audio_path=self.audio_path, duration_ms=3640)
        audio_payload, lipsync_payload = asyncio.run(
            self._service(provider)._audio_then_lipsync("妈，今天药按时吃了没", "a_1"))
        self.assertIsNotNone(audio_payload, "配了 TTS 就必须产出 audio payload（第一版这里恒为 None）")
        self.assertTrue(audio_payload["url"].startswith("/v1/audio/"))
        self.assertEqual(audio_payload["assistantMsgId"], "a_1")
        self.assertGreater(audio_payload["bytes"], 2000)
        self.assertEqual(audio_payload["durationMs"], 3640)
        self.assertEqual(audio_payload["format"], "mp3")
        self.assertEqual(lipsync_payload["source"], "tts-aligned")

    def test_每轮音频各自暂存不串音(self):
        service = self._service(FakeAlignedTts(audio_path=self.audio_path))
        first, _ = asyncio.run(service._audio_then_lipsync("妈", "a_1"))
        second, _ = asyncio.run(service._audio_then_lipsync("妈", "a_2"))
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertNotEqual(first["url"], second["url"], "两轮的音频 id 必须不同")

    def test_TTS_失败时不产音频但口型照给(self):
        audio_payload, lipsync_payload = asyncio.run(
            self._service(FakeFailingTts())._audio_then_lipsync("你好", "a_1"))
        self.assertIsNone(audio_payload)
        self.assertEqual(lipsync_payload["source"], "estimated")

    def test_wav_路线的_format_跟着扩展名走(self):
        wav_path = os.path.join(self.workdir, "fake.wav")
        with open(wav_path, "wb") as handle:
            handle.write(b"RIFF" + b"\x00" * 1024)
        audio_payload, _ = asyncio.run(
            self._service(FakeAlignedTts(audio_path=wav_path))._audio_then_lipsync("妈", "a_1"))
        self.assertEqual(audio_payload["format"], "wav", "写死 mp3 会让 wav 路线下发错误格式")


if __name__ == "__main__":
    unittest.main(verbosity=2)
