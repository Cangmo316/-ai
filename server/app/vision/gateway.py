"""
比邻AI · 识图（读医院单据的照片）

## 为什么需要这一层

医院给的多数是**纸质单据拍的照片**（或者整页扫描的 PDF）——这类东西没有文本层，
纯文本模型一个字也读不到。老人不会打字，更不会把病历敲一遍。
所以"拍照 → 读出上面的字"是刚需，不是锦上添花。

## 为什么走 dashscope 的 Qwen-VL

  · `dashscope` **已经是本项目的依赖**（TTS 在用，见 app/voice/qwen_tts.py），
    再引一个多模态 SDK 等于多一套鉴权、多一份 requirements
  · 当前对话模型（deepseek-chat）**不是多模态的**，不能拿它识图
  · 同一个 key（DASHSCOPE_API_KEY）已经配好了，零额外配置

## 没配 key 时怎么办

返回 `NullVisionProvider`，`describe()` 里说明"未配置"。
调用方据此给老人一句人话（"拍照识别还没开通，你可以手动写一下"），
**而不是报一个 500 让他对着空白页发呆**。
"""

from __future__ import annotations

import abc
import asyncio
import base64
import logging
import os
import re
from dataclasses import dataclass

logger = logging.getLogger("bilin.vision")

#: 识别用的默认模型。
#:
#: **必须是稳定版标题，不能用 `-latest` 别名**：实测本项目的 key 是"工作区专属 key"
#: （`sk-ws-` 前缀），`qwen-vl-max-latest` / `qwen-vl-plus-latest` 会返回
#: 403 `access_denied`，而 `qwen-vl-max` / `qwen-vl-plus` / `qwen3-vl-plus` 正常。
#: 用别名会在换 key / 换工作区时静默失效，不如钉住一个确认可用的模型。
DEFAULT_MODEL = "qwen-vl-max"

#: 允许的图片类型与大小上限
ALLOWED_MIME = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/bmp": "bmp",
}
MAX_IMAGE_BYTES = 8 * 1024 * 1024

#: 提示词：把"读出单据上的字"这件事讲具体，并要求**不许编**
#: （医院单据上数字错一位就是大事，宁可说看不清）
DEFAULT_PROMPT = (
    "这是一张医院单据或检查报告的照片。请把上面的文字**如实**读出来，要求：\n"
    "1. 先给「主要信息」：医院名称、日期、科别、诊断/结论\n"
    "2. 再给「检查结果」：逐项列出指标名、数值、单位、参考范围（有就给）\n"
    "3. 再给「用药」：药名、剂量、用法（有就给）\n"
    "4. 看不清的字写「看不清」，**绝对不要猜、不要补全**\n"
    "5. 不要给任何医学判断或建议，你只负责读字\n"
    "只输出读到的内容，不要寒暄。"
)


@dataclass
class VisionResult:
    ok: bool
    text: str = ""
    reason: str = ""
    model: str = ""


class VisionProvider(abc.ABC):
    """识图能力的统一接口"""

    name: str = "vision"

    @abc.abstractmethod
    async def read_image(self, data: bytes, mime: str, prompt: str = "") -> VisionResult:
        ...

    def describe(self) -> dict:
        return {"provider": self.name}


class NullVisionProvider(VisionProvider):
    """没配 key 时的占位：明确说"没开通"，不装成识别成功"""

    name = "NullVisionProvider"

    def __init__(self, reason: str = "未配置 DASHSCOPE_API_KEY，拍照识别还没开通") -> None:
        self.reason = reason

    async def read_image(self, data: bytes, mime: str, prompt: str = "") -> VisionResult:
        return VisionResult(ok=False, reason=self.reason)

    def describe(self) -> dict:
        return {"provider": self.name, "ready": False, "note": self.reason}


