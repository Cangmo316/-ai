"""
比邻AI · 康养知识库读取与校验

数据来源与边界（医学选型文档 §1.5 的四条硬约束）：
1. **LLM 只做改写，不做知识来源** —— 计划引擎只从本文件取条目，禁止让模型"回忆"医学结论
2. 不诊断、不做剂量调整、不判断疾病
3. 计划必须**家属确认后生效**
4. 订阅制数据库内容禁止引入

本模块只负责「把条目表安全地读进来」：结构不对就抛错，绝不让半成品条目流进计划引擎——
带着缺 `boundary` 或缺 `source` 的条目生成计划，等于把合规风险直接送到老人面前。

⚠️ 改 `guidelines.yaml` 后必须跑 `node app/knowledge/validate.mjs`（仓库约定），
本模块的 `validate_knowledge()` 在服务启动/生成计划时也会查同一批必填字段。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger("bilin.knowledge")

KNOWLEDGE_PATH = Path(__file__).resolve().parent / "guidelines.yaml"

# 必填字段（与 validate.mjs 的 REQUIRED 保持一致）
REQUIRED_FIELDS = (
    "id",
    "source",
    "version",
    "category",
    "audience",
    "advice",
    "detail",
    "boundary",
    "plan_hint",
    "review_by",
)
PLAN_HINT_FIELDS = ("time", "type", "freq", "strong_remind", "weight")
# 允许值（与 validate.mjs 一致；计划引擎与调度器都依赖这两组枚举）
PLAN_TYPES = ("用药", "午餐", "活动", "监测", "问候")
FREQUENCIES = ("每日", "每周", "每月", "每季度", "每年")
# 需要按年龄判定的人群标签
AGE_TAGS = {"65岁以上": 65}


class KnowledgeError(Exception):
    """知识库结构不合法。带上全部问题，避免一次只报一个、来回改。"""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("知识库校验失败：" + "；".join(problems[:5]) + (
            "" if len(problems) <= 5 else f"（共 {len(problems)} 处）"
        ))


@dataclass(frozen=True)
class KnowledgeEntry:
    id: str
    source: str
    version: str
    category: str
    audience: tuple[str, ...]
    advice: str
    detail: str
    boundary: str
    time: str
    type: str
    freq: str
    strong_remind: bool
    weight: float
    review_by: str
    plan_hint: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "version": self.version,
            "category": self.category,
            "audience": list(self.audience),
            "advice": self.advice,
            "detail": self.detail,
            "boundary": self.boundary,
            "planHint": self.plan_hint,
            "reviewBy": self.review_by,
        }


@dataclass
class KnowledgeBase:
    version: str
    updated: str
    sources: dict[str, dict]
    entries: tuple[KnowledgeEntry, ...]
    path: str = ""

    def source_name(self, source_id: str) -> str:
        info = self.sources.get(source_id) or {}
        return str(info.get("name") or source_id)

    def by_id(self, entry_id: str) -> KnowledgeEntry | None:
        for entry in self.entries:
            if entry.id == entry_id:
                return entry
        return None

    def summary(self) -> dict:
        by_source: dict[str, int] = {}
        for entry in self.entries:
            by_source[entry.source] = by_source.get(entry.source, 0) + 1
        return {
            "version": self.version,
            "updated": self.updated,
            "entries": len(self.entries),
            "sources": [
                {"id": key, "name": self.source_name(key), "entries": by_source.get(key, 0)}
                for key in self.sources
            ],
        }


def load_knowledge(path: Path | str | None = None) -> KnowledgeBase:
    """读知识库；结构不合法直接抛 KnowledgeError。"""
    target = Path(path) if path else KNOWLEDGE_PATH
    if not target.exists():
        raise KnowledgeError([f"找不到知识库文件 {target}"])
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise KnowledgeError([f"YAML 解析失败：{exc}"]) from exc
    if not isinstance(raw, dict):
        raise KnowledgeError(["顶层应为映射（meta / entries）"])

    meta = raw.get("meta") or {}
    entries_raw = raw.get("entries") or []
    if not isinstance(entries_raw, list) or not entries_raw:
        raise KnowledgeError(["entries 应为非空列表"])

    problems: list[str] = []
    sources: dict[str, dict] = {}
    for item in meta.get("sources") or []:
        if not isinstance(item, dict) or not item.get("id"):
            problems.append("meta.sources 里有一条缺 id")
            continue
        sources[str(item["id"])] = item

    entries: list[KnowledgeEntry] = []
    seen: set[str] = set()
    for index, item in enumerate(entries_raw, start=1):
        if not isinstance(item, dict):
            problems.append(f"第 {index} 条不是映射")
            continue
        entry_id = str(item.get("id") or f"#{index}")
        where = f"[{entry_id}]"
        # 先把这一条的问题收齐，有任何一条就不再构造对象——不让带伤的条目流进计划引擎
        broken: list[str] = []
        for name in REQUIRED_FIELDS:
            if name not in item or item[name] in (None, ""):
                broken.append(f"{where} 缺少必填字段 {name}")
        if entry_id in seen:
            broken.append(f"{where} id 重复")
        seen.add(entry_id)
        if item.get("source") and str(item["source"]) not in sources:
            broken.append(f"{where} source '{item['source']}' 未在 meta.sources 声明")

        hint = item.get("plan_hint") or {}
        if not isinstance(hint, dict):
            broken.append(f"{where} plan_hint 应为映射")
            hint = {}
        for name in PLAN_HINT_FIELDS:
            if name not in hint:
                broken.append(f"{where} plan_hint 缺少 {name}")
        if hint.get("type") and hint["type"] not in PLAN_TYPES:
            broken.append(f"{where} plan_hint.type '{hint['type']}' 不在允许值 {PLAN_TYPES}")
        if hint.get("freq") and hint["freq"] not in FREQUENCIES:
            broken.append(f"{where} plan_hint.freq '{hint['freq']}' 不在允许值 {FREQUENCIES}")
        time_value = str(hint.get("time") or "")
        if time_value and not _is_hhmm(time_value):
            broken.append(f"{where} plan_hint.time 应为 HH:MM，当前 '{time_value}'")

        audience = item.get("audience")
        if not isinstance(audience, list) or not audience:
            broken.append(f"{where} audience 应为非空数组，如 [全员]")
            audience = []
        elif any(not str(tag).strip() for tag in audience):
            broken.append(f"{where} audience 里有空标签")

        if broken:
            problems.extend(broken)
            continue

        entries.append(
            KnowledgeEntry(
                id=entry_id,
                source=str(item["source"]),
                version=str(item["version"]),
                category=str(item["category"]),
                audience=tuple(str(tag) for tag in audience),
                advice=str(item["advice"]).strip(),
                detail=str(item["detail"]).strip(),
                boundary=str(item["boundary"]).strip(),
                time=time_value,
                type=str(hint["type"]),
                freq=str(hint["freq"]),
                strong_remind=bool(hint["strong_remind"]),
                weight=float(hint["weight"]),
                review_by=str(item["review_by"]),
                plan_hint=dict(hint),
            )
        )

    if problems:
        raise KnowledgeError(problems)

    base = KnowledgeBase(
        version=str(meta.get("version") or "unknown"),
        updated=str(meta.get("updated") or ""),
        sources=sources,
        entries=tuple(entries),
        path=str(target),
    )
    logger.info(
        "知识库已加载：%s 条，来源 %s 个，版本 %s",
        len(base.entries),
        len(base.sources),
        base.version,
    )
    return base


def validate_knowledge(path: Path | str | None = None) -> list[str]:
    """返回问题列表（空列表=通过）。测试与自检用，不抛异常。"""
    try:
        load_knowledge(path)
        return []
    except KnowledgeError as exc:
        return exc.problems


def _is_hhmm(value: str) -> bool:
    if len(value) != 5 or value[2] != ":":
        return False
    hour, minute = value[:2], value[3:]
    return hour.isdigit() and minute.isdigit() and 0 <= int(hour) <= 23 and 0 <= int(minute) <= 59
