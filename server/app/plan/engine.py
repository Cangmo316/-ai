"""
比邻AI · 计划引擎

职责边界（医学选型文档 §1.5 第 1 条）：
**LLM 只负责把知识库条目改写成老人听得懂的话，不做诊疗推理。**
所以生成链条是「规则匹配 → 结构化 PlanItem → （可选）LLM 改写话术 → 家属确认」，
而不是"让模型自己发明一套康养计划"。

条目筛选规则（可解释、可测试，刻意不引入权重调参黑箱）：
1. 命中老人人群标签（慢病 / 65岁以上）的条目**全部纳入**——这是"针对性"的意义所在
2. 其余从 `全员` 条目按 weight 降序补足，但同一时刻只留一条、同一类型最多两条
   （老人一天记不住太多事，日程也不能堆）
3. 总数不超过 `max_items`

三条硬规则的落点：
- 生成出来的是 **draft**，要经过 `submit()` → `pending_confirm` 才算"等家属确认"
- `confirm()` 才把它变成 `active`，**并且在那一刻才结束旧计划**（过渡期旧计划继续执行）
- 今日计划 / 对话卡片只从 `PlanStore.active()` 取数，未确认的草稿产生不了任何提醒
"""

from __future__ import annotations

import dataclasses
import logging
import re
from datetime import date, timedelta

from ..knowledge.loader import KnowledgeBase, KnowledgeEntry
from ..llm.base import LLMError, LLMProvider
from ..models.elder import ElderStore
from ..models.message import now_iso
from ..style.compliance import has_medical_risk
from ..style.punctuation import apply_style
from .models import (
    DEFAULT_DAYS,
    DEFAULT_MAX_ITEMS,
    STATUS_ACTIVE,
    STATUS_ADJUSTING,
    STATUS_DRAFT,
    STATUS_ENDED,
    STATUS_PENDING,
    STATUS_REJECTED,
    CarePlan,
    PlanItem,
    add_days,
    new_item_id,
    new_plan_id,
    today_str,
)
from .store import PlanStore

logger = logging.getLogger("bilin.plan")

# 同一时刻只留一条提醒
MAX_PER_TIMESLOT = 1
# 同一类型（午餐/问候/监测…）最多几条
MAX_PER_TYPE = 2
# 话术改写长度上限（字）
POLISH_MAX_LENGTH = 24
# 完成率低于这个值就建议家属看一眼
LOW_COMPLETION = 0.5
# 强提醒连续几天没打卡就提请注意
STRONG_MISS_DAYS = 3
# 各频率的「提醒窗口」（天）。0 = 整个周期都算该做。
#
# 为什么需要这个：知识库里有「每年做一次体检」「每三个月去社区量一次血压」这类条目。
# 如果只按"本周期还没做就一直提醒"，年度体检会从 1 月 1 日一直挂在今日计划里到 12 月 31 日——
# 老人每天看到同一件事，很快就学会无视它（提醒失效比不提醒更糟）。
# 所以给长周期项一个窗口：窗口内提醒，错过就安静等下一个周期。
DUE_WINDOW_DAYS = {"每日": 0, "每周": 0, "每月": 0, "每季度": 30, "每年": 60}

POLISH_SYSTEM = """你在帮一个面向老人的康养 App 改写生活提醒话术。

要求：
- 改写成对老人说的口语，像家里人顺口提醒，不要像公告
- 每条不超过 20 字，句末不加句号
- 不提疾病名，不提药量，不判断该不该吃药，不出现"建议""应该""确诊"这类词
- 不改变原意，只换说法
- 只输出「序号. 话术」一行一条，不要任何其他内容
"""


