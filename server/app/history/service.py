"""
比邻AI · 对话历史压缩服务

负责三件事：
  1. 判断该不该压（超过阈值）
  2. 压（调模型，把旧对话变摘要）
  3. 存取摘要（按会话 id）

## 为什么压缩要异步

压缩要调模型，几百毫秒到几秒。挂在老人的请求里，他会明显感觉"这次回得慢"。
所以放在回复发完之后的后台任务里跑 —— 摘要晚一轮生效完全可以接受
（这一轮本来也要带最近 8 轮原文）。

## 摘要为什么按"会话"存而不是按"老人"

同一个老人可能有多个会话（跟 AI 聊、跟不同家人聊），
各会话的上下文不该混在一起。所以按 conversation_id 存。
"""

from __future__ import annotations

import asyncio
import logging

from .compactor import (
    DEFAULT_KEEP_RECENT,
    DEFAULT_THRESHOLD,
    build_compress_messages,
    build_turns,
    parse_summary,
    should_compress,
    split_for_compress,
)

logger = logging.getLogger("bilin.history")


class HistoryCompactor:
    """对话历史压缩器。"""

    def __init__(
        self,
        store,
        *,
        threshold: int = DEFAULT_THRESHOLD,
        keep_recent: int = DEFAULT_KEEP_RECENT,
    ) -> None:
        #: 消息存储（要有 history/append 等接口，这里只用 history）
        self.store = store
        self.threshold = max(4, int(threshold))
        self.keep_recent = max(2, int(keep_recent))
        #: 会话 id → 摘要
        self._summaries: dict[str, str] = {}
        #: 正在压缩的会话（避免同一会话并发压两次，压出两份互相覆盖的摘要）
        self._busy: set[str] = set()
        self._tasks: set[asyncio.Task] = set()

    # ---------------------------------------------------------------- 摘要
    def summary_of(self, conversation_id: str) -> str:
        return self._summaries.get(str(conversation_id or ""), "")

    def set_summary(self, conversation_id: str, text: str) -> None:
        key = str(conversation_id or "")
        if not key:
            return
        body = str(text or "").strip()
        if body:
            self._summaries[key] = body
        else:
            self._summaries.pop(key, None)

    # ---------------------------------------------------------------- 触发
    def maybe_compress(self, conversation_id: str, provider) -> None:
        """如果这个会话的历史超过阈值，就把旧的那段压掉（后台跑）。"""
        key = str(conversation_id or "")
        if not key or provider is None:
            return
        # 同一会话已经在压，就别再起一个（否则两份摘要互相覆盖）
        if key in self._busy:
            return
        try:
            messages = self.store.history(key, limit=0)
        except Exception:  # noqa: BLE001 —— 取历史失败不影响对话
            logger.exception("读历史失败，跳过本轮压缩")
            return
        if not should_compress(len(messages), self.threshold):
            return

        old, _recent = split_for_compress(messages, self.keep_recent)
        if len(old) < 2:
            return

        self._busy.add(key)
        try:
            task = asyncio.create_task(self._compress(key, old, provider))
        except RuntimeError:
            self._busy.discard(key)
            logger.debug("没有事件循环，跳过压缩")
            return
        self._tasks.add(task)

        def _done(t: asyncio.Task) -> None:
            self._tasks.discard(t)
            self._busy.discard(key)

        task.add_done_callback(_done)

    async def _compress(self, conversation_id: str, old_messages: list, provider) -> None:
        """真正压缩：旧消息 → 摘要。失败只记日志，下一轮还会再试。"""
        turns = build_turns(old_messages)
        if not turns:
            return
        previous = self.summary_of(conversation_id)
        try:
            chunks: list[str] = []
            async for delta in provider.stream(build_compress_messages(turns, previous)):
                chunks.append(delta)
                # 摘要本身该很短；跑太长说明模型跑偏了，及时止损
                if sum(len(c) for c in chunks) > 2400:
                    break
            summary = parse_summary("".join(chunks))
        except Exception:  # noqa: BLE001 —— 压缩失败不影响对话，下轮重试
            logger.exception("对话压缩失败（会话 %s）", conversation_id)
            return

        if not summary:
            logger.info("压缩产出为空，保持原摘要（会话 %s）", conversation_id)
            return
        self.set_summary(conversation_id, summary)
        logger.info(
            "已压缩对话历史：%d 条 → %d 字摘要（会话 %s）",
            len(old_messages), len(summary), conversation_id,
        )

    # ---------------------------------------------------------------- 测试
    async def drain(self) -> None:
        """等所有后台压缩任务结束（测试用）。"""
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
