"""
比邻AI · OpenAI 兼容协议的模型客户端

为什么选这个协议而不是绑定某一家 SDK：
DeepSeek、通义千问、Kimi、智谱、以及本地自建的 vLLM / Ollama / LM Studio 都提供
`/v1/chat/completions` 的 SSE 流式接口。写一份实现，换模型只改 `.env` 三行，
既符合「优先开源免费」也能在付费/自建之间随时切换。

注意两处与产品红线相关的处理：
1. **绝不把 `reasoning_content` 混进正文**。部分推理模型会在 delta 里同时给思维链与答案，
   思维链一旦下发到老人端，既听不懂又可能夹带体检/用药判断的措辞，越界风险很高。
   这里只取 `content`，其余字段一律丢弃。
2. 鉴权/额度类错误翻译成人话，不把 HTTP 原文抛给端侧。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from .base import LLMError, LLMProvider


class OpenAICompatProvider(LLMProvider):
    name = "openai_compat"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 30.0,
        temperature: float = 0.8,
        max_tokens: int = 300,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens
        # 注入传输层只为测试（httpx.MockTransport），生产路径不传
        self._transport = transport

    def describe(self) -> dict:
        # 只回显 model 与地址，密钥由 Settings.masked_api_key() 单独处理
        return {"provider": "openai_compat", "model": self.model, "base_url": self.base_url}

    @property
    def endpoint(self) -> str:
        return self.base_url + "/chat/completions"

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        if not self.api_key:
            raise LLMError("模型还没配置好，让家里人看一下", code="llm_auth", retryable=False)

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        headers = {
            "Authorization": "Bearer " + self.api_key,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        # 连接超时单独收紧：连不上要快速失败，别让老人对着空气等 30 秒
        timeout = httpx.Timeout(self.timeout, connect=min(10.0, self.timeout))
        client_kwargs: dict = {"timeout": timeout}
        if self._transport is not None:
            client_kwargs["transport"] = self._transport

        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                async with client.stream("POST", self.endpoint, json=payload, headers=headers) as response:
                    if response.status_code >= 400:
                        raise self._error_from_response(response.status_code, await response.aread())
                    async for line in response.aiter_lines():
                        chunk = self._parse_line(line)
                        if chunk:
                            yield chunk
        except LLMError:
            raise
        except httpx.TimeoutException as exc:
            raise LLMError("等我一下 我这边有点慢", code="llm_timeout", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise LLMError("我这边连不上网了，一会儿再试", code="llm_unavailable", retryable=True) from exc

    # ---------------------------------------------------------------- 内部

    def _parse_line(self, line: str) -> str:
        """解析一行 SSE。返回正文增量，无内容则返回空串。"""
        if not line:
            return ""
        line = line.strip()
        if not line or line.startswith(":"):
            return ""
        if line.startswith("data:"):
            line = line[len("data:") :].strip()
        if not line or line == "[DONE]":
            return ""
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            # 上游偶发的心跳/非 JSON 行：跳过，不让整条流失败
            return ""

        choices = payload.get("choices") or []
        if not choices:
            return ""
        delta = choices[0].get("delta") or {}
        # 只认 content；reasoning_content 等字段一律丢弃（见模块注释）
        content = delta.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            # 少数实现会把 content 拆成 [{type:text, text:...}]
            parts = [item.get("text", "") for item in content if isinstance(item, dict)]
            return "".join(parts)
        return ""

    def _error_from_response(self, status_code: int, body: bytes) -> LLMError:
        detail = ""
        try:
            parsed = json.loads(body.decode("utf-8", errors="replace"))
            detail = str((parsed.get("error") or {}).get("message") or "")
        except (json.JSONDecodeError, AttributeError):
            detail = body.decode("utf-8", errors="replace")[:200]

        if status_code in (401, 403):
            return LLMError(
                "模型还没配置好，让家里人看一下",
                code="llm_auth",
                retryable=False,
                status_code=status_code,
            )
        if status_code == 404:
            return LLMError(
                "模型名字不对，让家里人检查一下",
                code="llm_model_not_found",
                retryable=False,
                status_code=status_code,
            )
        if status_code == 429:
            return LLMError("说得太快了，歇一会儿再说", code="llm_rate_limited", retryable=True, status_code=status_code)
        if status_code >= 500:
            return LLMError("服务器开小差了，一会儿再试", code="llm_unavailable", retryable=True, status_code=status_code)
        message = "模型调用失败（" + str(status_code) + "）"
        if detail:
            message += "：" + detail
        return LLMError(message, code="llm_error", retryable=True, status_code=status_code)
