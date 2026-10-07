"""
比邻AI · 会话与消息路由

老人端用这几个：

    GET  /v1/conversations              我的会话列表（带未读数）
    GET  /v1/conversations/messages     拉某会话的历史
    POST /v1/conversations/messages     发一条消息
    POST /v1/conversations/read         标记已读
    GET  /v1/conversations/bindings     我绑定的家人
    POST /v1/conversations/bindings     绑定家人（按 8 位编号）

鉴权：`Authorization: Bearer <token>`，与 `/v1/accounts/*` 同一套账号会话。
每个接口都会校验"这个会话是不是你的"，不是参与者一律 403——否则拿到会话 id
就能读别人的聊天记录。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..accounts import Account
from ..errors import api_error
from ..messaging import (
    KIND_AI,
    ROLE_AGENT,
    ROLE_ELDER,
    agent_sender_id,
    ai_conversation_id,
    kind_of,
)
from ..models.message import now_iso

logger = logging.getLogger("bilin.messaging.api")

router = APIRouter(prefix="/v1/conversations", tags=["conversations"])

#: 单条消息长度上限（老人打字慢，一般不会超；挡住的是粘贴长文/滥用）
MAX_TEXT = 1000
#: 一次最多返回多少条历史
MAX_LIMIT = 200


class SendRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    conversation_id: str = Field(default="", alias="conversationId")
    text: str = Field(default="")
    #: agent = 智能体（服务端/家人端代为发送），缺省是老人本人
    sender_role: str = Field(default=ROLE_ELDER, alias="senderRole")


class ReadRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    conversation_id: str = Field(default="", alias="conversationId")


class BindRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    number: str = Field(default="")


def _store(request: Request):
    return request.app.state.messaging


def _accounts(request: Request):
    return request.app.state.accounts


def _current_account(request: Request) -> Account | None:
    """复用账号路由里的会话校验（同一套 token）"""
    from .accounts import _current_account as resolve

    return resolve(request)


def _require_account(request: Request):
    """返回 (account, None) 或 (None, 错误响应)"""
    account = _current_account(request)
    if account is None:
        return None, api_error("auth_required")
    return account, None


def _conversation_for(request: Request, account: Account, conversation_id: str):
    """取会话并校验归属。返回 (conversation, None) 或 (None, 错误响应)。"""
    cid = str(conversation_id or "").strip()
    if not cid:
        return None, api_error("conversation_required")
    store = _store(request)
    conversation = store.conversation(cid)
    # 智能体会话可能还没建过（老人从没聊过）→ 按需补建，而不是报"没找到"
    if conversation is None and cid == ai_conversation_id(account.id):
        conversation = store.ensure_ai_conversation(account.id)
    if conversation is None:
        return None, api_error("conversation_not_found")
    if account.id not in conversation.participants():
        logger.warning("越权访问会话：account=%s conversation=%s", account.id, cid)
        return None, api_error("not_a_participant")
    return conversation, None


@router.get("")
async def list_conversations(request: Request):
    """我的会话列表。

    智能体会话**总是**出现（哪怕一条消息都没有）：老人打开对话栏目
    必须看得到"能跟谁说话"，不能因为没聊过就空列表。
    """
    account, error = _require_account(request)
    if error:
        return error

    store = _store(request)
    # 保证智能体会话存在（老账号第一次调用这个接口时补建）
    store.ensure_ai_conversation(account.id)

    items = []
    for conversation in store.conversations_of(account.id):
        unread = store.unread_count(conversation.id, account.id)
        last = store.last_message(conversation.id)
        data = conversation.to_dict(unread=unread, last=last)
        if conversation.kind == KIND_AI:
            data["title"] = "比邻AI"
        else:
            # 家人会话的标题是对方名字（端侧可能会用备注覆盖）
            peer_id = next((p for p in conversation.participants() if p != account.id), "")
            peer = _accounts(request).by_id(peer_id)
            data["peerId"] = peer_id
            # 一并给编号：端侧要用它调「家人查看管理」接口（按编号授权）
            data["peerNumber"] = peer.number if peer else ""
            data["title"] = (peer.name if peer else "家人")
        items.append(data)

    return JSONResponse(
        content={
            "conversations": items,
            "totalUnread": sum(item["unread"] for item in items),
        }
    )


@router.get("/messages")
async def get_messages(
    request: Request,
    conversation_id: str = Query(default="", alias="conversationId"),
    limit: int = Query(default=100, alias="limit"),
):
    """拉某会话的历史消息（按时间正序）"""
    account, error = _require_account(request)
    if error:
        return error
    conversation, error = _conversation_for(request, account, conversation_id)
    if error:
        return error

    capped = max(1, min(int(limit or 100), MAX_LIMIT))
    store = _store(request)
    messages = store.messages_of(conversation.id, capped)
    return JSONResponse(
        content={
            "conversationId": conversation.id,
            "messages": [m.to_dict() for m in messages],
            "unread": store.unread_count(conversation.id, account.id),
        }
    )


@router.post("/messages")
async def send_message(payload: SendRequest, request: Request):
    """发一条消息。

    发出去之后**发送方自己算已读**（见 models.add_message），
    所以不会出现"自己发的消息给自己涨未读"。
    """
    account, error = _require_account(request)
    if error:
        return error

    text = str(payload.text or "").strip()
    if not text:
        return api_error("message_empty")
    if len(text) > MAX_TEXT:
        return api_error("message_too_long")

    conversation, error = _conversation_for(request, account, payload.conversation_id)
    if error:
        return error

    store = _store(request)
    # 消息署名用当前账号的名字：家人会话里对方看到的就是这个名字。
    # 智能体例外：它不是某个账号，必须用独立的 sender id，
    # 否则未读/已读分不清"谁发给谁"（见 messaging/models.py 的 AGENT_ID_PREFIX）。
    role = payload.sender_role or ROLE_ELDER
    is_agent = role == ROLE_AGENT
    message = store.add_message(
        conversation.id,
        sender_id=agent_sender_id(conversation.id) if is_agent else account.id,
        sender_name=account.name,
        sender_role=role,
        text=text,
    )
    return JSONResponse(
        content={
            "message": message.to_dict(),
            "unread": store.unread_count(conversation.id, account.id),
        },
        status_code=201,
    )


@router.post("/read")
async def mark_read(payload: ReadRequest, request: Request):
    """标记已读（端侧进会话 1 秒后调用，见需求）"""
    account, error = _require_account(request)
    if error:
        return error
    conversation, error = _conversation_for(request, account, payload.conversation_id)
    if error:
        return error

    store = _store(request)
    # 已读边界取「会话最后一条消息的时间」而不是 now：
    # 语义是"这个会话里现有的消息我都看过了"，比"读到此刻"更贴合按钮含义，
    # 也不会被「服务端时钟与消息时间戳来源不同」影响（测试注入时钟时尤其明显）。
    last = store.last_message(conversation.id)
    marked = store.mark_read(conversation.id, account.id, last.created_at if last else now_iso())
    return JSONResponse(
        content={
            "conversationId": conversation.id,
            "marked": marked,
            "unread": store.unread_count(conversation.id, account.id),
            "totalUnread": store.total_unread(account.id),
        }
    )


@router.get("/bindings")
async def list_bindings(request: Request):
    """我绑定的家人（含共享会话 id，端侧据此在对话栏目里显示）"""
    account, error = _require_account(request)
    if error:
        return error
    store = _store(request)
    return JSONResponse(
        content={"bindings": [b.to_dict() for b in store.bindings_of(account.id)]}
    )


@router.post("/bindings")
async def bind_family(payload: BindRequest, request: Request):
    """按 8 位编号绑定家人。

    绑定成功会**开通一条共享会话**：双方都能看到这条会话并互发消息。
    """
    account, error = _require_account(request)
    if error:
        return error

    number = str(payload.number or "").strip()
    if not number.isdigit() or len(number) != 8:
        return api_error("bad_request", "家人编号是 8 位数字")

    peer = _accounts(request).by_number(number)
    if peer is None:
        return api_error("account_not_found", "没找到这个编号，核对一下")
    if peer.id == account.id:
        return api_error("bind_self")

    store = _store(request)
    if store.binding_with(account.id, peer.id) is not None:
        return api_error("bind_already")

    binding = store.bind(
        account_id=account.id,
        account_number=account.number,
        account_name=account.name,
        peer_id=peer.id,
        peer_number=peer.number,
        peer_name=peer.name,
    )
    logger.info("家人绑定：%s(%s) ↔ %s(%s)", account.name, account.number, peer.name, peer.number)
    return JSONResponse(
        content={"binding": binding.to_dict()},
        status_code=201,
    )


@router.delete("/bindings")
async def unbind_family(
    request: Request,
    number: str = Query(default=""),
):
    """解绑（按编号）"""
    account, error = _require_account(request)
    if error:
        return error
    peer = _accounts(request).by_number(str(number or "").strip())
    if peer is None:
        return api_error("account_not_found", "没找到这个编号")
    store = _store(request)
    if not store.unbind(account.id, peer.id):
        return api_error("bind_not_found")
    return JSONResponse(content={"ok": True})
