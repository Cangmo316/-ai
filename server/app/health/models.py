"""
比邻AI · 健康档案（结构化身体数据）

## 为什么是"带时间戳的记录"而不是档案里的几个字段

原来 L1 档案里只有 `chronic`（老毛病）、`medication`（吃的药）这类**静态文字**，
没有具体数值。而"智能体主动慰问和建议"要看的是**数值和趋势**：
「昨天 158/96，今天又 160/98」和「有高血压」是完全不同的两件事。

所以做成时间序列：每次测量都是一条记录，带自己的类型、数值、时间。
这样才谈得上"最近怎么样""比上次好还是坏"。

## 为什么不硬编码字段

不同测量项的参数不一样：血压是收缩压+舒张压+脉搏，血糖还要分空腹/餐后，
体重只有一个数。硬编码会写成一堆可空字段（二十几个列、大半是空的）。

所以**每一项的类型定义（字段/单位/正常范围）集中放在 `HEALTH_ITEM_TYPES`**，
数值存在 `values` 字典里。加一项新指标（比如尿酸）只改这张表，
存储、接口、界面都跟着走，不用动结构。

## 与知识库的关系

`HEALTH_ITEM_TYPES` 里的 `normalRange` 是**给界面显示参考区间用的**（灰字提示），
**不是诊断标准**。服务端绝不根据它下结论——越界判断与建议一律走知识库
（`app/knowledge/guidelines.yaml`）与人设 prompt 的红线。
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field

from ..models.message import now_iso

logger = logging.getLogger("bilin.health")

# --------------------------------------------------------------------- 指标定义

#: 三项**基础数据**（按需求：只留这三项；心率/血氧/体温已删去）。
#: 医院给的文书类信息走「病例病史」（app/docs），不混在这里——
#: 基础数据是老人自己量的**数值**（看趋势），病例是医院的**文书**（看诊断与医嘱）。
HEALTH_ITEM_TYPES: dict[str, dict] = {
    "bloodPressure": {
        "label": "血压",
        "unit": "mmHg",
        "fields": [
            {"key": "systolic", "label": "高压（收缩压）", "required": True, "min": 50, "max": 300},
            {"key": "diastolic", "label": "低压（舒张压）", "required": True, "min": 30, "max": 200},
            {"key": "pulse", "label": "脉搏（次/分）", "required": False, "min": 30, "max": 220},
        ],
        # 参考区间只用于界面灰字提示，**不是诊断依据**
        "normalRange": "高压 90–139，低压 60–89",
        "hint": "坐着量，量之前先歇 5 分钟",
    },
    "bloodSugar": {
        "label": "血糖",
        "unit": "mmol/L",
        "fields": [
            {"key": "value", "label": "血糖值", "required": True, "min": 1, "max": 40, "step": 0.1},
        ],
        "timings": ["空腹", "餐后2小时", "睡前", "随机"],
        "normalRange": "空腹 3.9–6.1，餐后2小时 < 7.8",
        "hint": "记一下是饭前还是饭后量的",
    },
    "weight": {
        "label": "体重",
        "unit": "kg",
        "fields": [
            {"key": "value", "label": "体重", "required": True, "min": 20, "max": 200, "step": 0.1},
        ],
        "normalRange": "",
        "hint": "早上空腹称最准",
    },
}

#: 记录来源（家族史/设备/手输），用于区分可信度与展示
SOURCE_MANUAL = "manual"
SOURCE_DEVICE = "device"


def item_label(item_type: str) -> str:
    spec = HEALTH_ITEM_TYPES.get(str(item_type or ""))
    return spec["label"] if spec else str(item_type or "")


def validate_values(item_type: str, values: dict) -> tuple[dict, str]:
    """校验并规范化数值。

    @returns (清洗后的 values, 错误说明)。错误说明为空串表示通过。
    """
    spec = HEALTH_ITEM_TYPES.get(str(item_type or ""))
    if spec is None:
        return {}, "不认识的测量项"

    clean: dict[str, float] = {}
    for item in spec["fields"]:
        key = item["key"]
        raw = (values or {}).get(key)
        if raw in (None, ""):
            if item.get("required"):
                return {}, "请填写" + item["label"]
            continue
        try:
            number = float(raw)
        except (TypeError, ValueError):
            return {}, item["label"] + "要填数字"
        if number < item["min"] or number > item["max"]:
            return {}, (
                item["label"] + "填得不太对（应在 "
                + str(item["min"]) + " 到 " + str(item["max"]) + " 之间）"
            )
        # 血压/心率/血氧是整数，血糖/体重/体温保留一位小数
        clean[key] = round(number, 1) if item.get("step") else int(round(number))

    # 血压的高压必须大于低压，否则一定是填反了
    if item_type == "bloodPressure" and "systolic" in clean and "diastolic" in clean:
        if clean["systolic"] <= clean["diastolic"]:
            return {}, "高压应该比低压大，是不是填反了"

    if not clean:
        return {}, "请至少填一项"

    timing = str((values or {}).get("timing") or "").strip()
    if timing and spec.get("timings") and timing not in spec["timings"]:
        return {}, "测量时点不对"
    if timing:
        clean["timing"] = timing

    return clean, ""


def summarize(item_type: str, values: dict) -> str:
    """一句话摘要，用于列表显示与注入 prompt。

    例如血压 `128/82`、血糖 `6.4（空腹）`、体重 `62.5 kg`。
    """
    spec = HEALTH_ITEM_TYPES.get(str(item_type or ""))
    if spec is None:
        return ""
    v = values or {}
    unit = spec.get("unit", "")

    if item_type == "bloodPressure":
        text = ""
        if v.get("systolic") is not None and v.get("diastolic") is not None:
            text = str(v["systolic"]) + "/" + str(v["diastolic"])
        if v.get("pulse") is not None:
            text += ("，" + str(v["pulse"]) + " 次/分") if text else (str(v["pulse"]) + " 次/分")
        return text + ((" " + unit) if text else "")

    if v.get("value") is None:
        return ""
    text = str(v["value"]) + (" " + unit if unit else "")
    if v.get("timing"):
        text += "（" + str(v["timing"]) + "）"
    return text


# --------------------------------------------------------------------- 数据

@dataclass
class HealthRecord:
    id: str
    elder_id: str
    item_type: str
    values: dict
    measured_at: str = field(default_factory=now_iso)
    note: str = ""
    source: str = SOURCE_MANUAL
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "elderId": self.elder_id,
            "itemType": self.item_type,
            "itemLabel": item_label(self.item_type),
            "values": dict(self.values),
            "summary": summarize(self.item_type, self.values),
            "measuredAt": self.measured_at,
            "note": self.note,
            "source": self.source,
            "createdAt": self.created_at,
        }


def new_record_id() -> str:
    return "h_" + secrets.token_hex(8)


class HealthStore:
    """健康记录（内存实现；接口与 SQL 版逐字一致）"""

    def __init__(self) -> None:
        self._records: dict[str, list[HealthRecord]] = {}

    # ---------------------------------------------------------------- 读

    def records_of(self, elder_id: str, *, item_type: str = "", limit: int = 0) -> list[HealthRecord]:
        """某位老人的记录，**按测量时间倒序**（最近的在前）"""
        items = [r for r in self._records.get(str(elder_id or ""), []) if r is not None]
        if item_type:
            items = [r for r in items if r.item_type == item_type]
        items.sort(key=lambda r: (r.measured_at or "", r.created_at or ""), reverse=True)
        if limit and len(items) > limit:
            return items[:limit]
        return items

    def find(self, record_id: str) -> HealthRecord | None:
        wanted = str(record_id or "")
        for items in self._records.values():
            for record in items:
                if record.id == wanted:
                    return record
        return None

    def latest_of(self, elder_id: str, item_type: str) -> HealthRecord | None:
        items = self.records_of(elder_id, item_type=item_type, limit=1)
        return items[0] if items else None

    # ---------------------------------------------------------------- 写

    def add(
        self,
        *,
        elder_id: str,
        item_type: str,
        values: dict,
        measured_at: str = "",
        note: str = "",
        source: str = SOURCE_MANUAL,
    ) -> HealthRecord:
        record = HealthRecord(
            id=new_record_id(),
            elder_id=str(elder_id or ""),
            item_type=str(item_type or ""),
            values=dict(values or {}),
            measured_at=measured_at or now_iso(),
            note=str(note or ""),
            source=source or SOURCE_MANUAL,
        )
        self._records.setdefault(record.elder_id, []).append(record)
        return record

    def remove(self, record_id: str) -> bool:
        wanted = str(record_id or "")
        for elder_id, items in self._records.items():
            for index, record in enumerate(items):
                if record.id == wanted:
                    items.pop(index)
                    return True
        return False

    def count(self) -> int:
        return sum(len(items) for items in self._records.values())

    # ---------------------------------------------------------------- 给智能体

    def snapshot_for_prompt(self, elder_id: str, *, per_type: int = 3) -> list[str]:
        """给人设 prompt 用的一句话摘要（每项最近几条）。

        只给**最近几条**、不给全量：全量会把上下文淹掉，
        而"最近怎么样、比上次好还是坏"才是聊天里真用得上的信息。
        """
        lines: list[str] = []
        for item_type in HEALTH_ITEM_TYPES:
            recent = self.records_of(elder_id, item_type=item_type, limit=per_type)
            if not recent:
                continue
            parts = []
            for record in recent:
                text = summarize(item_type, record.values)
                if not text:
                    continue
                day = str(record.measured_at or "")[:10]
                parts.append(text + "（" + day + "）")
            if parts:
                lines.append(item_label(item_type) + "：" + "；".join(parts))
        return lines

    def readings_for_prompt(self, elder_id: str, item_type: str, per_type: int = 3) -> list[dict]:
        """某个指标的最近几条（结构化），给主动消息的触发判定用"""
        return [
            record.to_dict()
            for record in self.records_of(elder_id, item_type=item_type, limit=per_type)
        ]
