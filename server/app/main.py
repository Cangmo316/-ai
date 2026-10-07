"""
比邻AI · FastAPI 入口

    python run.py            # 等价于 uvicorn app.main:app --host <HOST> --port <PORT>
    GET /healthz             # 自检：模型、知识库版本、计划数量（不回显密钥）
    GET /docs                # 自动生成的接口文档

`create_app()` 支持注入 provider / settings / 知识库 / 计划引擎，测试据此换成假模型
与临时数据，不用改环境变量、也不会打到真实模型上。
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .api.accounts import router as accounts_router
from .api.conversations import router as conversations_router
from .api.family import router as family_router
from .api.health import router as health_router
from .api.cases import router as cases_router
from .api.chat import router as chat_router
from .api.memories import router as memories_router
from .api.plans import router as plans_router
from .api.push import router as push_router
from .api.reminders import router as reminders_router
from .auth import MODE_REQUIRED, auth_required, check_request, parse_tokens, warn_if_open
from .config import Settings, get_settings
from .errors import api_error
from .asr import gateway as asr_gateway
from .voice import audio_store
from .voice import gateway as voice_gateway
from .errors import code_for_status
from .errors import table as error_table
from .knowledge.loader import KnowledgeBase, KnowledgeError, load_knowledge
from .llm import build_provider
from .memory import (
    MemoryStore,
    SqlMemoryStore,
    describe,
    extract_with_llm,
    remember_candidates,
    remember_from_turn,
    search,
)
from .storage import open_database
from .accounts import AccountStore, SqlAccountStore, ensure_dev_account
from .messaging import MessagingStore, SqlMessagingStore
from .health import HealthStore, SqlHealthStore
from .docs import CaseStore, SqlCaseStore
from .vision import build_vision_provider
from .models.elder import DEFAULT_ELDER_ID, ElderStore
from .models.message import ConversationStore
from .models.push_client import PushClientRegistry
from .models.sql_store import SqlConversationStore
from .orchestration.idempotency import IdempotencyStore
from .orchestration.service import ChatService
from .persona.prompts import PersonaRegistry
from .plan.engine import PlanEngine
from .plan.models import STATUS_ACTIVE, STATUS_PENDING
from .plan.sql_store import SqlPlanStore
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
    # P2 落库：有库就落库（默认 sqlite），DATABASE_URL=memory:// 时退回纯内存（测试/CI）。
    # 建库放在最前面：会话 / 记忆 / 计划三个 store 都要在装配期挂到同一条库上
    database = open_database(config.database_url, base_dir=Path(__file__).resolve().parents[1])
    # 会话与计划跟记忆同一套模式：写穿透 + 启动加载，接口与内存版逐字一致
    conversations = SqlConversationStore(database) if database.enabled else ConversationStore()
    personas = PersonaRegistry(default_id=config.default_persona_id)
    elders = ElderStore()
    # 幂等：端侧重试复用同一个 clientMsgId，命中缓存就不重复生成（也不重复调模型）
    idempotency = IdempotencyStore()
    # P2 三层记忆：L2 经历 / L3 偏好（L1 档案在 elders 里）
    memories = SqlMemoryStore(database) if database.enabled else MemoryStore()
    # 账号（注册 / 登录）：编号必须跨重启不复用，所以有库就落库并加载
    accounts = SqlAccountStore(database) if database.enabled else AccountStore()
    if isinstance(accounts, SqlAccountStore):
        accounts.init_schema()
        loaded = accounts.load()
        if loaded:
            logger.info("已加载账号 %s 个，下一个编号 %s", loaded, accounts.peek_next_number())
    # 测试开发账号（比邻AI / BILINAI0316，编号 00000000）：幂等写入，已存在则不动
    ensure_dev_account(accounts)
    # 会话与消息：支持两个账号共享一条会话（家人之间互发消息）
    messaging = SqlMessagingStore(database) if database.enabled else MessagingStore()
    if isinstance(messaging, SqlMessagingStore):
        messaging.init_schema()
        messaging.load()
    # 健康档案：结构化的身体数据（血压/血糖/体重…），作为智能体主动关心的依据
    health = SqlHealthStore(database) if database.enabled else HealthStore()
    if isinstance(health, SqlHealthStore):
        health.init_schema()
        health.load()
    # 病例病史：医院单据（图片/PDF）。**文件字节落盘**（base_dir 用 server 目录），
    # 库里只存路径与解析出的文字——SQLite 存大 BLOB 会让库膨胀、备份变慢
    case_base = Path(__file__).resolve().parents[1]
    cases = SqlCaseStore(database, base_dir=case_base) if database.enabled else CaseStore(base_dir=case_base)
    if isinstance(cases, SqlCaseStore):
        cases.init_schema()
        cases.load()
    # 识图：读医院单据的照片。没配 DASHSCOPE_API_KEY 时是 Null 实现——
    # 功能不可用会如实告诉老人，其余功能完全不受影响
    vision = build_vision_provider()

    if knowledge is None:
        try:
            knowledge = load_knowledge()
        except KnowledgeError as exc:
            # 计划引擎的每一条依据都来自知识库，读不出来就不该硬撑着启动
            logger.error("知识库加载失败：%s", exc)
            raise
    if plan_engine is not None:
        engine = plan_engine
    else:
        # 计划与打卡也要落库：不落的话重启后 active() 会返回 None，
        # 老人端「今日计划」整个空掉（家属确认过的计划白确认了）
        plan_store = SqlPlanStore(database) if database.enabled else PlanStore()
        engine = PlanEngine(knowledge, plan_store, elders, config)

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

    def memories_for(elder_id: str, query: str) -> list[str]:
        """L2/L3：按当前这句话检索相关往事与偏好，取 Top-K 格式化成提示词用的一行行。

        只取"已复核可用"的记忆；待复核的绝不进上下文（设计方案 §3.4 的硬要求）。
        """
        return [describe(entry) for entry, _ in search(memories, elder_id, query, limit=5)]

    async def after_turn(elder_id: str, elder_text: str) -> None:
        """一轮对话产出后的记忆整理。

        两道闸门：① 开关默认关着（需明确告知本人后在家属端打开）
                 ② 规则抽取同步做（微秒级，不拖慢这一轮）；模型抽取丢后台
        """
        settings = memories.settings_for(elder_id)
        if not settings.auto_extract:
            return
        await remember_from_turn(memories, settings, elder_id, elder_text)

        if not config.uses_real_model:
            return

        async def refine() -> None:
            # 模型抽取要调一次 LLM（秒级），绝不能挂在 done 事件前面
            try:
                candidates = await extract_with_llm(llm, elder_text)
                if candidates:
                    remember_candidates(memories, elder_id, candidates)
            except Exception:  # noqa: BLE001
                logger.warning("模型整理记忆失败（不影响对话）", exc_info=True)

        asyncio.create_task(refine())

    service = ChatService(
        llm,
        conversations,
        personas,
        config,
        # L1 档案注入：人设 prompt 会带上"有高血压、平时吃什么药"这类稳定事实
        elder_profiles=elders.elders,
        plan_cards=plan_cards_for,
        idempotency=idempotency,
        memory_provider=memories_for,
        # 健康数值注入：有了它，智能体的"关心"才说得出具体内容
        # （"昨天 158/96，今天量了吗"），而不是永远只会说"注意身体"
        health_provider=lambda elder_id: health.snapshot_for_prompt(elder_id),
        # 病例病史：让智能体知道「医生说过什么」（诊断 / 就诊日期 / 医院）
        case_provider=lambda elder_id: cases.snapshot_for_prompt(elder_id),
        after_turn=after_turn,
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
        # 落库后端也要喊出来：跑了一整天以为在落库、其实 DATABASE_URL=memory:// 最坑
        logger.info("存储后端：%s（记忆 / 会话 / 计划 / 打卡）", database.describe())
        if not database.enabled:
            logger.warning(
                "未落库（DATABASE_URL=memory://）—— 进程重启后记忆、会话、计划与打卡都会清空"
            )
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
        # 关连接前 SQLite 会自己 checkpoint（WAL 模式下不关会留 -wal 文件）
        database.close()

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
    app.state.memories = memories
    app.state.accounts = accounts
    app.state.messaging = messaging
    app.state.health = health
    app.state.cases = cases
    app.state.vision = vision
    app.state.database = database
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
    app.include_router(memories_router)
    app.include_router(accounts_router)
    app.include_router(conversations_router)
    app.include_router(family_router)
    app.include_router(health_router)
    app.include_router(cases_router)

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

    @app.get("/v1/audio/{audio_id}", tags=["voice"])
    async def get_audio(audio_id: str, request: Request):
        """取合成音频（**短期签名 URL**，端侧播放器直接当 src 用）。

        为什么不用普通鉴权：`uni.createInnerAudioContext().src` 与 H5 `<audio>`
        **都带不了 Authorization 请求头**（见 `auth.py` 里 `/v1/audio` 的说明）。
        所以鉴权信息编进 URL 本身（`expires` + `sig`），端点自己校验。

        返回 403/404 **不区分原因**（签名错/过期/不存在都给同一句话），
        避免通过错误差异探测音频 id 是否存在。
        """
        settings = request.app.state.settings
        expires = request.query_params.get("expires", "")
        signature = request.query_params.get("sig", "")
        ok, reason = audio_store.verify(audio_id, expires, signature, settings)
        if not ok:
            logger.warning("音频拒绝：%s（id 前缀 %s）", reason, audio_id[:8])
            return JSONResponse({"code": "audio_forbidden", "message": "音频链接无效或已过期"},
                                status_code=403)
        data = audio_store.get_store().get(audio_id)
        if not data:
            return JSONResponse({"code": "audio_gone", "message": "音频链接无效或已过期"},
                                status_code=404)
        # media_type 用 audio/mpeg：百炼默认输出 MP3；端侧按扩展名/Content-Type 都能放
        return Response(content=data, media_type="audio/mpeg",
                        headers={"Cache-Control": "private, max-age=300"})

    @app.post("/v1/asr/transcribe", tags=["voice"])
    async def transcribe(request: Request):
        """语音识别（老人端「按住说话」用）。

        收 `multipart/form-data` 的 `file` 字段（音频），返回 `{ok, text, reason, ...}`。

        **为什么用 multipart 而不是 base64**：录音动辄几十到几百 KB，
        base64 平白多 33% 体积，而老人端往往是弱网。

        **失败要明确**：没配 ASR 或引擎失败时返回 `ok: false` + 中文原因，
        端侧据此提示"暂时听不清"，**老人仍可打字** —— 语音是增强项，不是唯一入口。
        失败返 200 而不是 4xx/5xx：这是**业务结果**，端侧按 `ok` 字段处理更简单。
        """
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            return JSONResponse({"ok": False, "reason": "没有收到音频文件"}, status_code=400)
        content = await upload.read()
        if not content:
            return JSONResponse({"ok": False, "reason": "音频是空的"}, status_code=400)
        # 大小上限：60 秒 16bit/16kHz 单声道 ≈ 1.9MB，留足余量
        if len(content) > 8 * 1024 * 1024:
            return JSONResponse({"ok": False, "reason": "录音太长了，一次说短一点"},
                                status_code=413)

        suffix = asr_gateway.suffix_for(getattr(upload, "filename", ""),
                                        getattr(upload, "content_type", ""))
        workdir = tempfile.mkdtemp(prefix="bilin-asr-upload-")
        audio_path = os.path.join(workdir, "input" + suffix)
        with open(audio_path, "wb") as handle:
            handle.write(content)

        provider = asr_gateway.build_asr_provider()
        result = await provider.transcribe(audio_path, language="zh")
        return JSONResponse({
            "ok": result.ok,
            "text": result.text,
            "reason": result.reason,
            "language": result.language,
            "bytes": len(content),
            "engine": type(provider).__name__,
        })

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
            "memory": memories.counts(),
            # 语音链路状态：如实反映"真跑还是降级"（与 auth/storage 同一原则：
            # 部署方必须能从 /healthz 一眼看出真实状态，而不是猜）。
            # 未配置时口型走估算版（source=estimated），对话完全不受影响。
            "voice": voice_gateway.describe(),
            # 语音识别（老人端"按住说话"）：同样如实报，未配置时端侧提示"暂时听不清"
            "asr": asr_gateway.describe(),
            "storage": database.describe(),
            "storageDurable": database.enabled,
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
                "GET  /v1/memories",
                "POST /v1/memories",
                "PATCH/DELETE /v1/memories/{id}",
                "POST /v1/memories/clear",
                "POST /v1/memories/review",
                "GET/PUT /v1/memories/settings",
                "GET  /v1/memories/topics",
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
