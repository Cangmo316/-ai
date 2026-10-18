"""
比邻AI · wiki 服务

把「提取 → 合并 → 落盘」串起来，并保证三件事：
  1. 注入是**同步**的（这轮回复要立刻用上）
  2. 更新是**异步**的（不能拖慢老人等回复）
  3. 任何异常都不影响对话

## 为什么注入同步、更新异步

注入要赶在这轮 prompt 组装之前完成，必须同步，但它只是读内存缓存 + 拼字符串，
开销可以忽略。更新要额外调一次模型，几百毫秒到几秒，**绝不能**让老人等。
"""

from __future__ import annotations

import asyncio
import logging
import time

from .inject import Injection, build_injection
from .models import WIKI_ELDER, WIKI_PERSONA
from .store import WikiStore
from .updater import build_update_messages, merge_facts, _parse_json

logger = logging.getLogger("bilin.wiki")

#: 缓冲里攒的几轮，若隔了这么久才有新消息，就把它们先学掉。
#: 否则一段只有 3 轮的对话永远凑不满 5 轮，那 3 轮就白攒了。
IDLE_FLUSH_SECONDS = 180.0


class WikiService:
    """wiki 的对外门面。编排层只跟它打交道。"""

    def __init__(self, store: WikiStore | None = None, learn_every: int = 5) -> None:
        self.store = store or WikiStore()
        #: 攒够多少轮才学一次。1 = 每轮都学（最贵）。
        #: 5 是折中：一次学 5 轮的对话，信息足够，调用次数降到 1/5。
        self.learn_every = max(1, int(learn_every))
        #: 待学习的对话缓冲：elder_id → [(老人说的, 对方回的), ...]
        #: 进程内内存，重启会丢 —— 可接受（丢的是"还没学的几轮"，不是已学的 wiki）
        self._pending: dict[str, list[tuple[str, str]]] = {}
        #: 每轮最后活动时间，用于"聊完就停"时补一次学习
        self._last_turn: dict[str, float] = {}
        #: 后台更新任务的引用。不持有引用的话，任务可能被 GC 掉（asyncio 的坑）
        self._tasks: set[asyncio.Task] = set()

    # ---------------------------------------------------------------- 注入
    def inject(self, elder_id: str, query_text: str) -> Injection:
        """按这一轮的话题挑 wiki 内容（同步，给 prompt 用）。"""
        try:
            pages = self.store.load_all(elder_id)
            return build_injection(pages, query_text)
        except Exception:  # noqa: BLE001 —— 注入失败当没有，不能让对话挂
            logger.exception("wiki 注入失败，本轮不带 wiki")
            return Injection(elder_lines=[], persona_lines=[])

    def snapshot(self, elder_id: str) -> dict:
        """给接口/调试看当前两份 wiki 的完整内容。"""
        pages = self.store.load_all(elder_id)
        return {
            "elder": pages[WIKI_ELDER].to_dict(),
            "persona": pages[WIKI_PERSONA].to_dict(),
        }

    # ---------------------------------------------------------------- 更新
    async def learn(
        self,
        elder_id: str,
        turns: list[tuple[str, str]],
        provider,
        *,
        learn_persona: bool = False,
        family: bool = False,
    ) -> int:
        """从**若干轮**对话里学东西，返回新增条数。

        `turns` 是多轮 [(老人说的, 对方回的), ...] ——
        为什么不是单轮：学习改成每 N 轮一次后，只拿最后一轮学会把前面的丢掉。

        两个开关的区别（容易混）：

        · `family`      —— 这是"老人和家人"的聊天（两边都是真人）。
          用家人专用提示词，让模型分清楚谁说的、把内容归到正确的一侧。
          需求原话：「老人跟子女聊就同时记录老人和子女的表达习惯」。

        · `learn_persona` —— 是否把抽到的 "子女说话风格" 真正写进 persona.md。
          ⚠️ 默认 **False**：智能体会话里"对方回的话"是模型自己生成的，
          从它身上学「子女怎么说话」是循环的（学到的是 prompt 里已经写的东西）。

        所以：智能体会话 → family=False, learn_persona=False
              家人会话   → family=True,  learn_persona=True
        """
        # 太短的话没有可学的（"嗯""好""知道了"）
        pairs = [
            (str(a or "").strip(), str(b or "").strip())
            for a, b in (turns or [])
        ]
        pairs = [p for p in pairs if max(len(p[0]), len(p[1])) >= 4]
        if not pairs or provider is None:
            return 0

        try:
            elder_page = self.store.load(elder_id, WIKI_ELDER)
            persona_page = self.store.load(elder_id, WIKI_PERSONA)
            messages = build_update_messages(
                turns=[(a[:300], b[:300]) for a, b in pairs],
                elder_page=elder_page,
                persona_page=persona_page,
                family=family,
            )
            chunks: list[str] = []
            async for delta in provider.stream(messages):
                chunks.append(delta)
                # 提取结果很短，超过这个长度基本是模型跑偏了，及时止损
                if sum(len(c) for c in chunks) > 1200:
                    break
            data = _parse_json("".join(chunks))
        except Exception:  # noqa: BLE001 —— 学不到就算了，下一轮还有机会
            logger.exception("wiki 提取失败（会话继续，不影响回复）")
            return 0

        added = 0
        try:
            # ── 频率优先：把反复出现的短语也带进 wiki ──
            # 需求："优先保留出现次数多的语句写进记忆""wiki 学习也是
            # 出现频率较高的话题以及老人的表达习惯"。
            # 模型抽取会漏掉一些高频但"不够像事实"的表达（口头禅就是典型），
            # 所以这里**在代码层面兜一道**：高频短语直接进对应小节。
            frequent = self._frequent_of(pairs)
            if frequent:
                added += self._merge_frequent(
                    elder_page, persona_page, frequent, learn_persona=learn_persona
                )

            added += merge_facts(elder_page, data.get("elder") or {})
            # 只有明确要求时才写 persona —— 否则会把 AI 自己的口吻记成子女的
            if learn_persona:
                added += merge_facts(persona_page, data.get("persona") or {})
            if added:
                self.store.save(elder_page)
                if learn_persona:
                    self.store.save(persona_page)
                logger.info("wiki 学到 %d 条（%s）", added, elder_id)
        except Exception:  # noqa: BLE001
            logger.exception("wiki 落盘失败")
        return added

    @staticmethod
    def _frequent_of(pairs: list[tuple[str, str]]) -> list:
        """取出这批对话里反复出现的短语。"""
        from ..history.frequency import count_phrases

        texts = [a for a, _b in pairs if a]
        if not texts:
            return []
        return count_phrases(texts, limit=6)

    @staticmethod
    def _merge_frequent(elder_page, persona_page, frequent, *, learn_persona: bool) -> int:
        """把高频短语写进合适的小节。

        分派规则：
          · 老人的高频表达 → 老人画像的【聊过的话题】（他常提什么）
          · 子女的高频表达（仅 learn_persona 时）→ 【口头禅】（长期记忆，不裁）
        """
        added = 0
        elder_facts = {"聊过的话题": [p.text for p in frequent]}
        added += merge_facts(elder_page, elder_facts)
        if learn_persona:
            persona_facts = {"口头禅": [p.text for p in frequent]}
            added += merge_facts(persona_page, persona_facts)
        return added

    def collect_turn(
        self,
        elder_id: str,
        elder_text: str,
        agent_text: str,
        provider,
    ) -> None:
        """把这一轮放进缓冲；**攒够 N 轮**才触发一次学习。

        为什么不是每轮都学：
          每轮学要额外调一次模型（成本翻倍），而单轮的增量信息很少 ——
          效果差别不大，钱差一倍。攒 5 轮一起学，一次给模型 5 轮上下文，
          质量反而更好。
        """
        try:
            key = str(elder_id or "")
            now = time.monotonic()
            pending = self._pending.setdefault(key, [])
            last = self._last_turn.get(key)

            # 聊完就停的情况：隔了一段时间又来一句，
            # 说明上一段对话已经结束 —— 先把攒着的几轮学掉，别让它一直压在缓冲里。
            if pending and last is not None and (now - last) > IDLE_FLUSH_SECONDS:
                self._flush(key, provider)
                pending = self._pending.setdefault(key, [])

            pending.append((elder_text, agent_text))
            self._last_turn[key] = now

            if len(pending) >= self.learn_every:
                self._flush(key, provider)
        except Exception:  # noqa: BLE001 —— 学习调度出问题不能影响对话
            logger.exception("wiki 学习调度失败（不影响本轮回复）")

    def _flush(self, elder_id: str, provider) -> None:
        """把缓冲里的几轮交给后台任务学习，并清空缓冲。"""
        turns = self._pending.pop(elder_id, [])
        if not turns:
            return
        try:
            task = asyncio.create_task(self.learn(elder_id, turns, provider))
        except RuntimeError:
            # 没有运行中的事件循环（同步调用场景）：放回去，下次再试
            self._pending.setdefault(elder_id, []).extend(turns)
            logger.debug("没有事件循环，暂缓 wiki 学习")
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        logger.info("wiki 开始学习 %d 轮对话（%s）", len(turns), elder_id)

    def pending_count(self, elder_id: str) -> int:
        """缓冲里还压着几轮没学（测试与调试用）。"""
        return len(self._pending.get(str(elder_id or ""), []))

    async def drain(self) -> None:
        """等所有后台学习任务结束（测试用；生产不调用）。"""
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    # ---------------------------------------------------------------- 子女风格
    async def learn_from_peer_message(
        self,
        elder_id: str,
        peer_text: str,
        provider,
    ) -> int:
        """从**子女本人发的真实消息**里学他的说话风格。

        与 `learn()` 的区别：
          · `learn()` 的"对方回的话"是 AI 生成的 → 学它等于学自己，循环无意义
          · 这里是真的子女说话 → 才是"子女说话风格"的正确来源

        由家人会话的发消息接口调用（见 api/conversations.py）。

        注意这里**不攒批**：子女发消息本身不频繁，
        再攒 5 条可能要好几天，风格 wiki 会长期空着。
        """
        text = str(peer_text or "").strip()
        if len(text) < 4 or provider is None:
            return 0
        return await self.learn(
            elder_id,
            turns=[("", text)],     # 单条真人消息，没有成对的老人发言
            provider=provider,
            learn_persona=True,
            family=True,            # 用家人提示词：他可能是子女，也可能是老人
        )

    def schedule_peer_style_learn(self, elder_id: str, peer_text: str, provider) -> None:
        """把"学子女风格"放进后台（不阻塞发消息）。"""
        try:
            task = asyncio.create_task(
                self.learn_from_peer_message(elder_id, peer_text, provider)
            )
        except RuntimeError:
            logger.debug("没有事件循环，跳过子女风格学习")
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