class PlanStateError(Exception):
    """状态流转不合法（例如确认一份已经是 active 的计划）"""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class PlanEngine:
    def __init__(
        self,
        knowledge: KnowledgeBase,
        store: PlanStore,
        elders: ElderStore,
        settings=None,
    ) -> None:
        self.knowledge = knowledge
        self.store = store
        self.elders = elders
        self.settings = settings

    # ------------------------------------------------------------ 条目匹配

    def match_entries(self, elder_id: str, max_items: int = DEFAULT_MAX_ITEMS) -> list[KnowledgeEntry]:
        """按人群标签挑条目。返回顺序即"优先级从高到低"。"""
        tags = self.elders.tags(elder_id)
        targeted: list[KnowledgeEntry] = []
        general: list[KnowledgeEntry] = []
        for entry in self.knowledge.entries:
            audience = set(entry.audience)
            if audience & tags:
                targeted.append(entry)
            elif "全员" in audience:
                general.append(entry)

        targeted.sort(key=lambda item: (-item.weight, item.time, item.id))
        general.sort(key=lambda item: (-item.weight, item.time, item.id))

        selected: list[KnowledgeEntry] = []
        used_slots: set[str] = set()
        type_counts: dict[str, int] = {}

        def take(entry: KnowledgeEntry, strict: bool) -> bool:
            if entry.time in used_slots:
                return False
            if strict and type_counts.get(entry.type, 0) >= MAX_PER_TYPE:
                return False
            if any(chosen.id == entry.id for chosen in selected):
                return False
            selected.append(entry)
            used_slots.add(entry.time)
            type_counts[entry.type] = type_counts.get(entry.type, 0) + 1
            return True

        # 针对性条目：不受类型上限约束（但要受时段唯一 + 总数上限）
        for entry in targeted:
            if len(selected) >= max_items:
                break
            take(entry, strict=False)
        # 全员条目：补足，受类型上限约束
        for entry in general:
            if len(selected) >= max_items:
                break
            take(entry, strict=True)

        selected.sort(key=lambda item: (item.time, item.id))
        logger.info(
            "为 %s 匹配到 %s 条（人群标签 %s）：%s",
            elder_id,
            len(selected),
            ",".join(sorted(tags)) or "无",
            ",".join(item.id for item in selected),
        )
        return selected

    # -------------------------------------------------------------- 生成

    def build_plan(
        self,
        elder_id: str,
        *,
        goal: str = "",
        days: int = DEFAULT_DAYS,
        max_items: int = DEFAULT_MAX_ITEMS,
        start: str | None = None,
    ) -> CarePlan:
        """生成计划草稿（draft）。**不产生任何提醒**，必须走 submit → confirm。"""
        elder = self.elders.get(elder_id)
        entries = self.match_entries(elder_id, max_items=max_items)
        if not entries:
            raise PlanStateError("知识库里没有适合这位老人的条目，没法生成计划")

        start_date = start or today_str()
        items = [
            PlanItem(
                id=new_item_id(),
                time=entry.time,
                type=entry.type,
                title=entry.advice,
                detail=entry.detail,
                freq=entry.freq,
                strong_remind=entry.strong_remind,
                weight=entry.weight,
                entry_id=entry.id,
                source=entry.source,
                source_name=self.knowledge.source_name(entry.source),
                version=entry.version,
                boundary=entry.boundary,
            )
            for entry in entries
        ]

        used_sources = sorted({item.source for item in items})
        plan = CarePlan(
            id=new_plan_id(),
            elder_id=elder_id,
            status=STATUS_DRAFT,
            items=items,
            goal=goal or "按医嘱坚持日常起居与提醒",
            start_date=start_date,
            end_date=add_days(start_date, max(1, days) - 1),
            knowledge_version=self.knowledge.version,
            sources=[
                {
                    "id": source_id,
                    "name": self.knowledge.source_name(source_id),
                    "entries": sum(1 for item in items if item.source == source_id),
                }
                for source_id in used_sources
            ],
            note=(
                "依据公开权威指南整理的生活提醒，仅用于日常提醒与依从性管理，"
                "不构成诊断或用药建议；请家里人确认后再生效"
            ),
        )
        plan.log("draft", f"依据知识库 {self.knowledge.version} 生成 {len(items)} 项")
        self.store.add(plan)
        logger.info("生成计划草稿 %s（%s，%s 项）", plan.id, elder_id, len(items))
        return plan

    # ------------------------------------------------------------ 状态流转

    def submit(self, plan: CarePlan) -> CarePlan:
        self._require(plan, STATUS_DRAFT, "提交确认")
        plan.status = STATUS_PENDING
        plan.log("submit", "已提交家属确认")
        return plan

    def confirm(self, plan: CarePlan, actor: str = "家属") -> CarePlan:
        """家属确认 → 生效。**在生效这一刻才结束旧计划**，过渡期不留提醒真空。"""
        self._require(plan, STATUS_PENDING, "确认")
        previous = self.store.active(plan.elder_id)
        if previous and previous.id != plan.id:
            previous.status = STATUS_ENDED
            previous.log("ended", "新计划已生效，旧计划结束", actor)
            logger.info("旧计划 %s 结束（新计划 %s 生效）", previous.id, plan.id)
        plan.status = STATUS_ACTIVE
        plan.confirmed_at = now_iso()
        plan.confirmed_by = actor
        plan.log("confirm", "家属确认，计划生效", actor)
        return plan

    def reject(self, plan: CarePlan, reason: str = "", actor: str = "家属") -> CarePlan:
        self._require(plan, STATUS_PENDING, "驳回")
        plan.status = STATUS_REJECTED
        plan.rejected_reason = reason
        plan.log("reject", reason or "家属驳回", actor)
        return plan

    def mark_adjusting(self, plan: CarePlan, reason: str) -> CarePlan:
        """完成率触发调整建议 → adjusting，等待家属确认（**不自动改计划**）"""
        self._require(plan, STATUS_ACTIVE, "转入调整")
        plan.status = STATUS_ADJUSTING
        plan.log("adjusting", reason)
        return plan

    def adopt_adjustment(self, plan: CarePlan, actor: str = "家属") -> CarePlan:
        self._require(plan, STATUS_ADJUSTING, "采纳调整")
        plan.status = STATUS_ACTIVE
        plan.log("adopt", "家属确认调整，计划继续执行", actor)
        return plan

    def end(self, plan: CarePlan, reason: str = "", actor: str = "家属") -> CarePlan:
        if plan.status == STATUS_ENDED:
            return plan
        plan.status = STATUS_ENDED
        plan.log("ended", reason or "手动结束", actor)
        return plan

    @staticmethod
    def _require(plan: CarePlan, expected: str, action: str) -> None:
        if plan.status != expected:
            raise PlanStateError(
                f"计划当前是「{plan.status_label}」，不能{action}"
            )

    # ------------------------------------------------------------ 今日计划

    def today(self, elder_id: str, day: date | None = None) -> dict:
        """今日计划 + 打卡状态。**只取 active 计划**（未确认的草稿拿不到）。"""
        target = day or date.today()
        key = target.isoformat()
        plan = self.store.active(elder_id)
        if not plan:
            return {
                "elderId": elder_id,
                "date": key,
                "planId": "",
                "status": "",
                "statusLabel": "还没有计划",
                "items": [],
                "total": 0,
                "done": 0,
                "rate": 0.0,
            }

        items = []
        for item, due, done in self.due_items(plan, target):
            if not due:
                continue
            payload = item.to_dict()
            record = self.store.find_checkin(item.id, key)
            payload["done"] = done
            payload["doneAt"] = record.done_at if record else ""
            items.append(payload)

        done_count = sum(1 for item in items if item["done"])
        total = len(items)
        return {
            "elderId": elder_id,
            "date": key,
            "planId": plan.id,
            "status": plan.status,
            "statusLabel": plan.status_label,
            "items": items,
            "total": total,
            "done": done_count,
            "rate": round(done_count / total, 3) if total else 0.0,
        }

    def due_items(self, plan: CarePlan, day: date) -> list[tuple[PlanItem, bool, bool]]:
        """返回 [(item, 今天该不该做, 今天做没做)]。

        频率语义（P1 的简化，设计文档只给了频率枚举没给具体日）：
        - 每日：每天都在列表里（做完打勾、不消失——老人需要看到今天一共几件事）
        - 每周/每月：整个周期内都算该做（错过周一的散步，周二仍会提醒，
          这正是"依从性管理"想要的效果）
        - 每季度/每年：只在周期起点后的窗口内提醒（见 DUE_WINDOW_DAYS），
          避免年度体检从年头挂到年尾、把提醒变成噪音
        - 今天已经做过的项一定显示（老人要看到自己完成了什么）
        """
        key = day.isoformat()
        result: list[tuple[PlanItem, bool, bool]] = []
        for item in plan.items:
            done_today = self.store.find_checkin(item.id, key) is not None
            if item.freq == "每日":
                result.append((item, True, done_today))
                continue
            start, finish = period_bounds(item.freq, day)
            window = DUE_WINDOW_DAYS.get(item.freq, 0)
            if window > 0:
                finish = min(finish, start + timedelta(days=window - 1))
            in_window = start <= day <= finish
            last = self.store.last_checkin(item.id)
            done_this_period = last is not None and date.fromisoformat(last.date) >= start
            due = done_today or (in_window and not done_this_period)
            result.append((item, due, done_today))
        return result

    # -------------------------------------------------------- 完成率与调整

    def completion(self, plan: CarePlan, days: int = 7, day: date | None = None) -> dict:
        """最近 N 天的完成率。

        每日项可以精确算（期望 = 项数 × 天数）；非每日项按"本周期内是否做过"算，
        期望是这段时间内落在窗口里的周期起点个数。这样两类频率互不污染。
        """
        end = day or date.today()
        start = end - timedelta(days=max(1, days) - 1)
        records = self.store.checkins_of(plan.elder_id, since=start.isoformat())
        done_by_date: dict[str, set[str]] = {}
        for record in records:
            if record.date > end.isoformat():
                continue
            done_by_date.setdefault(record.date, set()).add(record.plan_item_id)

        def done_between(item_id: str, begin: date, finish: date) -> bool:
            for day_key, ids in done_by_date.items():
                if item_id in ids and begin.isoformat() <= day_key <= finish.isoformat():
                    return True
            return False

        expected = 0
        done = 0
        missing: dict[str, int] = {}
        for item in plan.items:
            item_expected = 0
            item_done = 0
            if item.freq == "每日":
                item_expected = (end - start).days + 1
                for offset in range(item_expected):
                    cursor = start + timedelta(days=offset)
                    if item.id in done_by_date.get(cursor.isoformat(), set()):
                        item_done += 1
            else:
                for offset in range((end - start).days + 1):
                    cursor = start + timedelta(days=offset)
                    if period_start(item.freq, cursor) != cursor:
                        continue
                    item_expected += 1
                    period_end = min(period_bounds(item.freq, cursor)[1], end)
                    if done_between(item.id, cursor, period_end):
                        item_done += 1

            expected += item_expected
            done += item_done
            if item.strong_remind and item_done < item_expected:
                missing[item.id] = item_expected - item_done

        return {
            "days": days,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "expected": expected,
            "done": done,
            "rate": round(done / expected, 3) if expected else 0.0,
            "strongMissing": missing,
        }

    def adjustment_suggestion(
        self, plan: CarePlan, days: int = 7, day: date | None = None
    ) -> dict:
        """是否建议调整 + 理由。

        ⚠️ 建议只谈**提醒安排**，绝不谈治疗：不说"这项用药可以去掉"，
        只说"用药提醒连着几天没打卡，请家属确认还要不要继续提醒"。
        """
        stats = self.completion(plan, days=days, day=day)
        reasons: list[str] = []
        if stats["expected"] and stats["rate"] < LOW_COMPLETION:
            reasons.append(
                f"最近 {days} 天只完成了 {stats['done']}/{stats['expected']} 项，"
                "提醒安排可能太多或时间不合适"
            )
        if len(stats["strongMissing"]) >= 1:
            names = "、".join(
                item.time for item in plan.items if item.id in stats["strongMissing"]
            )
            reasons.append(f"强提醒里 {names} 这几个点漏得比较多，建议家属确认还要不要保留")
        return {
            "shouldAdjust": bool(reasons),
            "reasons": reasons,
            "stats": stats,
            "advice": "建议由家属确认后调整；未确认前计划照旧执行",
        }

    # ------------------------------------------------------------ 话术改写

    async def polish_items(
        self, items: list[PlanItem], elder: dict, provider: LLMProvider | None
    ) -> tuple[list[PlanItem], dict]:
        """用 LLM 把条目原文改写成老人听得懂的话。

        **每一句都要过合规闸门**：命中用药/诊断类措辞、太长、带网址的，一律退回知识库原文。
        原文是人工整理过的，退回不会更差；让模型自由发挥才会出事。
        """
        stats = {"asked": len(items), "polished": 0, "fallback": 0, "reasons": []}
        if not provider or not items:
            stats["fallback"] = len(items)
            stats["reasons"].append("未启用模型改写")
            return items, stats

        lines = "\n".join(f"{index + 1}. {item.title}" for index, item in enumerate(items))
        messages = [
            {"role": "system", "content": POLISH_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"这位老人称呼是「{elder.get('address') or '您'}」，"
                    f"要提醒的内容如下：\n{lines}"
                ),
            },
        ]
        try:
            raw = ""
            async for delta in provider.stream(messages):
                raw += delta
        except LLMError as exc:
            stats["fallback"] = len(items)
            stats["reasons"].append(f"模型改写失败：{exc.code}")
            logger.warning("计划话术改写失败，退回知识库原文：%s", exc.message)
            return items, stats

        rewritten: dict[int, str] = {}
        for line in raw.splitlines():
            match = re.match(r"^\s*(\d+)\s*[.、)]\s*(.+?)\s*$", line)
            if not match:
                continue
            index = int(match.group(1)) - 1
            candidate = apply_style(match.group(2))
            if not candidate:
                continue
            if len(candidate) > POLISH_MAX_LENGTH:
                stats["reasons"].append(f"第 {index + 1} 条过长，退回原文")
                continue
            if re.search(r"https?://|www\.", candidate, re.IGNORECASE):
                stats["reasons"].append(f"第 {index + 1} 条带网址，退回原文")
                continue
            if has_medical_risk(candidate):
                stats["reasons"].append(f"第 {index + 1} 条触碰医疗边界，退回原文")
                continue
            rewritten[index] = candidate

        polished: list[PlanItem] = []
        for index, item in enumerate(items):
            candidate = rewritten.get(index)
            if candidate and candidate != item.title:
                polished.append(dataclasses.replace(item, title=candidate))
                stats["polished"] += 1
            else:
                polished.append(item)
                stats["fallback"] += 1
        logger.info(
            "计划话术改写：成功 %s 条，退回原文 %s 条 %s",
            stats["polished"],
            stats["fallback"],
            ("；" + "；".join(stats["reasons"])) if stats["reasons"] else "",
        )
        return polished, stats


def period_start(freq: str, day: date) -> date:
    """返回该频率下 day 所在周期的起点。"""
    if freq == "每日":
        return day
    if freq == "每周":
        return day - timedelta(days=day.weekday())
    if freq == "每月":
        return day.replace(day=1)
    if freq == "每季度":
        return date(day.year, ((day.month - 1) // 3) * 3 + 1, 1)
    if freq == "每年":
        return date(day.year, 1, 1)
    return day


def period_bounds(freq: str, day: date) -> tuple[date, date]:
    """返回 day 所在周期的 (起点, 终点)。终点 = 下个周期起点的前一天。"""
    start = period_start(freq, day)
    if freq == "每日":
        return start, start
    if freq == "每周":
        return start, start + timedelta(days=6)
    if freq == "每月":
        if start.month == 12:
            nxt = date(start.year + 1, 1, 1)
        else:
            nxt = date(start.year, start.month + 1, 1)
        return start, nxt - timedelta(days=1)
    if freq == "每季度":
        month = start.month + 3
        year = start.year + (1 if month > 12 else 0)
        month = month - 12 if month > 12 else month
        return start, date(year, month, 1) - timedelta(days=1)
    if freq == "每年":
        return start, date(start.year, 12, 31)
    return start, start
