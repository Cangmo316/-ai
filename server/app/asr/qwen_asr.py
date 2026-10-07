"""
比邻AI · 语音识别（ASR）：DashScope 通义千问 `qwen3-asr-flash`

## 为什么走托管而不是本地 whisper

与 TTS 同一个理由（见 `app/voice/qwen_tts.py`）：本地 whisper 要先下模型、要 GPU，
原型阶段不划算。这个 key 已经为 TTS / 识图配过了，复用即可。

## 调用形状（实测出来的，不是照文档猜的）

    MultiModalConversation.call(
        model="qwen3-asr-flash",
        messages=[{"role": "user", "content": [{"audio": "data:audio/mp3;base64,…"}]}],
    )

⚠️ **不要带 `system` 消息**。实测带上之后返回：

    <400> InternalError.Algo.InvalidParameter: The dedicated task `asr` co…

去掉 system 消息后同一个模型立刻返回 200。文档里的示例各版本不一，
这里以**本工作区实测通过**的写法为准。

## 返回结构

    output.choices[0].message.content = [{"text": "今天天气不错，我吃过药了。"}]
    output.choices[0].message.annotations = [{"emotion": "happy", "language": "zh", …}]

`content` 在不同版本里可能是 list 也可能是 str，两种都兼容。
"""

from __future__ import annotations

import base64
import importlib.util
import logging
import os
from pathlib import Path

from .gateway import AsrProvider, AsrResult

logger = logging.getLogger(__name__)

#: 模型名。可用 `BILIN_ASR_MODEL` 覆盖。
DEFAULT_MODEL = "qwen3-asr-flash"

#: 扩展名 → MIME。data URL 里必须给对，否则服务端解码失败。
_MIME = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".aac": "audio/aac",
    ".wav": "audio/wav",
    ".pcm": "audio/wav",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".amr": "audio/amr",
    ".webm": "audio/webm",
}


def sdk_available() -> bool:
    """dashscope SDK 装了吗（与 TTS 共用同一个包）。"""
    return importlib.util.find_spec("dashscope") is not None


def _mime_of(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return _MIME.get(suffix, "audio/mpeg")


def _text_of(output) -> str:
    """从 output 里取识别文本。兼容 content 是 list / str 两种形态。"""
    try:
        choices = output["choices"] if isinstance(output, dict) else getattr(output, "choices", None)
        if not choices:
            return ""
        message = choices[0].get("message") if isinstance(choices[0], dict) else choices[0].message
        content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
        if isinstance(content, list):
            return "".join(str(c.get("text") or "") for c in content if isinstance(c, dict)).strip()
        if isinstance(content, str):
            return content.strip()
    except Exception:  # noqa: BLE001 —— 结构变了不该炸，交给上层当"没识别出来"
        logger.exception("解析 ASR 返回结构失败")
    return ""


class QwenAsrProvider(AsrProvider):
    """通义千问 ASR（`qwen3-asr-flash`）。"""

    def __init__(self, model: str = "", api_key: str = ""):
        self.model = (model or os.environ.get("BILIN_ASR_MODEL") or DEFAULT_MODEL).strip()
        self.api_key = (api_key or os.environ.get("DASHSCOPE_API_KEY") or "").strip()

    async def transcribe(self, audio_path: str, language: str = "zh") -> AsrResult:
        if not sdk_available():
            return AsrResult(ok=False, reason="没装 dashscope SDK")
        if not self.api_key:
            return AsrResult(ok=False, reason="没配 DASHSCOPE_API_KEY")
        try:
            raw = Path(audio_path).read_bytes()
        except OSError as exc:
            return AsrResult(ok=False, reason="读不到录音文件：%s" % exc)
        if not raw:
            return AsrResult(ok=False, reason="录音是空的")

        data_url = "data:%s;base64,%s" % (_mime_of(audio_path), base64.b64encode(raw).decode())

        # SDK 是同步的；放线程池里跑，别把事件循环堵住（一次识别可能几秒）
        import anyio

        def _call():
            from dashscope import MultiModalConversation

            return MultiModalConversation.call(
                model=self.model,
                # ⚠️ 不要加 system 消息，见模块开头的实测说明
                messages=[{"role": "user", "content": [{"audio": data_url}]}],
                api_key=self.api_key,
            )

        try:
            response = await anyio.to_thread.run_sync(_call)
        except Exception as exc:  # noqa: BLE001 —— 识别失败不能影响 App 其他功能
            logger.exception("ASR 调用异常")
            return AsrResult(ok=False, reason="识别调用异常：%s" % exc)

        status = getattr(response, "status_code", None)
        if status != 200:
            message = str(getattr(response, "message", "") or "")
            return AsrResult(ok=False, reason="识别服务返回 %s：%s" % (status, message[:120]))

        text = _text_of(getattr(response, "output", None))
        if not text:
            return AsrResult(ok=False, reason="没听清，再说一遍试试")
        return AsrResult(text=text, ok=True, language=language or "zh")
