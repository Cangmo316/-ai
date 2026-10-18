"""
比邻AI · 主动关心的问题库

## 需求

「智能体需要有人的好奇心，在一些时候需要问老人一些日程的问题，
比如吃了什么，有没有遇到特别的事，有没有什么想做的事，每天要主动问1-2次」

## 三个设计约束

**1. 不能天天问同一句**
"您今天吃什么了"每天雷同，三天就变成机械问候，反而显得假。
所以按下标轮换，且**记住上次问的类别**，避免连着两次同一类。

**2. 分时段**
早上问"今天打算做什么"，中午问"吃了没"，傍晚问"今天有啥特别的事"。
时间对不上的问题会像机器人（下午三点问"早饭吃了吗"）。

**3. 问法要像人，不像调查表**
"今日饮食情况如何"是表格语气；"今儿吃啥了"才是人话。
每条都准备了 2-3 种说法随机选，避免每次字面都一样。
"""

from __future__ import annotations

import random

from ..care.models import TOPIC_EAT, TOPIC_DAY, TOPIC_EVENT, TOPIC_WISH

#: (类别, 适用时段, 问法)
#: 时段用 (起, 止) 的小时数，左闭右开。
QUESTIONS: tuple[tuple[str, tuple[int, int], tuple[str, ...]], ...] = (
    # ── 吃了什么 ──
    (TOPIC_EAT, (6, 10), (
        "早上吃点啥了",
        "早饭吃了没",
        "今儿早上吃的什么呀",
    )),
    (TOPIC_EAT, (10, 14), (
        "中午吃的啥",
        "午饭吃了没 别凑合",
        "中午这顿吃的什么",
    )),
    (TOPIC_EAT, (17, 21), (
        "晚上吃的什么",
        "晚饭吃了没",
        "今儿晚上这顿吃啥了",
    )),
    # ── 有没有遇到特别的事 ──
    (TOPIC_EVENT, (7, 21), (
        "今天有啥特别的事没有",
        "今儿遇上什么有意思的事没",
        "今天过得怎么样 有没有什么新鲜事",
    )),
    # ── 今天打算做什么 ──
    (TOPIC_DAY, (6, 11), (
        "今天打算干点啥",
        "今儿有什么安排没有",
        "今天准备忙点什么",
    )),
    # ── 有没有什么想做的事 ──
    (TOPIC_WISH, (9, 21), (
        "有没有什么想做的事 我记着",
        "最近有什么想干的没有",
        "您有没有什么想办的事 我帮您记着",
    )),
)

#: 兜底问法（问题库按时间筛空时用）
FALLBACK = (
    "今天过得怎么样",
    "今儿有什么新鲜事吗",
)

#: 各类别在一天里的"权重"。吃的最常问（一天三顿都有话说），
#: 想做的事偶尔问（问太勤会像催他）。
TOPIC_WEIGHT = {
    TOPIC_EAT: 3,
    TOPIC_EVENT: 2,
    TOPIC_DAY: 1,
    TOPIC_WISH: 1,
}


def candidates_at(hour: int) -> list[tuple[str, tuple[str, ...]]]:
    """某个小时可问的问题（类别 + 问法）。"""
    out: list[tuple[str, tuple[str, ...]]] = []
    for topic, (start, end), variants in QUESTIONS:
        if start <= hour < end:
            out.append((topic, variants))
    return out


def pick_question(
    hour: int,
    last_topic: str = "",
    rng: random.Random | None = None,
) -> tuple[str, str]:
    """挑一个问题，返回 (类别, 问法)。

    `last_topic` 是上次问的类别 —— 尽量别连着两次问同一类
    （刚问完"吃了啥"紧接着又问"吃了啥"，一眼就是机器）。
    """
    rng = rng or random
    pool = candidates_at(hour)
    if not pool:
        return "", rng.choice(FALLBACK)

    # 排掉上次问过的类别；如果排空了（比如某个时段只有一类），就允许重复
    filtered = [item for item in pool if item[0] != last_topic] or pool

    # 按权重铺开再随机取，让"吃的"出现得更多但不至于老是吃
    weighted: list[tuple[str, tuple[str, ...]]] = []
    for topic, variants in filtered:
        weighted.extend([(topic, variants)] * TOPIC_WEIGHT.get(topic, 1))

    topic, variants = rng.choice(weighted)
    return topic, rng.choice(variants)


def topic_label(topic: str) -> str:
    labels = {
        TOPIC_EAT: "吃了什么",
        TOPIC_EVENT: "特别的事",
        TOPIC_DAY: "今天安排",
        TOPIC_WISH: "想做的事",
    }
    return labels.get(topic, topic)
