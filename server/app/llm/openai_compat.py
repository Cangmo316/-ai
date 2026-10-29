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
from collections.abc import AsyncIterator, Callable

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

    async def stream(
        self,
        messages: list[dict],
        on_finish: Callable[[str], None] | None = None,
        tools: list[dict] | None = None,
        tool_sink: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        """流式产出正文增量。

        ## tools / tool_sink：让模型**自己决定**调哪个工具

        传了 `tools`（OpenAI function 声明）后，模型可能不直接回答，而是返回
        `tool_calls`。流式协议里它是**分片**到达的（delta.tool_calls，按 index 累积），
        所以这里一边解析一边累积，结束前把完整调用列表塞进 `tool_sink`。

        ⚠️ 为什么用 `tool_sink`（调用方传入的列表）而不是返回值：
           `stream()` 的产出约定是 `str`，多处测试断言具体文本序列；
           改成产出事件对象会连带破坏它们。传列表是**可选**参数，
           不传时行为与以前完全一致。

        ⚠️ 为什么不放 self 上：provider 实例被缓存、内置的那个还跨账号共享，
           存实例会在并发下互相覆盖。

        ## on_finish：把"为什么停下来"告诉调用方

        OpenAI 兼容流在最后一片里带 `finish_reason`：
          · `"stop"`   —— 模型自然说完了
          · `"length"` —— **撞上 max_tokens 被硬切断**（端上看到的半句话就是这个）

        这个信息以前被 `_parse_line` 丢掉了，于是编排层没法知道"这句话是没说完的"，
        只能把半句直接发给老人。

        ⚠️ 为什么用回调而不是把它变成产出的一部分：
           `stream()` 产出 `str` 是既有契约，多处测试断言 `["妈"," 好"]` 这种序列，
           改产出类型会连带破坏它们。回调是**可选**的，不传的调用方行为完全不变。

        ⚠️ 为什么不存到 self 上：provider 实例被 `ProviderResolver` 缓存、
           内置那个还被所有账号共享，存实例会被并发请求互相覆盖。
           回调是请求级的，天然没有这个问题。
        """
        if not self.api_key:
            raise LLMError("模型还没配置好，让家里人看一下", code="llm_auth", retryable=False)

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            # 只有显式传了工具才带 tools 字段 —— 不带时请求体与以前逐字节一致
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
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
                    # 工具调用分片累积：key 是 index（同一次调用可能拆成多片）
                    pending_calls: dict[int, dict] = {}
                    async for line in response.aiter_lines():
                        chunk, reason, tool_deltas = self._parse_line_full(line)
                        for delta in tool_deltas:
                            index = int(delta.get("index") or 0)
                            slot = pending_calls.setdefault(
                                index, {"id": "", "type": "function", "name": "", "arguments": ""}
                            )
                            call_id = delta.get("id")
                            if call_id:
                                slot["id"] = call_id
                            fn = delta.get("function") or {}
                            if fn.get("name"):
                                slot["name"] = fn["name"]
                            if fn.get("arguments"):
                                slot["arguments"] += fn["arguments"]
                        if reason and on_finish is not None:
                            on_finish(reason)
                        if chunk:
                            yield chunk
                    # 流结束后把完整调用交出去（保持 index 顺序）
                    if tool_sink is not None and pending_calls:
                        for index in sorted(pending_calls):
                            call = pending_calls[index]
                            if call["name"]:
                                tool_sink.append(call)
        except LLMError:
            raise
        except httpx.TimeoutException as exc:
            raise LLMError("等我一下 我这边有点慢", code="llm_timeout", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise LLMError("我这边连不上网了，一会儿再试", code="llm_unavailable", retryable=True) from exc

    # ---------------------------------------------------------------- 内部

    def _parse_line(self, line: str) -> str:
        """解析一行 SSE。返回正文增量，无内容则返回空串。

        签名保持不变（别处与测试都在用）；需要 finish_reason 的场景
        走 `_parse_line_with_reason`。
        """
        return self._parse_line_with_reason(line)[0]

    def _parse_line_with_reason(self, line: str) -> tuple[str, str]:
        """解析一行 SSE，返回 (正文增量, finish_reason)。

        finish_reason 只在该片里出现时非空。调用方据此区分
        "模型自然说完（stop）"与"撞上 max_tokens 被切断（length）"。
        """
        text, reason, _tools = self._parse_line_full(line)
        return text, reason

    def _parse_line_full(self, line: str) -> tuple[str, str, list[dict]]:
        """解析一行 SSE，返回 (正文增量, finish_reason, 工具调用分片)。

        工具调用在流式里是 `delta.tool_calls` 数组，每片可能只带一部分
        （id / function.name / function.arguments 分几次到），
        由调用方按 index 累积 —— 这里只负责原样取出。
        """
        if not line:
            return "", "", []
        line = line.strip()
        if not line or line.startswith(":"):
            return "", "", []
        if line.startswith("data:"):
            line = line[len("data:") :].strip()
        if not line or line == "[DONE]":
            return "", "", []
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            # 上游偶发的心跳/非 JSON 行：跳过，不让整条流失败
            return "", "", []

        choices = payload.get("choices") or []
        if not choices:
            return "", "", []
        choice = choices[0]
        reason = str(choice.get("finish_reason") or "")
        delta = choice.get("delta") or {}
        raw_calls = delta.get("tool_calls")
        tool_deltas = [item for item in raw_calls if isinstance(item, dict)] if isinstance(raw_calls, list) else []
        # 只认 content；reasoning_content 等字段一律丢弃（见模块注释）
        content = delta.get("content")
        if isinstance(content, str):
            return content, reason, tool_deltas
        if isinstance(content, list):
            # 少数实现会把 content 拆成 [{type:text, text:...}]
            parts = [item.get("text", "") for item in content if isinstance(item, dict)]
            return "".join(parts), reason, tool_deltas
        return "", reason, tool_deltas

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
