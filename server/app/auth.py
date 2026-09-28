"""
比邻AI · 接口鉴权（P1 的最小可用版本）

**先说清这一版能防什么、不能防什么**（不写"看起来安全"的代码）：

| 能防 | 不能防 |
|---|---|
| 接口被内网/公网随便扫到就调用 | 从 App 里把 token 抠出来的人（App 里的任何常量都能被逆向） |
| 提醒、计划、健康档案被无关的人读到 | 同一 token 在多台设备间滥用（还没有设备级撤销） |
| 误把测试环境暴露出去 | 细粒度权限（老人 / 家属 / 运营三种角色还没区分） |

所以这只是"把门关上"，不是"做完账号体系"。真正的做法（P2 随家人端一起做）是：
员工/家属账号登录（手机号 + 验证码）→ 服务端签发 JWT（短期）+ refresh token →
老人端用绑定关系换取只读自己数据的 scoped token → 设备级撤销。
在那之前，`AUTH_MODE=required` + 一机一 token（`API_TOKENS` 里逗号分隔）足够挡住
"接口裸奔"这个最要命的问题。

配置（`server/.env`）：

    # auto（默认）：配了 API_TOKENS 就强制校验，没配则放行并在启动日志里大声警告
    # required：强制校验；没配 token 直接启动失败（**上线用这个**）
    # off：明确关闭（本机开发）
    AUTH_MODE=auto
    API_TOKENS=给老人端的一串随机串,给家人端的一串随机串
"""

from __future__ import annotations

import hmac
import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from .errors import api_error

logger = logging.getLogger("bilin.auth")

MODE_AUTO = "auto"
MODE_REQUIRED = "required"
MODE_OFF = "off"

# 公开接口：健康检查与错误码表。探针要能用，错误码表本身不含敏感信息
PUBLIC_PATHS = ("/healthz", "/v1/errors", "/docs", "/openapi.json", "/redoc")
# 家人端静态页与它依赖的 api 模块也必须公开：HTML/JS 先拿到手，才有机会带着 token 去调接口。
# 注意只放开 /uni-app/api（那一层客户端），不放开整个 uni-app 目录
PUBLIC_PREFIXES = ("/docs", "/redoc", "/family", "/uni-app/api")


def parse_tokens(raw: str) -> list[str]:
    return [item.strip() for item in str(raw or "").split(",") if item.strip()]


def auth_required(settings) -> bool:
    """最终是否强制校验（把 auto 解析成确定答案）"""
    mode = str(getattr(settings, "auth_mode", MODE_AUTO) or MODE_AUTO).lower()
    if mode == MODE_OFF:
        return False
    if mode == MODE_REQUIRED:
        return True
    return bool(parse_tokens(getattr(settings, "api_tokens", "")))


def extract_token(request: Request) -> str:
    """支持 `Authorization: Bearer xxx`，也支持 `X-API-Token: xxx`（调试方便）"""
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return (request.headers.get("x-api-token") or "").strip()


def token_valid(settings, provided: str) -> bool:
    """常量时间比较，避免用 == 泄露前缀匹配长度"""
    if not provided:
        return False
    for token in parse_tokens(getattr(settings, "api_tokens", "")):
        if hmac.compare_digest(token, provided):
            return True
    return False


def check_request(request: Request) -> JSONResponse | None:
    """返回 None 表示放行，否则返回 401 响应"""
    settings = request.app.state.settings
    if not auth_required(settings):
        return None
    path = request.url.path
    if path in PUBLIC_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
        return None
    if token_valid(settings, extract_token(request)):
        return None
    if not extract_token(request):
        return api_error("auth_required")
    logger.warning("鉴权失败：path=%s ip=%s", path, request.client.host if request.client else "-")
    return api_error("unauthorized")


def warn_if_open(settings) -> None:
    """启动时把"接口是裸的"这件事喊出来，别让它悄悄上线"""
    if auth_required(settings):
        count = len(parse_tokens(settings.api_tokens))
        logger.info("接口鉴权已启用（%s 个 token，模式 %s）", count, settings.auth_mode)
        return
    if str(getattr(settings, "auth_mode", MODE_AUTO)).lower() == MODE_OFF:
        logger.warning("接口鉴权已明确关闭（AUTH_MODE=off）—— 仅限本机开发使用")
        return
    logger.warning(
        "⚠️ 接口未鉴权（未配置 API_TOKENS）：任何能访问到这个端口的人都能读健康档案、"
        "改计划、发提醒。仅限本机/内网联调；对外提供服务前请设 AUTH_MODE=required 并配置 API_TOKENS"
    )
