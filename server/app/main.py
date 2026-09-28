"""
比邻AI · FastAPI 入口

    python run.py            # 等价于 uvicorn app.main:app --host <HOST> --port <PORT>
    GET /healthz             # 自检：当前用的是真模型还是假模型（不回显密钥）
    GET /docs                # 自动生成的接口文档

`create_app()` 支持注入 provider / settings，测试据此换成假模型与临时配置，
不用改环境变量、也不会打到真实模型上。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .api.chat import router as chat_router
from .config import Settings, get_settings
from .llm import build_provider
from .models.message import ConversationStore
from .orchestration.service import ChatService
from .persona.prompts import PersonaRegistry

logger = logging.getLogger("bilin")


def create_app(settings: Settings | None = None, provider=None) -> FastAPI:
    config = settings or get_settings()
    llm = provider or build_provider(config)
    store = ConversationStore()
    personas = PersonaRegistry(default_id=config.default_persona_id)
    service = ChatService(llm, store, personas, config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info(
            "比邻AI agent 服务启动 | provider=%s model=%s key=%s",
            llm.name,
            getattr(llm, "model", "-"),
            config.masked_api_key(),
        )
        if not config.uses_real_model:
            logger.warning("当前使用假模型（未配置 LLM_API_KEY）—— 端侧能连通，但回复是固定话术")
        yield

    app = FastAPI(
        title="比邻AI agent 服务",
        description="面向康复养老场景的对话编排服务。接口契约见 uni-app/api/README.md",
        version=__version__,
        lifespan=lifespan,
    )

    app.state.settings = config
    app.state.provider = llm
    app.state.chat_service = service

    # 开发期允许跨域：HBuilderX 的 H5 预览跑在另一个端口上
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(chat_router)

    @app.get("/healthz", tags=["meta"])
    async def healthz(request: Request):
        current = request.app.state.settings
        return {
            "ok": True,
            "service": "bilin-agent",
            "version": __version__,
            "llm": {
                "provider": llm.name,
                "model": getattr(llm, "model", None),
                "usesRealModel": current.uses_real_model,
                "apiKey": current.masked_api_key(),
            },
            "endpoints": [
                "POST /v1/chat/stream",
                "POST /v1/chat/send",
                "GET /v1/chat/history",
                "GET /v1/personas",
            ],
            "knowledge": "app/knowledge/guidelines.yaml（25 条草稿，未接入计划引擎）",
        }

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """把框架自带的 {"detail": ...} 也统一成契约里的 {"error": {...}}。

        端侧的 request() 只会读 body.error.message，不统一的话老人会看到英文的 Not Found。
        """
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": _code_for_status(exc.status_code), "message": _message_for_status(exc.status_code)}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        logger.warning("请求参数不合法: %s", exc.errors())
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "invalid_request", "message": "请求格式不对"}},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):  # pragma: no cover
        logger.exception("未捕获异常: %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal", "message": "服务器开小差了，一会儿再试"}},
        )

    return app


_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    422: "invalid_request",
    429: "rate_limited",
}

_STATUS_MESSAGES = {
    400: "请求格式不对",
    401: "登录已过期，让家里人重新登录一下",
    403: "没有权限",
    404: "没有这个接口",
    405: "请求方式不对",
    422: "请求格式不对",
    429: "说得太快了，歇一会儿再说",
}


def _code_for_status(status_code: int) -> str:
    if status_code in _STATUS_CODES:
        return _STATUS_CODES[status_code]
    return "http_error" if status_code < 500 else "internal"


def _message_for_status(status_code: int) -> str:
    if status_code in _STATUS_MESSAGES:
        return _STATUS_MESSAGES[status_code]
    return "服务器开小差了，一会儿再试" if status_code >= 500 else "请求失败（" + str(status_code) + "）"


app = create_app()
