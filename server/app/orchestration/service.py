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
import inspect
import logging
import os
import re
from collections.abc import AsyncIterator

from ..avatar.visemes import build_lipsync_payload, from_alignment
from ..llm.base import LLMError, LLMProvider
from ..voice import audio_store
from ..voice.gateway import NullTtsProvider
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
from ..persona.prompts import (
    KIND_MEDICAL,
    MODE_AUTO,
    PersonaRegistry,
    build_system_prompt,
    choose_persona,
    ensure_medical_notice,
    guard_address,
    normalize_mode,
    merge_orphan_address,
    fix_leading_address,
    strip_medical_notice,
)
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

#: 撞上 max_tokens 后最多续写几次。
#: 上限存在的意义：万一模型陷入"总也写不完"的循环，不能无休止地烧钱和时间。
#: 3 次足够覆盖正常的长回复（每次 800 token）。
MAX_CONTINUATIONS = 3

#: "这句话说完了"的判据：以中文/英文句末标点结尾。
#: 用来决定续写时是**另起一条消息**（读起来是两段完整的话）还是**并回同一条**
#: （上一段停在半句中间，硬拆成两条会两句都读不通）。
END_OF_SENTENCE = re.compile(r"[。！？!?…；;]\s*$")

#: 续写时交给模型的指令。
#: 关键是"不要重复已经说过的"——否则第二段会把第一段重抄一遍。
CONTINUE_PROMPT = (
    "你刚才的话被长度限制截断了。请**接着最后一句继续说完**，"
    "不要重复已经说过的内容，不要重新打招呼，直接接着写。"
)


async def _stream_with_finish(
    provider: LLMProvider,
    messages: list[dict],
    on_finish,
) -> AsyncIterator[str]:
    """调 `provider.stream`，**只在 provider 支持时**传 `on_finish`。

    为什么要这层适配：
      `on_finish` 是用来取 `finish_reason` 的（判断回复是否被 token 上限截断）。
      但它是**新增的可选参数**，而工程里有多处自带 provider
      （测试的 ScriptedProvider / FakeProvider 等）签名仍是 `stream(messages)`。
      直接传 `on_finish=` 会让它们 TypeError，把既有测试全打挂——这类
      "新功能顺手改了公共契约"造成的回归最难查，所以在这里挡掉。

    支持与否用**签名自省**判断，而不是 try/except TypeError：
    后者会把 provider 内部真正的 TypeError 一起吞掉，变成难查的静默降级。
    """
    if _accepts_on_finish(provider):
        async for chunk in provider.stream(messages, on_finish=on_finish):
            yield chunk
        return
    async for chunk in provider.stream(messages):
        yield chunk


