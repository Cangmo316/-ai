"""
比邻AI · 从聊天里整理记忆（L2/L3 的自动录入通道）

**这条通道默认是关的**（`MemorySettings.auto_extract=False`）。设计方案的原文是
"从聊天中自动抽取（**需明确告知并允许关闭**）"——默认开启等于没告知，所以必须显式打开。

三道闸门，缺一不可：

1. **开关**：`auto_extract` 为 False 时，本模块的所有函数都不写库
2. **置信度**：低于 `AUTO_MIN_CONFIDENCE` 的候选只进 `review="pending"`，**不参与检索**
   （方案："自动抽取的低置信内容不得直接用于主动话题"）
3. **隐私**：自动抽取的记忆 `visible_to_family=False`（家人端看不到），
   而且**只存整理后的短句，不存聊天原文**

抽取实现分两层：
- `extract_rules()`：零依赖的规则抽取，永远可用（老人自述里那些典型句式命中率不低）
- `extract_with_llm()`：配了真模型时用它补充；返回必须是严格 JSON，解析失败就当没有
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from .models import (
    KIND_EXPERIENCE,
    KIND_PREFERENCE,
    KIND_PROFILE,
    KINDS,
    SOURCE_AUTO,
    MemorySettings,
    MemoryStore,
)
from .retrieval import tokens_of

logger = logging.getLogger("bilin.memory")


@dataclass
class Candidate:
    kind: str
    text: str
    tags: list[str] = field(default_factory=list)
    confidence: float = 0.8
    happened_at: str = ""


# 规则表：命中即抽取。"老人主动说出来的事"通常句式固定，规则够用且完全可解释
_RULES: list[tuple[str, re.Pattern, float]] = [
    # 经历：带时间词 + 事件动词
    (
        KIND_EXPERIENCE,
        re.compile(
            r"[^。！？\n]{0,6}(以前|年轻时|年轻的时候|小时候|当年|去年|前年|今年|上个月|"
            r"上个星期|前几天)[^。！？\n]{2,40}"
        ),
        0.78,
    ),
    (
        KIND_EXPERIENCE,
        re.compile(r"[^。！？\n]{0,6}(去过|见过|待过|住过|当过|参加过|搬过|结过婚|上过学)[^。！？\n]{1,40}"),
        0.74,
    ),
    # 偏好
    (
        KIND_PREFERENCE,
        re.compile(r"[^。！？\n]{0,4}(喜欢|爱听|爱看|爱吃|最爱|不喜欢|讨厌|不爱)[^。！？\n]{1,30}"),
        0.8,
    ),
    # 习惯/称呼（L1 的补充）
    (
        KIND_PROFILE,
        re.compile(r"[^。！？\n]{0,4}(不吃|吃的少|忌口|每天|平时|习惯)[^。！？\n]{1,30}"),
        0.7,
    ),
    (
        KIND_PROFILE,
        re.compile(r"[^。！？\n]{0,4}(叫我|大家都叫我|我的名字)[^。！？\n]{1,16}"),
        0.82,
    ),
]

# 亲属词：作为标签用，方便"聊到孙子时能不能带出这条"
_KIN_TAGS = ("儿子", "女儿", "老伴", "孙子", "孙女", "外孙", "外孙女", "儿媳", "女婿", "哥哥", "姐姐", "弟弟", "妹妹")
_YEAR_RE = re.compile(r"((?:19|20)\d{2}\s*年|去年|前年|今年|上个月)")


def _clean(sentence: str) -> str:
    text = re.sub(r"\s+", " ", sentence or "").strip(" ，,。.！!？?、")
    return text


def extract_rules(message: str) -> list[Candidate]:
    """规则抽取：只从**老人自己说的话**里抽（家属说的话不该记成老人的经历）"""
    text = message or ""
    if len(text) < 6:
        return []

    found: list[Candidate] = []
    seen: set[str] = set()
    for kind, pattern, confidence in _RULES:
        for match in pattern.finditer(text):
            snippet = _clean(match.group(0))
            # 太短或纯语气词的不算
            if len(snippet) < 5 or snippet in seen:
                continue
            seen.add(snippet)
            tags = [word for word in _KIN_TAGS if word in text]
            happened = _YEAR_RE.search(text)
            found.append(
                Candidate(
                    kind=kind,
                    text=snippet,
                    tags=tags,
                    confidence=confidence,
                    happened_at=happened.group(1).replace(" ", "") if happened else "",
                )
            )
    return found


def _parse_llm_json(raw: str) -> list[Candidate]:
    """模型返回必须是 JSON 数组；多一层容错：从文本里抠出第一个 [...]"""
    text = (raw or "").strip()
    if not text:
        return []
    if not text.startswith("["):
        match = re.search(r"\[[\s\S]*\]", text)
        if not match:
            return []
        text = match.group(0)
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return []
    if not isinstance(payload, list):
        return []

    items: list[Candidate] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        snippet = _clean(str(row.get("text", "")))
        kind = str(row.get("kind", "")).strip()
        if not snippet or kind not in KINDS:
            continue
        try:
            confidence = float(row.get("confidence", 0.6))
        except (TypeError, ValueError):
            confidence = 0.6
        raw_tags = row.get("tags") or []
        tags = [str(tag).strip() for tag in raw_tags if str(tag).strip()] if isinstance(raw_tags, list) else []
        items.append(
            Candidate(
                kind=kind,
                text=snippet,
                tags=tags[:4],
                confidence=max(0.0, min(1.0, confidence)),
                happened_at=_clean(str(row.get("happenedAt", "")))[:12],
            )
        )
    return items


EXTRACT_PROMPT = """你从一段老人与数字人的对话里，整理出**值得长期记住**关于这位老人的事。

