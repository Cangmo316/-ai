"""
比邻AI · LLM wiki（替代关键词记忆检索）

两套 Markdown wiki，由 LLM 在对话中自动维护：

    wiki/<elder_id>/elder.md     老人画像
    wiki/<elder_id>/persona.md   子女说话风格

作用：
  · **注入** —— 按这一轮的话题挑相关小节放进 prompt（见 inject.py）
  · **学习** —— 回复发完后，从这段对话里提取事实合并进 wiki（见 updater.py）

为什么换掉原来的关键词记忆检索：
  原来存的是"孤立事件碎片"，聊 100 轮还是 100 条互不相干的记录；
  wiki 存的是"这个人是什么样"，会把新信息合并进既有认知，越聊越像认识他。
"""

from .inject import Injection, build_injection
from .models import (
    ELDER_SECTIONS,
    PERSONA_SECTIONS,
    WIKI_ELDER,
    WIKI_LABELS,
    WIKI_PERSONA,
    WIKIS,
    WikiItem,
    WikiPage,
    WikiSection,
    parse_markdown,
)
from .service import WikiService
from .store import WikiStore, default_wiki_root
from .updater import build_update_messages, merge_facts

__all__ = [
    "ELDER_SECTIONS",
    "Injection",
    "PERSONA_SECTIONS",
    "WIKIS",
    "WIKI_ELDER",
    "WIKI_LABELS",
    "WIKI_PERSONA",
    "WikiItem",
    "WikiPage",
    "WikiSection",
    "WikiService",
    "WikiStore",
    "build_injection",
    "build_update_messages",
    "default_wiki_root",
    "merge_facts",
    "parse_markdown",
]
