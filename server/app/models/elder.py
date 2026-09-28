"""
比邻AI · 老人档案（L1 记忆的最小实现）

P0 里 `elder_id` 只是个透传字段，计划引擎开始才真正需要档案——因为「按 audience 匹配条目」
的一切前提就是"这个老人有什么慢病、多大年纪"。

**当前是内存 + 3 个模拟档案**（医学选型文档 §四 明确要求：开发期用测试数据跑通链路，
不涉及真实医学建议）。P2 接记忆系统时，这里换成 PostgreSQL 的 `elder` / `memory_fact` 表，
上层（计划引擎）的调用方式不变。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ⚠️ 开发期模拟数据，不是真实病例，也不构成任何医学建议
DEMO_ELDERS: dict[str, dict] = {
    "e_1": {
        "id": "e_1",
        "name": "张桂兰",
        "address": "妈",
        "birth": "1954-03-02",
        "age": 71,
        "chronic": ["高血压"],
        "medication": ["降压药 1 片（遵医嘱）"],
        "diet": ["少盐"],
        "habits": ["早上出去走走"],
        "family": "儿子小明在本地，女儿小红在外地",
        "care_level": "居家",
    },
    "e_2": {
        "id": "e_2",
        "name": "李建国",
        "address": "爸",
        "birth": "1957-08-19",
        "age": 68,
        "chronic": ["糖尿病"],
        "medication": ["降糖药（遵医嘱）"],
        "diet": ["控糖", "少油"],
        "habits": ["饭后散步"],
        "family": "女儿小丽同住",
        "care_level": "居家",
    },
    "e_3": {
        "id": "e_3",
        "name": "王秀英",
        "address": "奶奶",
        "birth": "1947-01-11",
        "age": 79,
        "chronic": [],
        "medication": [],
        "diet": [],
        "habits": ["爱听戏"],
        "family": "孙辈常来看",
        "care_level": "居家",
    },
}

DEFAULT_ELDER_ID = "e_1"


@dataclass
class ElderStore:
    elders: dict[str, dict] = field(default_factory=lambda: dict(DEMO_ELDERS))

    def get(self, elder_id: str | None) -> dict:
        if elder_id and elder_id in self.elders:
            return self.elders[elder_id]
        return self.elders[DEFAULT_ELDER_ID]

    def all(self) -> list[dict]:
        return list(self.elders.values())

    def upsert(self, elder: dict) -> dict:
        elder_id = str(elder.get("id") or "")
        if not elder_id:
            raise ValueError("老人档案必须有 id")
        self.elders[elder_id] = dict(elder)
        return self.elders[elder_id]

    def tags(self, elder_id: str | None) -> set[str]:
        """用于 audience 匹配的人群标签：慢病 + 年龄档。"""
        elder = self.get(elder_id)
        tags = {str(item) for item in (elder.get("chronic") or [])}
        age = elder.get("age")
        if isinstance(age, int) and age >= 65:
            tags.add("65岁以上")
        return tags
