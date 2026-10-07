"""
比邻AI · 账号路由（注册 / 登录 / 我的资料 / 换头像）

老人端只用这四个：

    POST /v1/accounts/register    注册 → 拿到 8 位编号 + 会话 token
    POST /v1/accounts/login       登录 → 拿到会话 token
    GET  /v1/accounts/me          我的资料（名字 + 编号 + 头像）
    POST /v1/accounts/avatar      换头像

**鉴权方式**：登录/注册返回的 `token` 放在 `Authorization: Bearer <token>` 里。
与 `app/auth.py` 的接口级 token 是两套东西——那套防的是"谁能访问这个服务"，
这套答的是"你是哪个账号"。两者可以同时存在（接口级鉴权关掉时本路由照样能用）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..accounts import (
    AVATAR_PRESETS,
    DEV_ACCOUNT_NAME,
    DEV_ACCOUNT_NUMBER,
    MAX_NUMBER,
    TOKEN_TTL_SECONDS,
    Account,
    format_number,
    password_problem,
)
from ..errors import api_error
from ..models.message import now_iso

logger = logging.getLogger("bilin.accounts.api")

router = APIRouter(prefix="/v1/accounts", tags=["accounts"])

#: 头像里允许的 data URI 前缀（端侧选图后压成小图再传，服务端不存大文件）
_AVATAR_PREFIXES = ("data:image/png;base64,", "data:image/jpeg;base64,", "data:image/webp;base64,")
#: 头像 data URI 上限：约 400KB。超过就不收——避免有人把整张原图塞进来
_AVATAR_MAX_CHARS = 400_000


class RegisterRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    name: str = Field(default="")
    password: str = Field(default="")
    confirm: str = Field(default="")


class LoginRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    name: str = Field(default="")
    password: str = Field(default="")


class AvatarRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    avatar: str = Field(default="")


def _store(request: Request):
    return request.app.state.accounts


def _clock(request: Request):
    """统一时间源（见 main.py 的 app.state.clock）"""
    clock = request.app.state.clock
    return clock() if callable(clock) else datetime.now()


def _token_of(request: Request) -> str:
    raw = request.headers.get("authorization") or ""
    if raw.lower().startswith("bearer "):
        return raw[7:].strip()
    return raw.strip()


def _current_account(request: Request) -> Account | None:
    token = _token_of(request)
    if not token:
        return None
    store = _store(request)
    session = store.session(token)
    if session is None:
        return None
    if session.expires_at:
        try:
            if datetime.fromisoformat(session.expires_at) < _clock(request):
                # 过期即回收，别留着占位置
                store.revoke_session(token)
                return None
        except ValueError:
            pass
    return store.by_id(session.account_id)


def _session_payload(account: Account, token: str, expires_at: str) -> dict:
    return {
        "token": token,
        "expiresAt": expires_at,
        "account": account.to_dict(),
    }


@router.post("/register")
async def register(payload: RegisterRequest, request: Request):
    """注册：校验 → 分配编号 → 建账号 → 直接返回会话（注册完就是登录态）"""
    store = _store(request)
    name = str(payload.name or "").strip()

    if not name:
        return api_error("account_name_required")
    if len(name) > 20:
        return api_error("account_name_required", "账号名称太长了，写短一点")
    if store.by_name(name) is not None:
        return api_error("account_name_taken")

    problem = password_problem(payload.password)
    if problem:
        return api_error("account_password_weak", problem)
    if str(payload.confirm or "") != str(payload.password or ""):
        return api_error("account_password_mismatch")

    if store.issued_count() > MAX_NUMBER:
        return api_error("account_number_exhausted")

    moment = _clock(request)
    created = now_iso()
    try:
        account = store.create(name, payload.password, created_at=created)
    except ValueError as exc:
        # 唯一索引兜底：并发注册同名时会走到这里
        logger.info("注册失败：%s", exc)
        return api_error("account_name_taken")

    expires = (moment + timedelta(seconds=TOKEN_TTL_SECONDS)).isoformat(timespec="seconds")
    session = store.issue_session(account, created_at=created, expires_at=expires)
    logger.info("新账号：%s（编号 %s）", account.name, account.number)
    return JSONResponse(
        content=_session_payload(account, session.token, expires),
        status_code=201,
    )


@router.post("/login")
async def login(payload: LoginRequest, request: Request):
    """登录：账号不存在与密码错误**返回同一个错误码**，不告诉对方哪个错了"""
    store = _store(request)
    name = str(payload.name or "").strip()
    if not name or not payload.password:
        return api_error("account_bad_password")

    account = store.by_name(name)
    if account is None or not account.check_password(payload.password):
        return api_error("account_bad_password")

    moment = _clock(request)
    expires = (moment + timedelta(seconds=TOKEN_TTL_SECONDS)).isoformat(timespec="seconds")
    session = store.issue_session(account, created_at=now_iso(), expires_at=expires)
    logger.info("登录成功：%s（编号 %s）", account.name, account.number)
    return JSONResponse(content=_session_payload(account, session.token, expires))


@router.get("/me")
async def me(request: Request):
    """我的资料。端侧每次冷启动用它确认会话还有效。"""
    account = _current_account(request)
    if account is None:
        return api_error("auth_required")
    return JSONResponse(content={"account": account.to_dict()})


@router.post("/avatar")
async def update_avatar(payload: AvatarRequest, request: Request):
    """换头像。

    头像有两种形态，都接受：
      · 预设名（`grandma` / `son` …）：端侧内置图，服务端只存这个短字符串
      · data URI（`data:image/png;base64,...`）：老人自己拍/选的照片，端侧压小后传
    """
    account = _current_account(request)
    if account is None:
        return api_error("auth_required")

    avatar = str(payload.avatar or "").strip()
    if avatar and avatar not in AVATAR_PRESETS and not avatar.startswith(_AVATAR_PREFIXES):
        return api_error("account_avatar_invalid")
    if len(avatar) > _AVATAR_MAX_CHARS:
        return api_error("account_avatar_invalid", "这张照片太大了，换一张小一点的")

    account.avatar = avatar
    account.updated_at = now_iso()
    _store(request).save(account)
    return JSONResponse(content={"account": account.to_dict()})


@router.get("/lookup")
async def lookup(request: Request, number: str = ""):
    """按 8 位编号查账号（只回名字与编号，不回任何敏感信息）。

    用途：创建角色时「绑定家人」一栏要让老人填**家人的编号**，
    填完得能立刻告诉他"绑的是谁"——否则填错一位也没人知道。
    刻意**不要求登录**：绑家人这个动作发生在注册前后都可能。
    但也刻意**只回名字和编号**，不泄露账号的其它字段。
    """
    wanted = str(number or "").strip()
    if not wanted:
        return api_error("bad_request", "请输入家人编号")
    if not wanted.isdigit() or len(wanted) != 8:
        return api_error("bad_request", "家人编号是 8 位数字")

    account = _store(request).by_number(wanted)
    if account is None:
        return JSONResponse(content={"found": False, "account": None})
    return JSONResponse(
        content={"found": True, "account": {"name": account.name, "number": account.number}}
    )


@router.get("/options")
async def options():
    """注册/换头像要用到的固定选项（端侧不用写死）"""
    return JSONResponse(
        content={
            "avatars": list(AVATAR_PRESETS),
            "devAccount": {
                "name": DEV_ACCOUNT_NAME,
                "number": DEV_ACCOUNT_NUMBER,
            },
            "numberWidth": 8,
            "firstNumber": format_number(0),
        }
    )
