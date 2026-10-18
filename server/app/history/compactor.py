"""
比邻AI · 对话历史压缩

## 问题

`history_turns=8` 意味着**只把最近 8 轮喂给模型**，更早的直接丢掉 ——
聊到第 50 轮时，前 42 轮里说过的"老伴走了三年""腿脚不好要多歇"全没了。
表现是：它突然又问一遍早就说过的事，老人觉得"这孩子不上心"。

## 做法

超过阈值时，把**较早的那一大段**压成一份摘要（保留在会话上），
后续每轮把「摘要 + 最近几轮原文」一起给模型。

```
摘要（压缩后的旧对话，几百字）
+ 最近 8 轮原文
+ 本轮
```

## 冗余怎么判定（需求原话：以出现频率为准）

压的时候不是随便概括，而是**先数频率**（`frequency.py`）：

  · 反复出现的话题 / 老话 → **优先保留**（这是他现在的常态）
  · 只提过一次的 → 可以丢（多半是过场话）
  · 但**带明确事实的一次性内容要留**（"我下周二要去复查" 说一次也重要）

最后一条很重要：纯按频率会丢掉关键的一次性安排。
所以提示词里明确要求"时间/地点/人物/数字这类事实，即使只出现一次也要留"。

## 人也是会变的

摘要会**被新一轮摘要"叠上去"**（旧的摘要在前、新的在后），
所以近期的说法会逐渐盖过早期说法 —— 自然体现了"人在变"。
真正长期不变的东西（口头禅）不靠摘要，走 wiki 的长期记忆（见 updater.py）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .frequency import count_phrases

logger = logging.getLogger("bilin.history")

#: 触发压缩的消息条数（含双方）。8 轮 ≈ 16 条，留 3 倍余量。
DEFAULT_THRESHOLD = 48
#: 压缩后保留多少条最近的原文（不压）。
DEFAULT_KEEP_RECENT = 16
#: 摘要总长度上限（字）。超了就把最早的摘要再压一次。
MAX_SUMMARY_CHARS = 1200

COMPRESS_PROMPT = """你在压缩一段**老人和陪伴智能体**的聊天记录，写成一份长期摘要。

目标：以后智能体只看这份摘要和最近几轮对话，就能自然地接着聊，
不会重复问已经说过的事。

## 必须保留

1. **反复出现的事**（已经给你频率统计）—— 这是他现在最在意的东西
2. **明确的事实与安排**：时间、地点、人物、数字、医嘱、约定
   （即使只出现一次也要留，比如"下周二去复查"）
3. **情绪与敏感点**：什么话题让他高兴、什么让他难受

## 可以丢

- 寒暄、应答（"嗯""好""知道了"）
- 重复说过多次的同一句话（留一句就够）
- 智能体自己的废话（只保留它给出的有用信息）

## 输出要求

- 用**第三人称**写（"他""老人"），不要写成对话
- 分 3 到 5 条，每条一行，以 "· " 开头
- 总长不超过 400 字
- 不要编造：摘要里只能出现原文有的信息
"""


@dataclass
class Turn:
    """一对问答。"""

    elder: str
    agent: str


def should_compress(message_count: int, threshold: int = DEFAULT_THRESHOLD) -> bool:
    """消息条数是否超过压缩阈值。"""
    return int(message_count or 0) > max(4, int(threshold or DEFAULT_THRESHOLD))


def split_for_compress(messages: list, keep_recent: int = DEFAULT_KEEP_RECENT):
    """把消息切成「要压的旧部分」与「保留的近期部分」。

    返回 (旧消息列表, 近期消息列表)。消息不够长就全都不压。
    """
    keep = max(2, int(keep_recent or DEFAULT_KEEP_RECENT))
    if len(messages) <= keep:
        return [], list(messages)
    return list(messages[:-keep]), list(messages[-keep:])


def build_turns(messages: list) -> list[Turn]:
    """把消息列表归并成问答对。

    智能体可能连发多条（正文+表情+卡片），这里只取文本并合并到同一个 Turn。
    """
    turns: list[Turn] = []
    pending: list[str] = []
    for msg in messages:
        role = getattr(msg, "role", "")
        text = (getattr(msg, "text", "") or "").strip()
        if not text:
            continue
        if role == "elder":
            # 上一个 turn 还没收尾就再开口：先把它当成只有老人的一问
            if pending:
                turns.append(Turn(elder=" ".join(pending), agent=""))
                pending = []
            pending.append(text)
        else:
            turns.append(Turn(elder=" ".join(pending), agent=text))
            pending = []
    if pending:
        turns.append(Turn(elder=" ".join(pending), agent=""))
    return turns


def build_compress_messages(
    turns: list[Turn],
    previous_summary: str = "",
) -> list[dict]:
    """拼压缩用的消息（带上频率统计与已有摘要）。"""
    elder_texts = [t.elder for t in turns if t.elder]
    phrases = count_phrases(elder_texts, limit=10)

    freq_block = (
        "\n".join("· " + p.to_line() for p in phrases)
        if phrases
        else "（这段里没有明显重复出现的内容）"
    )

    transcript: list[str] = []
    for i, turn in enumerate(turns, 1):
        if turn.elder:
            transcript.append(f"{i}. 老人：{turn.elder}")
        if turn.agent:
            transcript.append(f"   智能体：{turn.agent}")

    user_block = (
        "## 已有的摘要（更早的对话，请在此基础上补充新内容，不要丢掉它还成立的部分）\n"
        f"{previous_summary or '（还没有摘要）'}\n\n"
        "## 反复出现的内容（按覆盖轮数排序，**优先保留**）\n"
        f"{freq_block}\n\n"
        "## 要压缩的聊天记录\n"
        + "\n".join(transcript)
        + "\n\n请输出压缩后的摘要。"
    )
    return [
        {"role": "system", "content": COMPRESS_PROMPT},
        {"role": "user", "content": user_block},
    ]


def clip_summary(text: str, limit: int = MAX_SUMMARY_CHARS) -> str:
    """限制摘要总长。

    超长时保留**后半部分**：摘要里新的内容在后（见 COMPRESS_PROMPT 的叠加约定），
    近期信息比早期更能反映"现在的他"（需求：人也是会变的）。
    """
    body = str(text or "").strip()
    if len(body) <= limit:
        return body
    cut = body[-limit:]
    # 从第一个完整行开始，避免半句话
    newline = cut.find("\n")
    if 0 <= newline < len(cut) - 1:
        cut = cut[newline + 1:]
    return "（更早的内容已省略）\n" + cut.strip()


def parse_summary(raw: str) -> str:
    """清理模型输出：去掉 ``` 包裹、多余空行。"""
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = "\n".join(
            line for line in text.splitlines() if not line.strip().startswith("```")
        )
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    return clip_summary("\n".join(lines))
