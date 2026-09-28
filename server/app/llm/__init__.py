"""
比邻AI · LLM 抽象层

只暴露一个约定：`LLMProvider.stream(messages) -> AsyncIterator[str]`，逐段吐出文本增量。
上层（orchestration）不关心背后是谁——DeepSeek、通义、Kimi、本地 vLLM/Ollama 都走
OpenAI 兼容协议；没配 key 时走 fake，保证链路永远能跑通、测试永远不需要外网。
"""

from __future__ import annotations

from .base import LLMError, LLMProvider
from .fake import FakeProvider
from .openai_compat import OpenAICompatProvider

__all__ = ["LLMError", "LLMProvider", "FakeProvider", "OpenAICompatProvider", "build_provider"]


def build_provider(settings) -> LLMProvider:
    """按配置挑实现。auto 的解析在 Settings.resolved_provider 里。"""
    resolved = settings.resolved_provider
    if resolved == "openai_compat":
        return OpenAICompatProvider(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout=settings.llm_timeout,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
    return FakeProvider()
