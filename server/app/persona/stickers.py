"""
比邻AI · 表情包受控白名单（服务端侧）

设计方案 §3.1：**LLM 不允许输出 URL**，只能输出受控 token（`<sticker:love>`），
端上再映射成素材。白名单是这条约束的落点——模型偶尔会自己编一个 token
（`<sticker:heart>` 之类），服务端必须拦掉，否则端上会渲染成兜底表情甚至空图。

⚠️ 三处必须同步（改一处就要改全部）：
    - 本文件（服务端校验）
    - `uni-app/common/stickers.js`（端侧素材映射）
    - `tools/mock-server.mjs`（假后端）
"""

from __future__ import annotations

STICKER_TOKENS: tuple[str, ...] = (
    "love",
    "sun",
    "hug",
    "smile",
    "meal",
    "pill",
    "night",
    "cheer",
    "water",
    "walk",
)


def is_allowed_sticker(token: str) -> bool:
    return str(token or "").strip().lower() in STICKER_TOKENS
