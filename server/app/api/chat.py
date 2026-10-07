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
# 当前账号：智能体设置（按账号换模型）与模型读写接口都要用
from .accounts import _current_account

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


def _account_id(request: Request) -> str:
    """
    当前账号 id（按 token 反查）。取不到就返回空串 —— 表示"用服务端内置模型"。

    **为什么要它**：智能体设置里可以给某个账号换成第三方模型
    （见 app/llm/resolver.py），编排层需要知道"这一轮是谁在问"才能挑对 provider。
    鉴权没开（AUTH_MODE=off）时这里拿到空串，走内置模型，行为与以前一致。
    """
    try:
        account = _current_account(request)
        return str(getattr(account, "id", "") or "")
    except Exception:  # noqa: BLE001 —— 拿不到就退回内置，不该影响对话
        return ""


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
        account_id=_account_id(request),
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
            account_id=_account_id(request),
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


# ══════════════════════════════════════════════════════════════════════
# 智能体设置：模型选择（默认内置 / 自定义第三方）
# ══════════════════════════════════════════════════════════════════════


class ModelSettingRequest(BaseModel):
    """`我的 → 智能体设置` 提交的内容。"""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    #: builtin = 用服务端配置的模型（默认）；custom = 用下面三项
    mode: str = "builtin"
    base_url: str = Field(default="", alias="baseUrl")
    api_key: str = Field(default="", alias="apiKey")
    model: str = Field(default="")


def _override_store(request: Request):
    store = getattr(request.app.state, "model_overrides", None)
    if store is None:
        return None, api_error("model_settings_unavailable", "模型设置暂时不可用")
    return store, None


def _resolver(request: Request):
    return getattr(request.app.state, "provider_resolver", None)


@router.get("/chat/model")
async def get_model_setting(request: Request):
    """读当前账号的模型设置。**密钥只回脱敏值**（完整 key 绝不外发）。"""
    account = _current_account(request)
    if account is None:
        return api_error("auth_required")
    store, error = _override_store(request)
    if error:
        return error

    override = store.get(account.id)
    # 顺带告诉端侧"现在实际用的是哪个模型"，界面才好显示真实状态。
    # ⚠️ 取的是 `app.state.provider`（main.py 里挂的名字），不是 `llm`——
    #    写错会 500，且只在真机上才发现（本地测试没覆盖到这条读接口）
    builtin = getattr(request.app.state, "provider", None)
    active = {
        "provider": getattr(builtin, "name", ""),
        "model": getattr(builtin, "model", ""),
        "custom": False,
        "fallbackReason": "",
    }
    resolver = _resolver(request)
    if resolver is not None:
        resolved = resolver.resolve(account.id)
        active["custom"] = bool(resolved.custom)
        active["fallbackReason"] = resolved.fallback_reason
        if resolved.custom:
            active["provider"] = getattr(resolved.provider, "name", "openai_compat")
            active["model"] = getattr(resolved.provider, "model", "")

    return JSONResponse(content={"setting": override.to_public(), "active": active})


@router.put("/chat/model")
async def save_model_setting(payload: ModelSettingRequest, request: Request):
    """保存模型设置。切到 `builtin` 时会把自定义三件套清空。"""
    account = _current_account(request)
    if account is None:
        return api_error("auth_required")
    store, error = _override_store(request)
    if error:
        return error

    mode = (payload.mode or "builtin").strip().lower()
    if mode not in ("builtin", "custom"):
        return api_error("model_mode_invalid")

    from datetime import datetime, timezone

    from ..llm.overrides import MODE_BUILTIN, MODE_CUSTOM, ModelOverride

    if mode == MODE_BUILTIN:
        override = ModelOverride(mode=MODE_BUILTIN, updated_at=datetime.now(timezone.utc).isoformat())
    else:
        base_url = (payload.base_url or "").strip()
        api_key = (payload.api_key or "").strip()
        model = (payload.model or "").strip()
        # 三项都要：缺一项就没法真的调用，早点告诉用户比"存下来但用不了"好
        missing = []
        if not base_url:
            missing.append("API URL")
        if not api_key:
            missing.append("API KEY")
        if not model:
            missing.append("模型名称")
        if missing:
            return api_error("model_field_missing", "还没填：" + "、".join(missing))
        if not (base_url.startswith("http://") or base_url.startswith("https://")):
            return api_error("model_url_invalid")
        override = ModelOverride(
            mode=MODE_CUSTOM,
            base_url=base_url,
            api_key=api_key,
            model=model,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

    try:
        store.save(account.id, override)
    except (OSError, ValueError) as exc:
        logger.exception("保存模型设置失败")
        return api_error("model_save_failed", "存不上：%s" % exc)

    # 配置变了，把解析缓存清掉，下一个请求立刻生效
    resolver = _resolver(request)
    if resolver is not None:
        resolver.invalidate(account.id)

    return JSONResponse(content={"setting": override.to_public()})


@router.post("/chat/model/test")
async def test_model_setting(payload: ModelSettingRequest, request: Request):
    """用填的三项**真发一次请求**验证连通性。

    为什么要真发：填错的 URL / 过期的 key，只有真调一次才暴露；
    存下来"看起来成功了"但对话一用就报错，老人那边就是"它不说话了"。
    """
    account = _current_account(request)
    if account is None:
        return api_error("auth_required")

    from ..llm.openai_compat import OpenAICompatProvider

    base_url = (payload.base_url or "").strip()
    api_key = (payload.api_key or "").strip()
    model = (payload.model or "").strip()
    if not (base_url and api_key and model):
        return api_error("model_field_missing", "三项都要填才能测试")

    settings = getattr(request.app.state, "settings", None)
    try:
        provider = OpenAICompatProvider(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout=20.0,               # 测试要快，别让界面一直转
            temperature=0.0,
            max_tokens=16,
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "reason": "创建失败：%s" % exc})

    try:
        chunks = []
        async for delta in provider.stream([{"role": "user", "content": "你好"}]):
            chunks.append(delta)
            if len("".join(chunks)) >= 8:
                break
        text = "".join(chunks).strip()
        return JSONResponse({"ok": True, "reason": "", "sample": text[:60]})
    except LLMError as exc:
        # 走 LLMError 说明"请求真的发出去了、对面拒绝了"（key 无效 / 模型名不对 / 限流）。
        # ⚠️ 这里要回**原始 code 与 message**，不要回那句给老人看的友好文案：
        #    这个接口是给"填配置的人"用的，他需要知道到底哪里错了。
        logger.info("模型连通性测试失败：code=%s msg=%s", exc.code, exc.message)
        return JSONResponse({"ok": False, "reason": "%s：%s" % (exc.code, exc.message), "code": exc.code})
    except Exception as exc:  # noqa: BLE001 —— 测试失败是**业务结果**，不是 5xx
        logger.info("模型连通性测试异常：%s", exc)
        return JSONResponse({"ok": False, "reason": "%s：%s" % (type(exc).__name__, exc)})
