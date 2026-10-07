"""比邻AI · 语音识别（ASR）网关

老人端的真实入口应该是**按住说话**，而不是打字。本模块把"语音 → 文字"这一步
做成可插拔的 Provider，与 `app/voice/gateway.py`（TTS）同一套结构。

## ⚠️ 引擎选型的实测约束（这条路为什么不是 faster-whisper）

本机实测前提：**Python 3.13.14**（项目 venv 与系统 python 都是）、RTX 4060 Laptop 8GB、
内存 15.6GB、**没有 ffmpeg**。

- **`faster-whisper`**：依赖 `ctranslate2`，而 **ctranslate2 目前没有 Python 3.13 的轮子**
  （社区 issue：[OpenNMT/CTranslate2#1853](https://github.com/OpenNMT/CTranslate2/issues/1853)
  "No matching distribution found for ctranslate2<5,>=4.0"）。
  要装它就得**为 ASR 单独再装一个 Python 3.10/3.11 环境**（conda 或独立 venv）。
- **`whisper.cpp`（推荐）**：C++ 实现的独立可执行文件，**不依赖 Python 版本**，
  自带 CUDA 后端，支持中文，模型是单个 `.bin` 文件。
  与我们已有的"命令行 Provider"模式（`CommandTtsProvider`）完全一致。
- **`sherpa-onnx`**：ONNX 系，同样不依赖 Python 版本，中文识别可用，模型体积更小。

**所以本模块默认推荐 whisper.cpp**，并把引擎细节关在 `CommandAsrProvider` 的命令模板里 ——
换引擎只改一个环境变量，**端侧与接口都不用动**。

## 降级链（与 TTS 同一原则：不配就明确降级，绝不假装成功）

    配了 ASR → 语音转文字可用（`/v1/asr/transcribe` 正常返回）
       ↓ 没配 / 引擎失败
    返回明确错误 + `available: false`，端侧提示"暂时听不清"，**老人仍可打字**

## 2026-10 补充：托管路线已经打通

上面那段是把 whisper.cpp 当首选写的。后来发现**这个 key（DASHSCOPE_API_KEY）
本来就有**（TTS 与识图都在用），于是加了 `QwenAsrProvider`
（`qwen3-asr-flash`）—— 不用装任何东西就能真跑，实测把
"今天天气不错，我吃过药了" 一字不差地识别出来。
`build_asr_provider()` 在没显式指定引擎、又检测到 key 时会自动选它。
本地 whisper.cpp 那条路仍然保留（`BILIN_ASR_CMD`），弱网或要离线时可切。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field

# ⚠️ 不要在这里 import .qwen_asr：
#    `qwen_asr` 需要 `AsrProvider`/`AsrResult`，而它们定义在本模块**下面**，
#    顶层互相 import 会造成 partially initialized module 的循环导入。
#    与 `voice/gateway.py` 引用 `qwen_tts` 同一做法：**在函数里延迟导入**。
logger = logging.getLogger(__name__)

# 支持的音频格式（端侧录音给的格式；转码交给引擎命令自己处理）
SUPPORTED_SUFFIXES = (".wav", ".mp3", ".m4a", ".aac", ".ogg", ".webm", ".pcm")
# 单次识别最长时长（秒）—— 防止把长录音丢给模型把显存吃满
MAX_AUDIO_SECONDS = 60


@dataclass
class AsrResult:
    """一次识别结果。`text` 为空表示没识别出来（降级）。"""
    text: str = ""
    ok: bool = False
    reason: str = ""
    language: str = ""
    duration_ms: int = 0
    extra: dict = field(default_factory=dict)


class AsrProvider:
    """识别接口。实现方只需给出 `transcribe()`。"""

    async def transcribe(self, audio_path: str, language: str = "zh") -> AsrResult:  # pragma: no cover
        raise NotImplementedError


class NullAsrProvider(AsrProvider):
    """不接 ASR（默认）。**刻意不假装成功**：返回明确的 not-ok 与原因，
    端侧据此提示"暂时听不清"，而不是给一个空字符串让上层以为识别成功。"""

    async def transcribe(self, audio_path: str, language: str = "zh") -> AsrResult:
        return AsrResult(
            ok=False,
            reason="未配置语音识别（BILIN_ASR_CMD 或 BILIN_ASR_URL）",
        )


class CommandAsrProvider(AsrProvider):
    """调用本地命令行引擎（**whisper.cpp 用这条**）。

    命令模板占位符：
      `{audio}`  音频文件路径
      `{language}` 语言（默认 zh）
      `{out}`    可选的输出文本文件路径（引擎若支持 `-otxt` 之类）

    例（whisper.cpp）：
      `D:\\\\whisper.cpp\\\\build\\\\bin\\\\Release\\\\main.exe -m D:\\\\whisper.cpp\\\\models\\\\ggml-small.bin -f {audio} -l {language} -nt`

    约定：**引擎把识别文本写到 stdout 即可**，本模块取最后一行非空文本
    （whisper.cpp 的 `-nt` 关掉时间戳后正好是纯文本）。
    若引擎只能写文件，用 `{out}` 让它写文件，本模块会优先读文件。
    """

    def __init__(self, template: str, timeout_s: float = 90.0):
        self.template = template
        self.timeout_s = timeout_s

    async def transcribe(self, audio_path: str, language: str = "zh") -> AsrResult:
        if not self.template:
            return AsrResult(ok=False, reason="命令模板为空")
        if not audio_path or not os.path.exists(audio_path):
            return AsrResult(ok=False, reason="音频文件不存在")

        workdir = tempfile.mkdtemp(prefix="bilin-asr-")
        out_file = os.path.join(workdir, "result.txt")
        command = (self.template
                   .replace("{audio}", audio_path)
                   .replace("{language}", language or "zh")
                   .replace("{out}", out_file))
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout_s)
            if process.returncode != 0:
                tail = (stderr or b"").decode("utf-8", "ignore")[-300:]
                return AsrResult(ok=False, reason="ASR 命令退出码 %d：%s" % (process.returncode, tail))
            # 引擎若写了文件就用文件，否则从 stdout 取
            text = ""
            if os.path.exists(out_file):
                with open(out_file, "r", encoding="utf-8", errors="ignore") as handle:
                    text = handle.read().strip()
            if not text:
                text = _last_text_line((stdout or b"").decode("utf-8", "ignore"))
            if not text:
                return AsrResult(ok=False, reason="引擎没有输出识别文本")
            return AsrResult(text=text, ok=True, language=language or "zh")
        except asyncio.TimeoutError:
            return AsrResult(ok=False, reason="识别超时（%.0fs）" % self.timeout_s)
        except Exception as exc:  # noqa: BLE001 —— 识别失败不能影响 App 其他功能
            return AsrResult(ok=False, reason="识别调用异常：%s" % exc)


class HttpAsrProvider(AsrProvider):
    """调用本地/内网 ASR 服务（如 whisper.cpp 的 `server` 模式、sherpa-onnx 服务）。

    约定对方接受 `POST multipart` 的 `file` 字段，返回 `{"text": "..."}`。
    用 multipart 而不是 base64：录音动辄几十 KB~几百 KB，base64 会平白多 33% 体积。
    """

    def __init__(self, url: str, timeout_s: float = 90.0):
        self.url = url
        self.timeout_s = timeout_s

    async def transcribe(self, audio_path: str, language: str = "zh") -> AsrResult:
        if not self.url:
            return AsrResult(ok=False, reason="未配置 ASR URL")
        try:
            import httpx
        except Exception as exc:  # noqa: BLE001
            return AsrResult(ok=False, reason="缺少 httpx：%s" % exc)
        try:
            with open(audio_path, "rb") as handle:
                content = handle.read()
            files = {"file": (os.path.basename(audio_path), content)}
            data = {"language": language or "zh"}
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(self.url, files=files, data=data)
            if response.status_code != 200:
                return AsrResult(ok=False, reason="ASR 服务 HTTP %d" % response.status_code)
            payload = response.json()
            text = ""
            if isinstance(payload, dict):
                text = str(payload.get("text") or payload.get("result") or "").strip()
            if not text:
                return AsrResult(ok=False, reason="ASR 服务没有返回文本")
            return AsrResult(text=text, ok=True, language=language or "zh")
        except Exception as exc:  # noqa: BLE001
            return AsrResult(ok=False, reason="ASR 请求异常：%s" % exc)


import re

# whisper.cpp 的默认输出形如 `[00:00.000 --> 00:02.000]   妈今天药吃了吗`
# —— 时间戳是前缀，**必须剥掉而不是跳过整行**（第一版就把真实文本一起丢了，被测试抓到）。
_TIMESTAMP_PREFIX = re.compile(r"^\s*\[[0-9:.\s\->]*\]\s*")


def _last_text_line(raw: str) -> str:
    """从引擎输出里取**最后一行识别文本**，剥掉时间戳前缀、跳过引擎日志。

    为什么取最后一行：whisper.cpp 默认会打印模型加载等日志，
    识别结果在最后。若引擎给了多行识别结果，取最后一行也符合"当前这一句"的语义
    （端侧是**按住说话、松手识别**，一次只对应一句话）。
    """
    for line in reversed((raw or "").splitlines()):
        cleaned = _TIMESTAMP_PREFIX.sub("", line).strip()
        if not cleaned:
            continue
        lowered = cleaned.lower()
        # 跳过引擎自身的日志行
        if lowered.startswith(("whisper_", "main:", "error", "warning")):
            continue
        return cleaned
    return ""


def suffix_for(filename: str, content_type: str = "") -> str:
    """从文件名或 Content-Type 推扩展名（引擎对格式敏感，必须给对后缀）。"""
    name = (filename or "").lower()
    for suffix in SUPPORTED_SUFFIXES:
        if name.endswith(suffix):
            return suffix
    kind = (content_type or "").lower()
    if "wav" in kind:
        return ".wav"
    if "mpeg" in kind or "mp3" in kind:
        return ".mp3"
    if "mp4" in kind or "m4a" in kind or "aac" in kind:
        return ".m4a"
    if "ogg" in kind:
        return ".ogg"
    if "webm" in kind:
        return ".webm"
    # 兜底用 wav：端侧录音最容易给的就是 wav / pcm
    return ".wav"


def build_asr_provider() -> AsrProvider:
    """按环境变量装配 ASR。

    优先级（显式指定 > 托管 > URL > 命令行 > Null）：
      BILIN_ASR_PROVIDER=qwen  → DashScope 通义千问（复用 DASHSCOPE_API_KEY）
      BILIN_ASR_URL            → 本地/内网 ASR 服务
      BILIN_ASR_CMD            → 本机命令行引擎（whisper.cpp 等）
      都不配                   → NullAsrProvider（端侧提示"暂时听不清"，仍可打字）
    """
    kind = (os.environ.get("BILIN_ASR_PROVIDER") or "").strip().lower()
    # 延迟导入（避免循环导入，见文件顶部说明）
    from .qwen_asr import QwenAsrProvider

    if kind in ("qwen", "dashscope", "qwen3-asr", "qwen3-asr-flash"):
        return QwenAsrProvider()
    if kind in ("whisper.cpp", "whispercpp", "command", "cli"):
        command = (os.environ.get("BILIN_ASR_CMD") or "").strip()
        return CommandAsrProvider(command) if command else NullAsrProvider()
    # 没显式指定时：配了 URL 用 URL，配了 CMD 用 CMD；否则托管（有 key 就用）
    url = (os.environ.get("BILIN_ASR_URL") or "").strip()
    if url:
        return HttpAsrProvider(url)
    command = (os.environ.get("BILIN_ASR_CMD") or "").strip()
    if command:
        return CommandAsrProvider(command)
    if _dashscope_ready():
        return QwenAsrProvider()
    return NullAsrProvider()


def _dashscope_ready() -> bool:
    """有 key 且 SDK 在 → 可以直接走托管 ASR。"""
    if not (os.environ.get("DASHSCOPE_API_KEY") or "").strip():
        return False
    from .qwen_asr import sdk_available

    return sdk_available()


def describe() -> dict:
    """给 `/healthz` 用：如实反映 ASR 是"真跑"还是"降级"。"""
    provider = build_asr_provider()
    ready = not isinstance(provider, NullAsrProvider)
    info = {
        "asr": type(provider).__name__,
        "asrReady": ready,
        "note": ("未配置时老人端提示『暂时听不清』，仍可打字；不影响其他功能"
                 if not ready else "语音识别已启用"),
    }
    if ready:
        # 引擎是否真的可执行 —— 不实际跑一次，只报配置（避免 healthz 变慢）
        info["source"] = "command" if isinstance(provider, CommandAsrProvider) else "http"
    return info


def parse_engine_json(raw: str) -> dict:
    """解析引擎可能输出的 JSON（部分引擎给 `{"text": ...}`）。

    单独抽出来是为了**可测**：命令行的输出格式五花八门，
    解析逻辑必须能被单元测试覆盖，而不是埋在 subprocess 调用里。
    """
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if isinstance(payload, dict):
        return payload
    return {}
