"""
比邻AI · 会话编排

一次对话的完整链路：

    老人发言
      → 落库（乐观：端侧已经先上屏了）
      → 组装上下文（system prompt + 最近几轮）
      → 调模型（LLMProvider 流式）
      → 抽受控表情 token（<sticker:xxx>，白名单外的丢弃）
      → 风格后处理（句末去句号 / 句号转换行，流式逐字）
      → 产出事件（meta / token / sticker / done / error）
      → agent 消息落库

两个刻意的设计：

1. **`generate()` 是唯一的事实来源**。SSE 路径与一次性路径（/v1/chat/send）都消费它，
   所以两条路径的风格、表情、落库行为不可能分叉——这类"两边逻辑各写一遍"的分叉
   是后面最难查的一类 bug。
2. **meta 事件先于任何模型调用发出**。这样即便模型鉴权失败、超时、断流，
   端侧也已经拿到 assistantMsgId 并建好了气泡，随后收到 `error` 事件即可就地提示重发，
   不会出现"点了发送什么也没有"的空窗。
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator

from ..llm.base import LLMError, LLMProvider
from ..models.elder import DEFAULT_ELDER_ID
from ..models.message import (
    ROLE_AGENT,
    ROLE_ELDER,
    TYPE_CARD,
    TYPE_STICKER,
    TYPE_TEXT,
    ConversationStore,
    Message,
    new_id,
)
from ..persona.prompts import PersonaRegistry, build_system_prompt
from ..persona.stickers import is_allowed_sticker
from ..style.compliance import scan
from ..style.punctuation import StyleStreamer
from . import events
from .idempotency import STATE_DONE, STATE_IN_FLIGHT, IdempotencyStore
from .intents import needs_plan_card

logger = logging.getLogger("bilin.chat")

# 完整的受控表情标签
STICKER_TAG = re.compile(r"<\s*sticker\s*:\s*([A-Za-z_][A-Za-z0-9_]*)\s*>")
# 未闭合标签的兜底长度：超过这个长度还不见 '>' 就当成普通文本，防止缓冲区无限增长
MAX_TAG_LENGTH = 64


class StickerExtractor:
    """从流式文本里抽出 `<sticker:xxx>`，并且**半个标签也不泄露**。

    难点在于标签会被切开：`<stic` | `ker:pill>`。如果只是简单地做正则替换，
    中间那几帧就会把 `<stic` 当正文发给老人。所以尾部一旦出现"可能是标签前缀"的片段
    就扣住不发，等后续字符补齐——这与句号后处理是同一套思路。
    """

    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, delta: str) -> tuple[str, list[str]]:
        """返回 (可以下发的正文, 抽到的 token 列表)"""
        self._buffer += delta or ""
        return self._drain(hold_partial=True)

    def flush(self) -> tuple[str, list[str]]:
        """流结束：未闭合的标签片段直接丢弃（宁可少几个字符，也不泄露指令文本）"""
        text, stickers = self._drain(hold_partial=True)
        rest = self._buffer
        self._buffer = ""
        if rest and not _looks_like_tag_prefix(rest):
            text += rest
        return text, stickers

    # ---------------------------------------------------------------- 内部

    def _drain(self, hold_partial: bool) -> tuple[str, list[str]]:
        chunks: list[str] = []
        stickers: list[str] = []
        while True:
            match = STICKER_TAG.search(self._buffer)
            if not match:
                break
            chunks.append(self._buffer[: match.start()])
            stickers.append(match.group(1).lower())
            self._buffer = self._buffer[match.end() :]

        if hold_partial:
            head, tail = _split_holdable_tail(self._buffer)
            self._buffer = tail
            chunks.append(head)
        else:
            chunks.append(self._buffer)
            self._buffer = ""
        return "".join(chunks), stickers


def _looks_like_tag_prefix(text: str) -> bool:
    """`<` / `<st` / `<sticker` / `<sticker:pi` 都算标签前缀"""
    if not text.startswith("<"):
        return False
    if len(text) > MAX_TAG_LENGTH:
        return False
    probe = text[1:].lstrip().lower()
    name = probe.split(":", 1)[0]
    if name == "" or name == "sticker":
        return True
    return "sticker".startswith(name)


def _split_holdable_tail(buffer: str) -> tuple[str, str]:
    """把缓冲区末尾"可能是半个标签"的部分扣下来，其余可以安全下发。"""
    if not buffer:
        return "", ""
    lt = buffer.rfind("<")
    if lt == -1:
        return buffer, ""
    tail = buffer[lt:]
    if ">" in tail:
        return buffer, ""
    if _looks_like_tag_prefix(tail):
        return buffer[:lt], tail
    return buffer, ""


class ChatService:
    def __init__(
        self,
        provider: LLMProvider,
        store: ConversationStore,
        personas: PersonaRegistry,
        settings,
        elder_profiles: dict[str, dict] | None = None,
        plan_cards=None,
        idempotency: IdempotencyStore | None = None,
        memory_provider=None,
        after_turn=None,
    ) -> None:
        self.provider = provider
        self.store = store
        self.personas = personas
        self.settings = settings
        self.elder_profiles = elder_profiles or {}
        # 取今日计划卡片的回调（由 main.py 注入，避免编排层直接依赖计划引擎）
        self.plan_cards = plan_cards
        # 幂等：端侧重试复用同一个 clientMsgId，命中缓存就不重复生成（也不重复调模型）
        self.idempotency = idempotency
        # 记忆检索回调：(elder_id, 这一轮老人说的话) → 已格式化的记忆短句。
        # 做成回调而不是直接依赖 memory 模块，是为了让编排层仍然只依赖接口
        self.memory_provider = memory_provider
        # 一轮成功产出后的钩子（自动整理记忆用）。它在 done 事件之前执行，
        # 所以**必须很快**——慢一步老人就多等一步（模型抽取那部分由 main.py 另行后台跑）
        self.after_turn = after_turn

    # ------------------------------------------------------------ 事件流

    async def generate(
        self,
        conversation_id: str,
        text: str,
        persona_id: str | None = None,
        elder_id: str | None = None,
        client_msg_id: str = "",
    ) -> AsyncIterator[tuple[str, dict]]:
        """产出一轮对话的事件序列：meta → (token | sticker)* → done / error。"""
        persona = self.personas.get(persona_id)
        # 单老人原型：调用方没给 elder_id 时落到默认档案。
        # 不这么做的话，少传一个参数就会**静默丢掉 L1 档案与 L2/L3 记忆**——
        # 表现是"智能体突然不记得我是谁了"，且极难排查
        elder_id = elder_id or DEFAULT_ELDER_ID

        # ── 幂等闸门放在最前面 ──
        # 端侧网络抖动重试时会复用同一个 clientMsgId：命中缓存就直接回放，
        # 否则老人会收到两条一模一样的回复（还白花一次模型调用）
        state = "new"
        cached = None
        if self.idempotency is not None:
            state, cached = self.idempotency.begin(conversation_id, client_msg_id)
            if state == STATE_IN_FLIGHT:
                logger.info("同一 clientMsgId 正在生成中，拒绝重复请求：%s", client_msg_id)
                yield events.EVENT_ERROR, {
                    "code": "duplicate_request",
                    "message": "这句话我正在回，等我一下",
                    "retryable": True,
                }
                return
            if state == STATE_DONE and cached is not None:
                logger.info("命中幂等缓存，回放上一轮结果：%s", client_msg_id)
                yield events.EVENT_META, {
                    "conversationId": conversation_id,
                    "assistantMsgId": cached.assistant_msg_id or new_id("a"),
                    "persona": persona.to_public(),
                    "replayed": True,
                }
                if cached.text:
                    # 回放不逐字下发：这是"补一次刚才没收到的话"，不是重新说话
                    yield events.EVENT_TOKEN, {"t": cached.text}
                for token in cached.stickers:
                    yield events.EVENT_STICKER, {"token": token}
                yield events.EVENT_DONE, {
                    "assistantMsgId": cached.assistant_msg_id or "",
                    "finishReason": "stop",
                    "replayed": True,
                }
                return

        self.store.append(
            conversation_id,
            Message(id=new_id("m"), role=ROLE_ELDER, type=TYPE_TEXT, text=text),
        )
        assistant_id = new_id("a")
        yield events.EVENT_META, {
            "conversationId": conversation_id,
            "assistantMsgId": assistant_id,
            "persona": persona.to_public(),
        }

        messages = self._build_messages(conversation_id, persona, elder_id, text)
        streamer = StyleStreamer()
        extractor = StickerExtractor()
        # 本轮产出的片段，按顺序落库：正文 / 表情（顺序与端上看到的完全一致）
        parts: list[dict] = []

        def current_text_part() -> dict:
            if not parts or parts[-1]["type"] != TYPE_TEXT:
                parts.append({"type": TYPE_TEXT, "text": ""})
            return parts[-1]

        # 只有真正产出内容才算"完成"，否则在 finally 里放开幂等记录（见下面的注释）
        completed = False
        try:
            async for delta in self.provider.stream(messages):
                plain, sticker_tokens = extractor.feed(delta)
                if plain:
                    chunk = streamer.feed(plain)
                    if chunk:
                        current_text_part()["text"] += chunk
                        yield events.EVENT_TOKEN, {"t": chunk}
                for token in sticker_tokens:
                    if not is_allowed_sticker(token):
                        # 模型自己编的 token：拦掉，端上不会出现空图
                        logger.warning("丢弃白名单外的表情 token: %s", token)
                        continue
                    # 表情之前先结算句子，保证"先说完话再发表情"
                    streamer.flush()
                    parts.append({"type": TYPE_STICKER, "sticker": token})
                    yield events.EVENT_STICKER, {"token": token}

            # 收尾：把最后一段没有标点的文字吐出去
            tail_text, tail_stickers = extractor.flush()
            if tail_text:
                chunk = streamer.feed(tail_text)
                if chunk:
                    current_text_part()["text"] += chunk
                    yield events.EVENT_TOKEN, {"t": chunk}
            streamer.flush()
            for token in tail_stickers:
                if is_allowed_sticker(token):
                    parts.append({"type": TYPE_STICKER, "sticker": token})
                    yield events.EVENT_STICKER, {"token": token}

            # 越界话术持续监控：不拦回复（拦了老人会觉得莫名其妙），只留痕，
            # 让"模型偶尔说错话"这件事有人知道，而不是等出事才发现
            reply_text = "".join(
                part.get("text", "") for part in parts if part["type"] == TYPE_TEXT
            )
            for hint in scan(reply_text):
                logger.warning("回复命中越界话术检查：%s | 原文：%s", hint, reply_text[:60])

            # 老人问「今天要做什么」这类问题时，顺带把今日计划作为卡片发出去
            if self.plan_cards and needs_plan_card(text):
                try:
                    cards = self.plan_cards(elder_id) or []
                except Exception:  # noqa: BLE001 —— 卡片取不到不影响对话本身
                    logger.exception("取今日计划卡片失败")
                    cards = []
                for card in cards[:3]:
                    parts.append({"type": TYPE_CARD, "card": card})
                    yield events.EVENT_CARD, {"card": card}

            self._persist(conversation_id, parts)
            has_visible = any(
                (part["type"] == TYPE_TEXT and part.get("text", "").strip())
                or part["type"] in (TYPE_STICKER, TYPE_CARD)
                for part in parts
            )
            if not has_visible:
                # 端侧收到 done 但一个字都没有时会显示「没听清 再说一遍」，这里留痕方便排查
                logger.info("本轮没有任何内容产出（会话 %s）", conversation_id)

            # 产出成功才写幂等缓存：第一轮就失败（模型鉴权错/超时）时不能写，
            # 否则端侧重试会拿到空回复，永远修不好
            if self.idempotency is not None and has_visible:
                self.idempotency.complete(
                    conversation_id,
                    client_msg_id,
                    text=reply_text,
                    stickers=[part["sticker"] for part in parts if part["type"] == TYPE_STICKER],
                    assistant_msg_id=assistant_id,
                )
                completed = True

            # 自动整理记忆（L2/L3）：默认关着；开了也只做规则抽取，很快。
            # 放在 done 之前是为了"这一轮说过的事"立刻可检索；模型抽取那部分另行后台跑
            if self.after_turn is not None and elder_id and (text or "").strip():
                try:
                    await self.after_turn(elder_id, text)
                except Exception:  # noqa: BLE001 —— 记忆整理失败不能影响这一轮对话
                    logger.warning("本轮记忆整理失败，已忽略", exc_info=True)

            yield events.EVENT_DONE, {"assistantMsgId": assistant_id, "finishReason": "stop"}

        except LLMError as exc:
            logger.warning("模型调用失败: code=%s status=%s", exc.code, exc.status_code)
            yield events.EVENT_ERROR, exc.to_payload()
        except Exception:  # noqa: BLE001 —— 兜住一切，绝不让老人端看到连接被掐断
            logger.exception("对话生成出现未预期错误")
            yield events.EVENT_ERROR, {
                "code": "internal",
                "message": "我这边出了点小问题，一会儿再试",
                "retryable": True,
            }
        finally:
            # 失败 / 被端侧中断 / 一个字都没产出：把 in-flight 记录放掉。
            # 不放的话，端侧拿同一个 clientMsgId 重试会一直收到"这句话我正在回，等我一下"——
            # 老人点了重试却永远等不到，比重复回复更糟。
            if not completed and self.idempotency is not None:
                self.idempotency.release(conversation_id, client_msg_id)

    # ---------------------------------------------------------- SSE 封装

    async def stream_sse(
        self,
        conversation_id: str,
        text: str,
        persona_id: str | None = None,
        elder_id: str | None = None,
        client_msg_id: str = "",
    ) -> AsyncIterator[str]:
        """把事件序列编码成 SSE 帧，并在等模型时插入心跳注释。

        为什么要心跳：端侧有 20s 首字节看门狗（`api/transport.js`），而推理模型的
        第一个 content token 可能要等几十秒（思维链不算 content，我们不转发它）。
        没有心跳，端侧会在老人什么都没看到的情况下直接断开重试。

        实现上用「生产者任务 + 定时取件」：生成逻辑照常跑，取件超时就吐一个 `: ping`。
        客户端断开时（Starlette 取消本生成器）finally 里会把生产者一并取消，不留悬挂任务。
        """
        interval = max(0.1, float(getattr(self.settings, "sse_heartbeat_seconds", 10.0)))
        queue: asyncio.Queue = asyncio.Queue()
        finished = object()

        async def produce() -> None:
            try:
                async for item in self.generate(
                    conversation_id, text, persona_id, elder_id, client_msg_id
                ):
                    await queue.put(item)
            finally:
                await queue.put(finished)

        producer = asyncio.create_task(produce())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=interval)
                except asyncio.TimeoutError:
                    yield events.HEARTBEAT
                    continue
                if item is finished:
                    return
                name, payload = item
                yield events.frame(name, payload)
        finally:
            if not producer.done():
                producer.cancel()

    # -------------------------------------------------------- 一次性回复

    async def reply_once(
        self,
        conversation_id: str,
        text: str,
        persona_id: str | None = None,
        elder_id: str | None = None,
        client_msg_id: str = "",
    ) -> dict:
        """非流式路径（/v1/chat/send）。契约里 text/sticker/card 各最多一个。"""
        body = ""
        stickers: list[str] = []
        cards: list[dict] = []
        assistant_id = ""
        persona_public: dict = {}
        error: dict | None = None

        async for name, payload in self.generate(
            conversation_id, text, persona_id, elder_id, client_msg_id
        ):
            if name == events.EVENT_META:
                assistant_id = payload["assistantMsgId"]
                persona_public = payload["persona"]
            elif name == events.EVENT_TOKEN:
                body += payload["t"]
            elif name == events.EVENT_STICKER:
                stickers.append(payload["token"])
                # 表情/卡片把正文切成两段：这里补一个换行，避免两句话黏在一起
                if body and not body.endswith("\n"):
                    body += "\n"
            elif name == events.EVENT_CARD:
                cards.append(payload["card"])
                if body and not body.endswith("\n"):
                    body += "\n"
            elif name == events.EVENT_ERROR:
                error = payload

        if error:
            raise LLMError(
                error["message"],
                code=error["code"],
                retryable=bool(error.get("retryable", True)),
            )

        return {
            "conversationId": conversation_id,
            "assistantMsgId": assistant_id,
            "persona": persona_public,
            "text": body.rstrip("\n"),
            "sticker": stickers[0] if stickers else "",
            "card": cards[0] if cards else None,
            "finishReason": "stop",
        }

    # ---------------------------------------------------------------- 内部

    def _build_messages(
        self,
        conversation_id: str,
        persona,
        elder_id: str | None,
        query_text: str = "",
    ) -> list[dict]:
        elder = self.elder_profiles.get(elder_id) if elder_id else None
        # L2/L3：按这一轮老人说的话检索相关往事与偏好（取不到就什么都不注入）
        memories: list[str] = []
        if self.memory_provider and elder_id and query_text:
            try:
                memories = self.memory_provider(elder_id, query_text) or []
            except Exception:  # noqa: BLE001 —— 记忆取不到绝不能影响对话本身
                logger.exception("记忆检索失败，本轮不注入记忆")
                memories = []
        messages: list[dict] = [
            {"role": "system", "content": build_system_prompt(persona, elder, memories)}
        ]
        limit = max(2, self.settings.history_turns * 2 + 2)
        for message in self.store.history(conversation_id, limit=limit):
            if message.type != TYPE_TEXT or not message.text:
                # 语音 / 表情 / 卡片不进上下文：P0 只有文本语义是可靠的
                continue
            if message.role == ROLE_ELDER:
                messages.append({"role": "user", "content": message.text})
            elif message.role == ROLE_AGENT:
                messages.append({"role": "assistant", "content": message.text})
        return messages

    def _persist(self, conversation_id: str, parts: list[dict]) -> None:
        for part in parts:
            if part["type"] == TYPE_TEXT:
                body = (part.get("text") or "").strip()
                if not body:
                    continue
                self.store.append(
                    conversation_id,
                    Message(id=new_id("a"), role=ROLE_AGENT, type=TYPE_TEXT, text=body),
                )
            elif part["type"] == TYPE_STICKER:
                self.store.append(
                    conversation_id,
                    Message(
                        id=new_id("a"),
                        role=ROLE_AGENT,
                        type=TYPE_STICKER,
                        sticker=part["sticker"],
                    ),
                )
            elif part["type"] == TYPE_CARD:
                self.store.append(
                    conversation_id,
                    Message(
                        id=new_id("a"),
                        role=ROLE_AGENT,
                        type=TYPE_CARD,
                        card=part.get("card"),
                    ),
                )
