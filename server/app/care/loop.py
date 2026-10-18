"""
比邻AI · 主动关心的后台循环

每 `CARE_TICK_SECONDS` 检查一次：该不该给老人主动发一句关心的话。
比调度器（30 秒）慢很多 —— 关心不需要秒级精确，
而且"到点必发"本身就像闹钟，慢一点反而更像人想起来问。

## 为什么不在请求链路里做

主动关心必须**自己发起**：老人不说话也得问。
所以只能靠后台循环，不能等他来请求。

## 发出去之后会怎样

插一条 AI 消息进他的会话 → 打开 App 就看到。
没有推送客户端也没关系，消息在会话里，下次打开就是新的。
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("bilin.care")

#: 检查间隔（秒）。10 分钟足够：关心是"想起来问一句"，不是定时器。
CARE_TICK_SECONDS = 600


class CareLoop:
    """在后台按时间检查"要不要主动关心"。"""

    def __init__(
        self,
        care,
        conversations,
        *,
        elder_ids: list[str],
        interval: float = CARE_TICK_SECONDS,
        push=None,
    ) -> None:
        self.care = care
        #: 会话存储（往里插 AI 消息，老人打开 App 就能看到）
        self.conversations = conversations
        self.elder_ids = [str(x) for x in (elder_ids or [])]
        self.interval = max(30.0, float(interval))
        self.push = push
        self._task: asyncio.Task | None = None
        self.ticks = 0
        self.last_asks: dict[str, str] = {}

    async def tick(self) -> list[dict]:
        """检查一轮。返回这一轮发出的提问（便于测试与调试）。"""
        self.ticks += 1
        sent: list[dict] = []
        for elder_id in self.elder_ids:
            try:
                # 先预览、投递成功才记账（见 CareService.preview_ask 的说明：
                # 投递失败却记了账，会把当天下一次提问堵死）
                ask = self.care.preview_ask(elder_id)
            except Exception:  # noqa: BLE001 —— 一个老人出错不能停掉整个循环
                logger.exception("主动关心检查失败（%s）", elder_id)
                continue
            if ask is None:
                continue
            if self._deliver(elder_id, ask):
                self.care.commit_ask(ask)
                sent.append(ask.to_dict())
                self.last_asks[elder_id] = ask.question
        if sent:
            logger.info("本轮主动关心发出 %d 条", len(sent))
        return sent

    def _deliver(self, elder_id: str, ask) -> bool:
        """把这条关心投递出去（进会话 + 可选推送）。"""
        conversation_id = self.care._conversations.get(str(elder_id or ""))
        if not conversation_id:
            # 还没跟他聊过，不知道往哪个会话里发。
            # 这种情况**跳过投递**（记录留着，等他第一次开口后自然会补）。
            logger.info("还没有会话，跳过主动关心的投递（%s）", elder_id)
            return False

        try:
            from ..models.message import Message, ROLE_AGENT, TYPE_TEXT

            self.conversations.append(
                conversation_id,
                Message(
                    id="a_care_" + ask.id,
                    role=ROLE_AGENT,
                    type=TYPE_TEXT,
                    text=ask.question,
                ),
            )
        except Exception:  # noqa: BLE001
            logger.exception("主动关心写入会话失败（%s）", elder_id)
            return False

        # 说明：这里**不做系统级推送**。
        # 项目目前的 push_client 是进程内的 SSE 长连接，没有 FCM/APNs，
        # 关掉 App 就收不到通知。所以投递只走"往会话里插一条消息"——
        # 老人下次打开 App 就能看到，效果上等于"它一直在惦记着我"。
        # 将来接了真正的推送通道，在这里补一行即可。
        return True

    async def run_forever(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("主动关心循环异常（继续跑）")
            await asyncio.sleep(self.interval)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run_forever())

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
