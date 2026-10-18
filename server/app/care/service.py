"""
比邻AI · 主动关心服务

## 需求

「智能体需要有人的好奇心……每天要主动问1-2次，这些要记录下来，
在后续的标记日期里再次提出来，让老人真正认为智能体是在乎他的」

## 一天怎么问（频率控制）

不做成"到点必发"，那样像闹钟。规则是：

  · 每天 **最多 MAX_PER_DAY 次**（默认 2）
  · 两次之间至少隔 **MIN_GAP_HOURS 小时**（默认 4）
  · 只在**清醒时段**问（默认 8:00–21:00）—— 深夜推送会吓着人
  · 老人**刚说过话**就不问（他正在聊，插一句"吃了吗"很怪）
  · 上次是他没回，就不要连着追问（问过一次没答，隔天再说）

## 怎么发出去

两步，缺一不可：

1. **进对话**：往他的 AI 会话里插一条 AI 消息（打开 App 就能看到）
2. **推送**：有推送客户端就顺手发一条通知（没开 App 也知道有人在想着他）

## 收回访

`due_followups()` 返回今天该提的回访，编排层把它注进 prompt，
让智能体在回话时**自然地**问一句"今天去复查了吧"。

⚠️ 提过一次就标 done，不再重复提 —— 反复问同一件事会变成催命。
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

from . import dates as date_util
from . import topics as topic_lib
from .models import (
    FOLLOWUP_DONE,
    FOLLOWUP_DUE,
    FOLLOWUP_PENDING,
    CareAsk,
    FollowUp,
    now_iso,
)
from .store import CareStore

logger = logging.getLogger("bilin.care")

#: 每天最多主动问几次
MAX_PER_DAY = 2
#: 两次之间至少隔几小时
MIN_GAP_HOURS = 4
#: 清醒时段（左闭右开）
WAKE_START = 8
WAKE_END = 21
#: 老人刚说过话后的冷静期（分钟）—— 他正在聊就别插嘴
QUIET_AFTER_CHAT_MINUTES = 30

#: 回访最多允许过期几天。
#:
#: 为什么要有这个上限：他说"明天闺女来"，三天后再问"闺女来了吗"已经没意义了
#: （要么来了要么没来，都过去了）。超过这个天数的回访直接不再提，
#: 免得变成"翻旧账"。踩过一次：10/9 说"明天闺女来"，10/13 还在问。
FOLLOWUP_MAX_OVERDUE_DAYS = 2


class CareService:
    """主动关心 + 到期回访。"""

    def __init__(self, store: CareStore | None = None, clock=None) -> None:
        self.store = store or CareStore()
        #: 时间源（测试注入；生产用系统时间）
        self.clock = clock or (lambda: datetime.now().astimezone())
        #: elder_id → 他最近的 AI 会话 id（用于往对话里插消息）
        self._conversations: dict[str, str] = {}
        #: elder_id → 最后一次说话的时间（用于冷静期）
        self._last_chat: dict[str, datetime] = {}

    # ---------------------------------------------------------------- 记录
    def now(self) -> datetime:
        return self.clock()

    def today(self) -> date:
        return self.now().date()

    def note_conversation(self, elder_id: str, conversation_id: str) -> None:
        """记住这个老人的 AI 会话 id（供后台主动发消息用）。"""
        key = str(elder_id or "")
        if key and conversation_id:
            self._conversations[key] = str(conversation_id)

    def note_chat(self, elder_id: str) -> None:
        """记下"他刚说过话"，用于冷静期判断。"""
        key = str(elder_id or "")
        if key:
            self._last_chat[key] = self.now()

    # ---------------------------------------------------------------- 频率
    def asked_today(self, elder_id: str) -> int:
        return self.store.count_asks(elder_id, self.today().isoformat())

    def last_ask(self, elder_id: str) -> CareAsk | None:
        return self.store.last_ask(elder_id)

    def should_ask(self, elder_id: str) -> tuple[bool, str]:
        """现在该不该主动问一句。返回 (是否问, 原因)。

        原因只用于日志与调试 —— 出问题时要能看出"为什么没问"。
        """
        moment = self.now()
        hour = moment.hour

        if hour < WAKE_START or hour >= WAKE_END:
            return False, "不在清醒时段"

        if self.asked_today(elder_id) >= MAX_PER_DAY:
            return False, "今天已经问够了"

        last = self.last_ask(elder_id)
        if last is not None:
            # 两次之间要有间隔（跨天不算间隔，所以先比日期）
            try:
                last_at = datetime.fromisoformat(last.asked_at)
            except ValueError:
                last_at = None
            if last_at is not None:
                gap = moment - last_at
                # 时钟被回拨/注入过时 gap 可能是负数，别拿它算间隔
                if gap.total_seconds() < 0:
                    gap = timedelta(0)
                if gap < timedelta(hours=MIN_GAP_HOURS):
                    return False, "离上次问才 %d 分钟" % int(gap.total_seconds() // 60)
            # 上次问了没答，不要紧跟着追问
            if not last.answer and last.day == self.today().isoformat():
                return False, "上次问了还没答"

        # 刚聊过就别插嘴（他正在跟它说话，突然问"吃了吗"很怪）
        last_chat = self._last_chat.get(str(elder_id or ""))
        if last_chat is not None:
            quiet = moment - last_chat
            if quiet < timedelta(minutes=QUIET_AFTER_CHAT_MINUTES):
                return False, "刚聊过 %d 分钟" % int(quiet.total_seconds() // 60)

        return True, ""

    # ---------------------------------------------------------------- 提问
    def preview_ask(
        self, elder_id: str, rng: random.Random | None = None
    ) -> CareAsk | None:
        """生成一次提问但**不记账**。

        为什么要拆成 preview/commit：
        踩过一个坑 —— 提问先生成并记账，然后才发现"还没有会话可以投递"，
        结果这条没送出去的提问把下一次提问堵死了
        （should_ask 认为"上次问了还没答"，当天再也不问）。
        现在只有**投递成功**才 commit，账才对得上。
        """
        ok, reason = self.should_ask(elder_id)
        if not ok:
            logger.debug("暂不主动关心（%s）：%s", elder_id, reason)
            return None

        last = self.last_ask(elder_id)
        topic, question = topic_lib.pick_question(
            self.now().hour,
            last_topic=last.topic if last else "",
            rng=rng,
        )
        return CareAsk(
            id="care_" + datetime.now().strftime("%Y%m%d%H%M%S%f")[:20],
            elder_id=str(elder_id),
            day=self.today().isoformat(),
            topic=topic,
            question=question,
            # ⚠️ 时间戳必须用**注入的时钟**，不能用 now_iso() 的系统时间。
            # 踩过一次：系统时间是 10-18，测试注入 10-08，
            # 间隔算出来是 -14396 分钟（负数），"离上次问才"那句日志读起来像 bug。
            asked_at=self.now().isoformat(timespec="seconds"),
        )

    def commit_ask(self, ask: CareAsk) -> CareAsk:
        """投递成功后记账（频率控制靠它）。"""
        self.store.add_ask(ask)
        logger.info("主动关心（%s）：%s", ask.elder_id, ask.question)
        return ask

    def ask_now(self, elder_id: str, rng: random.Random | None = None) -> CareAsk | None:
        """生成并记账一次提问（不负责投递）。

        只给"投递一定有保证"的场景用（测试、或调用方自己会投递）。
        后台循环用 preview_ask + commit_ask，见 care/loop.py。
        """
        ask = self.preview_ask(elder_id, rng=rng)
        if ask is None:
            return None
        return self.commit_ask(ask)

    def record_answer(self, elder_id: str, text: str) -> CareAsk | None:
        """老人说话了：把这句话当作上一次提问的回答。

        不判断"这句到底在答什么" —— 老人不会按格式回话。
        只要他开口了，就算答了（内容会另外进 wiki 学习）。
        """
        last = self.last_ask(elder_id)
        if last is None or last.answer:
            return None
        body = str(text or "").strip()
        if not body:
            return None
        last.answer = body[:200]
        last.answered_at = self.now().isoformat(timespec="seconds")
        self.store.update_ask(last)
        return last

    # ---------------------------------------------------------------- 回访
    def add_followup_if_any(
        self,
        elder_id: str,
        text: str,
        *,
        today: date | None = None,
    ) -> FollowUp | None:
        """如果这句话里提到将来的事，就记一条回访。

        需求：「在后续的标记日期里再次提出来」。

        ⚠️ 只记**将来**的日子。说"昨天去医院了"不记 ——
        那已经发生了，之后没有"到期"可言。
        """
        base = today or self.today()
        parsed = date_util.parse_when(text, base)
        # ⚠️ 只记**严格将来**的日子（明天及以后），不包括"今天"。
        # 踩过一次：老人说"我今天心情不好"，因为含"今天"被记成回访，
        # 第二天就跑去问"您今天心情不好那事怎么样了" —— 完全是噪音。
        # "今天要做什么"这类当天的事由主动提问覆盖，不需要回访。
        if parsed is None or parsed.day <= base:
            return None

        body = str(text or "").strip()
        item = FollowUp(
            id="fu_" + datetime.now().strftime("%Y%m%d%H%M%S%f")[:20],
            elder_id=str(elder_id),
            due_day=parsed.day.isoformat(),
            text=body[:60],
            raw=parsed.raw,
        )
        # 同一件事别记两遍（同一天 + 内容高度相似）
        for old in self.store.followups(elder_id):
            if old.due_day == item.due_day and old.text[:12] == item.text[:12]:
                return old
        self.store.add_followup(item)
        logger.info(
            "记下回访：%s（%s 到期）", item.text[:24], item.due_day
        )
        return item

    def due_followups(self, elder_id: str, day: date | None = None) -> list[FollowUp]:
        """今天该提的回访（含刚过期的）。

        过期太久的不再返回 —— 见 FOLLOWUP_MAX_OVERDUE_DAYS。
        """
        base = day or self.today()
        out: list[FollowUp] = []
        for item in self.store.followups(elder_id):
            if item.status not in (FOLLOWUP_PENDING, FOLLOWUP_DUE):
                continue
            if not item.due_day:
                continue
            try:
                due = date.fromisoformat(item.due_day)
            except ValueError:
                continue
            if due > base:
                continue                       # 还没到
            if (base - due).days > FOLLOWUP_MAX_OVERDUE_DAYS:
                continue                       # 过期太久，翻旧账没意义
            out.append(item)
        return out

    def mark_followup_done(self, elder_id: str, follow_id: str) -> bool:
        items = self.store.followups(elder_id)
        for item in items:
            if item.id == follow_id:
                item.status = FOLLOWUP_DONE
                item.asked_at = now_iso()
                self.store.save_followups(elder_id, items)
                return True
        return False

    def followup_lines(self, elder_id: str) -> list[str]:
        """给 prompt 用的回访提示（人话，不是数据）。"""
        base = self.today()
        lines: list[str] = []
        for item in self.due_followups(elder_id):
            try:
                due = date.fromisoformat(item.due_day)
            except ValueError:
                continue
            delta = (base - due).days
            # ⚠️ 措辞必须区分"今天到期"和"过了几天"。
            # 踩过一次：10/9 说的"明天闺女来"，10/13 注入的句子还写着
            # "今天正是这日子" —— 模型照着说就成了"今天闺女来"，明显不对。
            if delta == 0:
                when = "今天正是这日子"
            elif delta == 1:
                when = "这是昨天的事，顺口问问后来怎么样了"
            else:
                when = "这是%d天前的事，顺口问问后来怎么样了" % delta
            lines.append(
                f"他之前说过「{item.text}」——{when}（问一句就够，别追问）"
            )
        return lines

    # ---------------------------------------------------------------- 概况
    def snapshot(self, elder_id: str) -> dict:
        """给接口/调试看的当前状态。"""
        return {
            "todayAsks": self.asked_today(elder_id),
            "maxPerDay": MAX_PER_DAY,
            "dueFollowups": [f.to_dict() for f in self.due_followups(elder_id)],
            "recentAsks": [a.to_dict() for a in self.store.recent_asks(elder_id, 5)],
        }
