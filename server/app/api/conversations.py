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
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..accounts import Account
from ..errors import api_error
from ..messaging import (
    KIND_AI,
    KIND_FAMILY,
    ROLE_ELDER,
    STATUS_ACCEPTED,
    STATUS_PENDING,
    ai_conversation_id,
    is_agent_sender,
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
    #: 已废弃：智能体代发功能已删除，家人会话里只有真人说话。
    #: 字段保留只为兼容老端侧（传了也被忽略，一律按真人消息处理）。
    sender_role: str = Field(default=ROLE_ELDER, alias="senderRole")
    #: 引用的那条消息 id（端侧长按"引用"时带上）
    quote_id: str = Field(default="", alias="quoteId")


class MessageIdRequest(BaseModel):
    """撤回 / 删除共用的入参。"""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    conversation_id: str = Field(default="", alias="conversationId")
    message_id: str = Field(default="", alias="messageId")


#: 兼容旧名字（撤回与删除共用同一个入参结构）
RecallRequest = MessageIdRequest


class ReadRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    conversation_id: str = Field(default="", alias="conversationId")


class BindRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    number: str = Field(default="")


class RespondBindRequest(BaseModel):
    """回应绑定邀请：同意 / 拒绝。"""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    #: 发起邀请那一方的编号
    number: str = Field(default="")
    #: true = 同意，false = 拒绝
    accept: bool = Field(default=False)


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
    #
    # ⚠️ 2026-10 起**不再支持 senderRole=agent**（智能体代发功能已删除）。
    # 家人会话里只有真人说话；AI 只在它自己的会话（ai:）里说话。
    # 这里强制成 ROLE_ELDER 是为了兼容老端侧：万一还传 agent，
    # 也一律当真人消息落库，免得留下"署名是家人、其实是 AI 代回"的错乱记录。
    role = ROLE_ELDER
    message = store.add_message(
        conversation.id,
        sender_id=account.id,
        sender_name=account.name,
        sender_role=role,
        text=text,
        quote_id=str(payload.quote_id or ""),
    )

    # ── 家人说话风格：家人会话里都是真人的话，可以学 ──
    # 智能体会话里"对方"是 AI 生成的，不学（学了等于学模型自己的口吻）。
    if conversation.kind == KIND_FAMILY:
        _learn_peer_style(request, text)

    return JSONResponse(
        content={
            "message": message.to_dict(),
            "unread": store.unread_count(conversation.id, account.id),
        },
        status_code=201,
    )


def _learn_peer_style(request: Request, text: str) -> None:
    """让 wiki 学这条真人消息的说话风格（后台跑，失败无感）。

    wiki 是增强功能：这里任何异常都只记日志，
    绝不影响"消息本身已经发出去"这个事实。
    """
    wiki = getattr(request.app.state, "wiki", None)
    provider = getattr(request.app.state, "provider", None)
    if wiki is None or provider is None:
        return
    try:
        # 单老人原型：老人档案 id 用默认那个
        from ..models.elder import DEFAULT_ELDER_ID

        wiki.schedule_peer_style_learn(DEFAULT_ELDER_ID, text, provider)
    except Exception:  # noqa: BLE001
        logger.exception("子女说话风格学习启动失败（不影响消息）")


#: 撤回时间窗（秒）。与微信一致的"2 分钟内可撤回"。
RECALL_WINDOW_SECONDS = 120


@router.post("/messages/recall")
async def recall_message(payload: RecallRequest, request: Request):
    """撤回一条自己发的消息。

    **只有发送者本人能撤回**，且必须在 `RECALL_WINDOW_SECONDS` 之内
    （与微信一致；超时后服务端拒绝，端侧也不给这个选项）。

    撤回是**打标记**而不是删除：家人会话是双方共享的一份记录，
    直接删掉对方会看到消息凭空消失。撤回后 `to_dict()` 不再下发正文。
    """
    account, error = _require_account(request)
    if error:
        return error

    conversation, error = _conversation_for(request, account, payload.conversation_id)
    if error:
        return error

    store = _store(request)
    target = store.find_message(payload.message_id)
    if target is None or target.conversation_id != conversation.id:
        return api_error("message_not_found")

    # 归属校验：只能撤自己发的。
    # ⚠️ 这里**有意不**放宽到"我 AI 会话里的智能体回复"（虽然删除放宽了）：
    #    撤回是"让对方看到我收回了这句话"，而家人会话与 AI 会话的语义不同，
    #    放宽会牵动既有行为与测试。目前用户反馈的是「删不掉」，先只修删除。
    if target.sender_id != account.id:
        return api_error("not_your_message")

    if target.recalled_at:
        return api_error("already_recalled")

    age = _seconds_since(target.created_at)
    if age is not None and age > RECALL_WINDOW_SECONDS:
        return api_error("recall_expired")

    store.recall_message(target.id, now_iso())
    fresh = store.find_message(target.id)
    return JSONResponse(content={"message": (fresh or target).to_dict()})


@router.post("/messages/delete")
async def delete_message(payload: RecallRequest, request: Request):
    """删除一条**归我管**的消息（物理删除，与"撤回"区分开）。

    可删的两种（判据见 `_can_manage`）：
      · 我发的
      · **AI 会话里那条智能体回复** —— 它就是替我说话的，属于我这一侧

    不可删：家人在共享会话里发的、以及**对方智能体代他回的**（删了等于篡改
    我们俩共用的那份记录）。
    """
    account, error = _require_account(request)
    if error:
        return error

    conversation, error = _conversation_for(request, account, payload.conversation_id)
    if error:
        return error

    store = _store(request)
    target = store.find_message(payload.message_id)
    if target is None or target.conversation_id != conversation.id:
        return api_error("message_not_found")
    if not _can_manage(target, account, conversation):
        return api_error("not_your_message")

    store.delete_message(target.id)
    return JSONResponse(content={"ok": True, "id": target.id})


def _can_manage(target, account, conversation) -> bool:
    """这条消息我能不能删 / 撤。

    两种允许：
      1. **我发的**（`sender_id == 我的账号 id`）—— 自己的消息自己处置
      2. **我自己的 AI 会话里那条智能体回复** —— 它就是替我说话的，属于我这一侧

    ⚠️ 为什么第 2 条必须限定在 **AI 会话**：
       家人会话里也有 `agent:` 消息，那是**对方的智能体代他回的**。
       允许我在家人会话里删掉它，等于**篡改我们俩共享的那份记录** ——
       对方下次进来看不到自己说过的话。那不是"管理自己的消息"，是动别人的记录。

    所以判据不是"sender 带 agent: 前缀"，而是
    **"这条 agent 消息是否属于我自己的 AI 会话"**。
    会话 id 本身就编码了归属：`ai:<我的账号 id>`，不需要额外查表。
    """
    if target.sender_id == account.id:
        return True
    if not is_agent_sender(target.sender_id):
        return False
    if conversation.kind != KIND_AI:
        return False
    return conversation.id == ai_conversation_id(account.id)


def _seconds_since(stamp: str) -> float | None:
    """ISO 时间戳到现在过了多少秒。解析不了就返回 None（调用方放行）。"""
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - parsed).total_seconds()



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
    """我**已生效**的家人（含共享会话 id，端侧据此在对话栏目里显示）。

    ⚠️ **只回 `accepted`**：绑定要对方同意之后才算家人。
    待同意的邀请如果也从这里出去，端侧会把它当成家人显示、
    还会拿它的编号去调「家人查看管理」——那是越权。
    要看全部状态（含待同意）用 `/bindings/all`。
    """
    account, error = _require_account(request)
    if error:
        return error
    store = _store(request)
    accepted = [b for b in store.bindings_of(account.id) if b.status == STATUS_ACCEPTED]
    return JSONResponse(content={"bindings": [b.to_dict() for b in accepted]})


