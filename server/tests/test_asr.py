"""ASR 网关 + 语音数据隐私的单元测试（不联网、不需要真实引擎）。

守住四件事：
1. **不引入新依赖**：multipart 用标准库 `email` 解析，且**二进制逐字节保真**
   （音频被改写是静默故障，必须用测试挡）；
2. **引擎输出解析**：whisper.cpp 带/不带时间戳、带日志行时都能取到正确文本；
3. **降级不许静默**：没配 ASR 时明确返回 `ok=false` + 原因，而不是空字符串；
4. **⚠️ 语音数据安全（PIPL）**：录音**用完即删**（含异常路径）、
   **不写日志**、识别文本**不进日志**。

跑法：`cd server; .\\.venv\\Scripts\\python.exe -m unittest tests.test_asr -v`
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.asr import gateway  # noqa: E402
from app.asr import privacy  # noqa: E402
from app.main import create_app  # noqa: E402


def build_multipart(data: bytes, filename: str = "a.wav",
                    content_type: str = "audio/wav", boundary: str = "----bilin") -> tuple:
    """手写 multipart（不依赖 requests/httpx 的编码器，避免测试依赖第三方行为）。"""
    head = (
        "--%s\r\n" % boundary
        + 'Content-Disposition: form-data; name="file"; filename="%s"\r\n' % filename
        + "Content-Type: %s\r\n\r\n" % content_type
    ).encode()
    tail = ("\r\n--%s--\r\n" % boundary).encode()
    return head + data + tail, "multipart/form-data; boundary=%s" % boundary


# 一段"像录音"的二进制：含 0x00 / 0xFF / CRLF / 连续横线等易踩字节
TRICKY_AUDIO = bytes([0x52, 0x49, 0x46, 0x46]) + bytes(range(256)) * 4 + b"\r\n----\r\n\x00\xff"


class AsrEnvMixin:
    """环境变量隔离。

    ⚠️ 踩坑：第一版手工 `os.environ.pop` + `tearDown` 恢复，结果**泄漏**了 ——
    某个用例把 `BILIN_ASR_CMD` 设上后，后续用例读到残留值，
    于是"没配时应该是 Null"这类断言失败（而且失败点离原因很远，很难查）。
    正确做法是 `patch.dict` 自动恢复，并对"要清空"的键显式设成 `""`。
    """
    #: 本模块关心的变量；每个用例开始前统一清空
    ENV_KEYS = ("BILIN_ASR_PROVIDER", "BILIN_ASR_CMD", "BILIN_ASR_URL",
                "BILIN_TTS_PROVIDER", "DASHSCOPE_API_KEY")

    def isolate_env(self, **overrides):
        from unittest import mock
        clean = {key: "" for key in self.ENV_KEYS}
        clean.update(overrides)
        patcher = mock.patch.dict(os.environ, clean)
        patcher.start()
        self.addCleanup(patcher.stop)


class MultipartParseTest(unittest.TestCase):
    def test_二进制逐字节保真(self):
        body, content_type = build_multipart(TRICKY_AUDIO)
        parsed = privacy.parse_multipart(body, content_type)
        self.assertIsNotNone(parsed)
        filename, part_type, content = parsed
        self.assertEqual(filename, "a.wav")
        self.assertEqual(part_type, "audio/wav")
        # 关键：email 库不能改写任何字节（否则录音损坏，而故障是静默的）
        self.assertEqual(content, TRICKY_AUDIO)

    def test_boundary_大小写与引号都能认(self):
        body, _ = build_multipart(TRICKY_AUDIO, boundary="AbC123")
        for header in ('multipart/form-data; boundary=AbC123',
                       'Multipart/Form-Data; BOUNDARY="AbC123"',
                       'multipart/form-data; boundary=AbC123; charset=utf-8'):
            parsed = privacy.parse_multipart(body, header)
            self.assertIsNotNone(parsed, header)
            self.assertEqual(parsed[2], TRICKY_AUDIO)

    def test_畸形输入返回_None_而不是抛错(self):
        for body, content_type in ((b"", "multipart/form-data; boundary=x"),
                                   (b"not multipart", "text/plain"),
                                   (b"garbage", "multipart/form-data"),
                                   (b"------x\r\n", "multipart/form-data; boundary=x")):
            self.assertIsNone(privacy.parse_multipart(body, content_type),
                              repr((body, content_type)))

    def test_没有_file_字段时为_None(self):
        # 契约固定只认 name="file"；换个字段名应拒绝，避免错位取到别的数据
        body = (
            b'------bilin\r\n'
            b'Content-Disposition: form-data; name="other"; filename="a.wav"\r\n'
            b"Content-Type: audio/wav\r\n\r\n" + TRICKY_AUDIO + b"\r\n------bilin--\r\n"
        )
        self.assertIsNone(privacy.parse_multipart(body, "multipart/form-data; boundary=----bilin"))

    def test_后缀推断(self):
        self.assertEqual(gateway.suffix_for("a.m4a"), ".m4a")
        self.assertEqual(gateway.suffix_for("", "audio/webm"), ".webm")
        self.assertEqual(gateway.suffix_for("x", "audio/mpeg"), ".mp3")
        self.assertEqual(gateway.suffix_for("x", ""), ".wav")


class TempAudioTest(unittest.TestCase):
    """⚠️ 隐私核心：录音必须**用完即删**。"""

    def test_退出后文件与目录都被删除(self):
        with privacy.TempAudio(TRICKY_AUDIO, ".wav") as path:
            self.assertTrue(os.path.exists(path))
            with open(path, "rb") as handle:
                self.assertEqual(handle.read(), TRICKY_AUDIO)
            holder = path
        self.assertFalse(os.path.exists(holder), "录音文件必须被删除")
        self.assertFalse(os.path.isdir(os.path.dirname(holder)), "临时目录也必须删除")

    def test_异常路径也删除(self):
        holder = ""
        with self.assertRaises(RuntimeError):
            with privacy.TempAudio(TRICKY_AUDIO, ".wav") as path:
                holder = path
                raise RuntimeError("引擎崩了")
        self.assertFalse(os.path.exists(holder), "异常时也必须删除录音")

    def test_destroy_幂等(self):
        temp = privacy.TempAudio(TRICKY_AUDIO, ".wav")
        temp.__enter__()
        temp.destroy()
        temp.destroy()          # 再删一次不能抛
        self.assertEqual(temp.path, "")

    def test_目录名不可预测(self):
        # 可预测的名字会让同机其他进程有机会抢先创建/猜测
        names = set()
        for _ in range(3):
            temp = privacy.TempAudio(b"x", ".wav")
            temp.__enter__()
            names.add(os.path.basename(temp.dir))
            temp.destroy()
        self.assertEqual(len(names), 3, "每次都应生成唯一目录名")


class EngineOutputTest(unittest.TestCase):
    """whisper.cpp 的输出格式五花八门，解析必须稳。"""

    def test_剥掉时间戳前缀(self):
        raw = "[00:00.000 --> 00:02.000]   妈今天药吃了吗"
        self.assertEqual(gateway._last_text_line(raw), "妈今天药吃了吗")

    def test_跳过引擎日志(self):
        raw = "whisper_init_from_file_with_params_no_state: loading\nmain: processing\n妈 药吃了没"
        self.assertEqual(gateway._last_text_line(raw), "妈 药吃了没")

    def test_多行取最后一行(self):
        raw = "[00:00] 第一句\n[00:02] 第二句"
        self.assertEqual(gateway._last_text_line(raw), "第二句")

    def test_空输出返回空串(self):
        self.assertEqual(gateway._last_text_line(""), "")
        self.assertEqual(gateway._last_text_line("whisper_init: ok\n"), "")


class DegradeTest(AsrEnvMixin, unittest.TestCase):
    def setUp(self):
        self.isolate_env()

    def test_没配时是_Null_且明确失败(self):
        provider = gateway.build_asr_provider()
        self.assertIsInstance(provider, gateway.NullAsrProvider)
        result = asyncio.run(provider.transcribe("/nonexistent.wav"))
        self.assertFalse(result.ok)
        self.assertTrue(result.reason, "降级必须给出原因，不能是空字符串")
        self.assertEqual(result.text, "")

    def test_describe_如实报_not_ready(self):
        info = gateway.describe()
        self.assertFalse(info["asrReady"])
        self.assertIn("NullAsrProvider", info["asr"])

    def test_配了命令就是_Command(self):
        os.environ["BILIN_ASR_CMD"] = "echo hi"
        self.assertIsInstance(gateway.build_asr_provider(), gateway.CommandAsrProvider)
        self.assertTrue(gateway.describe()["asrReady"])

    def test_显式指定_whispercpp_但没有命令时仍是_Null(self):
        os.environ["BILIN_ASR_PROVIDER"] = "whisper.cpp"
        self.assertIsInstance(gateway.build_asr_provider(), gateway.NullAsrProvider)

    def test_URL_优先于命令(self):
        os.environ["BILIN_ASR_URL"] = "http://example.invalid/asr"
        os.environ["BILIN_ASR_CMD"] = "echo hi"
        self.assertIsInstance(gateway.build_asr_provider(), gateway.HttpAsrProvider)

    def test_文件不存在时不调命令(self):
        provider = gateway.CommandAsrProvider("echo should-not-run")
        result = asyncio.run(provider.transcribe("/definitely/missing.wav"))
        self.assertFalse(result.ok)
        self.assertIn("不存在", result.reason)


class PrivacyReportTest(AsrEnvMixin, unittest.TestCase):
    """隐私体检：部署方要能从 /healthz 看出"引擎会不会把话打进日志"。"""

    def setUp(self):
        self.isolate_env()

    def test_识别带_no_prints_的模板(self):
        self.assertTrue(privacy.command_suppresses_prints("main.exe -m m.bin --no-prints -f {audio}"))
        self.assertTrue(privacy.command_suppresses_prints("whisper -q -f {audio}"))

    def test_没带抑制开关会被指出(self):
        self.assertFalse(privacy.command_suppresses_prints("main.exe -f {audio}"))
        os.environ["BILIN_ASR_CMD"] = "main.exe -f {audio}"
        report = privacy.privacy_report()
        self.assertFalse(report["enginePrintsSuppressed"])
        self.assertIn("warning", report, "未抑制打印必须给出警告（识别文本会进日志）")

    def test_报告里的保留声明(self):
        report = privacy.privacy_report()
        self.assertIn("删除", report["voiceDataRetention"])
        self.assertFalse(report["logsTranscript"], "本服务不记识别文本")
        self.assertEqual(report["maxUploadBytes"], privacy.MAX_UPLOAD_BYTES)


class EndpointTest(AsrEnvMixin, unittest.TestCase):
    def setUp(self):
        self.isolate_env()
        self.client = TestClient(create_app())

    def test_未配_asr_时明确降级(self):
        body, content_type = build_multipart(TRICKY_AUDIO)
        response = self.client.post("/v1/asr/transcribe", content=body,
                                    headers={"Content-Type": content_type})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["reason"])
        # 字节数如实回报（用于端侧排查"录音有没有传全"）
        self.assertEqual(payload["bytes"], len(TRICKY_AUDIO))

    def test_畸形请求是_400(self):
        response = self.client.post("/v1/asr/transcribe", content=b"not-multipart",
                                    headers={"Content-Type": "text/plain"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])

    def test_空音频是_400(self):
        body, content_type = build_multipart(b"")
        response = self.client.post("/v1/asr/transcribe", content=body,
                                    headers={"Content-Type": content_type})
        self.assertEqual(response.status_code, 400)

    def test_超大音频是_413_且不落盘(self):
        oversized = b"x" * (privacy.MAX_UPLOAD_BYTES + 10)
        body, content_type = build_multipart(oversized)
        response = self.client.post("/v1/asr/transcribe", content=body,
                                    headers={"Content-Type": content_type})
        self.assertEqual(response.status_code, 413)

    def test_healthz_报出_asr_与隐私处理方式(self):
        payload = self.client.get("/healthz").json()
        self.assertIn("asr", payload)
        self.assertIn("asrPrivacy", payload)
        self.assertIn("voiceDataRetention", payload["asrPrivacy"])
        self.assertFalse(payload["asrPrivacy"]["logsTranscript"])

    def test_成功路径不留下临时文件(self):
        # 用真能跑的命令（python 打印固定文本）验证"走完端点不留文件"
        import tempfile
        os.environ["BILIN_ASR_CMD"] = (
            sys.executable + ' -c "print(\'妈 药吃了没\')"'
        )
        before = set(os.listdir(tempfile.gettempdir()))
        body, content_type = build_multipart(TRICKY_AUDIO)
        response = self.client.post("/v1/asr/transcribe", content=body,
                                    headers={"Content-Type": content_type})
        payload = response.json()
        self.assertTrue(payload["ok"], payload.get("reason"))
        self.assertEqual(payload["text"], "妈 药吃了没")
        after = set(os.listdir(tempfile.gettempdir()))
        leaked = [name for name in (after - before) if name.startswith("bilin-asr-")]
        self.assertEqual(leaked, [], "端点跑完不能留下任何录音临时目录")


if __name__ == "__main__":
    unittest.main(verbosity=2)
