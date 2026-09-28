"""
比邻AI · 提醒投递通道

设计成可插拔，是因为**能不能真推送到手机，取决于外部服务**：

| 通道 | 现状 | 说明 |
|---|---|---|
| `InboxChannel` | ✅ 已实现 | 站内消息：提醒写进会话，端侧拉取后展示（App 前台一定收得到） |
| `LogChannel` | ✅ 已实现 | 只记日志。开发期用，也当"其它通道全挂"时的兜底凭据 |
| 厂商推送（uni-push / 极光 / 个推 / 华为小米通道） | ⛔ 未接入 | **需要开发者账号与资质，部分功能收费**。按仓库约定「引入付费或受限许可组件前必须先确认」，等确认后再实现 |

补一个厂商通道只需要：实现 `PushChannel.deliver()`，在 `main.py` 里加进 `ChannelRegistry`。
任务的 `channel` 字段会记下是哪条通道送出去的，方便排查"到底推没推出去"。

**端侧本地提醒是另一条腿**：App 端应同时注册本地定时通知（推送丢了也能响）。
当前端侧只做了前台轮询 + 震动 + 提醒条——本地通知需要真机验证 `plus.push` 的能力与字段，
未做（见 server/README.md 的待验证清单），不写成看起来能用、实际没验过的代码。
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass

from ..models.message import ROLE_AGENT, TYPE_TEXT, Message, new_id
from .models import ReminderTask

logger = logging.getLogger("bilin.schedule")


@dataclass
class ChannelResult:
    ok: bool
    channel: str
    message_id: str = ""
    detail: str = ""


class PushChannel(abc.ABC):
    name: str = "channel"

    @abc.abstractmethod
    async def deliver(self, task: ReminderTask, text: str) -> ChannelResult:
        """把一条提醒送出去。返回 ok=False 时任务保持待投递，下一个 tick 会重试。"""
        raise NotImplementedError

    def describe(self) -> dict:
        return {"name": self.name}


class InboxChannel(PushChannel):
    """站内消息通道：写进老人的会话。

    为什么把它当主通道：它不依赖任何外部账号，端侧拉会话历史或轮询收件箱都能拿到，
    而且**留痕**——"提醒发过没有"随时可查。真接了厂商推送之后，它就是"双保险"里的第二条。
    """

    name = "inbox"

    def __init__(self, conversations) -> None:
        self.conversations = conversations

    async def deliver(self, task: ReminderTask, text: str) -> ChannelResult:
        message = Message(
            id=new_id("m"),
            role=ROLE_AGENT,
            type=TYPE_TEXT,
            text=text,
        )
        self.conversations.append(task.conversation_id, message)
        logger.info(
            "提醒已写入会话：%s → %s（%s %s，%s）",
            task.send_at,
            task.conversation_id,
            task.level_label,
            task.title,
            task.id,
        )
        return ChannelResult(ok=True, channel=self.name, message_id=message.id)


class LogChannel(PushChannel):
    """只记日志。开发期与测试用；也是没有可用通道时的最后一条腿。"""

    name = "log"

    async def deliver(self, task: ReminderTask, text: str) -> ChannelResult:
        logger.info(
            "[提醒] %s %s %s | %s",
            task.send_at,
            task.level_label,
            task.elder_id,
            text,
        )
        return ChannelResult(ok=True, channel=self.name)


class ChannelRegistry:
    """多通道投递：任一通道成功即算投递成功（这是"双保险"的服务端侧）。"""

    def __init__(self, channels: list[PushChannel] | None = None) -> None:
        self.channels: list[PushChannel] = list(channels or [])

    def add(self, channel: PushChannel) -> None:
        self.channels.append(channel)

    def describe(self) -> list[dict]:
        return [channel.describe() for channel in self.channels]

    async def deliver(self, task: ReminderTask, text: str) -> ChannelResult:
        if not self.channels:
            return ChannelResult(ok=False, channel="", detail="没有可用通道")
        last = ChannelResult(ok=False, channel="", detail="")
        for channel in self.channels:
            try:
                result = await channel.deliver(task, text)
            except Exception:  # noqa: BLE001 —— 一条通道挂掉不能拖垮整次投递
                logger.exception("通道 %s 投递失败", channel.name)
                continue
            if result.ok:
                return result
            last = result
        return last
