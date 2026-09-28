"""
比邻AI · 提醒投递通道

设计成可插拔，是因为**能不能真推送到手机，取决于外部服务**：

| 通道 | 现状 | 说明 |
|---|---|---|
| `InboxChannel` | ✅ 已实现 | 站内消息：提醒写进会话，端侧拉取后展示（App 前台一定收得到） |
| `UniPushChannel` | ✅ 已实现，**待你开通 uni-push** | 转发给 uniCloud 云函数发 uni-push 2.0；需要 DCloud appid + 云函数 URL |
| `LogChannel` | ✅ 已实现 | 只记日志。开发期用，也当"其它通道全挂"时的兜底凭据 |

补一个厂商通道只需要：实现 `PushChannel.deliver()`，在 `main.py` 里加进 `ChannelRegistry`。
任务的 `channel` 字段会记下是哪条通道送出去的，方便排查"到底推没推出去"。

**端侧本地提醒是另一条腿**：App 端用 `uni.createPushMessage({delay})` 预排本地通知栏消息，
推送丢了、断网了也能响（见 `uni-app/stores/push.js`）。它只在 App 端有效，
H5/小程序会安全跳过。
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


class UniPushChannel(PushChannel):
    """uni-push 2.0 通道：把提醒转给一个 uniCloud 云函数去发。

    **为什么是"转发给云函数"而不是自己调个推**（已核实官方文档）：
    1. uni-push 2.0 的服务端 SDK（`uni-cloud-push`）**只跑在 uniCloud 云函数里**；
       自建服务器想直连个推，文档明确要求改用老版 uni-push 1.0 的凭证体系
    2. 个推的 appkey / mastersecret 属于高敏感凭证，放在云函数的环境里比放在业务服务器上更安全
       —— 我们这边只需要一个「云函数 URL + 自定义校验 token」

    对应的云函数参考实现见 `server/deploy/unipush-cloudfunction/`。

    没配置 `UNIPUSH_SEND_URL` 时**绝不假装成功**：返回 ok=False，让 `ChannelRegistry`
    继续走站内消息通道（这样"没接推送"和"推送挂了"在日志里是两回事）。
    """

    name = "unipush"

    def __init__(
        self,
        send_url: str = "",
        token: str = "",
        registry=None,
        timeout: float = 10.0,
        force_notification: bool = True,
        poster=None,
    ) -> None:
        self.send_url = (send_url or "").strip()
        self.token = (token or "").strip()
        self.registry = registry
        self.timeout = timeout
        # 在线时不加这个参数就不会创建通知栏消息（老人可能根本没看手机），
        # 提醒类消息要"一定响"，所以默认打开；代价是前台可能同时看到提醒条与通知
        self.force_notification = force_notification
        self._poster = poster or _httpx_post

    @property
    def configured(self) -> bool:
        return bool(self.send_url)

    def describe(self) -> dict:
        return {
            "name": self.name,
            "configured": self.configured,
            "clients": self.registry.counts() if self.registry else {},
        }

    async def deliver(self, task: ReminderTask, text: str) -> ChannelResult:
        if not self.configured:
            return ChannelResult(ok=False, channel=self.name, detail="未配置 UNIPUSH_SEND_URL")
        if not self.registry:
            return ChannelResult(ok=False, channel=self.name, detail="没有推送客户端登记表")

        clients = self.registry.clients_for(task.elder_id)
        if not clients:
            return ChannelResult(
                ok=False, channel=self.name, detail="这位老人还没登记推送标识（cid）"
            )

        sent = 0
        last_detail = ""
        for client in clients:
            payload = {
                "cid": client.cid,
                "title": task.label or "比邻AI 提醒",
                "content": text,
                "force_notification": self.force_notification,
                "payload": {
                    "type": "reminder",
                    "taskId": task.id,
                    "planItemId": task.plan_item_id,
                    "level": task.level,
                },
            }
            headers = {"Content-Type": "application/json"}
            if self.token:
                headers["Authorization"] = "Bearer " + self.token
            try:
                status, body = await self._poster(self.send_url, payload, headers, self.timeout)
            except Exception as exc:  # noqa: BLE001 —— 通道异常不能拖垮调度
                logger.exception("uni-push 云函数调用失败")
                last_detail = "云函数调用异常：" + str(exc)
                continue

            if status != 200:
                last_detail = "云函数返回 HTTP " + str(status) + "：" + str(body)[:120]
                continue
            # 云函数约定返回 {"code": 0, ...}；非 0 视为失败，把原文带回去方便排查
            if not _push_ok(body):
                last_detail = "云函数返回失败：" + str(body)[:120]
                continue
            sent += 1

        if sent:
            logger.info("uni-push 已投递 %s 台设备：%s", sent, text)
            return ChannelResult(
                ok=True,
                channel=self.name,
                message_id="unipush:" + task.id,
                detail="投递 " + str(sent) + " 台设备",
            )
        return ChannelResult(ok=False, channel=self.name, detail=last_detail or "没有可用设备")


def _push_ok(body) -> bool:
    """云函数返回体判定：兼容 {"code":0} 与直接返回字符串/True 的实现。"""
    if isinstance(body, bool):
        return body
    if isinstance(body, dict):
        if "code" in body:
            return body.get("code") in (0, "0")
        return bool(body.get("success", True))
    if isinstance(body, str):
        text = body.strip().lower()
        return text in ("", "ok", "true", "success") or '"code":0' in text.replace(" ", "")
    return True


async def _httpx_post(url: str, payload: dict, headers: dict, timeout: float):
    """默认 HTTP 实现（测试可注入 poster 替换掉，避免依赖外部服务）"""
    import httpx

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=payload, headers=headers)
        text = response.text
        try:
            body = response.json()
        except Exception:  # noqa: BLE001 —— 非 JSON 就保留原文
            body = text
        return response.status_code, body


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
