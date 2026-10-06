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
# 口型关键帧：**在 done 之前发一次**。端侧据此驱动 3D 数字人的 viseme 形态键。
# 老端侧对未知事件是静默忽略的（uni-app/api/chat.js 的 normalize 有 default 分支），
# 所以新增这个事件对旧端向后兼容。
EVENT_LIPSYNC = "lipsync"
# 合成音频（**在 lipsync 之前发**：端侧要先拿到音频、起播，再按音频时钟驱动口型）。
# `url` 是**短期签名 URL**：端侧播放器带不了 Authorization 头，所以鉴权信息编进 URL。
EVENT_AUDIO = "audio"
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


def audio_frame(payload: dict) -> str:
    """合成音频帧。payload：`{assistantMsgId, url, durationMs, format}`。

    `url` 是**相对路径**（端侧自己拼 base），带 `expires` 与 `sig` 查询参数 ——
    播放器直接当 `src` 用，不需要任何请求头（见 `app/voice/audio_store.py`）。
    """
    return frame(EVENT_AUDIO, payload)


def lipsync_frame(payload: dict) -> str:
    """口型关键帧帧（payload 由 `app/avatar/visemes.py` 产出）。

    字段：`assistantMsgId` / `durationMs` / `cues[{c,b,e,v[]}]` / `version` / `source`。
    `source: "estimated"` 表示时间轴是按字数估算的（真 TTS 对齐后应为 `"tts-aligned"`），
    端侧可据此决定要不要额外做平滑。
    """
    return frame(EVENT_LIPSYNC, payload)


def done_frame(assistant_msg_id: str, finish_reason: str = "stop") -> str:
    return frame(EVENT_DONE, {"assistantMsgId": assistant_msg_id, "finishReason": finish_reason})


def error_frame(code: str, message: str, retryable: bool = True) -> str:
    return frame(EVENT_ERROR, {"code": code, "message": message, "retryable": retryable})
