"""比邻AI · 阿里云百炼 Qwen-Audio-TTS Provider（托管路线）

选这条路的理由（用户 2026-10-05 决定）：**本机零安装**、且它**原生给字级时间戳**——
连"再跑一遍强制对齐"都省了。代价是音频出网 + 按字计费（与"自建 GPU 推理"的取向不同，
这是产品取舍，代码层不评判）。

## 与 CosyVoice 路线的结构差异（重要）

CosyVoice 那套是**两步**：先合成音频，再拿音频去 WhisperX/MFA 对齐。
Qwen-Audio-TTS 是**一步**：同一次 WebSocket 会话里，
音频走 `on_data(data)` 回调、字级时间戳走 `on_event(message)` 回调
（Python SDK 的 `on_event` **只给 message 字符串、不给音频**）。
所以本 Provider 把"音频 + 时间戳"一起收齐再返回，
上层不必再调 Aligner（`describe()` 会报 `alignReady: true` 表示"不需要额外对齐"）。

## 契约依据（阿里云官方文档，2026-09 更新）

- 模型名：`qwen-audio-3.0-tts-flash`（文档示例）；端点：`wss://…/api-ws/v1/inference`
- 字级时间戳：`additional_params={"word_timestamp_enabled": True}`
  —— **仅流式输出模式可用**（所以必须传 callback，不能走非流式 `call()`）
- 回调：`on_open` / `on_event(json字符串)` / `on_data(bytes音频)` / `on_complete` / `on_error` / `on_close`
- 时间戳位置：`payload.output.sentence.words[]`，每项含 `text` / `begin_time` / `end_time`（**毫秒**）
- 事件类型：`sentence-begin` / `sentence-synthesis` / `sentence-end`（**`sentence-end` 才带全量 words**）

⚠️ 文档未明确：**哪些音色支持字级时间戳**（只写"supported system voices 见音色列表"、
"cloned voices are supported"）。所以本模块在**拿不到 words 时明确降级**
（`word_timestamps_ok=False`），由上层回退到估算版口型，而不是假装成功。
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import tempfile
import threading

from .gateway import TtsProvider, TtsResult

logger = logging.getLogger(__name__)

# 文档示例用的模型名；实际可用 `BILIN_TTS_MODEL` 覆盖（百炼的模型名会随版本变化）
DEFAULT_MODEL = "qwen-audio-3.0-tts-flash"
# 默认音色（文档示例音色）
DEFAULT_VOICE = "longanhuan_v3.6"


def sdk_available() -> bool:
    """检查 dashscope SDK 是否装了。

    **不写进 requirements.txt**：仓库约定"只装四个包、能不装就不装"，
    而且托管路线是可选能力 —— 没装时明确降级，不因为缺依赖让服务起不来。
    用 `importlib.util.find_spec` 而不是 try-import：不触发真正的模块导入开销。
    """
    return importlib.util.find_spec("dashscope") is not None


def _extract_words_from_event(message: str) -> list[dict]:
    """从 `on_event` 的 JSON 里取出字级时间戳。

    容错点（照文档写但仍然防一手）：
    · `payload.output` 可能不存在（心跳/其他事件）
    · `sentence.words` 可能为空数组（音色不支持、或还是 `sentence-begin` 阶段）
    · 有的版本把时间戳放在 `payload.output.words`（顶层）—— 一并兼容
    """
    try:
        data = json.loads(message)
    except (TypeError, ValueError):
        return []
    payload = data.get("payload") if isinstance(data, dict) else None
    output = payload.get("output") if isinstance(payload, dict) else None
    if not isinstance(output, dict):
        return []
    candidates: list = []
    sentence = output.get("sentence")
    if isinstance(sentence, dict) and isinstance(sentence.get("words"), list):
        candidates = sentence["words"]
    elif isinstance(output.get("words"), list):
        candidates = output["words"]
    words: list[dict] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        text = item.get("text") or item.get("word") or ""
        begin = item.get("begin_time", item.get("beginTime"))
        end = item.get("end_time", item.get("endTime"))
        if not text or begin is None or end is None:
            continue
        try:
            words.append({"word": str(text), "start": float(begin), "end": float(end)})
        except (TypeError, ValueError):
            continue
    return words


def words_to_segments(words: list[dict]) -> list[dict]:
    """百炼的 words（毫秒、键名 begin/end）→ `from_alignment` 认的 segments（秒、键名 start/end）。

    为什么在这里转换而不是让 `from_alignment` 兼容两套键名：
    契约层只认一种形状（WhisperX 形状），转换放在"数据来源"这一侧，
    以后再加别的 TTS 只要各写各的转换、`from_alignment` 不用动。
    """
    segments: list[dict] = []
    for item in words or []:
        if not isinstance(item, dict):
            continue
        text = item.get("word") or item.get("text") or ""
        start = item.get("start")
        end = item.get("end")
        if not text or start is None or end is None:
            continue
        try:
            # 毫秒 → 秒（from_alignment 会按整批判定单位，两种都给得通，这里给秒更直观）
            segments.append({"word": str(text), "start": float(start) / 1000.0, "end": float(end) / 1000.0})
        except (TypeError, ValueError):
            continue
    return segments


class QwenTtsProvider(TtsProvider):
    """百炼 Qwen-Audio-TTS：一次调用同时拿到**音频**与**字级时间戳**。

    返回的 `TtsResult.extra` 里放 `word_segments`（WhisperX 形状），
    上层用 `from_alignment(...)` 直接转成 `lipsync` payload（`source: tts-aligned`）。
    """

    def __init__(self, model: str = DEFAULT_MODEL, voice: str = DEFAULT_VOICE,
                 api_key: str = "", region: str = "", timeout_s: float = 60.0):
        self.model = model or DEFAULT_MODEL
        self.voice = voice or DEFAULT_VOICE
        self.api_key = api_key or os.environ.get("DASHSCOPE_API_KEY", "")
        # 工作区专属域名（文档推荐）：不配就用 SDK 默认（北京）
        self.region = region or os.environ.get("BILIN_DASHSCOPE_WS_URL", "")
        self.timeout_s = timeout_s

    async def synthesize(self, text: str, voice: str = "") -> TtsResult:
        if not sdk_available():
            return TtsResult(ok=False, reason="未安装 dashscope SDK（pip install dashscope）")
        if not self.api_key:
            return TtsResult(ok=False, reason="未配置 DASHSCOPE_API_KEY")
        if not (text or "").strip():
            return TtsResult(ok=False, reason="文本为空")

        # 放到线程里跑：dashscope 的 SDK 是**同步 + 回调**模型，
        # 直接在事件循环里跑会阻塞整个 SSE 流（本项目对首包延迟有预算）。
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: self._synthesize_blocking(text, voice or self.voice)
        )

    def _synthesize_blocking(self, text: str, voice: str) -> TtsResult:
        """同步实现：收齐音频 + 字级时间戳。"""
        try:
            import dashscope
            from dashscope.audio.tts_v2 import AudioFormat, ResultCallback, SpeechSynthesizer
        except Exception as exc:  # noqa: BLE001
            return TtsResult(ok=False, reason="dashscope 导入失败：%s" % exc)

        dashscope.api_key = self.api_key
        if self.region:
            dashscope.base_websocket_api_url = self.region

        audio_chunks: list[bytes] = []
        words: list[dict] = []
        error_message: list[str] = []
        finished = threading.Event()

        class _Callback(ResultCallback):
            def on_open(self):
                pass

            def on_data(self, data: bytes) -> None:
                if data:
                    audio_chunks.append(bytes(data))

            def on_event(self, message) -> None:
                # 字级时间戳在 `sentence-end` 事件的 payload.output.sentence.words 里；
                # 逐事件累加即可（同一句不会重复给两遍全量）
                words.extend(_extract_words_from_event(message))

            def on_complete(self) -> None:
                finished.set()

            def on_error(self, message) -> None:
                error_message.append(str(message))
                finished.set()

            def on_close(self) -> None:
                finished.set()

        try:
            synthesizer = SpeechSynthesizer(
                model=self.model,
                voice=voice,
                # 字级时间戳开关（文档：仅流式输出模式可用 → 必须传 callback）
                additional_params={"word_timestamp_enabled": True},
                callback=_Callback(),
            )
            # 用 streaming_call + streaming_complete：文档说双向流式，
            # 且 `word_timestamp_enabled` 只在流式输出模式生效
            synthesizer.streaming_call(text)
            synthesizer.streaming_complete()
        except Exception as exc:  # noqa: BLE001
            return TtsResult(ok=False, reason="Qwen-Audio-TTS 调用异常：%s" % exc)

        if error_message:
            return TtsResult(ok=False, reason="Qwen-Audio-TTS 报错：%s" % error_message[0][:300])
        if not audio_chunks:
            return TtsResult(ok=False, reason="Qwen-Audio-TTS 没有返回音频")

        workdir = tempfile.mkdtemp(prefix="bilin-qwen-tts-")
        # 文档默认输出 MP3；落盘只为"给对齐/播放用"，扩展名跟着默认格式
        out_file = os.path.join(workdir, "output.mp3")
        with open(out_file, "wb") as handle:
            for chunk in audio_chunks:
                handle.write(chunk)

        segments = words_to_segments(words)
        return TtsResult(
            audio_path=out_file,
            duration_ms=0,          # MP3 头解析不做（要额外依赖）；时长由 words 的末尾给出
            ok=True,
            reason="" if segments else "本次未返回字级时间戳（该音色可能不支持）→ 口型将走估算版",
            extra={
                "word_segments": segments,
                "word_timestamps_ok": bool(segments),
                "model": self.model,
                "voice": voice,
            },
        )


def build_qwen_provider() -> TtsProvider:
    """按环境变量装配（缺 key 也不报错，返回 provider 由它自己报 not ok）。"""
    return QwenTtsProvider(
        model=os.environ.get("BILIN_TTS_MODEL") or DEFAULT_MODEL,
        voice=os.environ.get("BILIN_TTS_VOICE") or DEFAULT_VOICE,
        region=os.environ.get("BILIN_DASHSCOPE_WS_URL", ""),
    )
