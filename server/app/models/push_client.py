"""
比邻AI · 推送客户端标识（cid）登记

uni-push 2.0 的推送对象是"客户端推送标识"（个推的 cid），不是用户 id。
所以端侧必须把 cid 报给服务端，服务端才知道这条提醒该往哪台设备发：
不登记 cid，提醒就只能靠站内消息（App 打开着才收得到）。

一个老人可能有多台设备（自己的手机 + 子女给买的平板），所以是 elder → [cid] 的一对多。
cid 会变（重装、清数据、卸载重登），所以登记按 cid 幂等 upsert，并记录更新时间。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .message import now_iso


@dataclass
class PushClient:
    cid: str
    elder_id: str
    platform: str = ""
    app_version: str = ""
    enabled: bool = True
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        # ⚠️ cid 属于设备标识：对外只回显后 6 位，避免日志/看板把它当普通 id 到处传
        return {
            "cid": self.cid,
            "cidTail": self.cid[-6:] if len(self.cid) > 6 else self.cid,
            "elderId": self.elder_id,
            "platform": self.platform,
            "appVersion": self.app_version,
            "enabled": self.enabled,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


class PushClientRegistry:
    def __init__(self) -> None:
        self._clients: dict[str, PushClient] = {}

    def register(
        self,
        elder_id: str,
        cid: str,
        platform: str = "",
        app_version: str = "",
    ) -> PushClient:
        cid = str(cid or "").strip()
        if not cid:
            raise ValueError("cid 不能为空")
        existing = self._clients.get(cid)
        if existing:
            existing.elder_id = elder_id or existing.elder_id
            existing.platform = platform or existing.platform
            existing.app_version = app_version or existing.app_version
            existing.enabled = True
            existing.updated_at = now_iso()
            return existing
        client = PushClient(
            cid=cid,
            elder_id=elder_id,
            platform=platform,
            app_version=app_version,
        )
        self._clients[cid] = client
        return client

    def unregister(self, cid: str) -> bool:
        """老人关掉推送 / 换设备时调用（设备可能已经卸载，所以按 cid 删）"""
        return self._clients.pop(str(cid or "").strip(), None) is not None

    def clients_for(self, elder_id: str) -> list[PushClient]:
        items = [
            client
            for client in self._clients.values()
            if client.elder_id == elder_id and client.enabled
        ]
        items.sort(key=lambda client: client.updated_at, reverse=True)
        return items

    def get(self, cid: str) -> PushClient | None:
        return self._clients.get(str(cid or "").strip())

    def all(self) -> list[PushClient]:
        return list(self._clients.values())

    def counts(self) -> dict:
        elders = {client.elder_id for client in self._clients.values() if client.enabled}
        return {
            "clients": len(self._clients),
            "enabled": sum(1 for client in self._clients.values() if client.enabled),
            "elders": len(elders),
        }

    def clear(self) -> None:
        self._clients.clear()
