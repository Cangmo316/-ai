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


class _CareTask:
    """把一次主动关心包装成 `PushChannel` 认的任务形状。

    为什么要这么绕：现有通道（`schedule/channels.py`）的签名是
    `deliver(task: ReminderTask, text)`，那里只用到 task 的
    elder_id / conversation_id / label / id 这几个字段。
    主动关心不是提醒，不该把自己伪装成 ReminderTask 进提醒表；
    所以只提供一个**同样字段的轻量对象**，通道那边一行都不用改。
    """

    __slots__ = ("elder_id", "conversation_id", "title", "id", "level", "plan_item_id", "send_at")

    def __init__(self, *, elder_id, conversation_id, text, task_id, send_at=""):
        self.elder_id = elder_id
        self.conversation_id = conversation_id
        # 通道用它当通知标题（见 UniPushChannel.deliver 的 task.label）
        self.title = text
        self.id = task_id
        self.level = "normal"
        self.plan_item_id = ""
        # InboxChannel 的日志里会打 send_at；关心没有"计划时间"，用当前时刻
        self.send_at = send_at

    @property
    def label(self) -> str:
        """UniPushChannel 读的是 task.label —— 关心不是"提醒"，用应用名。"""
        return "比邻AI"

    @property
    def level_label(self) -> str:
        """InboxChannel 的日志会打这个。关心不分级，给个中性值。"""
        return "关心"


class CareLoop:
    """在后台按时间检查"要不要主动关心"。"""

    def __init__(
        self,
        care,
        conversations,
        *,
        elder_ids=None,
        interval: float = CARE_TICK_SECONDS,
        channels=None,
    ) -> None:
        self.care = care
        #: 会话存储（往里插 AI 消息，老人打开 App 就能看到）
        self.conversations = conversations
        #: 推送通道（`schedule.channels.ChannelRegistry`）。
        #:
        #: 为什么复用它而不是另造一套：它已经有两级通道 ——
        #:   inbox   写会话（不依赖任何外部账号，一定留痕）
        #:   unipush 转发 uniCloud 云函数（关掉 App 也能收到系统通知）
        #: 提醒和关心共用同一条链路，凭证与降级逻辑只需维护一处。
        self.channels = channels
        #: 关心对象。可以是列表，也可以是**每轮重新算的函数**。
        #:
        #: 为什么要支持函数（需求："主动关心只对用户绑定的这个老人"）：
        #:   老人档案里有一堆 demo 老人，全问一遍就成了骚扰。
        #:   只关心"真的在用"的那一个 —— 判据是他在这个进程里聊过
        #:   （care._conversations 里有记录），那是唯一可靠的"绑定了"信号：
        #:   没聊过的人，我们连往哪个会话发都不知道。
        if callable(elder_ids):
            self._targets = elder_ids
        else:
            fixed = [str(x) for x in (elder_ids or [])]
            self._targets = lambda: list(fixed)
        self.interval = max(30.0, float(interval))
        self._task: asyncio.Task | None = None
        self.ticks = 0
        self.last_asks: dict[str, str] = {}

    def targets(self) -> list[str]:
        """这一轮该关心谁。"""
        try:
            return [str(x) for x in (self._targets() or [])]
        except Exception:  # noqa: BLE001 —— 算目标出错就当没人需要关心
            logger.exception("计算关心对象失败")
            return []

    async def tick(self) -> list[dict]:
        """检查一轮。返回这一轮发出的提问（便于测试与调试）。"""
        self.ticks += 1
        sent: list[dict] = []
        for elder_id in self.targets():
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
        """把这条关心投递出去（进会话 + 可选系统推送）。"""
        conversation_id = self.care._conversations.get(str(elder_id or ""))
        if not conversation_id:
            # 还没跟他聊过，不知道往哪个会话里发。
            # 这种情况**跳过投递**（记录留着，等他第一次开口后自然会补）。
            logger.info("还没有会话，跳过主动关心的投递（%s）", elder_id)
            return False

        # 有通道注册表就交给它：inbox 写会话 + unipush 发系统通知。
        # 没有（单测/未装配）就退回"只写会话"，行为与以前一致。
        if self.channels is not None:
            try:
                task = _CareTask(
                    elder_id=elder_id,
                    conversation_id=conversation_id,
                    text=ask.question,
                    task_id=ask.id,
                    send_at=ask.asked_at,
                )
                # 通道内部是 async（unipush 要发 HTTP）。不 await：
                # inbox 是同步写入，先落会话；推送在后台完成，不拖慢 tick。
                # 用 deliver_all 而不是 deliver —— 关心要**双通道**：
                # deliver 命中 inbox 就返回了，unipush 永远轮不到（见 channels.py）。
                result = self.channels.deliver_all(task, ask.question)
                if asyncio.iscoroutine(result):
                    push_task = asyncio.create_task(result)
                    push_task.add_done_callback(self._push_done)
                return True
            except Exception:  # noqa: BLE001 —— 通道出错也不能让关心流程挂住
                logger.exception("主动关心投递失败，退回只写会话（%s）", elder_id)

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
        return True

    @staticmethod
    def _push_done(task: asyncio.Task) -> None:
        try:
            result = task.result()
        except Exception:  # noqa: BLE001
            logger.info("主动关心推送异常（会话里的消息不受影响）")
            return
        if not getattr(result, "ok", False):
            logger.info("主动关心推送未成功：%s", getattr(result, "detail", ""))

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
