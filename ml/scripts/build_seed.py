"""构建 SFT 种子集：真实场景 + 已验证的高质量回复。

## 为什么用现有评测结果当种子

真模型评测 100% 通过的那 63 条回复，是 DeepSeek 在**真实康养场景**下、
配合真实产品提示词产出的优质样本。拿它当 SFT 目标，等于**蒸馏**：
把大模型在这个领域的行为固化进小模型，而不是从零教它。

## 关键设计：system 用**真实产品提示词**

不是另写一份简化提示词 —— 那样训练出来的模型换个提示词就废了。
这里直接调 `app.persona.prompts.build_system_prompt`，
保证训练时与生产时看到的是同一套话术边界。

用法：
    python scripts/build_seed.py
输出：
    data/seed/seed.jsonl
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = Path(r"E:\比邻AI\server")
sys.path.insert(0, str(SERVER))

from app.persona.prompts import (  # noqa: E402
    KIND_DAILY,
    KIND_MEDICAL,
    PersonaRegistry,
    build_system_prompt,
    is_medical_question,
)
from tests.scenarios import SCENARIOS  # noqa: E402  复用 63 条真实场景

OUT = ROOT / "data" / "seed"
REPORT = SERVER / "eval-report.json"


def system_prompt_for(medical: bool) -> str:
    """取真实产品提示词（不带动态档案，保证可复现）。"""
    registry = PersonaRegistry()
    persona = registry.by_kind(KIND_MEDICAL if medical else KIND_DAILY)
    return build_system_prompt(
        persona,
        elder={"name": "老人"},   # 只给最基本的，避免把某个具体老人写进数据集
        memories=None,
        health=None,
        cases=None,
        wiki_elder=None,
        wiki_persona=None,
        history_summary="",
        care_followups=None,
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # ① 从评测报告里取"最终通过的回复"当教学样本
    replies: dict[str, str] = {}
    if REPORT.exists():
        for item in json.loads(REPORT.read_text(encoding="utf-8")):
            text = (item.get("text") or "").strip()
            reply = (item.get("reply") or "").strip()
            if text and reply and not item.get("issues"):
                replies[text] = reply
        print("  评测报告里可用的优质回复: %d 条" % len(replies))
    else:
        print("  ⚠️ 没有评测报告，种子集只会有场景、没有目标回复")

    # ② 组装种子
    rows: list[dict] = []
    for case in SCENARIOS:
        text = case["text"]
        reply = replies.get(text)
        if not reply:
            continue
        medical = case.get("medical")
        if medical is None:
            medical = is_medical_question(text)
        rows.append({
            "messages": [
                {"role": "system", "content": system_prompt_for(bool(medical))},
                {"role": "user", "content": text},
                {"role": "assistant", "content": reply},
            ],
            "meta": {
                "group": case.get("group", ""),
                "persona": "medical" if medical else "daily",
                "source": "eval_seed",
            },
        })

    path = OUT / "seed.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    chars = sum(
        len(r["messages"][1]["content"]) + len(r["messages"][2]["content"]) for r in rows
    )
    user_chars = sum(len(r["messages"][1]["content"]) for r in rows)
    asst_chars = sum(len(r["messages"][2]["content"]) for r in rows)
    print("  种子样本          : %d 条" % len(rows))
    print("  用户侧字数        : %d 字" % user_chars)
    print("  回复侧字数        : %d 字" % asst_chars)
    print("  对话字数合计      : %d 字" % chars)
    print("  输出              : %s" % path)


if __name__ == "__main__":
    main()
