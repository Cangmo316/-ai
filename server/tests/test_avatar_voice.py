"""`app/avatar/visemes.py` 与 `app/voice/gateway.py` 的单元测试。

重点守住两件事：
1. **对齐版与估算版给同一个契约形状**（端侧只认一种，两条路径必须一致）；
2. **降级不许静默**：没有 CosyVoice / 没有对齐工具时，必须明确 `ok=False` / `source` 正确，
   而不是假装成功（本项目已经因为"静默失效"踩过坑：口型写入返回 0 但没人发现）。

跑法：`cd server; .\\.venv\\Scripts\\python.exe -m unittest tests.test_avatar_voice -v`
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.avatar.visemes import (  # noqa: E402
    LIPSYNC_VERSION,
    build_lipsync_payload,
    from_alignment,
    visemes_for_char,
)
from app.voice.gateway import (  # noqa: E402
    CommandAligner,
    CommandTtsProvider,
    HttpTtsProvider,
    NullAligner,
    NullTtsProvider,
    build_aligner,
    build_tts_provider,
    describe,
    extract_word_segments,
    probe_wav_ms,
)


class VisemeMappingTest(unittest.TestCase):
    def test_每字最多两个_viseme(self):
        for char in "妈今天药吃了没你说好":
            self.assertLessEqual(len(visemes_for_char(char)), 2, char)

    def test_双唇音走_MBP(self):
        # 妈/爸/不 都是双唇音，必须先闭唇
        for char in "妈爸不":
            self.assertEqual(visemes_for_char(char)[0], "vis_MBP", char)

    def test_未收录字回退开口而不是沉默(self):
        self.assertEqual(visemes_for_char("龘"), ["vis_AA"])


class EstimatedPayloadTest(unittest.TestCase):
    def test_契约字段齐全(self):
        payload = build_lipsync_payload("妈，今天药按时吃了没", "a_1")
        self.assertEqual(payload["assistantMsgId"], "a_1")
        self.assertEqual(payload["source"], "estimated")
        self.assertEqual(payload["version"], LIPSYNC_VERSION)
        self.assertGreater(payload["durationMs"], 0)
        for cue in payload["cues"]:
            self.assertIn("b", cue)
            self.assertIn("e", cue)
            self.assertIsInstance(cue["v"], list)
            self.assertLessEqual(len(cue["v"]), 2)

    def test_时间轴单调且末尾回静止(self):
        payload = build_lipsync_payload("你好呀", "a_1")
        previous_end = -1
        for cue in payload["cues"]:
            self.assertGreaterEqual(cue["b"], previous_end - 1)
            self.assertGreaterEqual(cue["e"], cue["b"])
            previous_end = cue["e"]
        self.assertEqual(payload["cues"][-1]["v"], ["vis_silence"])


class AlignmentPayloadTest(unittest.TestCase):
    """真·字级对齐（WhisperX 形状）→ payload。"""

    SEGMENTS = [
        {"word": "妈", "start": 0.00, "end": 0.18},
        {"word": "，", "start": 0.18, "end": 0.18},
        {"word": "今天", "start": 0.40, "end": 0.76},
    ]

    def test_source_标为_tts_aligned(self):
        payload = from_alignment(self.SEGMENTS, "a_1")
        self.assertEqual(payload["source"], "tts-aligned")

    def test_秒制输入得到毫秒时间轴(self):
        payload = from_alignment(self.SEGMENTS, "a_1")
        # 最后一个字结束于 0.76s，加 120ms 收尾
        self.assertAlmostEqual(payload["durationMs"], 880, delta=5)

    def test_毫秒制输入按整批判定(self):
        # ⚠️ 回归：单条 {"start":0,"end":400} 曾被逐条判成 400 秒 → 时长 400120ms
        payload = from_alignment([{"word": "你", "start": 0, "end": 400}], "a_2")
        self.assertAlmostEqual(payload["durationMs"], 520, delta=5)

    def test_一个词多个字按词内均分(self):
        payload = from_alignment([{"word": "今天", "start": 0.0, "end": 0.4}], "a_3")
        chars = [cue for cue in payload["cues"] if cue["c"]]
        self.assertEqual([cue["c"] for cue in chars], ["今", "天"])
        # 每个字各占 200ms
        self.assertAlmostEqual(chars[0]["b"], 0, delta=2)
        self.assertAlmostEqual(chars[0]["e"], 200, delta=2)
        self.assertAlmostEqual(chars[1]["b"], 200, delta=2)

    def test_标点不产生口型只推进时间(self):
        payload = from_alignment(self.SEGMENTS, "a_1")
        self.assertNotIn("，", [cue["c"] for cue in payload["cues"]])

    def test_零长度区间不被吞掉(self):
        # WhisperX 对标点常给 end == start；这里用一个真的零长度汉字验证兜底
        payload = from_alignment([{"word": "好", "start": 0.5, "end": 0.5}], "a_4")
        chars = [cue for cue in payload["cues"] if cue["c"]]
        self.assertEqual(len(chars), 1)
        self.assertGreater(chars[0]["e"], chars[0]["b"], "零长度区间应给最小可见时长")

    def test_空输入返回空_cues(self):
        payload = from_alignment([], "a_5")
        self.assertEqual(payload["cues"], [])
        self.assertEqual(payload["durationMs"], 0)

    def test_坏数据不抛异常(self):
        payload = from_alignment([
            None,
            "not-a-dict",
            {"word": "好"},                      # 缺 start/end
            {"word": "你", "start": "x", "end": 1},
            {"word": "我", "start": 0.0, "end": 0.2},
        ], "a_6")
        self.assertEqual([cue["c"] for cue in payload["cues"] if cue["c"]], ["我"])

    def test_两条路径的契约形状一致(self):
        estimated = build_lipsync_payload("你好", "a_1")
        aligned = from_alignment([{"word": "你好", "start": 0.0, "end": 0.4}], "a_1")
        self.assertEqual(sorted(estimated.keys()), sorted(aligned.keys()))
        for payload in (estimated, aligned):
            for cue in payload["cues"]:
                self.assertEqual(sorted(cue.keys()), ["b", "c", "e", "v"])


class WordSegmentExtractionTest(unittest.TestCase):
    """对齐工具输出形状变过，必须都认得（认不出会静默回退估算、看不出错）。"""

    SEGMENTS = [{"word": "妈", "start": 0.0, "end": 0.18}]

    def test_顶层数组(self):
        self.assertEqual(len(extract_word_segments(self.SEGMENTS)), 1)

    def test_word_segments_键(self):
        self.assertEqual(len(extract_word_segments({"word_segments": self.SEGMENTS})), 1)

    def test_segments_里嵌_words(self):
        payload = {"segments": [{"words": self.SEGMENTS}]}
        self.assertEqual(len(extract_word_segments(payload)), 1)

    def test_认不出时返回空(self):
        self.assertEqual(extract_word_segments({"unknown": 1}), [])
        self.assertEqual(extract_word_segments(None), [])


class GatewayDegradeTest(unittest.TestCase):
    """降级链：默认全部降级，且**必须显式**（不许假装成功）。"""

    def setUp(self):
        self._saved = {key: os.environ.get(key) for key in
                       ("BILIN_TTS_URL", "BILIN_TTS_CMD", "BILIN_ALIGN_CMD")}
        for key in self._saved:
            os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_默认装配为_Null(self):
        self.assertIsInstance(build_tts_provider(), NullTtsProvider)
        self.assertIsInstance(build_aligner(), NullAligner)

    def test_describe_如实反映未就绪(self):
        info = describe()
        self.assertFalse(info["ttsReady"])
        self.assertFalse(info["alignReady"])

    def test_配了_URL_走_Http(self):
        os.environ["BILIN_TTS_URL"] = "http://127.0.0.1:9999/tts"
        self.assertIsInstance(build_tts_provider(), HttpTtsProvider)

    def test_配了_CMD_走_Command(self):
        os.environ["BILIN_TTS_CMD"] = "python tts.py --out {out}"
        os.environ["BILIN_ALIGN_CMD"] = "python align.py --audio {audio} --out {json}"
        self.assertIsInstance(build_tts_provider(), CommandTtsProvider)
        self.assertIsInstance(build_aligner(), CommandAligner)

    def test_命令失败时显式失败而不是假成功(self):
        # 用一个必然失败的命令：断言 ok=False 且有 reason
        import asyncio
        provider = CommandTtsProvider("definitely-not-a-real-command-xyz --out {out}")
        result = asyncio.get_event_loop().run_until_complete(provider.synthesize("你好"))
        self.assertFalse(result.ok)
        self.assertTrue(result.reason)

    def test_空模板也显式失败(self):
        import asyncio
        provider = CommandTtsProvider("")
        result = asyncio.get_event_loop().run_until_complete(provider.synthesize("你好"))
        self.assertFalse(result.ok)


class WavProbeTest(unittest.TestCase):
    def test_读出_wav_时长(self):
        path = os.path.join(tempfile.mkdtemp(prefix="bilin-test-"), "a.wav")
        with wave.open(path, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(16000)
            handle.writeframes(b"\x00\x00" * 16000)   # 1 秒
        self.assertAlmostEqual(probe_wav_ms(path), 1000, delta=5)

    def test_不是_wav_返回0而不是抛错(self):
        path = os.path.join(tempfile.mkdtemp(prefix="bilin-test-"), "a.bin")
        with open(path, "wb") as handle:
            handle.write(b"not a wav")
        self.assertEqual(probe_wav_ms(path), 0)

    def test_文件不存在返回0(self):
        self.assertEqual(probe_wav_ms("definitely-missing-file.wav"), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
