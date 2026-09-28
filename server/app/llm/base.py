"""LLM 提供者的统一接口与错误类型"""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator


class LLMError(Exception):
    """模型调用失败。

    上层据此下发 SSE `error` 事件。`message` 会**直接展示给老人**，
    所以必须是「服务器开小差了，一会儿再试」这种能听懂的话，不是异常堆栈。
    """

    def __init__(
        self,
        message: str,
        code: str = "llm_error",
        retryable: bool = True,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.retryable = retryable
        self.status_code = status_code

    def to_payload(self) -> dict:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


class LLMProvider(abc.ABC):
    """逐段产出文本增量的模型客户端。"""

    name: str = "provider"

    @abc.abstractmethod
    def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        """messages 为 OpenAI 风格：[{"role": "system"|"user"|"assistant", "content": str}]"""
        raise NotImplementedError

    def describe(self) -> dict:
        """给 /healthz 与启动日志用的自述（不得包含密钥明文）。"""
        return {"provider": self.name}
