"""校验训练集：有无评测泄漏、各类样本占比、总字数。"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, r"E:\比邻AI\server")
from tests.scenarios import SCENARIOS  # noqa: E402


def norm(text: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffa-zA-Z0-9]", "", text or "").lower()


def main() -> None:
    held = {norm(c["text"]) for c in SCENARIOS}
    path = Path(r"E:\比邻AI\ml\data\final\train.jsonl")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    leak = [r for r in rows if norm(r["messages"][1]["content"]) in held]
    print("  训练集 %d 条，与生产场景重复 %d 条 %s"
          % (len(rows), len(leak), "✅ 干净" if not leak else "❌ 泄漏"))

    counter = Counter((r.get("meta") or {}).get("source") or "(种子)" for r in rows)
    print("  样本来源:")
    for key, count in counter.most_common():
        print("    %-16s %d" % (key, count))

    chars = sum(len(r["messages"][1]["content"]) + len(r["messages"][2]["content"]) for r in rows)
    print("  对话内容 %d 字" % chars)

    # 反向样本抽查：确认这批真的没提医生
    daily = [r for r in rows if (r.get("meta") or {}).get("source") == "daily_nowarn"]
    forbidden = ("医院", "医生", "急诊", "120", "检查", "挂号", "仅供参考", "以医嘱")
    dirty = [r for r in daily if any(w in r["messages"][2]["content"] for w in forbidden)]
    print("  日常反向上限样本 %d 条，其中提了医生的 %d 条 %s"
          % (len(daily), len(dirty), "✅" if not dirty else "⚠️"))


if __name__ == "__main__":
    main()
