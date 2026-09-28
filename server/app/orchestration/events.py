"""
比邻AI · SSE 帧编码（契约落点）

帧格式与事件名是端侧解析器的输入，**改动必须三处同步**：
    - 本文件
    - `tools/mock-server.mjs`
    - `uni-app/api/README.md`

关键约定：
- `json.dumps(..., ensure_ascii=False)`：中文直出，不转成 \\uXXXX（省带宽也更可读）
- 事件之间用空行分隔，端侧解析器按空行结算
- 心跳是注释行 `: ping`，端侧解析器会忽略
"""

from __future__ import annotations

import json

# 事件名（与 uni-app/api/chat.js 的 CHAT_EVENT 一致）
EVENT_META = "meta"
EVENT_TOKEN = "token"
EVENT_STICKER = "sticker"
EVENT_CARD = "card"
EVENT_DONE = "done"
EVENT_ERROR = "error"

HEARTBEAT = ": ping\n\n"


def frame(event: str, payload: dict) -> str:
    """编码一个 SSE 事件帧。"""
    return "event: " + event + "\ndata: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def meta_frame(conversation_id: str, assistant_msg_id: str, persona: dict) -> str:
    return frame(
        EVENT_META,
        {
            "conversationId": conversation_id,
            "assistantMsgId": assistant_msg_id,
            "persona": persona,
        },
    )


def token_frame(text: str) -> str:
    return frame(EVENT_TOKEN, {"t": text})


def sticker_frame(token: str) -> str:
    return frame(EVENT_STICKER, {"token": token})


def card_frame(card: dict) -> str:
    return frame(EVENT_CARD, {"card": card})


def done_frame(assistant_msg_id: str, finish_reason: str = "stop") -> str:
    return frame(EVENT_DONE, {"assistantMsgId": assistant_msg_id, "finishReason": finish_reason})


def error_frame(code: str, message: str, retryable: bool = True) -> str:
    return frame(EVENT_ERROR, {"code": code, "message": message, "retryable": retryable})