@router.post("/bindings")
async def bind_family(payload: BindRequest, request: Request):
    """按 8 位编号**发起绑定邀请**（需求：绑定家人需要对方同意）。

    返回 201 但 `status` 是 `pending`：**这时还没有绑定、也没有共享会话**。
    对方同意之后（`POST /bindings/respond`）才真的生效并开通会话。

    为什么要对方同意：绑定之后对方能看你的日程、聊天活跃等数据，
    单向说绑就绑等于"未经同意就能查看别人"，这是隐私问题不是体验问题。
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
    existing = store.any_binding_with(account.id, peer.id)
    if existing is not None:
        # 已生效 / 已拒绝 / 还在等同意 —— 三种都给明确回复，别让用户反复点
        if existing.status == STATUS_ACCEPTED:
            return api_error("bind_already")
        if existing.status == STATUS_PENDING:
            return api_error("bind_pending")
        return api_error("bind_rejected_before")

    binding = store.bind(
        account_id=account.id,
        account_number=account.number,
        account_name=account.name,
        peer_id=peer.id,
        peer_number=peer.number,
        peer_name=peer.name,
        # 关键：新流程一律先 pending，等对方同意
        status=STATUS_PENDING,
    )
    logger.info("家人绑定邀请：%s(%s) → %s(%s)", account.name, account.number, peer.name, peer.number)
    return JSONResponse(
        content={"binding": binding.to_dict()},
        status_code=201,
    )


@router.get("/bindings/pending")
async def list_pending_bindings(request: Request):
    """别人发给我、等我同意的邀请。"""
    account, error = _require_account(request)
    if error:
        return error
    store = _store(request)
    items = [b.to_dict() for b in store.pending_invites_for(account.id)]
    return JSONResponse(content={"pending": items})


@router.get("/bindings/all")
async def list_all_bindings(request: Request):
    """**全部**绑定关系，含 `pending` 待同意与 `rejected` 已拒绝。

    为什么不用 `/bindings`：那个接口只回已生效的家人（授权链要用它，
    不能把待同意的也当成家人）。而家人绑定页要同时显示
    "谁在等我同意"和"我发出去的邀请对方还没回"，所以需要这份全量的。
    """
    account, error = _require_account(request)
    if error:
        return error
    store = _store(request)
    items = [b.to_dict() for b in store.bindings_of(account.id)]
    return JSONResponse(content={"bindings": items})


@router.post("/bindings/respond")
async def respond_binding(payload: RespondBindRequest, request: Request):
    """同意 / 拒绝一条绑定邀请。

    - 同意 → 绑定生效，并**此时才**开通共享会话
    - 拒绝 → 记为 rejected（保留记录，避免对方反复重发）

    只有**被邀请的一方**能回应：不能替对方点同意。
    """
    account, error = _require_account(request)
    if error:
        return error

    number = str(payload.number or "").strip()
    peer = _accounts(request).by_number(number) if number else None
    if peer is None:
        return api_error("account_not_found", "没找到这个编号")

    store = _store(request)
    # 这条邀请必须是"他发给我的、且还在等"：反向记录存在才说明是我被邀请
    invite = None
    for item in store.pending_invites_for(account.id):
        if item.peer_id == peer.id:
            invite = item
            break
    if invite is None:
        return api_error("no_pending_invite")

    binding = store.respond_invite(account.id, peer.id, bool(payload.accept))
    if binding is None:
        return api_error("no_pending_invite")

    logger.info(
        "家人绑定%s：%s(%s) %s %s(%s)",
        "已同意" if payload.accept else "被拒绝",
        account.name, account.number,
        "←" if payload.accept else "✗",
        peer.name, peer.number,
    )
    return JSONResponse(content={"binding": binding.to_dict(), "accepted": bool(payload.accept)})


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

