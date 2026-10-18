"""
比邻AI · 对话频率分析

## 为什么需要它

需求：「对话冗余的定义在于其中内容的出现频率为准，优先保留出现次数多的语句」。
所以"什么该留到记忆里"不能拍脑袋，要**数出来**：
反复出现的才是他的常态，只说一次的通常是过场话。

## 中文为什么不用分词库

项目硬约束是零第三方依赖（`requirements.txt` 只有 5 个包）。
中文短句里"出现多次的子串"本身就极可能就是口头禅/常提的事：
  · "慢慢来""别着急""吃了没" → 会作为完整子串被数到
  · "我血压高" 里的 "血压" 也会被数到
所以这里用**滑动窗口枚举子串 + 计数**，不依赖分词。

## 两个必须有的约束

**1. 必须在多轮里出现，而不是同一句里重复**
   "哈哈哈哈"在一个长句里出现三次不算习惯。
   所以要求 `distinct_turns >= 2`。

**2. 长串优先，但要抑制"长串里套着短串"的重复计数**
   "我血压高" 与 "血压" 同时出现时，只报长的那个，
   否则同一个意思会被算成两条，灌进 wiki 反而更乱。
"""

from __future__ import annotations

from dataclasses import dataclass

#: 子串长度范围。太短（1 字）几乎都是噪声；太长（>8）很少有重复。
MIN_LEN = 2
MAX_LEN = 8

#: 至少在这些**不同轮次**里出现才算"频率高"，避免一句话里的重复被当成习惯
MIN_TURNS = 2

#: 「我」「你」这类高频虚词开头的子串没有信息量，直接丢
_STOP_PREFIX = (
    "我的", "你的", "他的", "这个", "那个", "什么", "怎么", "就是", "然后",
    "因为", "所以", "但是", "现在", "今天", "明天", "昨天", "一个", "一下",
)


@dataclass
class Phrase:
    """一个被数出频率的短语。"""

    text: str
    count: int
    turns: int

    def to_line(self) -> str:
        return f"{self.text}（{self.turns} 轮里出现 {self.count} 次）"


def _clauses(text: str) -> list[str]:
    """把一句话切成小句（按标点与空白）。"""
    out: list[str] = []
    buf = ""
    for ch in str(text or ""):
        if ch in "，。！？、；：,.!?;: \t\n\r“”\"'（）()":
            if buf.strip():
                out.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        out.append(buf.strip())
    return out


def count_phrases(texts: list[str], limit: int = 12) -> list[Phrase]:
    """数出反复出现的短语。

    `texts` 应当是**按时间排序的多轮老人原话**。
    返回按"覆盖轮数 → 出现次数 → 长度"降序的短语列表。
    """
    texts = [t for t in (texts or []) if str(t or "").strip()]
    if len(texts) < MIN_TURNS:
        # 轮次太少，谈不了"反复出现"
        return []

    stats: dict[str, dict] = {}   # 短语 → {count, turn_set}
    for turn_index, text in enumerate(texts):
        # 逐小句枚举子串：跨标点的子串没有意义
        for clause in _clauses(text):
            n = len(clause)
            for length in range(MIN_LEN, min(MAX_LEN, n) + 1):
                for start in range(0, n - length + 1):
                    piece = clause[start:start + length]
                    if not piece.strip():
                        continue
                    if piece.startswith(_STOP_PREFIX):
                        continue
                    slot = stats.setdefault(piece, {"count": 0, "turns": set()})
                    slot["count"] += 1
                    slot["turns"].add(turn_index)

    phrases: list[Phrase] = []
    for piece, slot in stats.items():
        turns = len(slot["turns"])
        # 必须在 ≥MIN_TURNS 个不同轮次里出现，才算"反复说的"
        if turns < MIN_TURNS:
            continue
        phrases.append(Phrase(text=piece, count=slot["count"], turns=turns))

    # 抑制"长串里套短串"：如果一个短语是某个更长命中短语的子串，
    # 且更长那个的覆盖轮数不低，就丢掉短的（同一件事不重复计）
    phrases.sort(key=lambda p: (-len(p.text), -p.turns, -p.count))
    kept: list[Phrase] = []
    for phrase in phrases:
        covered = any(
            phrase.text in bigger.text and bigger.turns >= phrase.turns
            for bigger in kept
        )
        if not covered:
            kept.append(phrase)

    kept.sort(key=lambda p: (-p.turns, -p.count, -len(p.text)))
    return kept[:limit]


def frequent_lines(texts: list[str], limit: int = 8) -> list[str]:
    """给 prompt 用的短句列表（"他常说 / 常提的"）。"""
    return [p.to_line() for p in count_phrases(texts, limit=limit)]
