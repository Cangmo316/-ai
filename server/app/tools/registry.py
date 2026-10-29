"""工具注册表：智能体能「自己决定」调用的能力。

## 为什么要有这一层

在此之前，系统的所有决策都在代码里：
  · 判人设 → `is_medical_question()` 关键词
  · 要不要出计划卡 → `needs_plan_card()` 关键词
  · 该问什么 → `care/topics.py` 固定题库

模型只负责"说话"。所以严格说它不是智能体，是**单轮对话流水线**。

这一层把"查什么、写什么"变成模型可以自己选的动作：
请求里带 `tools`，模型返回 `tool_calls`，我们执行后把结果喂回去，再让它说。

## 两条硬约束

1. **每个工具的返回值必须是纯数据**（可 JSON 序列化），且**不带病历原文**
   —— 工具结果会进入下一轮请求，等于又发一次给模型。
2. **写操作要留痕**：谁在什么时候写了什么，写进日志与返回体。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable

from ..wiki.models import ELDER_SECTIONS, WIKI_ELDER, WikiItem

MAX_RESULT_CHARS = 900  # 单个工具结果的字符上限：太长会把上下文顶爆


def section_titles(sections) -> list[str]:
    """从 wiki 的小节定义里取标题。

    ⚠️ `ELDER_SECTIONS` 是 `(标题, 提示)` 的元组序列，不是字符串列表 ——
    直接 join 会抛 "expected str instance, tuple found"。
    """
    titles: list[str] = []
    for item in sections:
        if isinstance(item, (tuple, list)):
            titles.append(str(item[0]))
        else:
            titles.append(str(item))
    return titles


@dataclass
class ToolContext:
    """一次对话里的工具执行上下文（只放句柄，不放请求级可变状态）。"""

    elder_id: str
    elders: Any = None
    health: Any = None
    plan_engine: Any = None
    plan_store: Any = None
    wiki: Any = None
    today: date = field(default_factory=date.today)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict
    handler: Callable[[ToolContext, dict], dict]
    writes: bool = False

    def to_openai(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# ── 只读工具 ────────────────────────────────────────────────────


def _get_profile(ctx: ToolContext, args: dict) -> dict:
    elder = {}
    try:
        elder = ctx.elders.get(ctx.elder_id) or {}
    except Exception:  # noqa: BLE001 —— 档案取不到不该让整轮失败
        elder = {}
    # 只回传称呼与基本情况，不回传住址门牌这种可识别信息
    return {
        "name": elder.get("name", ""),
        "age": elder.get("age", ""),
        "city": (elder.get("address") or "")[:8],
        "conditions": elder.get("conditions", "") or elder.get("tags", ""),
    }


def _get_recent_vitals(ctx: ToolContext, args: dict) -> dict:
    item_type = str(args.get("item_type") or "").strip()
    out: list[dict] = []
    try:
        if item_type:
            record = ctx.health.latest_of(ctx.elder_id, item_type)
            if record:
                out.append({"type": item_type, "summary": record.summary, "at": str(record.created_at)[:16]})
        else:
            for kind in ("血压", "血糖", "心率", "体温", "体重"):
                record = ctx.health.latest_of(ctx.elder_id, kind)
                if record:
                    out.append({"type": kind, "summary": record.summary, "at": str(record.created_at)[:16]})
    except Exception:  # noqa: BLE001
        return {"records": [], "note": "暂时读不到测量记录"}
    return {"records": out, "note": "" if out else "还没有记录过测量值"}


def _get_today_plan(ctx: ToolContext, args: dict) -> dict:
    try:
        today = ctx.plan_engine.today(ctx.elder_id, ctx.today)
    except Exception:  # noqa: BLE001
        return {"items": [], "note": "暂时读不到今天的安排"}
    items = [
        {
            "id": str(item.get("id", "")),
            "title": item.get("title", ""),
            "time": item.get("time", ""),
            "done": bool(item.get("done")),
        }
        for item in (today.get("items") or [])
    ]
    return {
        "date": today.get("date", ""),
        "statusLabel": today.get("statusLabel", ""),
        "items": items[:12],
        "pending": [i for i in items if not i["done"]][:12],
        "total": today.get("total", len(items)),
        "done": today.get("done", 0),
    }


def _get_week_completion(ctx: ToolContext, args: dict) -> dict:
    try:
        active = ctx.plan_store.active(ctx.elder_id)
        if active is None:
            return {"note": "还没有生效的计划", "rate": None}
        data = ctx.plan_engine.completion(active, days=7, day=ctx.today)
    except Exception:  # noqa: BLE001
        return {"note": "暂时算不出完成率", "rate": None}
    return {"rate": data.get("rate"), "done": data.get("done"), "total": data.get("total")}


def _get_recent_chat_topics(ctx: ToolContext, args: dict) -> dict:
    """从长期记忆里取"聊过的话题"，用来避免重复问同一件事。"""
    try:
        page = ctx.wiki.store.load(ctx.elder_id, WIKI_ELDER)
    except Exception:  # noqa: BLE001
        return {"topics": []}
    topics: list[str] = []
    for section in page.sections:
        if section.title == "聊过的话题":
            topics = [item.text for item in section.items][-6:]
    return {"topics": topics}


# ── 写工具 ──────────────────────────────────────────────────────


def _remember_fact(ctx: ToolContext, args: dict) -> dict:
    section_title = str(args.get("section") or "").strip()
    text = str(args.get("text") or "").strip()
    if not text:
        return {"ok": False, "reason": "没有要记的内容"}
    allowed = section_titles(ELDER_SECTIONS)
    if section_title not in allowed:
        return {"ok": False, "reason": "只能记到这些小节里：" + "、".join(allowed)}

    page = ctx.wiki.store.load(ctx.elder_id, WIKI_ELDER)
    target = None
    for section in page.sections:
        if section.title == section_title:
            target = section
            break
    if target is None:
        return {"ok": False, "reason": "找不到小节：" + section_title}
    if any(item.text.strip() == text for item in target.items):
        return {"ok": True, "duplicated": True, "section": section_title}
    target.items.append(WikiItem(text=text, source="agent"))
    ctx.wiki.store.save(page)
    return {"ok": True, "section": section_title, "text": text}


def _check_in_plan_item(ctx: ToolContext, args: dict) -> dict:
    item_id = str(args.get("item_id") or "").strip()
    if not item_id:
        return {"ok": False, "reason": "没有指定要打卡的条目"}
    try:
        plan = ctx.plan_store.active(ctx.elder_id)
        if plan is None:
            return {"ok": False, "reason": "还没有生效的计划"}
        record = ctx.plan_store.checkin(plan, item_id, ctx.elder_id, source="agent")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": "打卡失败：%s" % str(exc)[:40]}
    return {"ok": True, "item_id": item_id, "at": str(getattr(record, "created_at", ""))[:16]}


# ── 注册表 ──────────────────────────────────────────────────────

SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="get_profile",
        description="查老人的基本情况：叫什么、多大年纪、住哪座城市、有哪些慢性病。老人问『你还记得我吗』『我什么情况』时用。",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_get_profile,
    ),
    ToolSpec(
        name="get_recent_vitals",
        description="查最近一次测量数值（血压/血糖/心率/体温/体重）。老人问『我上次量的多少』『血压怎么样』时用。",
        parameters={
            "type": "object",
            "properties": {
                "item_type": {
                    "type": "string",
                    "description": "要查哪一项，如 血压、血糖；留空则都查",
                    "enum": ["血压", "血糖", "心率", "体温", "体重", ""],
                }
            },
            "required": [],
        },
        handler=_get_recent_vitals,
    ),
    ToolSpec(
        name="get_today_plan",
        description="查今天的安排和完成情况（吃了没、量了没）。老人问『今天要干啥』『药吃了没』时用。",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_get_today_plan,
    ),
    ToolSpec(
        name="get_week_completion",
        description="查最近 7 天的完成率。老人或家属问『这周坚持得怎么样』时用。",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_get_week_completion,
    ),
    ToolSpec(
        name="get_recent_chat_topics",
        description="查以前聊过哪些话题，避免重复问同一件事。开口找话题前可以用。",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_get_recent_chat_topics,
    ),
    ToolSpec(
        name="remember_fact",
        description="把老人刚说的一件值得记住的事写进长期记忆。只在确实是重要信息（家人、病情、爱好、忌讳）时用，闲聊别乱记。",
        parameters={
            "type": "object",
            "properties": {
                "section": {"type": "string", "description": "记到哪个小节", "enum": section_titles(ELDER_SECTIONS)},
                "text": {"type": "string", "description": "要记的一句话，用第三人称，不超过 40 字"},
            },
            "required": ["section", "text"],
        },
        handler=_remember_fact,
        writes=True,
    ),
    ToolSpec(
        name="check_in_plan_item",
        description="把今天某一项安排标记为已完成（老人说『吃了』『量过了』时用）。需要先知道 item_id，可用 get_today_plan 查。",
        parameters={
            "type": "object",
            "properties": {"item_id": {"type": "string", "description": "要打卡的条目 id"}},
            "required": ["item_id"],
        },
        handler=_check_in_plan_item,
        writes=True,
    ),
)

BY_NAME: dict[str, ToolSpec] = {spec.name: spec for spec in SPECS}


def openai_tools() -> list[dict]:
    """给请求体用的工具声明。"""
    return [spec.to_openai() for spec in SPECS]


def execute(name: str, args: dict | str | None, ctx: ToolContext) -> dict:
    """执行一个工具调用。任何异常都转成结构化失败，绝不让对话崩。"""
    spec = BY_NAME.get(name)
    if spec is None:
        return {"ok": False, "reason": "没有这个工具：%s" % name}
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError:
            args = {}
    if not isinstance(args, dict):
        args = {}
    try:
        result = spec.handler(ctx, args)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": "工具执行失败：%s" % str(exc)[:60]}

    payload = json.dumps(result, ensure_ascii=False)
    if len(payload) > MAX_RESULT_CHARS:
        result = {"truncated": True, "preview": payload[:MAX_RESULT_CHARS]}
    return result