def _accepts_on_finish(provider: LLMProvider) -> bool:
    """provider.stream 是否声明了 on_finish 参数（含 **kwargs 的情况）。"""
    try:
        params = inspect.signature(provider.stream).parameters
    except (TypeError, ValueError):
        return False
    if "on_finish" in params:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


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
        health_provider=None,
        case_provider=None,
        after_turn=None,
        voice=None,
        provider_resolver=None,
        wiki=None,
        compactor=None,
        care=None,
    ) -> None:
        self.provider = provider
        #: 按账号解析 LLM（智能体设置里可以给某个账号换模型）。
        #: 为空时所有账号共用 `provider`（老行为，测试里也这样）。
        self.provider_resolver = provider_resolver
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
        # 健康数值回调：elder_id → 最近几次测量的短句（血压/血糖/体重…）。
        # 同样是回调而不是直接 import health 模块：编排层只依赖接口，
        # 而且"健康数据没接上"时对话必须照常工作。
        self.health_provider = health_provider
        # 病例病史回调：elder_id → 最近几份病历的标题级信息（诊断/就诊日期）。
        # 与 health_provider 同一个理由：编排层只依赖接口
        self.case_provider = case_provider
        #: LLM wiki（老人画像 + 子女说话风格）。
        #: 为空时完全不启用 —— 老行为照常，测试里也不注入。
        #: 作用有两头：注入（同步，影响这轮 prompt）与学习（异步，不拖慢回复）。
        self.wiki = wiki
        #: 对话历史压缩器。为空时不压缩（只喂最近 N 轮，老行为）。
        #: 超过阈值时把旧对话压成摘要，摘要会注进 prompt 补上丢掉的记忆。
        self.compactor = compactor
        #: 主动关心（好奇心提问 + 到期回访）。为空时不主动发消息。
        #: 它同时负责"他说的话算不算回答了上次的提问""有没有约定将来的事"。
        self.care = care
        # 一轮成功产出后的钩子（自动整理记忆用）。它在 done 事件之前执行，
        # 所以**必须很快**——慢一步老人就多等一步（模型抽取那部分由 main.py 另行后台跑）
        self.after_turn = after_turn
        # 语音（TTS + 字级时间戳）：`app/voice/gateway.py` 里装配的 Provider。
        # 做成**可注入且可选**：没配（Null*）时口型走估算版，对话完全不受影响。
        # 默认取全局装配结果，测试与部署都可以覆盖。
        if voice is None:
            from ..voice import gateway as voice_gateway
            voice = voice_gateway.build_tts_provider()
        self.voice = voice
        # 音频暂存（进程内 + TTL）：TTS 产出音频后放进来，音频事件只带签名 URL。
        # 放在实例上而不是全局单例，是为了测试能注入自己的 store。
        from ..voice.audio_store import get_store
        self.audio_store = get_store()
        # `_build_lipsync()` 顺手把"这一轮要下发的音频事件 payload"放这里，
        # 由 generate() 在 lipsync **之前**取走发出（顺序：audio → lipsync → done）。
        self._last_audio_payload: dict | None = None

    # ------------------------------------------------------------ 事件流

    async def generate(
        self,
        conversation_id: str,
        text: str,
        persona_id: str | None = None,
        elder_id: str | None = None,
        client_msg_id: str = "",
        account_id: str = "",
        persona_mode: str = MODE_AUTO,
    ) -> AsyncIterator[tuple[str, dict]]:
        """产出一轮对话的事件序列：meta → (token | sticker)* → done / error。

        `account_id`：用哪个账号的模型配置（智能体设置）。为空则用服务端内置模型。
        """
        persona = self.personas.get(persona_id)
        # 单老人原型：调用方没给 elder_id 时落到默认档案。
        # 不这么做的话，少传一个参数就会**静默丢掉 L1 档案与 L2/L3 记忆**——
        # 表现是"智能体突然不记得我是谁了"，且极难排查
        elder_id = elder_id or DEFAULT_ELDER_ID

        # 按账号挑模型：没配 resolver（或没配自定义）就是内置那个
        provider = self.provider
        if self.provider_resolver is not None:
            try:
                provider = self.provider_resolver.resolve(account_id).provider
            except Exception:  # noqa: BLE001 —— 解析失败退回内置，绝不能让对话打不开
                logger.exception("解析账号模型配置失败，本轮改用内置模型")
                provider = self.provider

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

        # ── 按这一轮说的话 + 端侧模式选人设（需求：日常 / 医疗双人设）──
        # 必须在发 meta **之前**决定：meta 里的 persona 会下发给端侧，
        # 先发默认再切换的话，端侧看到的人设和实际回答的人设会对不上。
        # `persona_mode` 是端侧的开关（auto/chat/medical），auto 时按内容自动切。
        persona = choose_persona(text, self.personas, persona_id, persona_mode)
        medical_turn = persona.kind == KIND_MEDICAL

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
            # ── 撞上 token 上限时接着写，而不是把半句话丢给老人 ──
            #
            # 背景：max_tokens 原来是 300，模型正常长度的回复会被**说到一半硬切断**，
            # 端上就是一句没头没尾的话（用户反馈的问题）。
            # 现在 max_tokens 放宽到 800 作为安全阀；万一还是撞上限，
            # 就带着"已经说过的内容"再要一次，让模型把话说完。
            #
            # 为什么不把两段拼进同一个气泡：两段加起来会是一大段文字，
            # 对老人来说"两条短消息"比"一大块"好读。所以续写会**另起一条消息**
            # （发第二个 meta，端上就是第二个气泡）。
            # 但如果上一段是**停在半句中间**，另起一条会变成两句都读不通，
            # 那种情况就并回同一条（先保证读得通，再谈好不好读）。
            reply_messages = list(messages)
            for attempt in range(MAX_CONTINUATIONS + 1):
                finish_reason = "stop"

                def _note_finish(reason: str) -> None:
                    nonlocal finish_reason
                    finish_reason = reason

                streamed = ""

                # 开头闸门：模型常把「您」当称呼甩在开头（「您 我知道…」）。
                # 之前只在**落库/合成前**合并，字幕看着好了，可语音念的是合并前的原文，
                # 所以听起来还是"先说一个字'您'，停一下，再接着说"。
                # 这里在**发出之前**就把这个孤零零的前缀丢掉，字幕与语音才是同一份。
                gate_open = False
                gate_buf = ""

                def gate(chunk: str) -> str:
                    """放行/修正回复开头那几个字（孤立的「您」、漂移的「妈」）。"""
                    nonlocal gate_open, gate_buf
                    if gate_open or not chunk:
                        return chunk
                    gate_buf += chunk
                    fixed = fix_leading_address(gate_buf, persona.address)
                    if fixed != gate_buf:
                        # 判定成功：丢掉/替换掉开头那个称呼
                        gate_open = True
                        out = fixed
                        gate_buf = ""
                        return out
                    # 还看不出来（可能只有第一个字）：先压着，等下一片
                    if len(gate_buf) < 4:
                        return ""
                    # 不是"开头称呼"（比如「您先坐着」「药吃了没」）→ 原样放行
                    gate_open = True
                    out = gate_buf
                    gate_buf = ""
                    return out

                async for delta in _stream_with_finish(provider, reply_messages, _note_finish):
                    streamed += delta
                    plain, sticker_tokens = extractor.feed(delta)
                    if plain:
                        chunk = gate(streamer.feed(plain))
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

                # 自然说完、或已经续到上限：收工
                if finish_reason != "length" or attempt >= MAX_CONTINUATIONS:
                    if finish_reason == "length":
                        logger.warning(
                            "回复续写了 %s 次仍未收尾，按现状收下（可能仍有截断）", attempt
                        )
                    break

                # 撞上限了。只在**上一段停在句子边界**时另起一条消息，
                # 否则并回同一条（并回用空串表示，端侧不会新开气泡）。
                starts_new_message = bool(END_OF_SENTENCE.search(streamed.rstrip()))
                if starts_new_message:
                    streamer.flush()
                    assistant_id = new_id("a")
                    yield events.EVENT_META, {
                        "conversationId": conversation_id,
                        "assistantMsgId": assistant_id,
                        "persona": persona.to_public(),
                        "continued": True,
                    }
                    parts.append({"type": TYPE_TEXT, "text": ""})

                logger.info(
                    "回复撞上 token 上限，继续生成（第 %s 次，另起消息=%s）",
                    attempt + 1,
                    starts_new_message,
                )
                # 把"已经说过的话"当作模型的上一轮回答，再请它接着说完
                reply_messages = reply_messages + [
                    {"role": "assistant", "content": streamed},
                    {"role": "user", "content": CONTINUE_PROMPT},
                ]

            # 收尾：把最后一段没有标点的文字吐出去
            tail_text, tail_stickers = extractor.flush()
            if tail_text:
                chunk = gate(streamer.feed(tail_text))
                if chunk:
                    current_text_part()["text"] += chunk
                    yield events.EVENT_TOKEN, {"t": chunk}
            # 闸门里还压着东西（整篇回复只有"您"这种极端情况）→ 放出来，别吞字
            if not gate_open and gate_buf:
                current_text_part()["text"] += gate_buf
                yield events.EVENT_TOKEN, {"t": gate_buf}
                gate_open = True
                gate_buf = ""
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

            # ── 医疗话题的强制免责（需求：没认真询问时也必须带"仅供参考…"）──
            # 放在**落库之前、流式结束之后**处理：
            #   · 流式过程中插一句会打乱输出顺序，而免责本就该在回答末尾；
            #   · 必须在落库前补，否则刷新页面后历史里就没有这句（合规要求，不能丢）。
            # 是否补由代码判断（见 ensure_medical_notice），不指望模型每次都记得。
            medical_reply = "".join(
                part.get("text", "") for part in parts if part["type"] == TYPE_TEXT
            )
            # 先纠正称呼漂移（模型会把人设里的「您」说成「妈」），再判断免责：
            # 两步顺序不能反——称呼纠正会改动文本，必须在它之后做最终拼接。
            guarded = guard_address(medical_reply, persona.address)
            # 再把"孤零零的称呼"并回句子（模型会输出「您 我知道…」这种半句话）
            merged = merge_orphan_address(guarded, persona.address)
            if merged != guarded:
                guarded = merged
            if guarded != medical_reply and parts and parts[-1]["type"] == TYPE_TEXT:
                parts[-1]["text"] = guarded
                # 称呼是在流式过程中逐字发出去过的，这里无法撤回；
                # 下一轮会带上正确称呼，所以只记日志不重发（避免老人看到"改口"的怪异感）
                logger.info("纠正称呼漂移（会话 %s）：%s", conversation_id, persona.address)
            final_text = ensure_medical_notice(
                guarded, medical_turn, text, persona.address
            )
            if final_text != guarded:
                extra = final_text[len(guarded):]
                if extra and parts and parts[-1]["type"] == TYPE_TEXT:
                    # 直接并进最后一个文本片段：这样只落库一次，不会多出一条消息
                    parts[-1]["text"] = final_text
                    yield events.EVENT_TOKEN, {"t": extra}
                    logger.info("本轮命中医疗话题，已补免责声明（会话 %s）", conversation_id)

            # ── 反向兜底：日常闲聊里把多余的免责剥掉 ────────────────
            # 微调后模型学会了"高危必须提医生"，副作用是日常话题也乱加
            # （"我新学了个手机功能" → "…还是听医生的"）。
            # ⚠️ 流式已经把字发出去了，撤不回；所以剥完要把最终文本放进
            #    done 事件，由端侧用整段替换覆盖掉已经显示的那一版。
            stripped = strip_medical_notice(final_text, medical_turn, text)
            if stripped != final_text:
                final_text = stripped
                if parts and parts[-1]["type"] == TYPE_TEXT:
                    parts[-1]["text"] = final_text
                logger.info("日常轮剥掉多余免责（会话 %s）", conversation_id)

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

            # ── wiki 学习：从对话里学"他是什么样的人" ──
            # **不每轮都学**：攒够 N 轮（默认 5）才调一次模型。
            # 理由：每轮学一次要额外一次模型调用（成本翻倍），而单轮增量信息很少，
            #      效果差别不大、钱差一倍；一次给模型 5 轮上下文，质量反而更好。
            # collect_turn 只是入缓冲，立刻返回，不拖慢回复。
            if getattr(self, "wiki", None) is not None and elder_id and has_visible and (text or "").strip():
                self.wiki.collect_turn(elder_id, text, reply_text, provider)

            # ── 对话历史压缩：超过阈值就把旧的那段压成摘要 ──
            # 异步：压缩要调模型，挂在请求里会让老人觉得这轮回得慢。
            # 晚一轮生效完全可以接受（这一轮本来也带最近几轮原文）。
            if getattr(self, "compactor", None) is not None:
                self.compactor.maybe_compress(conversation_id, elder_id, provider)

            # ── 主动关心：记账（不发消息，只更新状态）──
            # 三件事：
            #   ① 他说话了 → 算作上次主动提问的回答
            #   ② 这句话里提到将来的事 → 记一条回访（"下周二去复查"）
            #   ③ 记下"刚聊过"，后台就不会马上插一句"吃了吗"
            care = getattr(self, "care", None)
            if care is not None and elder_id:
                try:
                    care.note_conversation(elder_id, conversation_id)
                    care.note_chat(elder_id)
                    care.record_answer(elder_id, text)
                    care.add_followup_if_any(elder_id, text)
                except Exception:  # noqa: BLE001 —— 记账失败不能影响对话
                    logger.exception("主动关心记账失败（不影响本轮回复）")

            # 口型关键帧：放在 done 之前发一次（端侧按 assistantMsgId 与这条回复关联）。
            # 只在**有正文**时发：纯表情/卡片不需要口型，发了反而让数字人"对空气张嘴"。
            #
            # 两条产出路径（**共用同一契约**，端侧只认 cues）：
            #   ① TTS 给了字级时间戳（如百炼 Qwen-Audio-TTS / 或 CosyVoice+强制对齐）
            #      → `from_alignment`，source: "tts-aligned"
            #   ② 没配 TTS 或没拿到时间戳 → `build_lipsync_payload`，source: "estimated"
            # 语音是**增强项**：任何失败都只记日志，绝不中断对话。
            # ⚠️ 必须用**定稿文本**（final_text）：reply_text 是流式途中拼的，
            #    既没有称呼纠正、也没有免责补全 —— 用它合成语音，就会出现
            #    "字幕是改好的、念的还是原文"（用户听到的多一个"您"就是这个原因）。
            if (final_text or "").strip():
                try:
                    # **音频先发、口型后发**：端侧要先把音频下载并起播，
                    # 才能用"音频播放时刻"驱动口型（否则音画会漂移）。
                    # ⚠️ 生产顺序不能反（真机踩过）：音频 payload 是 `_build_lipsync()`
                    # **内部**合成 TTS 时顺手写进 `self._last_audio_payload` 的。
                    # 第一版写成"先取 payload 再合成"，取到的永远是 None —— 于是配了百炼 TTS
                    # 也一个 audio 事件都不发，端侧表现就是"数字人没声音"。
                    audio_payload, payload = await self._audio_then_lipsync(final_text, assistant_id)
                    if audio_payload:
                        yield events.EVENT_AUDIO, audio_payload
                    yield events.EVENT_LIPSYNC, payload
                except Exception:  # noqa: BLE001 —— 口型是增强项，绝不能因为它失败而中断对话
                    logger.warning("口型关键帧生成失败，已忽略", exc_info=True)

            # 带上明文终稿：日常轮剥掉免责后，已流式发出的字收回不来，
            # 端侧收到 done 时用 `text` 整段替换气泡内容（字段可选，老客户端忽略即可）。
            yield events.EVENT_DONE, {
                "assistantMsgId": assistant_id,
                "finishReason": "stop",
                "text": final_text,
            }

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
        account_id: str = "",
        persona_mode: str = MODE_AUTO,
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
                    conversation_id, text, persona_id, elder_id,
                    client_msg_id, account_id, persona_mode,
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

    # ---------------------------------------------------------------- 内部

    async def _build_lipsync(self, reply_text: str, assistant_id: str) -> dict:
        """产出这一轮的口型关键帧：**优先用真语音时间戳**，拿不到就回退估算版。

        为什么放在编排层而不是别处：
        · 只有在"回复文本已经定稿"之后才能合成语音（文本还会被 StyleStreamer 重排）；
        · 语音是增强项，失败必须静默降级 —— 这个判断要贴着事件流写才好读。
        """
        # ① 真语音时间戳（百炼 Qwen-Audio-TTS 自带；或 CosyVoice + 强制对齐）
        provider = self.voice
        if provider is not None and not isinstance(provider, NullTtsProvider):
            # 百炼是"一次调用同时拿音频与时间戳"；CosyVoice 路线这里只拿音频，
            # 时间戳要另外走 Aligner —— 两条路都由 Provider 自己决定，
            # 编排层只看 "有没有 word_segments"。
            result = await provider.synthesize(reply_text)
            if result.ok:
                # 音频落进暂存、拼出短期签名 URL，交给 generate() 在 lipsync 之前发。
                # 读文件失败不该影响对话，所以整段包在 try 里。
                self._last_audio_payload = self._store_audio(result, assistant_id)
                segments = (result.extra or {}).get("word_segments") or []
                if segments:
                    return from_alignment(segments, assistant_id)
                logger.info("TTS 没给字级时间戳（音色可能不支持）→ 口型回退估算版")
            else:
                logger.info("TTS 未产出音频（%s）→ 口型回退估算版", result.reason)
        # ② 估算版（本机没有 TTS 时的默认，也是上面所有失败的兜底）
        return build_lipsync_payload(reply_text, assistant_id)

    async def _audio_then_lipsync(self, reply_text: str, assistant_id: str):
        """一次调用同时给出"音频事件 payload"与"口型 payload"（发送顺序由调用方决定）。

        为什么要有这个方法：音频 payload 是 `_build_lipsync()` **内部**合成 TTS 时
        顺手写进 `self._last_audio_payload` 的，所以"取音频"必须发生在"合成"之后。
        两件事拆在两处写时极易写成"先取后合成"——第一版就是这样，取到的永远是 None，
        端侧从头到尾收不到 audio 事件（配了 TTS 也没声音）。收进一个方法后顺序不可能再写反，
        单测也能直接断言（见 tests/test_lipsync_wiring.py）。

        返回 `(音频事件 payload 或 None, 口型 payload)`；音频失败时前者为 None，对话照常。
        """
        payload = await self._build_lipsync(reply_text, assistant_id)
        audio_payload = self._last_audio_payload
        self._last_audio_payload = None
        return audio_payload, payload

    def _store_audio(self, result, assistant_id: str) -> dict | None:
        """把 TTS 产出的音频放进暂存，拼出端侧可直取的**签名 URL**。

        返回 `None` 表示"没有可用音频"（读文件失败/内容为空）——
        这时**不发音频事件**，端侧会退回"用估算时钟驱动口型"，对话照常。
        """
        path = getattr(result, "audio_path", "") or ""
        if not path:
            return None
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError:
            logger.warning("读取合成音频失败：%s", path, exc_info=True)
            return None
        if not data:
            return None
        audio_id = self.audio_store.put(data)
        if not audio_id:
            return None
        settings = getattr(self, "settings", None)
        return {
            "assistantMsgId": assistant_id,
            "url": audio_store.build_audio_url(audio_id, settings),
            # 时长：TTS 若给了就用（百炼按字级时间戳末字给出），否则 0 由端侧按音频实际时长处理
            "durationMs": int(getattr(result, "duration_ms", 0) or 0),
            # 格式跟着**实际落盘的扩展名**走（百炼是 mp3、CosyVoice 是 wav）：
            # 原来写死 "mp3"，wav 路线会下发错误的 format
            "format": (os.path.splitext(path)[1].lstrip(".").lower() or "mp3"),
            "bytes": len(data),
        }

    async def reply_once(
        self,
        conversation_id: str,
        text: str,
        persona_id: str | None = None,
        elder_id: str | None = None,
        client_msg_id: str = "",
        account_id: str = "",
        persona_mode: str = MODE_AUTO,
    ) -> dict:
        """非流式路径（/v1/chat/send）。契约里 text/sticker/card 各最多一个。"""
        body = ""
        stickers: list[str] = []
        cards: list[dict] = []
        assistant_id = ""
        persona_public: dict = {}
        error: dict | None = None

        async for name, payload in self.generate(
            conversation_id, text, persona_id, elder_id, client_msg_id, account_id, persona_mode
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

        # ──── 以下为 ChatService 的内部辅助 ────

    def _summary_of(self, elder_id: str) -> str:
        """取这个老人的历史摘要（没有就空串）。

        按**老人**取而不是按会话：记忆应当跟着人走。
        跟 AI 聊过的和跟家人聊过的共享同一份摘要，否则
        "家人会话里说过的复查日期"在 AI 会话里就不存在了。
        """
        compactor = getattr(self, "compactor", None)
        if compactor is None:
            return ""
        try:
            return compactor.summary_of(elder_id)
        except Exception:  # noqa: BLE001 —— 摘要取不到就当没有
            logger.exception("读历史摘要失败")
            return ""

    def _followup_lines(self, elder_id: str) -> list[str]:
        """今天该提的回访（他说过的事到期了）。"""
        care = getattr(self, "care", None)
        if care is None or not elder_id:
            return []
        try:
            return care.followup_lines(elder_id)
        except Exception:  # noqa: BLE001 —— 回访取不到就当没有
            logger.exception("读回访失败")
            return []

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
        # 身体测量数值：最近几次（取不到就什么都不注入，不影响对话）
        health: list[str] = []
        if self.health_provider and elder_id:
            try:
                health = self.health_provider(elder_id) or []
            except Exception:  # noqa: BLE001
                logger.exception("健康数值取不到，本轮不注入")
                health = []
        # 病例病史：最近几份（同样取不到就不注入）
        cases: list[str] = []
        if self.case_provider and elder_id:
            try:
                cases = self.case_provider(elder_id) or []
            except Exception:  # noqa: BLE001
                logger.exception("病例病史取不到，本轮不注入")
                cases = []
        # ── wiki：长期积累的对这个人的认识（替代原来的关键词记忆检索）──
        # 按这一轮的话题挑相关小节，不整篇塞（整篇会淹掉上下文）
        wiki_elder: list[str] = []
        wiki_persona: list[str] = []
        wiki = getattr(self, "wiki", None)
        if wiki is not None and elder_id:
            try:
                shot = wiki.inject(elder_id, query_text)
                wiki_elder = shot.elder_lines
                wiki_persona = shot.persona_lines
            except Exception:  # noqa: BLE001 —— wiki 是增强，失败当没有
                logger.exception("wiki 注入失败，本轮不带 wiki")
        messages: list[dict] = [
            {
                "role": "system",
                "content": build_system_prompt(
                    persona, elder, memories, health, cases,
                    wiki_elder=wiki_elder,
                    wiki_persona=wiki_persona,
                    # 更早对话的摘要（历史压缩产物）。
                    # 只喂最近 N 轮原文时，更早的会全丢；摘要补上这一段。
                    # 摘要按**老人**存（不按会话）：记忆跟着人走，
                    # 跟 AI 聊的和跟家人聊的应该共享同一份上下文。
                    history_summary=self._summary_of(elder_id),
                    # 到期的回访（他说过"下周二去复查"，今天正是那天）
                    care_followups=self._followup_lines(elder_id),
                ),
            }
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
