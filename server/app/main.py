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
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .api.chat import router as chat_router
from .api.plans import router as plans_router
from .api.push import router as push_router
from .api.reminders import router as reminders_router
from .auth import MODE_REQUIRED, auth_required, check_request, parse_tokens, warn_if_open
from .config import Settings, get_settings
from .errors import api_error
from .errors import code_for_status
from .errors import table as error_table
from .knowledge.loader import KnowledgeBase, KnowledgeError, load_knowledge
from .llm import build_provider
from .models.elder import DEFAULT_ELDER_ID, ElderStore
from .models.message import ConversationStore
from .models.push_client import PushClientRegistry
from .orchestration.idempotency import IdempotencyStore
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
    # 上线要的是"配置不全就别启动"，而不是"启动了但门是开的"
    if str(config.auth_mode).lower() == MODE_REQUIRED and not parse_tokens(config.api_tokens):
        raise ValueError(
            "AUTH_MODE=required 但没配 API_TOKENS —— 请先在 server/.env 里配置访问 token，"
            "或把 AUTH_MODE 改成 auto/off（仅限本机开发）"
        )
    llm = provider or build_provider(config)
    conversations = ConversationStore()
    personas = PersonaRegistry(default_id=config.default_persona_id)
    elders = ElderStore()
    # 幂等：端侧重试复用同一个 clientMsgId，命中缓存就不重复生成（也不重复调模型）
    idempotency = IdempotencyStore()

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
        idempotency=idempotency,
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
        # 接口是不是裸的，这件事必须喊出来（见 app/auth.py 的"能防/不能防"表）
        warn_if_open(config)
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
    app.state.idempotency = idempotency
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

    # 家人端最小版（静态页）：只用浏览器就能确认计划，不用装 HBuilderX。
    # 它 import 的是 /uni-app/api 那一层客户端，所以契约只有一份实现。
    # 只挂 api 目录，不挂整个 uni-app（pages/components/stores 不需要暴露）
    repo_root = Path(__file__).resolve().parents[2]
    family_dir = repo_root / "family"
    api_dir = repo_root / "uni-app" / "api"
    if family_dir.is_dir():
        app.mount("/family", StaticFiles(directory=str(family_dir), html=True), name="family")
    if api_dir.is_dir():
        app.mount("/uni-app/api", StaticFiles(directory=str(api_dir)), name="uni-app-api")

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        """统一鉴权闸门。

        放在中间件而不是逐个路由加依赖，是因为**新加路由不可能被漏掉**——
        "加固"这件事最怕的就是以后新写一个接口忘了加鉴权。
        """
        denied = check_request(request)
        if denied is not None:
            return denied
        return await call_next(request)

    @app.get("/v1/errors", tags=["meta"])
    async def error_codes():
        """错误码表（公开）：端侧可据此把 code 映射成老人看得懂的提示与重试策略"""
        return {
            "codes": error_table(),
            "note": "error.message 会直接展示给老人；error.retryable 决定端侧要不要给重试入口",
        }

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
            "auth": {
                "mode": current.auth_mode,
                "enabled": auth_required(current),
                "tokens": len(parse_tokens(current.api_tokens)),
                "note": "auto=配了 API_TOKENS 才校验；上线请用 required",
            },
            "idempotency": idempotency.counts(),
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
                "GET  /v1/errors",
            ],
        }

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """把框架自带的 {"detail": ...} 也统一成契约里的 {"error": {...}}。

        端侧的 request() 只读 body.error.message，不统一的话老人会看到英文的 Not Found。
        """
        return api_error(code_for_status(exc.status_code), status=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        logger.warning("请求参数不合法: %s", exc.errors())
        return api_error("invalid_request")

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):  # pragma: no cover
        logger.exception("未捕获异常: %s %s", request.method, request.url.path)
        return api_error("internal")

    return app


app = create_app()