class QwenVisionProvider(VisionProvider):
    """dashscope 的 Qwen-VL 多模态识图"""

    name = "QwenVisionProvider"

    def __init__(self, api_key: str = "", model: str = "", timeout_s: float = 60.0) -> None:
        self.api_key = api_key or os.environ.get("DASHSCOPE_API_KEY", "")
        self.model = model or os.environ.get("BILIN_VISION_MODEL") or DEFAULT_MODEL
        self.timeout_s = timeout_s
        self._sdk = None

    def ready(self) -> bool:
        return bool(self.api_key)

    def _load_sdk(self):
        if self._sdk is None:
            import dashscope  # noqa: PLC0415 —— 可选依赖，用到才 import

            dashscope.api_key = self.api_key
            self._sdk = dashscope
        return self._sdk

    def _call_sync(self, data: bytes, mime: str, prompt: str) -> VisionResult:
        """同步调用（在线程里跑，见 read_image）"""
        try:
            dashscope = self._load_sdk()
        except ImportError:
            return VisionResult(ok=False, reason="没装 dashscope 库，拍照识别用不了")

        from dashscope import MultiModalConversation  # noqa: PLC0415

        data_uri = "data:" + mime + ";base64," + base64.b64encode(data).decode("ascii")
        messages = [
            {
                "role": "user",
                "content": [
                    {"image": data_uri},
                    {"text": prompt or DEFAULT_PROMPT},
                ],
            }
        ]

        try:
            response = MultiModalConversation.call(model=self.model, messages=messages)
        except Exception as exc:  # noqa: BLE001 —— SDK 会抛各种自家异常
            logger.warning("识图调用失败：%s", exc)
            return VisionResult(ok=False, reason="识图服务连不上，一会再试", model=self.model)

        status = getattr(response, "status_code", 0)
        if status != 200:
            code = str(getattr(response, "code", "") or "")
            message = getattr(response, "message", "") or code
            logger.warning("识图返回异常：status=%s code=%s message=%s", status, code, message)
            if status in (401, 403) or code in ("InvalidApiKey", "AccessDenied"):
                # 工作区专属 key 只能访问被授权的模型：模型名对了但没授权也会命中这里
                return VisionResult(
                    ok=False,
                    reason="识图服务没权限用这个模型，让家里人在设置里换一个模型",
                    model=self.model,
                )
            return VisionResult(ok=False, reason="识图没成功，一会再试", model=self.model)

        text = _pull_text(response)
        if not text.strip():
            return VisionResult(ok=False, reason="这张图上看不出字，换一张清楚点的", model=self.model)
        return VisionResult(ok=True, text=text.strip(), model=self.model)

    async def read_image(self, data: bytes, mime: str, prompt: str = "") -> VisionResult:
        if not self.api_key:
            return VisionResult(ok=False, reason="未配置识图密钥")
        # SDK 是同步阻塞的：丢到线程里，别把事件循环卡住（否则整站都变慢）
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._call_sync, data, mime, prompt)

    def describe(self) -> dict:
        return {"provider": self.name, "ready": self.ready(), "model": self.model}


def _pull_text(response) -> str:
    """从 dashscope 返回里取文本。

    返回结构在不同版本间有差异（content 里可能是 dict 列表），
    所以这里宽进：能取到 text 就取，取不到就拼接。
    """
    try:
        output = response.output
        choices = output.get("choices") if isinstance(output, dict) else getattr(output, "choices", None)
        if not choices:
            return ""
        message = choices[0].get("message") if isinstance(choices[0], dict) else choices[0].message
        content = message.get("content") if isinstance(message, dict) else message.content
    except (AttributeError, IndexError, KeyError, TypeError):
        return ""

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content or "")


def detect_mime(filename: str, provided: str = "") -> str:
    """判断图片类型：优先用调用方声明的，其次按扩展名猜"""
    if provided and provided in ALLOWED_MIME:
        return provided
    name = str(filename or "").lower()
    if name.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if name.endswith(".png"):
        return "image/png"
    if name.endswith(".webp"):
        return "image/webp"
    if name.endswith(".bmp"):
        return "image/bmp"
    return ""


def build_vision_provider(api_key: str = "") -> VisionProvider:
    """装配识图能力：有 key 就用 Qwen-VL，没有就返回明确说"没开通"的占位"""
    provider = QwenVisionProvider(api_key=api_key)
    if provider.ready():
        return provider
    logger.info("识图：未配置 DASHSCOPE_API_KEY，拍照识别不可用（其余功能不受影响）")
    return NullVisionProvider()


def is_pdf(mime: str, filename: str = "") -> bool:
    if mime == "application/pdf":
        return True
    return str(filename or "").lower().endswith(".pdf")


#: 从识别结果里抽"看起来像日期/诊断/数值"的行，用于给病历做标题
_DATE_RE = re.compile(r"(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})")
