"""
比邻AI · wiki 注入

## 为什么要"挑节"，不是整篇塞

wiki 会随对话一直长。全塞进 prompt 有三个后果：
  · 上下文被淹掉，模型反而抓不住当前话题（原来碎片检索就是为解决这个）
  · token 成本随使用时长线性上涨
  · 越到后面越慢

所以这里做**按话题挑节**：
  1. 先按"这一轮说了什么"给各小节打分（标题词 + 条目词的重合）
  2. 永远带上几个"基本盘"小节（基本情况 / 称呼习惯 / 说话风格）
  3. 按分数从高到低填，直到用完字符预算

## 一个关键取舍：宁可少带，不要带错

挑节的目的是提示，不是检索真相。带错了会让模型说出"您不是爱吃甜的吗"
这种明显不对的话，比不带更糟。所以打分阈值设得保守：
**没有明确相关的节就不带**，只保留基本盘。
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    MAX_INJECT_CHARS,
    WIKI_ELDER,
    WIKI_PERSONA,
    WikiPage,
)

#: 永远注入的小节（与话题无关的基础认知）。
#: 这几节缺失的话，模型连"该怎么称呼他"都不知道。
ALWAYS_ELDER = ("基本情况",)
ALWAYS_PERSONA = ("称呼习惯", "说话风格")

#: 相关小节命中的最低分。低于这个分数宁可不带（见模块注释的取舍说明）。
MIN_SCORE = 1.0


@dataclass
class Injection:
    """一次注入的结果。"""

    elder_lines: list[str]
    persona_lines: list[str]

    def is_empty(self) -> bool:
        return not self.elder_lines and not self.persona_lines


def _tokens(text: str) -> set[str]:
    """粗粒度切词：中文按字、英文数字按词。

    为什么不用分词库：零依赖是本项目的硬约束，而且中文按字已经够用
    （"血压" → {血,压}，能跟"高血压"里的字对上）。宁可召回粗一点。
    """
    out: set[str] = set()
    buf = ""
    for ch in str(text or ""):
        if ch.isalnum() and ord(ch) < 128:
            buf += ch.lower()
            continue
        if buf:
            out.add(buf)
            buf = ""
        if "\u4e00" <= ch <= "\u9fff":
            out.add(ch)
    if buf:
        out.add(buf)
    return out


def _section_score(title: str, items: list[str], query_tokens: set[str]) -> float:
    """小节与当前话题的相关度。标题权重高于条目（标题更能代表一小节讲什么）。"""
    if not query_tokens:
        return 0.0
    title_hit = len(_tokens(title) & query_tokens) * 3.0
    item_hit = 0.0
    for text in items:
        item_hit += len(_tokens(text) & query_tokens)
    return title_hit + item_hit


def _pick_sections(page: WikiPage, query_text: str, always: tuple[str, ...]) -> list[str]:
    """挑出要注入的小节标题（已按优先级排序）。"""
    query_tokens = _tokens(query_text)
    scored: list[tuple[float, str]] = []
    for title, section in page.sections.items():
        if section.is_empty():
            continue
        items = [item.text for item in section.items]
        score = _section_score(title, items, query_tokens)
        if title in always:
            # 基本盘给一个固定高权重，保证它一定在前面
            score = max(score, MIN_SCORE) + 100.0
        scored.append((score, title))

    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    picked: list[str] = []
    for score, title in scored:
        if title in always or score >= MIN_SCORE:
            picked.append(title)
    return picked


def build_injection(pages: dict[str, WikiPage], query_text: str) -> Injection:
    """按当前话题从两套 wiki 里挑内容，拼成待注入的行。"""
    elder_page = pages.get(WIKI_ELDER)
    persona_page = pages.get(WIKI_PERSONA)

    budget = MAX_INJECT_CHARS
    elder_lines: list[str] = []
    persona_lines: list[str] = []

    def fill(page: WikiPage | None, always: tuple[str, ...], sink: list[str]) -> int:
        """填充一个小节，返回消耗的字符数。"""
        nonlocal budget
        if page is None:
            return 0
        used = 0
        for title in _pick_sections(page, query_text, always):
            section = page.sections.get(title)
            if section is None or section.is_empty():
                continue
            header = f"【{title}】"
            cost = len(header)
            if cost > budget:
                continue
            sink.append(header)
            budget -= cost
            used += cost
            for item in section.items:
                line = "· " + item.text
                if len(line) + 1 > budget:
                    break
                sink.append(line)
                budget -= len(line) + 1
                used += len(line) + 1
        return used

    # 先填老人画像（更基础），再填说话风格（更细，超预算时先牺牲它）
    fill(elder_page, ALWAYS_ELDER, elder_lines)
    fill(persona_page, ALWAYS_PERSONA, persona_lines)

    return Injection(elder_lines=elder_lines, persona_lines=persona_lines)
