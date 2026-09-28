"""
比邻AI · FastAPI 入口

    python run.py            # 等价于 uvicorn app.main:app --host <HOST> --port <PORT>
    GET /healthz             # 自检：模型、知识库版本、计划数量（不回显密钥）
    GET /docs                # 自动生成的接口文档

`create_app()` 支持注入 provider / settings / 知识库 / 计划引擎，测试据此换成假模型
与临时数据，不用改环境变量、也不会打到真实模型上。
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
from .api.plans import router as plans_router
from .api.push import router as push_router
from .api.reminders import router as reminders_router
from .config import Settings, get_settings
from .knowledge.loader import KnowledgeBase, KnowledgeError, load_knowledge
from .llm import build_provider
from .models.elder import DEFAULT_ELDER_ID, ElderStore
from .models.message import ConversationStore
from .models.push_client import PushClientRegistry
from .orchestration.service import ChatService
from .persona.prompts import PersonaRegistry
from .plan.engine import PlanEngine
from .plan.models import STATUS_ACTIVE, STATUS_PENDING
from .plan.store import PlanStore
from .schedule import (
    ChannelRegistry,
    InboxChannel,
    LogChannel,
    ReminderStore,
    Scheduler,
    UniPushChannel,
)

logger = logging.getLogger("bilin")


def create_app(
    settings: Settings | None = None,
    provider=None,
    knowledge: KnowledgeBase | None = None,
    plan_engine: PlanEngine | None = None,
    scheduler: Scheduler | None = None,
    clock=None,
) -> FastAPI:
    config = settings or get_settings()
    llm = provider or build_provider(config)
    conversations = ConversationStore()
    personas = PersonaRegistry(default_id=config.default_persona_id)
    elders = ElderStore()

    if knowledge is None:
        try:
            knowledge = load_knowledge()
        except KnowledgeError as exc:
            # 计划引擎的每一条依据都来自知识库，读不出来就不该硬撑着启动
            logger.error("知识库加载失败：%s", exc)
            raise
    engine = plan_engine or PlanEngine(knowledge, PlanStore(), elders, config)

    if scheduler is None:
        # 通道顺序有意义：先站内消息（当前一定送得到），再 uni-push（配好了才真的发），最后日志兜底
        push_clients = PushClientRegistry()
        channels = ChannelRegistry([
            InboxChannel(conversations),
            UniPushChannel(
                send_url=config.unipush_send_url,
                token=config.unipush_token,
                registry=push_clients,
                timeout=config.unipush_timeout,
                force_notification=config.unipush_force_notification,
            ),
            LogChannel(),
        ])
        scheduler = Scheduler(
            engine=engine,
            plan_store=engine.store,
            reminders=ReminderStore(),
            channels=channels,
            elders=elders,
            settings=config,
            clock=clock,
        )
    else:
        push_clients = PushClientRegistry()

    def plan_cards_for(elder_id: str | None):
        """对话里「今天要做什么」时挂的今日计划卡片（最多 3 条，避免刷屏）"""
        today = engine.today(elder_id or DEFAULT_ELDER_ID)
        cards = []
        for item in (today.get("items") or [])[:3]:
            cards.append(
                {
                    "kind": "plan_item",
                    "plan": {
                        "time": item.get("time", ""),
                        "title": item.get("title", ""),
                        "desc": item.get("detail", ""),
                        "state": "done" if item.get("done") else "todo",
                    },
                }
            )
        return cards

    service = ChatService(
        llm,
        conversations,
        personas,
        config,
        # L1 档案注入：人设 prompt 会带上"有高血压、平时吃什么药"这类稳定事实
        elder_profiles=elders.elders,
        plan_cards=plan_cards_for,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info(
            "比邻AI agent 服务启动 | provider=%s model=%s key=%s | 知识库 %s（%s 条）",
            llm.name,
            getattr(llm, "model", "-"),
            config.masked_api_key(),
            knowledge.version,
            len(knowledge.entries),
        )
        if not config.uses_real_model:
            logger.warning("当前使用假模型（未配置 LLM_API_KEY）—— 端侧能连通，但回复是固定话术")
        if config.scheduler_enabled:
            scheduler.start()
            logger.info(
                "提醒调度已启用 | 每 %ss tick | 过期宽限 %s 分钟 | 强提醒重复 %s 次/%s 分钟",
                config.scheduler_tick_seconds,
                config.reminder_grace_minutes,
                config.reminder_max_repeats,
                config.reminder_repeat_minutes,
            )
        else:
            logger.warning("提醒调度未启用（SCHEDULER_ENABLED=false）—— 不会自动投递提醒")
        yield
        await scheduler.stop()

    app = FastAPI(
        title="比邻AI agent 服务",
        description=(
            "面向康复养老场景的对话编排与康养计划服务。"
            "接口契约见 uni-app/api/README.md"
        ),
        version=__version__,
        lifespan=lifespan,
    )

    app.state.settings = config
    app.state.provider = llm
    app.state.chat_service = service
    app.state.knowledge = knowledge
    app.state.plan_engine = engine
    app.state.elders = elders
    app.state.scheduler = scheduler
    app.state.push_clients = push_clients
    # 全局时间源：调度器与各路由都用它取"现在"，避免出现"路由按真实时间、调度按注入时间"
    # 这种只有测试才会暴露的分裂（踩过一次：手动 tick 到 15 点，打卡却按真实日期去找提醒）
    app.state.clock = scheduler.now

    # 开发期允许跨域：HBuilderX 的 H5 预览跑在另一个端口上
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(chat_router)
    app.include_router(plans_router)
    app.include_router(reminders_router)
    app.include_router(push_router)

    @app.get("/healthz", tags=["meta"])
    async def healthz(request: Request):
        current = request.app.state.settings
        active = pending = total = 0
        for elder in elders.all():
            plans = engine.store.plans_of(str(elder.get("id")))
            total += len(plans)
            active += sum(1 for plan in plans if plan.status == STATUS_ACTIVE)
            pending += sum(1 for plan in plans if plan.status == STATUS_PENDING)
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
            "knowledge": knowledge.summary(),
            "plans": {"total": total, "active": active, "pending": pending},
            "scheduler": scheduler.status(),
            "endpoints": [
                "POST /v1/chat/stream",
                "POST /v1/chat/send",
                "GET  /v1/chat/history",
                "GET  /v1/personas",
                "POST /v1/plans/draft",
                "GET  /v1/plans/pending",
                "POST /v1/plans/confirm",
                "POST /v1/plans/reject",
                "GET  /v1/plans/today",
                "POST /v1/plans/checkin",
                "GET  /v1/plans/summary",
                "POST /v1/plans/adjust",
                "GET  /v1/plans/history",
                "GET  /v1/elders",
                "GET  /v1/reminders/inbox",
                "POST /v1/reminders/read",
                "GET  /v1/reminders/tasks",
                "GET  /v1/scheduler/status",
                "POST /v1/scheduler/tick",
                "POST /v1/push/register",
                "POST /v1/push/unregister",
                "GET  /v1/push/status",
            ],
        }

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """把框架自带的 {"detail": ...} 也统一成契约里的 {"error": {...}}。

        端侧的 request() 只会读 body.error.message，不统一的话老人会看到英文的 Not Found。
        """
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": _code_for_status(exc.status_code),
                    "message": _message_for_status(exc.status_code),
                }
            },
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