只输出 JSON 数组，不要任何解释。每条：
{"kind":"experience|preference|profile","text":"一句第三人称的事实","tags":["标签"],"confidence":0-1,"happenedAt":"2023年"}

规则：
- 只整理老人**自己说过**的事实（经历、喜好、习惯、称呼）；数字人说的一律不要
- 不整理健康指标数值、不整理任何诊断/用药判断（那是医疗边界之外）
- 整理成短句、第三人称（"老人 2023 年去过海南"），不要照抄原话
- 不确定的宁可不输出；宁少不多

对话（老人）：{message}
"""


async def extract_with_llm(provider, message: str) -> list[Candidate]:
    """用模型补充抽取。provider 不可用 / 输出不合法时返回空列表，绝不抛给调用方"""
    if provider is None:
        return []
    prompt = EXTRACT_PROMPT.replace("{message}", (message or "")[:600])
    try:
        chunks = []
        async for delta in provider.stream([{"role": "user", "content": prompt}]):
            chunks.append(delta)
        return _parse_llm_json("".join(chunks))
    except Exception:  # noqa: BLE001 —— 抽取是"锦上添花"，不能影响对话
        logger.warning("模型抽取记忆失败，忽略本次", exc_info=True)
        return []


def _too_similar(store: MemoryStore, elder_id: str, text: str) -> bool:
    """已经很像的就不再记一条（老人会把同一件事说好几遍）"""
    target = set(tokens_of(text))
    if not target:
        return True
    for entry in store.all_of(elder_id):
        existing = set(tokens_of(entry.text))
        if not existing:
            continue
        overlap = len(target & existing) / max(1, len(target | existing))
        if overlap >= 0.6:
            return True
    return False


def remember_candidates(
    store: MemoryStore,
    elder_id: str,
    candidates: list[Candidate],
) -> list[str]:
    """把候选写进记忆库，返回新入库的 id 列表。

    **调用方必须先确认 `auto_extract` 已开启**（见 `remember_from_turn`）。
    置信度低于门槛的会以 `review="pending"` 入库：家属复核通过前不参与检索。
    """
    added: list[str] = []
    for candidate in candidates:
        if _too_similar(store, elder_id, candidate.text):
            continue
        entry = store.add(
            elder_id=elder_id,
            text=candidate.text,
            kind=candidate.kind,
            tags=candidate.tags,
            source=SOURCE_AUTO,
            confidence=candidate.confidence,
            happened_at=candidate.happened_at,
        )
        added.append(entry.id)
        logger.info(
            "自动整理了一条记忆（%s，置信度 %.2f，复核=%s）：%s",
            entry.kind_label,
            entry.confidence,
            entry.review,
            entry.text[:40],
        )
    return added


async def remember_from_turn(
    store: MemoryStore,
    settings: MemorySettings,
    elder_id: str,
    elder_message: str,
    provider=None,
    use_llm: bool = False,
) -> list[str]:
    """一轮对话结束后的入口：开关关着就什么都不做（这是默认状态）"""
    if not settings.auto_extract or not (elder_message or "").strip():
        return []

    candidates = extract_rules(elder_message)
    if use_llm:
        candidates = candidates + await extract_with_llm(provider, elder_message)
    return remember_candidates(store, elder_id, candidates)
