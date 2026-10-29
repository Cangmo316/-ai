"""智能体循环：让模型**自己决定**查什么、写什么，然后再回答。

## 为什么做成"包装器"

编排层（`service.py`）已经有一整套东西：开头称呼闸门、表情标签抽取、
标点平滑、截断续写、合规扫描……它们都建立在 `provider.stream(messages)`
这个契约上。

所以这里**不另开一条链路**，而是实现一个同契约的 `AgentProvider`：
它对内调真 provider 并插入工具循环，对外仍然只吐文本增量。
好处是上面那些逻辑一行都不用改，也就不会回归。

## 一轮对话实际发生什么

    ① 请求带 tools → 模型要么直接回答，要么返回 tool_calls
    ② 有 tool_calls → 执行 → 把结果以 role=tool 追加 → 再请求
    ③ 反复最多 max_steps 次 → 最后强制不带工具，让它把话说完整

## 两条安全边界

1. **工具结果不含病历原文**（注册表里已限制字段），避免"查一次多传一份敏感数据"
2. **工具调用全程留痕**：`trail` 记录每一步的工具名与参数，便于复盘"它为什么这么答"
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

from ..llm.base import LLMProvider
from ..tools import ToolContext, execute, openai_tools

logger = logging.getLogger("bilin.agent")

DEFAULT_MAX_STEPS = 3

#: 工具可用时追加到系统提示词末尾。
#: 实测教训：只把 `tools` 放进请求还不够 —— 产品提示词全是人设与边界规则，
#: 模型不知道"可以查"，就会凭上下文猜（"我这儿查不出吃没吃"）。
#: 必须显式告诉它"需要真实数据就调工具、闲聊别调"。
TOOL_GUIDE = """

【你有工具可用】
回答前如果需要**真实数据**，必须先调用工具，不要凭印象或猜测：
· 今天有什么安排 / 某件事做了没 → get_today_plan
· 最近一次测量数值 → get_recent_vitals
· 老人的基本情况 → get_profile
· 这周坚持得怎么样 → get_week_completion
· 以前聊过哪些话题 → get_recent_chat_topics
· 老人说了值得长期记住的事（家人、病情、爱好、忌讳）→ remember_fact
· 老人说"吃了""量过了"→ 先用 get_today_plan 拿到条目 id，再 check_in_plan_item

纯闲聊、安慰、常识问题**不要**调工具，直接说话。
工具查不到就如实说没记录，不要编数值。"""


class AgentProvider(LLMProvider):
    """带工具循环的 provider 包装器。对外契约与普通 provider 完全一致。"""

    name = "agent"

    def __init__(
        self,
        inner: LLMProvider,
        context: ToolContext,
        *,
        max_steps: int = DEFAULT_MAX_STEPS,
        on_tool: Callable[[dict], None] | None = None,
    ) -> None:
        self.inner = inner
        self.context = context
        self.max_steps = max(1, max_steps)
        self.on_tool = on_tool
        #: 本轮走过的工具调用（供上层记录/测试断言）
        self.trail: list[dict] = []

    async def stream(
        self,
        messages: list[dict],
        on_finish: Callable[[str], None] | None = None,
    ) -> AsyncIterator[str]:
        tools = openai_tools()
        convo = list(messages)

        for step in range(self.max_steps):
            calls: list[dict] = []
            text_parts: list[str] = []

            async for chunk in self._call(self.inner, convo, tools, calls, on_finish):
                text_parts.append(chunk)
                yield chunk

            if not calls:
                # 模型直接答完了：这一轮的文本就是最终答案
                return

            # 有工具调用：把这一轮说过的话当"前言"丢掉（它只是过渡语），
            # 只保留 tool_calls 放进对话，避免下一轮把前言再复述一遍。
            convo = convo + [
                {
                    "role": "assistant",
                    "content": "".join(text_parts).strip(),
                    "tool_calls": [
                        {
                            "id": call.get("id") or "call_%d" % index,
                            "type": "function",
                            "function": {
                                "name": call.get("name") or "",
                                "arguments": call.get("arguments") or "{}",
                            },
                        }
                        for index, call in enumerate(calls)
                    ],
                }
            ]

            for index, call in enumerate(calls):
                name = call.get("name") or ""
                raw_args = call.get("arguments") or "{}"
                result = execute(name, raw_args, self.context)
                record = {
                    "step": step,
                    "name": name,
                    "arguments": raw_args,
                    "ok": bool(result.get("ok", True)),
                }
                self.trail.append(record)
                logger.info(
                    "智能体调用工具 %s（会话上下文 elder=%s）结果 ok=%s",
                    name,
                    self.context.elder_id,
                    record["ok"],
                )
                if self.on_tool is not None:
                    self.on_tool(record)
                convo = convo + [
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id") or "call_%d" % index,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                ]

        # 步数用尽：最后强制"不带工具"地要一个答案，保证老人不会收到空回复
        logger.warning("智能体达到最大步数 %d，强制收口", self.max_steps)
        async for chunk in self._call(self.inner, convo, None, None, on_finish):
            yield chunk

    # ---------------------------------------------------------------- 内部

    async def _call(
        self,
        provider: LLMProvider,
        convo: list[dict],
        tools: list[dict] | None,
        sink: list[dict] | None,
        on_finish: Callable[[str], None] | None,
    ) -> AsyncIterator[str]:
        """调一次底层 provider。带 tools 时必须同时支持 tool_sink。"""
        if tools and sink is not None and self._supports_tools(provider):
            async for chunk in provider.stream(convo, on_finish=on_finish, tools=tools, tool_sink=sink):
                yield chunk
            return

        # 没传工具 / provider 不支持工具：退回原来的纯文本流（内置 fake 走这里）
        if on_finish is None:
            async for chunk in provider.stream(convo):
                yield chunk
        else:
            async for chunk in provider.stream(convo, on_finish=on_finish):
                yield chunk

    @staticmethod
    def _supports_tools(provider: LLMProvider) -> bool:
        import inspect

        try:
            params = inspect.signature(provider.stream).parameters
        except (TypeError, ValueError):
            return False
        return "tools" in params or any(p.kind is p.VAR_KEYWORD for p in params.values())


def _unused(*_args: Any) -> None:
    """占位，避免 lint 报未使用导入。"""
