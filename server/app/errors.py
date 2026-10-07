"""
比邻AI · 统一错误码表

为什么要单独一张表：错误码是**跨语言契约**的一部分。端侧要按 code 决定
"能不能重试 / 要不要让家里人重新登录 / 直接展示哪句话"，如果每个路由自己拼字符串，
端侧就只能靠 HTTP 状态码猜，猜错的表现就是老人看到一句莫名其妙的报错。

三条规矩：
1. **`message` 会直接展示给老人**：必须是人话（"服务器开小差了，一会儿再试"），
   不是 "500 Internal Server Error"，也不含堆栈
2. **`retryable` 是端侧重试按钮的开关**：鉴权失败、格式错误不该给重试按钮
3. **code 尽量稳定**：改 code 等于改契约，要同时改 `uni-app/api/README.md` 与端侧映射

错误体统一形状（`uni-app/api/README.md` §二）：

    { "error": { "code": "plan_state", "message": "计划当前是「草稿」，不能确认", "retryable": false } }
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi.responses import JSONResponse


@dataclass(frozen=True)
class ErrorSpec:
    status: int
    message: str
    retryable: bool = False


# ── 通用 ────────────────────────────────────────────────────────────────
GENERIC: dict[str, ErrorSpec] = {
    "bad_request": ErrorSpec(400, "请求格式不对", True),
    "invalid_request": ErrorSpec(422, "请求格式不对", False),
    "invalid_date": ErrorSpec(400, "日期格式不对，应该像 2026-09-24", False),
    "invalid_datetime": ErrorSpec(400, "时间格式不对，应该像 2026-09-24T08:00:00", False),
    "unauthorized": ErrorSpec(401, "登录已过期，让家里人重新登录一下", False),
    "auth_required": ErrorSpec(401, "需要先登录，让家里人帮你看一下", False),
    "forbidden": ErrorSpec(403, "没有权限", False),
    "not_found": ErrorSpec(404, "没有这个接口", False),
    "method_not_allowed": ErrorSpec(405, "请求方式不对", False),
    "rate_limited": ErrorSpec(429, "说得太快了，歇一会儿再说", True),
    "internal": ErrorSpec(500, "服务器开小差了，一会儿再试", True),
    "http_error": ErrorSpec(400, "请求失败", False),
    "unavailable": ErrorSpec(503, "服务器正在升级，一会儿再试", True),
}

# ── 对话 ────────────────────────────────────────────────────────────────
CHAT: dict[str, ErrorSpec] = {
    "empty_text": ErrorSpec(400, "我没听清 再说一遍", False),
    "duplicate_request": ErrorSpec(409, "这句话我正在回，等我一下", True),
}

# ── 模型 ────────────────────────────────────────────────────────────────
LLM: dict[str, ErrorSpec] = {
    "llm_auth": ErrorSpec(502, "模型还没配置好，让家里人看一下", False),
    "llm_model_not_found": ErrorSpec(502, "模型名字不对，让家里人检查一下", False),
    "llm_rate_limited": ErrorSpec(502, "说得太快了，歇一会儿再说", True),
    "llm_unavailable": ErrorSpec(502, "服务器开小差了，一会儿再试", True),
    "llm_timeout": ErrorSpec(504, "等我一下 我这边有点慢", True),
    "llm_error": ErrorSpec(502, "服务器开小差了，一会儿再试", True),
    "server_error": ErrorSpec(502, "服务器开小差了，一会儿再试", True),
}

# ── 计划 ────────────────────────────────────────────────────────────────
PLAN: dict[str, ErrorSpec] = {
    "plan_not_found": ErrorSpec(404, "没找到这份计划", False),
    "plan_item_not_found": ErrorSpec(404, "没找到这一项", False),
    "plan_state": ErrorSpec(409, "这份计划现在不能这么做", False),
    "plan_not_active": ErrorSpec(409, "还没有生效的计划，先让家里人确认", False),
    "no_matching_entries": ErrorSpec(409, "知识库里没有适合这位老人的条目，没法生成计划", False),
}

# ── 记忆（P2 三层记忆）────────────────────────────────────────────────
MEMORY: dict[str, ErrorSpec] = {
    "memory_not_found": ErrorSpec(404, "没找到这条记忆", False),
    "memory_empty": ErrorSpec(400, "要记的内容不能是空的", False),
}

# ── 提醒 / 推送 ─────────────────────────────────────────────────────────
REMINDER: dict[str, ErrorSpec] = {
    "manual_tick_disabled": ErrorSpec(403, "手动调度已关闭", False),
    "invalid_cid": ErrorSpec(400, "推送标识不能为空", False),
}

# ── 账号（注册 / 登录 / 编号 / 头像）──────────────────────────────────
# 文案都是说给老人听的：不出现"用户名已存在"这种后台话术
ACCOUNT: dict[str, ErrorSpec] = {
    "account_name_required": ErrorSpec(400, "请输入账号名称", False),
    "account_name_taken": ErrorSpec(409, "这个账号名称已经有人用了，换一个", False),
    "account_password_weak": ErrorSpec(400, "密码要 8 到 16 位，只能用数字或字母", False),
    "account_password_mismatch": ErrorSpec(400, "两次输入的密码不一样，请重新输入", False),
    "account_not_found": ErrorSpec(404, "没找到这个账号，先注册一个吧", False),
    "account_bad_password": ErrorSpec(401, "账号或密码不对，再试一次", False),
    "account_number_exhausted": ErrorSpec(409, "账号编号已经用完了，请联系管理员", False),
    "account_avatar_invalid": ErrorSpec(400, "这个头像不能用，换一张试试", False),
}

# ── 会话与消息（含跨账号共享会话、家人绑定）──────────────────────────
MESSAGING: dict[str, ErrorSpec] = {
    "conversation_required": ErrorSpec(400, "没说是哪个会话", False),
    "conversation_not_found": ErrorSpec(404, "没找到这个会话", False),
    "message_empty": ErrorSpec(400, "消息不能是空的", False),
    "message_too_long": ErrorSpec(400, "这条消息太长了，分两次发吧", False),
    "not_a_participant": ErrorSpec(403, "这个会话不是你的", False),
    "bind_self": ErrorSpec(400, "不能绑定自己，换一个编号", False),
    "bind_already": ErrorSpec(409, "已经绑过这个家人了", False),
    # 绑定要对方同意（2026-10）
    "bind_pending": ErrorSpec(409, "已经发过邀请了，等对方同意", False),
    "bind_rejected_before": ErrorSpec(409, "对方之前拒绝了，先跟他说一声", False),
    "no_pending_invite": ErrorSpec(404, "没有等着你同意的邀请", False),
    "bind_not_found": ErrorSpec(404, "没绑过这个家人", False),
    "peer_not_bound": ErrorSpec(403, "只能查看已绑定的家人", False),
    # 撤回 / 删除（长按消息菜单）
    "message_not_found": ErrorSpec(404, "这条消息不在了", False),
    "not_your_message": ErrorSpec(403, "只能撤回或删除自己发的消息", False),
    "already_recalled": ErrorSpec(409, "这条消息已经撤回过了", False),
    "recall_expired": ErrorSpec(400, "超过 2 分钟了，撤不回来了", False),
    # 对方智能体代回
    "not_a_family_conversation": ErrorSpec(400, "只有和家人的会话才能代回", False),
    "nothing_to_reply": ErrorSpec(400, "还没有可以接的话", False),
    # 智能体设置（模型选择）
    "model_settings_unavailable": ErrorSpec(503, "模型设置暂时不可用", True),
    "model_mode_invalid": ErrorSpec(400, "模型选择只能是内置或自定义", False),
    "model_field_missing": ErrorSpec(400, "自定义模型的三项都要填", False),
    "model_url_invalid": ErrorSpec(400, "地址要以网络协议开头，看看是不是漏了", False),
    "model_save_failed": ErrorSpec(500, "模型设置没存上，再试一次", True),
}

# ── 健康档案（血压 / 血糖 / 体重…）────────────────────────────────────
HEALTH: dict[str, ErrorSpec] = {
    "health_value_invalid": ErrorSpec(400, "这个数值填得不太对", False),
}

ERROR_TABLE: dict[str, ErrorSpec] = {
    **GENERIC,
    **CHAT,
    **LLM,
    **PLAN,
    **REMINDER,
    **MEMORY,
    **ACCOUNT,
    **MESSAGING,
    **HEALTH,
}

# 框架自带的 4xx 映射（FastAPI 抛 HTTPException 时用）
STATUS_FALLBACK: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    422: "invalid_request",
    429: "rate_limited",
}


def spec_of(code: str) -> ErrorSpec:
    """查表；未知 code 按 400 处理并保留 code 原文，方便排查"谁漏登记了" """
    return ERROR_TABLE.get(code, ErrorSpec(400, "请求失败", False))


def code_for_status(status_code: int) -> str:
    if status_code in STATUS_FALLBACK:
        return STATUS_FALLBACK[status_code]
    return "internal" if status_code >= 500 else "http_error"


def payload(code: str, message: str | None = None) -> dict:
    """错误体（code 未登记时用兜底 spec，message 可被调用方覆盖成人话）"""
    spec = spec_of(code)
    return {
        "error": {
            "code": code,
            "message": message or spec.message,
            "retryable": spec.retryable,
        }
    }


def api_error(code: str, message: str | None = None, status: int | None = None) -> JSONResponse:
    """路由里返回错误的标准写法：`return api_error("plan_not_found")`"""
    spec = spec_of(code)
    return JSONResponse(status_code=status or spec.status, content=payload(code, message))


def table() -> list[dict]:
    """给端侧/文档看的错误码表（`GET /v1/errors`）"""
    return [
        {
            "code": code,
            "status": spec.status,
            "message": spec.message,
            "retryable": spec.retryable,
        }
        for code, spec in sorted(ERROR_TABLE.items())
    ]
