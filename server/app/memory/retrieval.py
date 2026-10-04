"""
比邻AI · 记忆检索（L2 按相关性取 Top-K；L3 汇总话题权重）

**为什么现在不用向量库**：向量检索要么引入 embedding 模型（要 API、要额度、要联网），
要么塞一个本地模型（几十上百 MB，和"零依赖"的端侧约定冲突）。而记忆量在很长一段时间里
是"一位老人几十条"这个量级——**关键词/标签重合 + 时间衰减**已经足够好，而且**可解释**：
为什么这条被选中，能一条条说清（家属问起来能答得上）。

升级路径留清楚了：`score()` 是唯一打分入口，将来换成向量相似度只改这里；
`topics()` 的权重口径同理。
"""

from __future__ import annotations

import re
from datetime import datetime

from .models import KIND_PREFERENCE, MemoryEntry, MemoryStore

# 中文没有空格分词，零依赖下用「字 + 二元组」做重合度：简单、确定、可解释
_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]")
_STOP_TOKENS = {
    "的", "了", "是", "我", "你", "他", "她", "们", "在", "有", "和", "就", "都", "也",
    "不", "很", "还", "说", "要", "会", "去", "来", "个", "这", "那", "吗", "呢", "啊",
}


def tokens_of(text: str) -> list[str]:
    """中英混排的粗分词：英文/数字按整词，中文按单字 + 相邻二元组"""
    raw = _TOKEN_RE.findall(text or "")
    parts: list[str] = []
    for index, item in enumerate(raw):
        if not re.match(r"[\u4e00-\u9fff]", item):
            parts.append(item.lower())
            continue
        if item not in _STOP_TOKENS:
            parts.append(item)
        if index + 1 < len(raw):
            nxt = raw[index + 1]
            # 二元组只要**有一个字不是**停用词就保留：
            # 否则「去过」「去年」这种承载事实的词会被切掉（停用词表是按单字收的，
            # 「去」「年」单看没信息量，但「去过」恰恰是经历类记忆的关键词）
            if re.match(r"[\u4e00-\u9fff]", nxt) and (
                item not in _STOP_TOKENS or nxt not in _STOP_TOKENS
            ):
                parts.append(item + nxt)
    return parts


def _recency_bonus(happened_at: str, created_at: str, now: datetime) -> float:
    """越近的事越可能被提起（只是微调，不该压过内容相关性）"""
    stamp = happened_at or created_at
    year = None
    match = re.search(r"(19|20)\d{2}", stamp or "")
    if match:
        year = int(match.group(0))
    if year is None:
        return 0.05
    delta = max(0, now.year - year)
    if delta == 0:
        return 0.15
    if delta <= 1:
        return 0.12
    if delta <= 3:
        return 0.08
    return 0.03


def score(entry: MemoryEntry, query_tokens: list[str], now: datetime | None = None) -> float:
    """一条记忆对当前这句话的相关度。

    组成：标签命中（权重最高，标签是人给的，最可靠）> 正文重合 > 时间新鲜度 > 来源可信度。

    ⚠️ **只蹭上一个常用字不算相关**：实测问"老家的桥"时，"老人爱听戏"曾以 0.28 分被捞出来
    （共用了一个"老"字）。这种命中会把无关往事注进上下文，模型反而跑题——比"没想起来"更糟。
    所以要求至少满足一条：标签命中 / 有二元组（词组级）命中 / 至少两个不同的单字命中。
    """
    moment = now or datetime.now()
    if not query_tokens:
        return 0.0

    query_set = set(query_tokens)
    tag_tokens = set()
    for tag in entry.tags:
        tag_tokens.update(tokens_of(tag))
    text_tokens = set(tokens_of(entry.text))

    tag_hit = len(query_set & tag_tokens)
    overlap = query_set & text_tokens
    multi_hit = sum(1 for token in overlap if len(token) > 1)
    single_hit = sum(1 for token in overlap if len(token) == 1)

    if not tag_hit and not multi_hit and single_hit < 2:
        return 0.0

    # 长文本天然更容易撞词，用命中率而不是命中数，避免"话多的记忆总被选中"
    text_rate = (multi_hit * 2 + single_hit) / max(1, len(text_tokens))
    base = tag_hit * 0.45 + min(text_rate, 1.0) * 1.2
    # 老人自己说过 / 家属填写的比自动抽取的更可信
    trust = 1.0 if entry.source != "auto" else 0.85
    return base * trust + _recency_bonus(entry.happened_at, entry.created_at, moment)


def search(
    store: MemoryStore,
    elder_id: str,
    query: str,
    limit: int = 5,
    min_score: float = 0.12,
    now: datetime | None = None,
) -> list[tuple[MemoryEntry, float]]:
    """按相关性取 Top-K（只从"已复核可用"的记忆里取——待复核的绝不进上下文）"""
    query_tokens = tokens_of(query)
    ranked: list[tuple[MemoryEntry, float]] = []
    for entry in store.usable_of(elder_id):
        value = score(entry, query_tokens, now)
        if value >= min_score:
            ranked.append((entry, value))
    ranked.sort(key=lambda pair: pair[1], reverse=True)
    return ranked[: max(1, limit)]


def describe(entry: MemoryEntry) -> str:
    """给提示词用的一行文字：带来源，方便模型判断可不可以提、要不要说"你上次说过" """
    stamp = f"（{entry.happened_at}）" if entry.happened_at else ""
    return f"[{entry.kind_label}] {entry.text}{stamp} · {entry.source_label}"


def topics(
    store: MemoryStore,
    elder_id: str,
    limit: int = 5,
) -> list[dict]:
    """L3 的用法：把兴趣偏好聚合成"能聊什么"的候选，**不占对话上下文**。

    权重口径：同一个标签被提得越多越重；老人自己说的比自动抽取的重。
    返回给家属端/主动关怀用，将来调度器可以据此生成主动话题。
    """
    weights: dict[str, float] = {}
    evidence: dict[str, list[str]] = {}
    for entry in store.usable_of(elder_id):
        boost = 1.0 if entry.source != "auto" else 0.7
        if entry.kind == KIND_PREFERENCE:
            boost += 0.3  # 偏好本身就是"聊什么"的直接素材
        keys = entry.tags or [entry.text[:8]]
        for key in keys:
            weights[key] = weights.get(key, 0.0) + boost
            evidence.setdefault(key, []).append(entry.text)

    ranked = sorted(weights.items(), key=lambda pair: pair[1], reverse=True)[:limit]
    return [
        {
            "topic": key,
            "weight": round(value, 2),
            "from": evidence.get(key, [])[:3],
        }
        for key, value in ranked
    ]
