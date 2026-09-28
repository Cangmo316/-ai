"""
比邻AI · 对话相关路由

严格实现 `uni-app/api/README.md` 的契约。改动这里的字段名/状态码之前，
先回头看那份文档——端侧解析器是按它写死的。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from ..errors import api_error
from ..llm.base import LLMError
from ..orchestration.service import ChatService

logger = logging.getLogger("bilin.api")

router = APIRouter(prefix="/v1", tags=["chat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    # 反向代理（nginx 等）看到这行才会关掉缓冲；少了它整条流会变成「一次性吐完」
    "X-Accel-Buffering": "no",
}


class ChatRequest(BaseModel):
    """请求体字段用驼峰（与端侧、契约文档一致），内部转下划线。"""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    text: str = ""
    conversation_id: str = Field(default="c_son", alias="conversationId")
    elder_id: str | None = Field(default=None, alias="elderId")
    persona_id: str | None = Field(default=None, alias="personaId")
    # 端侧的本地消息 id：重试会复用同一个 id，服务端据此幂等（见 orchestration/idempotency.py）
    client_msg_id: str | None = Field(default=None, alias="clientMsgId")


def _service(request: Request) -> ChatService:
    return request.app.state.chat_service


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest, request: Request):
    """流式对话（SSE）。事件：meta → (token | sticker)* → done / error。"""
    text = (payload.text or "").strip()
    if not text:
        return api_error("empty_text")

    service = _service(request)
    generator = service.stream_sse(
        conversation_id=payload.conversation_id,
        text=text,
        persona_id=payload.persona_id,
        elder_id=payload.elder_id,
        client_msg_id=payload.client_msg_id or "",
    )
    return StreamingResponse(generator, media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/chat/send")
async def chat_send(payload: ChatRequest, request: Request):
    """非流式一次性回复：端侧降级路径。"""
    text = (payload.text or "").strip()
    if not text:
        return api_error("empty_text")

    service = _service(request)
    try:
        result = await service.reply_once(
            conversation_id=payload.conversation_id,
            text=text,
            persona_id=payload.persona_id,
            elder_id=payload.elder_id,
            client_msg_id=payload.client_msg_id or "",
        )
    except LLMError as exc:
        logger.warning("一次性回复失败: code=%s", exc.code)
        # code 到 HTTP 状态与文案的映射统一在 app/errors.py 里
        return api_error(exc.code, exc.message)
    return JSONResponse(content=result)


@router.get("/chat/history")
async def chat_history(
    request: Request,
    conversation_id: str = Query(default="c_son", alias="conversationId"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """历史消息。端侧拉取失败不报错（本地缓存会顶上）。"""
    messages = _service(request).store.history(conversation_id, limit=limit)
    return JSONResponse(
        content={
            "conversationId": conversation_id,
            "messages": [message.to_dict() for message in messages],
        }
    )


@router.get("/personas")
async def list_personas(request: Request):
    """人设列表（`我的 → 智能体角色` 用；端侧目前还是本地写死的四个）。"""
    personas = _service(request).personas.all()
    return JSONResponse(content={"personas": [persona.to_public() for persona in personas]})
