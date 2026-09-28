"""
比邻AI · 推送标识登记路由

端侧拿到 cid（`uni.getPushClientId`）后报给这里，服务端才知道提醒该发到哪台设备。
没有登记 cid 的老人，提醒只能靠站内消息（App 打开着才收得到）。

⚠️ cid 是设备标识，属于敏感信息：对外只回显后 6 位（`cidTail`），日志里也不打全文。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..models.elder import DEFAULT_ELDER_ID

logger = logging.getLogger("bilin.push.api")

router = APIRouter(prefix="/v1", tags=["push"])


class RegisterRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    cid: str
    elder_id: str = Field(default=DEFAULT_ELDER_ID, alias="elderId")
    platform: str = ""
    app_version: str = Field(default="", alias="appVersion")


class UnregisterRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    cid: str


@router.post("/push/register")
async def register_push_client(payload: RegisterRequest, request: Request):
    """登记/更新推送标识（同一 cid 重复登记是幂等的，老人换设备直接登记新的）"""
    cid = (payload.cid or "").strip()
    if not cid:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "invalid_cid", "message": "推送标识不能为空"}},
        )
    registry = request.app.state.push_clients
    client = registry.register(
        elder_id=payload.elder_id,
        cid=cid,
        platform=payload.platform,
        app_version=payload.app_version,
    )
    logger.info(
        "登记推送标识：elder=%s platform=%s cid尾号=%s",
        client.elder_id,
        client.platform or "-",
        client.cid[-6:],
    )
    return JSONResponse(
        content={
            "ok": True,
            "elderId": client.elder_id,
            "cidTail": client.to_dict()["cidTail"],
            "updatedAt": client.updated_at,
            "notice": "提醒会同时走站内消息与系统通知；关掉通知权限也能在 App 里看到",
        }
    )


@router.post("/push/unregister")
async def unregister_push_client(payload: UnregisterRequest, request: Request):
    """注销（老人关掉推送、换设备、卸载前调用）"""
    removed = request.app.state.push_clients.unregister(payload.cid)
    return JSONResponse(content={"ok": removed})


@router.get("/push/status")
async def push_status(
    request: Request,
    elder_id: str = Query(default=DEFAULT_ELDER_ID, alias="elderId"),
):
    """推送通道自检：是否配好云函数、这位老人登记了几台设备"""
    registry = request.app.state.push_clients
    settings = request.app.state.settings
    unipush = next(
        (channel for channel in request.app.state.scheduler.channels.channels if channel.name == "unipush"),
        None,
    )
    return JSONResponse(
        content={
            "elderId": elder_id,
            "channels": request.app.state.scheduler.channels.describe(),
            "unipushConfigured": bool(unipush and unipush.configured),
            "hasSendUrl": bool(getattr(settings, "unipush_send_url", "")),
            "forceNotification": bool(getattr(settings, "unipush_force_notification", True)),
            "clients": [client.to_dict() for client in registry.clients_for(elder_id)],
            "totals": registry.counts(),
            "note": "uni-push 2.0 的服务端 SDK 只能跑在 uniCloud 云函数里；本服务转发给它，凭证留在云函数侧",
        }
    )
