"""比邻AI · 语音（CosyVoice 2 网关 + 字级对齐）

选型文档 `比邻AI_医学条目与语音技术选型.md` §2.1 定的管线是：

    文本 → **CosyVoice 2** 合成音频 → **WhisperX / MFA 强制对齐** → 字级时间戳 → viseme

本包把那两步收口成两个可插拔的 Provider，并且**两者都可以不装依赖就工作**：

| Provider | 本机有 GPU + CosyVoice 时 | 没有时 |
|---|---|---|
| `TtsProvider` | `CommandTtsProvider`（本地推理）/ `HttpTtsProvider`（独立推理节点） | `NullTtsProvider`（不出音频，口型退回估算版） |
| `Aligner` | `CommandAligner`（WhisperX / MFA 命令行） | `NullAligner`（返回空，触发估算回退） |

**为什么用"命令行/HTTP"而不是直接 `import cosyvoice`**：
1. CosyVoice 2 需要 Python 3.10 + pynini 等编译依赖，与 agent 服务的
   Python 3.13 + 4 个依赖（fastapi/uvicorn/httpx/PyYAML）**不可能放同一个环境**；
2. 选型文档写的就是"自建推理服务（GPU），与 agent 服务**同机或独立推理节点**"；
3. 进程隔离后，TTS 崩了不会把对话服务带崩，GPU 排队也不会阻塞 SSE。

## 降级链（必须显式，不能静默）

    CosyVoice 可用 → 真音频 + 真对齐（`source: "tts-aligned"`）
       ↓ 失败
    只有 TTS 没有对齐 → 有音频，但口型仍按字数估算（`source: "estimated"`）
       ↓ 失败
    全都没有 → 无音频，口型估算（`source: "estimated"`）—— **对话照常进行**

任何一环失败都**不能**让对话中断：语音是增强项，不是主链路。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TtsResult:
    """一次合成结果。`audio_path` 为空表示"没出音频"（降级）。"""
    audio_path: str = ""
    duration_ms: int = 0
    ok: bool = False
    reason: str = ""
    extra: dict = field(default_factory=dict)


class TtsProvider:
    """合成接口。实现方只需给出 `synthesize()`。"""

    async def synthesize(self, text: str, voice: str = "") -> TtsResult:  # pragma: no cover
        raise NotImplementedError


class NullTtsProvider(TtsProvider):
    """不出音频的占位实现（本机没有 CosyVoice 时的默认）。

    **刻意不做任何假装**：返回 `ok=False` 并给出 reason，
    调用方据此走估算版口型 —— 而不是假装成功、让上层以为有音频。
    """

    async def synthesize(self, text: str, voice: str = "") -> TtsResult:
        return TtsResult(ok=False, reason="未配置 CosyVoice 推理服务（BILIN_TTS_CMD 或 BILIN_TTS_URL）")


class CommandTtsProvider(TtsProvider):
    """调用本地命令行做推理（本机装了 CosyVoice + GPU 时用这条）。

    命令模板里可用占位符：
      `{text}`  待合成文本（会写到临时文件，避免命令行转义问题）
      `{out}`   输出 wav 路径
      `{voice}` 音色 / 参考音频路径

    例（自建推理脚本）：
      `python D:\\\\CosyVoice\\\\tts_cli.py --text-file {text} --out {out} --voice {voice}`

    ⚠️ 用临时文件传文本而不是塞进命令行：中文 + 引号在 Windows 命令行上极易转义出错
    （本项目已经因为 PowerShell 引号踩过多次）。
    """

    def __init__(self, template: str, timeout_s: float = 60.0, voice: str = ""):
        self.template = template
        self.timeout_s = timeout_s
        self.voice = voice

    async def synthesize(self, text: str, voice: str = "") -> TtsResult:
        import tempfile
        if not self.template:
            return TtsResult(ok=False, reason="命令模板为空")
        workdir = tempfile.mkdtemp(prefix="bilin-tts-")
        text_file = os.path.join(workdir, "input.txt")
        out_file = os.path.join(workdir, "output.wav")
        with open(text_file, "w", encoding="utf-8") as handle:
            handle.write(text or "")
        command = (self.template
                   .replace("{text}", text_file)
                   .replace("{out}", out_file)
                   .replace("{voice}", voice or self.voice))
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout_s)
            if process.returncode != 0:
                reason = (stderr or b"").decode("utf-8", "ignore")[-400:]
                return TtsResult(ok=False, reason="TTS 命令退出码 %d：%s" % (process.returncode, reason))
            if not os.path.exists(out_file):
                return TtsResult(ok=False, reason="TTS 命令没有产出音频文件")
            return TtsResult(audio_path=out_file, ok=True, duration_ms=probe_wav_ms(out_file))
        except asyncio.TimeoutError:
            return TtsResult(ok=False, reason="TTS 超时（%.0fs）" % self.timeout_s)
        except Exception as exc:  # noqa: BLE001 —— 语音失败不能影响对话
            return TtsResult(ok=False, reason="TTS 调用异常：%s" % exc)


class HttpTtsProvider(TtsProvider):
    """调用独立推理节点（选型文档说的"独立推理节点"）。

    约定对方返回 `audio/wav` 二进制；`duration_ms` 从 wav 头推算（拿不到就 0，
    上层会退回按字数估算）。
    """

    def __init__(self, url: str, timeout_s: float = 60.0, voice: str = ""):
        self.url = url
        self.timeout_s = timeout_s
        self.voice = voice

    async def synthesize(self, text: str, voice: str = "") -> TtsResult:
        if not self.url:
            return TtsResult(ok=False, reason="未配置 TTS URL")
        try:
            import httpx
        except Exception as exc:  # noqa: BLE001
            return TtsResult(ok=False, reason="缺少 httpx：%s" % exc)
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(self.url, json={
                    "text": text,
                    "voice": voice or self.voice,
                })
            if response.status_code != 200:
                return TtsResult(ok=False, reason="TTS 服务 HTTP %d" % response.status_code)
            import tempfile
            workdir = tempfile.mkdtemp(prefix="bilin-tts-")
            out_file = os.path.join(workdir, "output.wav")
            with open(out_file, "wb") as handle:
                handle.write(response.content)
            return TtsResult(audio_path=out_file, ok=True, duration_ms=probe_wav_ms(out_file))
        except Exception as exc:  # noqa: BLE001
            return TtsResult(ok=False, reason="TTS 请求异常：%s" % exc)


# ---------------------------------------------------------------------------
# 字级对齐（WhisperX / MFA）
# ---------------------------------------------------------------------------

class Aligner:
    """对齐接口：给定音频 + 文本，返回字级时间戳（秒）。"""

    async def align(self, audio_path: str, text: str) -> list[dict]:  # pragma: no cover
        raise NotImplementedError


class NullAligner(Aligner):
    """不做对齐（返回空列表）。调用方据此回退到估算版口型。"""

    async def align(self, audio_path: str, text: str) -> list[dict]:
        return []


class CommandAligner(Aligner):
    """调用 WhisperX / MFA 命令行做强制对齐。

    命令模板占位符：
      `{audio}` 音频路径   `{text}` 文本文件路径   `{json}` 期望产出的对齐 JSON 路径

    期望产出**WhisperX 形状**的 JSON（本模块只认这一个形状，别的形状在命令模板里转换）：

        {"word_segments": [{"word": "妈", "start": 0.0, "end": 0.18}, ...]}

    例：
      `python D:\\\\tools\\\\align_cli.py --audio {audio} --text {text} --out {json}`
    """

    def __init__(self, template: str, timeout_s: float = 120.0):
        self.template = template
        self.timeout_s = timeout_s

    async def align(self, audio_path: str, text: str) -> list[dict]:
        import tempfile
        if not self.template or not audio_path or not os.path.exists(audio_path):
            return []
        workdir = tempfile.mkdtemp(prefix="bilin-align-")
        text_file = os.path.join(workdir, "text.txt")
        json_file = os.path.join(workdir, "align.json")
        with open(text_file, "w", encoding="utf-8") as handle:
            handle.write(text or "")
        command = (self.template
                   .replace("{audio}", audio_path)
                   .replace("{text}", text_file)
                   .replace("{json}", json_file))
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout_s)
            if process.returncode != 0:
                logger.warning("对齐命令失败：%s", (stderr or b"").decode("utf-8", "ignore")[-300:])
                return []
            if not os.path.exists(json_file):
                return []
            with open(json_file, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return extract_word_segments(payload)
        except asyncio.TimeoutError:
            logger.warning("对齐超时（%.0fs）", self.timeout_s)
            return []
        except Exception:  # noqa: BLE001
            logger.warning("对齐调用异常", exc_info=True)
            return []


def extract_word_segments(payload) -> list[dict]:
    """从对齐工具的 JSON 里取出字级片段，**兼容几种常见形状**。

    为什么要有这个函数：WhisperX 版本之间输出层级变过
    （顶层 `word_segments`、`segments[].words`、或纯数组），
    写死一种形状会在换版本时静默拿不到数据（返回空 → 口型退回估算，看不出错）。
    """
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("word_segments", "words"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    segments = payload.get("segments")
    if isinstance(segments, list):
        collected: list[dict] = []
        for segment in segments:
            if isinstance(segment, dict) and isinstance(segment.get("words"), list):
                collected.extend(item for item in segment["words"] if isinstance(item, dict))
        if collected:
            return collected
    return []


def probe_wav_ms(path: str) -> int:
    """从 wav 头读时长（毫秒）。读不出来返回 0（上层会退回估算）。

    自己解析而不是引 librosa/soundfile：仓库只允许 4 个依赖，而 wav 头足够简单
    （`RIFF` + fmt 块给采样率与位深，data 块给字节数）。
    """
    try:
        import wave
        with wave.open(path, "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate() or 0
            if rate <= 0:
                return 0
            return int(frames * 1000 / rate)
    except Exception:  # noqa: BLE001 —— 不是 wav 或读不了，交给上层降级
        return 0


# ---------------------------------------------------------------------------
# 工厂：按环境变量装配（**默认全部降级**，绝不因为没配就让服务起不来）
# ---------------------------------------------------------------------------

def build_tts_provider() -> TtsProvider:
    """按环境变量装配 TTS。

    优先级（**已定的路线优先，不猜**）：
    1. `BILIN_TTS_PROVIDER=qwen` → 阿里云百炼 Qwen-Audio-TTS（托管路线，**自带字级时间戳**）
    2. `BILIN_TTS_URL` → 独立推理节点（HTTP）
    3. `BILIN_TTS_CMD` → 本机命令行推理（GPU 机器上的自建脚本）
    4. 都没有 → `NullTtsProvider`（明确降级：口型走估算版，对话不受影响）
    """
    provider = (os.environ.get("BILIN_TTS_PROVIDER") or "").strip().lower()
    if provider in ("qwen", "dashscope", "bailian"):
        # 延迟导入：不装 dashscope SDK 时这一段根本不会执行
        from .qwen_tts import build_qwen_provider
        return build_qwen_provider()
    url = (os.environ.get("BILIN_TTS_URL") or "").strip()
    if url:
        return HttpTtsProvider(url, voice=os.environ.get("BILIN_TTS_VOICE", ""))
    command = (os.environ.get("BILIN_TTS_CMD") or "").strip()
    if command:
        return CommandTtsProvider(command, voice=os.environ.get("BILIN_TTS_VOICE", ""))
    return NullTtsProvider()


def build_aligner() -> Aligner:
    command = (os.environ.get("BILIN_ALIGN_CMD") or "").strip()
    if command:
        if not shutil.which("python") and "python" in command:
            logger.warning("BILIN_ALIGN_CMD 里用了 python，但 PATH 里找不到 python")
        return CommandAligner(command)
    return NullAligner()


def describe() -> dict:
    """给 `/healthz` 用：如实反映语音链路当前是"真跑"还是"降级"。"""
    tts = build_tts_provider()
    aligner = build_aligner()
    tts_name = type(tts).__name__
    # 百炼 Qwen-Audio-TTS **自带字级时间戳**，不需要再跑一遍强制对齐
    # （它在同一次会话里把音频与 words 一起给回来，见 qwen_tts.py 顶部说明）
    self_aligned = tts_name == "QwenTtsProvider"
    align_ready = self_aligned or not isinstance(aligner, NullAligner)
    info = {
        "tts": tts_name,
        "aligner": "（TTS 自带字级时间戳，无需额外对齐）" if self_aligned else type(aligner).__name__,
        "ttsReady": not isinstance(tts, NullTtsProvider),
        "alignReady": align_ready,
        "note": "未配置时口型走估算版（source=estimated），对话不受影响",
    }
    if self_aligned:
        # 托管路线的两个代价要能一眼看到，不要藏在文档里
        from .qwen_tts import sdk_available
        info["sdkInstalled"] = sdk_available()
        info["hasApiKey"] = bool(os.environ.get("DASHSCOPE_API_KEY"))
        info["voice"] = getattr(tts, "voice", "")
        info["model"] = getattr(tts, "model", "")
        info["note"] = "托管路线：音频出网 + 按字计费；sdkInstalled/hasApiKey 必须都为 true 才能真正工作"
    return info
