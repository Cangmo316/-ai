"""
比邻AI · 对话历史压缩

`history_turns=8` 只喂最近 8 轮，更早的直接丢 —— 聊到 50 轮时前 42 轮全没了，
表现是它反复问早就说过的事。这里把旧对话压成摘要留在会话上：

    摘要 + 最近 8 轮原文 + 本轮

冗余按**出现频率**判定（见 frequency.py）：
反复出现的优先保留，只提过一次的可以丢；
但时间/地点/人物/数字这类一次性事实必须留。
"""

from .compactor import (
    DEFAULT_KEEP_RECENT,
    DEFAULT_THRESHOLD,
    MAX_SUMMARY_CHARS,
    Turn,
    build_compress_messages,
    build_turns,
    clip_summary,
    parse_summary,
    should_compress,
    split_for_compress,
)
from .frequency import MIN_TURNS, Phrase, count_phrases, frequent_lines
from .service import HistoryCompactor

__all__ = [
    "DEFAULT_KEEP_RECENT",
    "DEFAULT_THRESHOLD",
    "HistoryCompactor",
    "MAX_SUMMARY_CHARS",
    "MIN_TURNS",
    "Phrase",
    "Turn",
    "build_compress_messages",
    "build_turns",
    "clip_summary",
    "count_phrases",
    "frequent_lines",
    "parse_summary",
    "should_compress",
    "split_for_compress",
]
