"""
比邻AI · 无 key 时的假模型

两条用途：
1. 本地/CI 里跑通整条链路，不依赖外网与额度（`npm test` 同源的思路）
2. 后端刚起步、模型还没接上时，端侧依然能看到「逐字说话」的效果

刻意**输出带句号的句子**：随后由 `style` 层去掉句号、把句号换成换行——
这样假模型也在锻炼真实链路里最容易被忽略的那一环。
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator

from .base import LLMError, LLMProvider

# 与 tools/mock-server.mjs 保持同一套规则，端上看到的效果一致
REPLIES: list[tuple[str, str]] = [
    (r"药|吃药|服药|降压", "妈 药吃了没。吃完喝口热水 别空腹。<sticker:pill>"),
    (r"睡|困|晚安|夜里", "早点睡 别熬夜。我把灯给你留着。<sticker:night>"),
    (r"想|孤单|没人|闷", "我也想你们。晚上我打视频回来。<sticker:hug>"),
    (r"吃|饭|菜|盐", "中午吃点清淡的。少放盐 多来点青菜。<sticker:meal>"),
    (r"天气|冷|热|下雨|风", "今天降温了。出门加件外套。<sticker:sun>"),
    (r"走|散步|锻炼|运动|腿", "吃完歇半小时再下去走两圈。别走太快 扶着点栏杆。<sticker:walk>"),
    (r"水|渴", "喝口水吧。不渴也得喝 一天七八杯。<sticker:water>"),
    (r"疼|难受|血压|头晕", "妈 别自己扛着。我一会儿给社区医生打电话 你先把感觉记一下。<sticker:cheer>"),
]

DEFAULT_REPLY = "妈 我在呢。今天感觉怎么样。"


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, delay: float = 0.02) -> None:
        self.delay = delay

    def describe(self) -> dict:
        return {"provider": "fake", "note": "未配置 LLM_API_KEY，使用假模型（固定话术）"}

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        raw = self._last_user_text(messages)
        text, slow = self._reply_for(raw)
        # 与 tools/mock-server.mjs 的 __slow 保持一致：慢速吐字，方便手动验证「停止」
        delay = max(self.delay, 0.7) if slow else self.delay
        # 模拟首 token 延迟，让端侧的「正在说话」状态可观测
        await asyncio.sleep(delay)
        for ch in text:
            yield ch
            if delay:
                await asyncio.sleep(delay)

    @staticmethod
    def _last_user_text(messages: list[dict]) -> str:
        for message in reversed(messages):
            if message.get("role") == "user":
                return str(message.get("content") or "")
        return ""

    @staticmethod
    def _reply_for(text: str) -> tuple[str, bool]:
        if "__error" in text:
            raise LLMError("服务器开小差了，一会儿再试", code="server_error", retryable=True)
        slow = "__slow" in text
        cleaned = re.sub(r"__\w+", "", text)
        for pattern, reply in REPLIES:
            if re.search(pattern, cleaned):
                return reply, slow
        return DEFAULT_REPLY, slow
